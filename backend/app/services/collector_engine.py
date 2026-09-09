"""
筱和灵眸(AethelEye) - 采集引擎 V3 (SKU提取增强版)

核心采集逻辑
- 商品页面访问
- SKU解析（多层策略）
- 到手价提取
- 截图和录屏
"""
import asyncio
import json
import re
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Callable
from playwright.async_api import Page, BrowserContext, TimeoutError as PlaywrightTimeoutError, Response

from app.config import settings
from app.models.browser import BrowserProfile
from app.models.task import MonitorTask
from app.models.sku import SKU
from app.utils.logger import get_logger
from app.services.browser_manager import get_browser_manager
from app.services.video_recorder import CDPVideoRecorder
from app.services.engine_base import BaseCollectionEngine, CollectionResult as _BaseCollectionResult

# 日志
log = get_logger("collector")


# CollectionResult 统一定义在 engine_base 中，此处保留向后兼容的导入
CollectionResult = _BaseCollectionResult


@dataclass
class InterceptedData:
    """拦截到的数据"""
    api_data: Optional[Dict] = None
    sku_data: Optional[List[Dict]] = None
    price_data: Optional[Dict] = None


class CollectorEngine(BaseCollectionEngine):
    """
    采集引擎 V3 - SKU提取增强版（Playwright 实现）

    负责执行商品页面采集任务
    SKU解析策略（按优先级）：
    1. 网络拦截（优先）：捕获淘系内部API返回的JSON数据
    2. JavaScript执行提取：在页面上下文中执行JS获取Hub数据
    3. DOM解析：从页面元素中提取SKU信息
    4. ld+json结构化数据
    5. CSS选择器兜底
    """

    ENGINE_NAME = "playwright"
    ENGINE_DISPLAY_NAME = "Playwright 采集引擎 V3"

    def __init__(self):
        """初始化采集引擎"""
        super().__init__()
        self.browser_manager = get_browser_manager()
        self._intercepted_data = InterceptedData()

    def _get_profile_lock(self, profile_id: int) -> asyncio.Lock:
        """向后兼容别名，委托给基类 get_profile_lock"""
        return self.get_profile_lock(profile_id)

    async def collect(
        self,
        task: MonitorTask,
        profile_id: int,
        headless: bool = True,
        record_video: bool = False,
        trace_id: Optional[str] = None
    ) -> CollectionResult:
        """
        执行采集任务

        录屏通过 CDP screencast 实现，不需要独立 context。

        Args:
            task: 监控任务
            profile_id: 浏览器配置ID
            headless: 是否静默模式
            record_video: 是否录屏
            trace_id: 日志追踪ID

        Returns:
            CollectionResult采集结果
        """
        result = CollectionResult()
        start_time = datetime.now()
        mtop_data = {}

        log.info(
            f"采集任务开始",
            task_id=task.id,
            trace_id=trace_id,
            data={
                "url": task.url,
                "platform": task.platform,
                "headless": headless,
                "record_video": record_video,
            }
        )

        try:
            # 获取浏览器配置（在新的session中）
            from app.database import get_sync_session
            with get_sync_session() as session:
                profile = session.query(BrowserProfile).filter(
                    BrowserProfile.id == profile_id
                ).first()
                if not profile:
                    raise Exception(f"浏览器配置不存在: {profile_id}")

            # 获取浏览器上下文（始终复用持久化 context）
            context = await self.browser_manager.get_context(
                profile_id=profile_id,
                headless=headless,
            )

            # 标签页复用：找到一个可用页面，多余的关掉（保留最多2个标签页）
            page = None
            pages = context.pages
            for p in pages:
                if page is None:
                    page = p  # 复用第一个标签页（无论当前URL是什么）
                elif len(pages) > 2:
                    try:
                        await p.close()
                    except Exception:
                        pass
            if not page:
                page = await context.new_page()

            # 设置超时
            page.set_default_timeout(settings.collect_timeout_seconds * 1000)

            # CDP 录屏器（在 persistent context 内工作，不影响 context 生命周期）
            recorder = None
            if record_video:
                try:
                    video_dir = settings.recordings_dir
                    video_path = video_dir / f"task_{task.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.webm"
                    recorder = CDPVideoRecorder()
                    await recorder.start(page, video_path)
                except Exception as rec_err:
                    log.warning(f"录屏启动失败（不影响采集）: {rec_err}")
                    recorder = None

            try:
                # [关键修复] 使用mtop拦截器导航，确保捕获API返回的准确价格
                mtop_data = await self._setup_mtop_interceptor_and_navigate(page, task.url, trace_id)

                # 解析页面内容，传入捕获的mtop数据
                parsed_data = await self._parse_product_page(page, task.platform, trace_id, mtop_data)

                # 提取结果
                result.success = True
                result.product_title = parsed_data.get("title")
                result.shop_name = parsed_data.get("shop_name")
                result.skus = parsed_data.get("skus", [])

                # 截图
                screenshot_path = await self._take_screenshot(
                    page, task_id=task.id, trace_id=trace_id,
                    shop_name=result.shop_name, url=task.url,
                    product_title=result.product_title
                )
                result.screenshot_path = screenshot_path

            finally:
                # 停止录屏（如果开启了）
                if recorder and recorder.is_recording:
                    video_file = await recorder.stop()
                    if video_file:
                        result.recording_path = video_file
                # 保留页面在当前状态，不导航到 about:blank（更像真人行为）
                # 仅在页面崩溃时关闭
                pass

        except PlaywrightTimeoutError as e:
            result.error = f"页面加载超时: {e}"
            log.error(
                f"采集失败: 超时",
                task_id=task.id,
                trace_id=trace_id,
                error_stack=str(e)
            )

        except Exception as e:
            error_text = str(e).strip() or repr(e)
            tb_text = traceback.format_exc()
            error_lower = error_text.lower()
            error_type_name = type(e).__name__

            # 判断故障级别
            is_driver_dead = (
                isinstance(e, NotImplementedError)
                or "notimplementederror" in error_lower
                or "connection closed" in error_lower
            )
            is_stale_context = (
                "nonetype' object has no attribute 'send'" in error_lower
                or "target page, context or browser has been closed" in error_lower
                or "browser has been closed" in error_lower
                or "object is not connected" in error_lower
            )

            if is_driver_dead or is_stale_context:
                recovery_method = "引擎重启" if is_driver_dead else "上下文重建"
                log.warning(
                    f"采集检测到浏览器故障({recovery_method})，正在恢复后重试",
                    task_id=task.id,
                    trace_id=trace_id,
                    data={"error": error_text, "error_type": error_type_name,
                          "profile_id": profile_id, "recovery": recovery_method,
                          "traceback": tb_text}
                )

                # 分级恢复：驱动死亡→完全重启引擎；上下文失效→仅重建context
                try:
                    if is_driver_dead:
                        await self.browser_manager.restart_playwright()
                    else:
                        await self.browser_manager.close_context(profile_id)
                except Exception:
                    # 恢复失败也尝试完全重启
                    try:
                        await self.browser_manager.restart_playwright()
                    except Exception:
                        pass

                # 重试一次
                page = None
                try:
                    context = await self.browser_manager.get_context(
                        profile_id=profile_id,
                        headless=headless,
                    )
                    page = None
                    for p in context.pages:
                        if page is None:
                            page = p
                            break
                    if not page:
                        page = await context.new_page()
                    page.set_default_timeout(settings.collect_timeout_seconds * 1000)

                    mtop_data = await self._setup_mtop_interceptor_and_navigate(page, task.url, trace_id)
                    parsed_data = await self._parse_product_page(page, task.platform, trace_id, mtop_data)

                    result.success = True
                    result.product_title = parsed_data.get("title")
                    result.shop_name = parsed_data.get("shop_name")
                    result.skus = parsed_data.get("skus", [])

                    screenshot_path = await self._take_screenshot(
                        page, task_id=task.id, trace_id=trace_id,
                        shop_name=result.shop_name, url=task.url,
                        product_title=result.product_title
                    )
                    result.screenshot_path = screenshot_path

                    log.info(f"{recovery_method}后采集成功", task_id=task.id, trace_id=trace_id)
                except Exception as retry_e:
                    retry_error_text = str(retry_e).strip() or repr(retry_e)
                    retry_tb = traceback.format_exc()
                    result.error = f"采集失败({recovery_method}后仍失败): {retry_error_text}"
                    log.error(
                        f"采集失败: {recovery_method}后仍失败",
                        task_id=task.id,
                        trace_id=trace_id,
                        error_stack=retry_error_text,
                        error_type=type(retry_e).__name__,
                        traceback=retry_tb
                    )
            else:
                result.error = f"采集失败: {error_text}"
                log.error(
                    f"采集失败: 异常",
                    task_id=task.id,
                    trace_id=trace_id,
                    error_stack=error_text,
                    error_type=error_type_name,
                    traceback=tb_text
                )

        # 计算耗时
        result.duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        log.info(
            f"采集任务结束",
            task_id=task.id,
            trace_id=trace_id,
            data={
                "success": result.success,
                "sku_count": len(result.skus),
                "duration_ms": result.duration_ms,
                "error": result.error,
                "prices": {s.get("name", "?")[:20]: s.get("price") for s in result.skus[:10]} if result.skus else None,
                "has_mtop": bool(mtop_data and mtop_data.get("data")),
            }
        )

        return result

    async def collect_for_parse(
        self,
        url: str,
        profile_id: int,
        headless: bool = True,
        trace_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        用于parse_url的采集（无任务ID）

        Args:
            url: 商品URL
            profile_id: 浏览器配置ID
            headless: 是否静默模式
            trace_id: 日志追踪ID

        Returns:
            解析结果字典
        """
        result = {"success": False, "title": None, "shop_name": None, "skus": [], "error": None}

        try:
            # 获取浏览器配置
            from app.database import get_sync_session
            with get_sync_session() as session:
                profile = session.query(BrowserProfile).filter(
                    BrowserProfile.id == profile_id
                ).first()
                if not profile:
                    raise Exception(f"浏览器配置不存在: {profile_id}")

            # 解析链路在Windows上可能遇到已失效上下文（new_page时NoneType.send），
            # 这里做一次自动重建+重试，避免前端直接500。
            attempt_errors: List[str] = []
            for attempt in range(2):
                page: Optional[Page] = None
                try:
                    context = await self.browser_manager.get_context(
                        profile_id=profile_id,
                        headless=headless,
                    )

                    # 标签页复用
                    page = None
                    for p in context.pages:
                        if page is None:
                            page = p
                            break
                    if not page:
                        page = await context.new_page()
                    page.set_default_timeout(settings.collect_timeout_seconds * 1000)

                    # [关键改进] 先设置网络拦截器，再导航
                    mtop_data = await self._setup_mtop_interceptor_and_navigate(page, url, trace_id)

                    # 解析平台
                    platform, _ = await self.parse_product_url(url)

                    # 解析页面内容，传入捕获的mtop数据
                    parsed_data = await self._parse_product_page(page, platform, trace_id, mtop_data)

                    result["success"] = True
                    result["title"] = parsed_data.get("title")
                    result["shop_name"] = parsed_data.get("shop_name")
                    result["skus"] = parsed_data.get("skus", [])

                    log.info(
                        f"parse_url完成",
                        trace_id=trace_id,
                        data={
                            "title": result["title"],
                            "shop_name": result["shop_name"],
                            "sku_count": len(result["skus"]),
                            "skus_preview": [{"name": s.get("name"), "price": s.get("price")} for s in result["skus"][:3]]
                        }
                    )
                    break
                except Exception as parse_error:
                    error_text = str(parse_error).strip() or repr(parse_error)
                    attempt_errors.append(error_text)
                    error_lower = error_text.lower()
                    is_driver_dead = (
                        isinstance(parse_error, NotImplementedError)
                        or "notimplementederror" in error_lower
                        or "connection closed" in error_lower
                    )
                    is_stale_context = (
                        "nonetype' object has no attribute 'send'" in error_lower
                        or "target page, context or browser has been closed" in error_lower
                        or "browser has been closed" in error_lower
                        or "object is not connected" in error_lower
                    )
                    if attempt == 0 and (is_driver_dead or is_stale_context):
                        recovery = "引擎重启" if is_driver_dead else "上下文重建"
                        log.warning(
                            f"parse_url检测到浏览器故障({recovery})，正在恢复后重试",
                            trace_id=trace_id,
                            data={"profile_id": profile_id, "error": error_text,
                                  "error_type": type(parse_error).__name__, "recovery": recovery}
                        )
                        try:
                            if is_driver_dead:
                                await self.browser_manager.restart_playwright()
                            else:
                                await self.browser_manager.close_context(profile_id)
                        except Exception:
                            try:
                                await self.browser_manager.restart_playwright()
                            except Exception:
                                pass
                        continue
                    raise Exception(" | ".join(attempt_errors))
                finally:
                    if page:
                        try:
                            await page.goto("about:blank", wait_until="commit", timeout=5000)
                        except Exception:
                            try:
                                await page.close()
                            except Exception:
                                pass

        except Exception as e:
            result["error"] = str(e)
            log.error(f"解析失败: {e}", trace_id=trace_id, error_stack=str(e))

        return result

    async def _setup_mtop_interceptor_and_navigate(
        self,
        page: Page,
        url: str,
        trace_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        [方案一] 设置mtop API拦截器并导航到页面

        在导航前设置响应拦截器，捕获mtop.taobao.pcdetail.data.get等API响应
        """
        captured_mtop_data = {}
        api_response_received = asyncio.Event()

        async def handle_mtop_response(response: Response):
            """处理mtop API响应"""
            try:
                resp_url = response.url

                # 检查是否是mtop API（PC详情页主数据）
                mtop_patterns = [
                    "mtop.taobao.pcdetail.data.get",
                    "mtop.taobao.detail",
                    "mtop.taobao.pcdetail",
                ]

                if any(pattern in resp_url for pattern in mtop_patterns):
                    log.info("拦截到 mtop API 响应", trace_id=trace_id)

                    try:
                        body = await response.text()

                        # 处理JSONP格式
                        json_str = body
                        if body.startswith("mtopjsonp") or body.startswith("jsonp"):
                            match = re.search(r'\((.*)\)$', body, re.DOTALL)
                            if match:
                                json_str = match.group(1)

                        # 解析JSON
                        data = json.loads(json_str)
                        captured_mtop_data.update({
                            "url": resp_url,
                            "data": data
                        })
                        api_response_received.set()
                        log.info(f"mtop API数据捕获成功", trace_id=trace_id)

                    except Exception as e:
                        log.debug(f"mtop API解析失败: {e}", trace_id=trace_id)

            except Exception:
                pass

        # 在导航前设置拦截器
        page.on("response", handle_mtop_response)

        try:
            # 导航到页面
            await page.goto(url, wait_until="domcontentloaded")
            log.info(f"页面导航完成，等待mtop API响应", trace_id=trace_id)

            # 检测是否被重定向到验证码/风控页面（URL 维度）
            current_url = page.url.lower()
            captcha_url_markers = ("punish", "captcha", "verify", "sec.taobao", "login.taobao", "login.tmall")
            if any(marker in current_url for marker in captcha_url_markers):
                raise Exception("被风控拦截，页面已重定向到验证码或登录流程")

            # 检测页面内验证码覆盖层（URL 不变但整页替换为验证码，如淘系滑块验证）
            doc_title = (await page.title() or "").lower()
            captcha_title_markers = ("验证码", "验证", "captcha", "punish", "安全验证", "身份验证")
            if any(marker in doc_title for marker in captcha_title_markers):
                raise Exception(f"被风控拦截，页面显示验证码覆盖层: document.title={await page.title()}")

            # 等待mtop API响应（最多等待5秒）
            try:
                await asyncio.wait_for(api_response_received.wait(), timeout=10.0)
                log.info(f"mtop API响应已捕获", trace_id=trace_id)
            except asyncio.TimeoutError:
                log.info(f"等待mtop API超时，继续解析页面", trace_id=trace_id)

            # 额外等待页面渲染
            await asyncio.sleep(2)

        finally:
            # 移除拦截器
            page.remove_listener("response", handle_mtop_response)

        return captured_mtop_data

    async def _setup_mtop_interceptor(
        self,
        page: Page,
        trace_id: Optional[str]
    ) -> Dict[str, Any]:
        """
        为已打开的页面设置mtop拦截器并等待数据
        """
        captured_mtop_data = {}
        api_response_received = asyncio.Event()

        async def handle_mtop_response(response: Response):
            try:
                resp_url = response.url
                if "mtop.taobao.pcdetail" in resp_url or "mtop.taobao.detail" in resp_url:
                    try:
                        body = await response.text()
                        json_str = body
                        if body.startswith("mtopjsonp"):
                            match = re.search(r'\((.*)\)$', body, re.DOTALL)
                            if match:
                                json_str = match.group(1)
                        data = json.loads(json_str)
                        captured_mtop_data.update({"url": resp_url, "data": data})
                        api_response_received.set()
                        log.info(f"从现有页面捕获mtop数据", trace_id=trace_id)
                    except:
                        pass
            except:
                pass

        page.on("response", handle_mtop_response)

        try:
            # 触发页面刷新或滚动以触发API请求
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
            await asyncio.sleep(1)

            try:
                await asyncio.wait_for(api_response_received.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                pass
        finally:
            page.remove_listener("response", handle_mtop_response)

        return captured_mtop_data

    async def _navigate_to_page(
        self,
        page: Page,
        url: str,
        trace_id: Optional[str],
        wait_until: str = "domcontentloaded"
    ) -> None:
        """
        导航到商品页面

        Args:
            page: Playwright页面
            url: 商品URL
            trace_id: 追踪ID
            wait_until: 等待条件（domcontentloaded/networkidle）
        """
        log.debug(f"页面导航开始", trace_id=trace_id, data={"url": url, "wait_until": wait_until})

        await page.goto(url, wait_until=wait_until)

        # 额外等待页面JS渲染完成
        await asyncio.sleep(2)

        # 等待关键元素出现
        try:
            await page.wait_for_selector("h1, [class*='title'], [class*='Title']", timeout=5000)
        except Exception:
            pass

        log.info(
            f"页面加载完成",
            trace_id=trace_id,
            data={"url": url}
        )

    async def _parse_product_page(
        self,
        page: Page,
        platform: str,
        trace_id: Optional[str],
        mtop_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        解析商品页面

        提取商品标题、店铺名、SKU及到手价

        Args:
            page: Playwright页面
            platform: 平台标识
            trace_id: 追踪ID
            mtop_data: 捕获的mtop API数据（方案一）
        """
        result = {}

        # 页面诊断（收集页面结构信息）
        await self._diagnose_page(page, trace_id)

        # 提取商品标题
        result["title"] = await self._extract_title(page, platform, trace_id)

        # 提取店铺名称
        result["shop_name"] = await self._extract_shop_name(page, platform, trace_id)

        # 提取SKU和到手价，传入mtop数据
        result["skus"] = await self._extract_skus_with_price(page, platform, trace_id, mtop_data)

        return result

    async def _diagnose_page(self, page: Page, trace_id: Optional[str]) -> None:
        """
        页面诊断 - 收集页面结构信息用于优化

        此函数会在后台自动收集页面信息，帮助改进提取策略
        """
        try:
            # 收集页面基本信息
            page_info = await page.evaluate("""() => {
                return {
                    title: document.title,
                    url: location.href,
                    hasSkuMap: !!window.g_skuMap,
                    hasSkuval: !!window.g_config?.skuval,
                    hasHub: !!window.Hub,
                    hasHubConfig: !!window.Hub?.config,
                };
            }""")

            log.debug("页面诊断", trace_id=trace_id, data=page_info)

            # 查找SKU相关元素
            sku_selectors = [
                ".tb-sku", ".tm-sku", "[class*='sku']", "[class*='Sku']",
                ".tb-prop", ".tm-prop", "[class*='prop']",
                "[data-spm*='sku']"
            ]

            sku_elements = {}
            for selector in sku_selectors:
                try:
                    count = await page.evaluate(f"() => document.querySelectorAll('{selector}').length")
                    if count > 0:
                        sku_elements[selector] = count
                except:
                    pass

            if sku_elements:
                log.debug("找到SKU元素", trace_id=trace_id, data=sku_elements)

            # 查找价格元素
            price_selectors = [
                ".tm-price", ".tb-rmb-num", "[class*='price']", "[class*='Price']"
            ]

            price_elements = {}
            for selector in price_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        price_elements[selector] = len(elements)
                        # 记录第一个价格
                        if len(elements) > 0:
                            text = await elements[0].inner_text()
                            price_elements[f"{selector}_text"] = text[:50]
                except:
                    pass

            if price_elements:
                log.debug("找到价格元素", trace_id=trace_id, data=price_elements)

            # 查找规格属性
            try:
                props = await page.query_selector_all(".tb-prop, .tm-prop")
                if props:
                    log.debug(f"找到{len(props)}个规格属性区域", trace_id=trace_id)
            except:
                pass

            # 尝试获取Hub数据
            hub_data = await page.evaluate("""() => {
                const data = {};
                if (window.g_config?.skuval) data.g_config_skuval = Object.keys(window.g_config.skuval).slice(0, 5);
                if (window.g_skuMap) {
                    const map = window.g_skuMap;
                    data.g_skuMap_keys = Object.keys(map).slice(0, 5);
                    if (Object.keys(map).length > 0) {
                        const firstKey = Object.keys(map)[0];
                        data.g_skuMap_sample = map[firstKey];
                    }
                }
                if (window.Hub?.config?.skuMap) {
                    data.Hub_skuMap_keys = Object.keys(window.Hub.config.skuMap).slice(0, 5);
                }
                return data;
            }""")

            if hub_data:
                log.info("从Hub获取到SKU数据", trace_id=trace_id, data=hub_data)

        except Exception as e:
            log.debug(f"页面诊断失败: {e}", trace_id=trace_id)

    async def _extract_title(self, page: Page, platform: str, trace_id: Optional[str]) -> Optional[str]:
        """
        提取商品标题
        """
        # 首先尝试从ICE_APP_CONTEXT提取（新版详情页）
        try:
            ice_title = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (ctx && ctx.loaderData && ctx.loaderData.home && ctx.loaderData.home.data && ctx.loaderData.home.data.res) {
                    const res = ctx.loaderData.home.data.res;
                    // 尝试从item获取标题
                    if (res.item && res.item.title) {
                        return res.item.title;
                    }
                }
                return null;
            }""")
            if ice_title and len(ice_title) > 5:
                log.debug(f"商品标题提取成功(ICE_CONTEXT)", trace_id=trace_id, data={"title": ice_title[:50]})
                return ice_title
        except:
            pass

        selectors = {
            "tmall": [
                "h1.tb-main-title",
                ".tb-detail-hd h1",
                "[class*='ItemTitle']",
                "[class*='itemTitle']",
                "[data-spm='title']",
            ],
            "taobao": [
                "h1.tb-main-title",
                ".tb-detail-hd h1",
                "[class*='ItemTitle']",
                "[class*='itemTitle']",
            ],
        }

        for selector in selectors.get(platform, []):
            try:
                element = await page.query_selector(selector)
                if element:
                    title = await element.inner_text()
                    title = title.strip()
                    if title and len(title) > 5:  # 过滤掉太短的标题
                        log.debug(f"商品标题提取成功", trace_id=trace_id, data={"title": title[:50], "selector": selector})
                        return title
            except Exception:
                continue

        # 尝试从页面标题提取
        page_title = await page.title()
        if page_title:
            # 通常格式为 "商品名-淘宝/天猫"
            parts = page_title.split("-")
            if parts and len(parts[0].strip()) > 5:
                return parts[0].strip()

        log.warning(f"商品标题提取失败", trace_id=trace_id)
        return None

    async def _extract_shop_name(self, page: Page, platform: str, trace_id: Optional[str]) -> Optional[str]:
        """
        提取店铺名称
        """
        # 首先尝试从ICE_APP_CONTEXT提取（新版详情页）
        try:
            ice_shop = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (ctx && ctx.loaderData && ctx.loaderData.home && ctx.loaderData.home.data && ctx.loaderData.home.data.res) {
                    const res = ctx.loaderData.home.data.res;
                    // 尝试从seller获取店铺名
                    if (res.seller) {
                        // 优先使用shopName，其次是sellerNick
                        return res.seller.shopName || res.seller.sellerNick || null;
                    }
                }
                return null;
            }""")
            if ice_shop and len(ice_shop) > 1:
                log.debug(f"店铺名称提取成功(ICE_CONTEXT)", trace_id=trace_id, data={"shop_name": ice_shop})
                return ice_shop
        except:
            pass

        selectors = {
            "tmall": [
                ".shop-name a",
                ".slogo-shopname",
                "[class*='shopName']",
                "[class*='ShopName']",
                "a[href*='shop']",
            ],
            "taobao": [
                ".shop-name a",
                ".shop-info .shop-name",
                "[class*='shopName']",
                "[class*='ShopName']",
            ],
        }

        for selector in selectors.get(platform, []):
            try:
                element = await page.query_selector(selector)
                if element:
                    shop_name = await element.inner_text()
                    shop_name = shop_name.strip()
                    if shop_name and len(shop_name) > 1:
                        log.debug(f"店铺名称提取成功", trace_id=trace_id, data={"shop_name": shop_name, "selector": selector})
                        return shop_name
            except Exception:
                continue

        log.warning(f"店铺名称提取失败", trace_id=trace_id)
        return None

    async def _extract_skus_with_price(
        self,
        page: Page,
        platform: str,
        trace_id: Optional[str],
        mtop_data: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """
        提取SKU及到手价（核心功能 - V4增强版 + 方案一）

        策略（按优先级）：
        0. [新增] mtop API捕获数据（方案一）
        1. 网络拦截：捕获淘系内部API
        2. JavaScript执行：从页面Hub获取SKU数据
        3. 点击SKU获取不同价格
        4. CSS选择器兜底

        Args:
            page: Playwright页面
            platform: 平台
            trace_id: 追踪ID
            mtop_data: 捕获的mtop API数据（方案一）

        Returns:
            SKU列表 [{name, price, sku_id}]
        """
        skus = []

        # [方案一] 策略0: 使用导航前捕获的mtop API数据
        if mtop_data and "data" in mtop_data:
            log.info(f"使用捕获的mtop API数据解析SKU", trace_id=trace_id)
            mtop_skus = self._parse_taobao_api_response(mtop_data["data"], trace_id)
            if mtop_skus and len(mtop_skus) > 0:
                max_mtop_price = max(s.get("price") or 0 for s in mtop_skus)
                has_coupon_price = any(
                    s.get("price") and s.get("price") < max_mtop_price * 0.9
                    for s in mtop_skus
                )
                if has_coupon_price:
                    log.info(f"mtop API数据含券后价，直接返回", trace_id=trace_id, data={"sku_count": len(mtop_skus)})
                    return mtop_skus
                else:
                    skus = mtop_skus
                    log.info(f"mtop API数据无券后价，继续尝试其他策略", trace_id=trace_id)

        # 策略1: ICE_CONTEXT（新版天猫PC，支持多层规格完整解析，优先级最高）
        ice_skus = await self._extract_from_ice_context(page, trace_id)
        if ice_skus and len(ice_skus) > 0:
            ice_prices = set(s.get("price") for s in ice_skus if s.get("price"))
            log.info(f"SKU提取成功(ICE_CONTEXT优先)", trace_id=trace_id, data={
                "strategy": "ice_context", "sku_count": len(ice_skus),
                "prices": list(ice_prices)
            })
            # ICE_CONTEXT 每个 SKU 有独立价格（来自 sku2info）
            # 仅当所有 SKU 价格相同时，才用大字号价格覆盖（可能是统一券后价场景）
            if len(ice_prices) == 1:
                max_ice_price = max(ice_prices)
                biggest_price = await self._get_biggest_font_price(page, trace_id)
                if biggest_price and biggest_price > 0 and biggest_price < max_ice_price:
                    for sku in ice_skus:
                        if sku.get("price") and sku["price"] > biggest_price:
                            sku["original_price"] = sku["price"]
                            sku["price"] = biggest_price
                    log.info(f"ICE_CONTEXT SKU已用大字号券后价覆盖: {biggest_price}元", trace_id=trace_id)
            return ice_skus

        # 策略2: 网络拦截（淘系详情API）获取SKU结构
        api_skus = await self._extract_from_network_api(page, platform, trace_id)
        if api_skus and len(api_skus) > 0:
            skus = api_skus
            log.info(f"SKU提取成功(网络API)", trace_id=trace_id, data={"strategy": "network_api", "sku_count": len(skus)})

        # 策略3: JavaScript执行提取（从Hub数据）
        if not skus:
            js_skus = await self._extract_from_js_hub(page, trace_id)
            if js_skus and len(js_skus) > 0:
                skus = js_skus
                log.info(f"SKU提取成功(JS Hub)", trace_id=trace_id, data={"strategy": "js_hub", "sku_count": len(skus)})

        # 如果已获取到SKU结构（券前价），尝试获取券后价
        if skus:
            max_price = max(s.get("price") or 0 for s in skus)

            # 检查是否有多个影响价格的SKU选项（区间价场景）
            price_prop = await self._discover_price_affecting_sku_options(page, trace_id)
            if price_prop and len(price_prop.get("values", [])) > 1:
                # 多选项：逐个点击获取区间券后价
                click_skus = await self._extract_by_clicking_skus(page, platform, trace_id)
                if click_skus:
                    click_prices = set(s.get("price") for s in click_skus if s.get("price"))
                    if click_prices and any(p < max_price for p in click_prices):
                        log.info(f"区间券后价获取成功", trace_id=trace_id, data={"prices": list(click_prices)})
                        return click_skus

            # 单选项或点击失败：用大字号价格作为统一券后价
            biggest_price = await self._get_biggest_font_price(page, trace_id)
            if biggest_price and biggest_price > 0 and biggest_price < max_price:
                for sku in skus:
                    if sku.get("price") and sku["price"] > biggest_price:
                        sku["original_price"] = sku["price"]
                        sku["price"] = biggest_price
                log.info(f"已用大字号价格覆盖所有SKU: {biggest_price}元", trace_id=trace_id)

            return skus

        # 策略3: DOM解析（从页面元素）
        dom_skus = await self._extract_from_dom_elements(page, platform, trace_id)
        if dom_skus and len(dom_skus) > 0:
            skus = dom_skus
            log.info(f"SKU提取成功(DOM)", trace_id=trace_id, data={"strategy": "dom", "sku_count": len(skus)})

            # 检查是否所有SKU价格都相同
            original_prices = set(s.get("price") for s in skus if s.get("price"))
            if len(original_prices) == 1:
                displayed_price = await self._get_displayed_price(page, trace_id)
                if displayed_price and displayed_price > 0:
                    for sku in skus:
                        if sku.get("price") and sku["price"] > 0:
                            sku["original_price"] = sku["price"]
                            sku["price"] = displayed_price
                    log.info(f"已使用页面显示价格(券后价): {displayed_price}元", trace_id=trace_id)

            return skus

        # 策略4: ld+json结构化数据
        ld_json_skus = await self._extract_from_ld_json(page, trace_id)
        if ld_json_skus and len(ld_json_skus) > 0:
            skus = ld_json_skus
            log.info(f"SKU提取成功(ld+json)", trace_id=trace_id, data={"strategy": "ld+json", "sku_count": len(skus)})
            return skus

        # 策略5: CSS选择器兜底
        css_skus = await self._extract_from_css_fallback(page, trace_id)
        if css_skus and len(css_skus) > 0:
            skus = css_skus
            log.info(f"SKU提取成功(CSS兜底)", trace_id=trace_id, data={"strategy": "css_fallback", "sku_count": len(skus)})
            return skus

        # 策略6: 模拟点击SKU组合获取价格（最可靠的方式）
        click_skus = await self._extract_by_clicking_skus(page, platform, trace_id)
        if click_skus and len(click_skus) > 0:
            skus = click_skus
            log.info(f"SKU提取成功(点击SKU)", trace_id=trace_id, data={"strategy": "click_sku", "sku_count": len(skus)})
            return skus

        log.warning(f"SKU价格提取失败，所有策略均未命中", trace_id=trace_id)
        return []

    async def _extract_by_clicking_skus(
        self,
        page: Page,
        platform: str,
        trace_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        通过点击SKU选项获取每个规格的券后价。
        核心策略：标记追踪法 + 动态SKU发现。
        """
        try:
            log.info(f"开始点击SKU策略(动态发现+标记追踪)", trace_id=trace_id)

            # Step 1: 动态发现影响价格的SKU选项
            price_prop = await self._discover_price_affecting_sku_options(page, trace_id)
            if not price_prop or not price_prop.get("values"):
                log.info(f"未发现影响价格的SKU维度", trace_id=trace_id)
                return []

            values = price_prop["values"]
            prop_name = price_prop.get("propName", "")
            log.info(f"发现价格维度[{prop_name}]，{len(values)}个选项",
                     trace_id=trace_id, data={"options": [v["name"] for v in values]})

            # Step 2: 标记主价格元素
            baseline_price = await self._tag_main_price_element(page, trace_id)
            if not baseline_price:
                log.warning(f"无法标记主价格元素", trace_id=trace_id)
                return []

            log.info(f"基准价格: {baseline_price}元", trace_id=trace_id)

            # Step 3: 逐个点击选项，捕获价格变化
            price_map = {}

            for val in values:
                value_name = val["name"]

                locator = page.get_by_text(value_name, exact=True)
                count = await locator.count()
                if count == 0:
                    locator = page.get_by_text(value_name, exact=False)
                    count = await locator.count()
                if count == 0:
                    log.info(f"SKU选项[{value_name}]未找到", trace_id=trace_id)
                    continue

                pre_price = await self._read_tagged_price(page, trace_id)
                if pre_price is None:
                    pre_price = await self._tag_main_price_element(page, trace_id)

                await locator.first.click()
                log.info(f"点击[{value_name}]", trace_id=trace_id)

                new_price = await self._wait_for_tagged_price_change(
                    page, pre_price, trace_id, timeout_ms=3000
                )

                if new_price is None:
                    new_price = await self._read_tagged_price(page, trace_id)
                    if new_price is None:
                        new_price = await self._tag_main_price_element(page, trace_id)

                if new_price and new_price > 0:
                    price_map[value_name] = new_price
                    log.info(f"[{value_name}] 券后价: {new_price}元", trace_id=trace_id)

            if not price_map:
                return []

            log.info(f"点击SKU获取到{len(price_map)}个区间价",
                     trace_id=trace_id, data={"prices": price_map})

            # Step 4: 结合尺码生成完整SKU列表
            sizes = await self._get_size_options_from_ice(page, trace_id)
            skus = []

            for value_name, coupon_price in price_map.items():
                if sizes:
                    for size in sizes:
                        skus.append({
                            "name": f"{value_name} / {size}",
                            "price": coupon_price,
                            "sku_id": None
                        })
                else:
                    skus.append({
                        "name": value_name,
                        "price": coupon_price,
                        "sku_id": None
                    })

            return skus

        except Exception as e:
            log.warning(f"点击SKU策略失败: {e}", trace_id=trace_id)
            return []

    async def _discover_price_affecting_sku_options(
        self, page: Page, trace_id: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        从ICE_CONTEXT动态发现影响价格的SKU维度。
        分析skuBase.props中哪个维度的不同值对应不同价格。
        """
        try:
            result = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (!ctx) return null;
                const res = ctx.loaderData?.home?.data?.res || {};
                const skuBase = res.skuBase || {};
                const skuCore = res.skuCore || {};
                const sku2info = skuCore.sku2info || {};
                const props = skuBase.props || [];
                const skus = skuBase.skus || [];
                if (!props.length || !skus.length) return null;

                // 为每个prop维度，统计不同value对应的价格集合
                for (const prop of props) {
                    const valuePrices = {};
                    for (const val of (prop.values || [])) {
                        valuePrices[val.vid] = new Set();
                    }
                    for (const sku of skus) {
                        const skuId = String(sku.skuId);
                        const info = sku2info[skuId];
                        if (!info) continue;
                        const price = parseFloat(info.price?.priceText || '0');
                        if (price <= 0) continue;
                        const parts = (sku.propPath || '').split(';');
                        for (const part of parts) {
                            const [pid, vid] = part.split(':');
                            if (pid === String(prop.pid) && valuePrices[vid]) {
                                valuePrices[vid].add(price);
                            }
                        }
                    }
                    // 检查该维度是否有不同价格
                    const allMinPrices = new Set();
                    const valueResults = [];
                    for (const val of (prop.values || [])) {
                        const prices = valuePrices[val.vid];
                        if (prices && prices.size > 0) {
                            const minP = Math.min(...prices);
                            allMinPrices.add(minP);
                            valueResults.push({
                                name: val.name,
                                vid: String(val.vid),
                                expectedPrice: minP
                            });
                        }
                    }
                    if (allMinPrices.size > 1) {
                        return {
                            propName: prop.name,
                            propId: String(prop.pid),
                            values: valueResults
                        };
                    }
                }
                return null;
            }""")

            if result:
                log.info(f"发现价格维度: {result['propName']}",
                         trace_id=trace_id, data=result)
            else:
                log.info(f"ICE_CONTEXT中未发现价格差异维度", trace_id=trace_id)
            return result

        except Exception as e:
            log.debug(f"动态SKU发现失败: {e}", trace_id=trace_id)
            return None

    async def _tag_main_price_element(
        self, page: Page, trace_id: Optional[str]
    ) -> Optional[float]:
        """
        找到页面最大字号价格元素，注入data-ae-price标记，返回当前价格。
        """
        try:
            price = await page.evaluate("""() => {
                // 清除旧标记
                const prev = document.querySelector('[data-ae-price]');
                if (prev) prev.removeAttribute('data-ae-price');

                let bestEl = null, bestFS = 0, bestPrice = 0;
                const els = document.querySelectorAll('*');
                for (const el of els) {
                    if (!el.offsetParent && el.tagName !== 'BODY') continue;
                    const text = (el.innerText || '').trim();
                    const m = text.match(/^¥?\\s*(\\d{2,5}(?:\\.\\d{1,2})?)\\s*$/);
                    if (!m) continue;
                    const p = parseFloat(m[1]);
                    if (p < 10 || p > 99999) continue;
                    const cs = window.getComputedStyle(el);
                    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
                    const fs = parseFloat(cs.fontSize);
                    if (fs > bestFS) {
                        bestFS = fs; bestEl = el; bestPrice = p;
                    }
                }
                if (bestEl) {
                    bestEl.setAttribute('data-ae-price', '1');
                    return bestPrice;
                }
                return null;
            }""")
            if price:
                log.info(f"标记主价格元素: {price}元", trace_id=trace_id)
            return price
        except Exception as e:
            log.debug(f"标记价格元素失败: {e}", trace_id=trace_id)
            return None

    async def _read_tagged_price(
        self, page: Page, trace_id: Optional[str]
    ) -> Optional[float]:
        """读取被标记元素的当前价格。标记丢失返回None。"""
        try:
            return await page.evaluate("""() => {
                const el = document.querySelector('[data-ae-price]');
                if (!el) return null;
                const text = (el.innerText || '').trim();
                const m = text.match(/(\\d{2,5}(?:\\.\\d{1,2})?)/);
                return m ? parseFloat(m[1]) : null;
            }""")
        except Exception:
            return None

    async def _wait_for_tagged_price_change(
        self, page: Page, prev_price: float,
        trace_id: Optional[str], timeout_ms: int = 3000
    ) -> Optional[float]:
        """等待被标记元素的价格变化。超时或标记丢失返回None。"""
        try:
            changed = await page.wait_for_function(
                """(prevPrice) => {
                    const el = document.querySelector('[data-ae-price]');
                    if (!el) return true;  // 标记丢失，立即返回
                    const text = (el.innerText || '').trim();
                    const m = text.match(/(\\d{2,5}(?:\\.\\d{1,2})?)/);
                    if (m) {
                        return parseFloat(m[1]) !== prevPrice;
                    }
                    return false;
                }""",
                prev_price,
                timeout=timeout_ms
            )
            # 读取新价格
            new_price = await self._read_tagged_price(page, trace_id)
            if new_price is None:
                # 标记丢失，重新标记
                new_price = await self._tag_main_price_element(page, trace_id)
            return new_price
        except Exception:
            # 超时，价格未变化
            return None

    async def _get_size_options_from_ice(
        self, page: Page, trace_id: Optional[str]
    ) -> List[str]:
        """从ICE_CONTEXT获取尺码选项（非价格影响维度）。"""
        try:
            sizes = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (!ctx) return [];
                const res = ctx.loaderData?.home?.data?.res || {};
                const props = (res.skuBase || {}).props || [];
                for (const prop of props) {
                    const name = (prop.name || '').toLowerCase();
                    if (name.includes('尺码') || name.includes('size') || name.includes('尺寸')) {
                        return (prop.values || []).map(v => v.name);
                    }
                }
                return [];
            }""")
            if sizes:
                log.info(f"获取到{len(sizes)}个尺码选项", trace_id=trace_id)
            return sizes or []
        except Exception:
            return []

    def _merge_coupon_prices(
        self,
        api_skus: List[Dict[str, Any]],
        price_map: Dict[str, float],
        trace_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """将点击获取的券后价合并到API获取的SKU列表中。"""
        for sku in api_skus:
            sku_name = sku.get("name", "")
            for option_name, coupon_price in price_map.items():
                if option_name in sku_name:
                    sku["original_price"] = sku.get("price")
                    sku["price"] = coupon_price
                    break
        return api_skus

    async def _extract_from_network_api(
        self,
        page: Page,
        platform: str,
        trace_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """
        通过网络拦截API提取SKU数据（优先策略）

        拦截淘系内部API并解析SKU信息
        """
        intercepted_data = []
        api_response_received = asyncio.Event()
        captured_responses = []  # 存储所有捕获的响应

        async def handle_response(response: Response):
            """处理响应拦截"""
            try:
                url = response.url

                # 检查是否是淘系详情API（扩展匹配规则，优先匹配PC详情页mtop API）
                api_patterns = [
                    "mtop.taobao.pcdetail.data.get",  # PC详情页主数据（含促销价）
                    "mtop.taobao.detail.getdesc",
                    "mtop.taobao.detail.getdetail",
                    "mtop.taobao.detail.getfull",
                    "mtop.taobao.detail",
                    "detail/simple",
                    "item/detail",
                    "h5/mtop.taobao.detail",
                    "item/detail/get",
                    "sku/detail",
                    "getItemDetail",
                ]

                # 检查是否包含mtop API关键字
                is_mtop_api = "mtop." in url or "mtopjsonp" in url

                if any(pattern in url for pattern in api_patterns):
                    log.debug(f"拦截到API响应", trace_id=trace_id, data={"url": url[:100]})

                    try:
                        body = await response.text()

                        # 处理JSONP格式
                        json_str = body
                        if body.startswith("mtopjsonp") or body.startswith("jsonp"):
                            match = re.search(r'\((.*)\)$', body, re.DOTALL)
                            if match:
                                json_str = match.group(1)

                        # 尝试解析JSON
                        data = json.loads(json_str)
                        captured_responses.append({"url": url, "data": data})

                        # 提取SKU数据
                        skus = self._parse_taobao_api_response(data, trace_id)
                        if skus:
                            intercepted_data.extend(skus)
                            api_response_received.set()
                            log.info(f"API数据解析成功", trace_id=trace_id, data={"sku_count": len(skus), "url": url[:50]})

                    except Exception as e:
                        log.debug(f"API响应解析失败: {e}", trace_id=trace_id)

            except Exception:
                pass

        # 设置响应拦截器
        page.on("response", handle_response)

        try:
            # 滚动页面触发更多请求
            await page.evaluate("""() => {
                window.scrollTo(0, document.body.scrollHeight / 2);
            }""")
            await asyncio.sleep(1)

            # 等待API响应（最多5秒）
            try:
                await asyncio.wait_for(api_response_received.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                log.debug(f"等待API响应超时，捕获{len(captured_responses)}个响应", trace_id=trace_id)

        finally:
            page.remove_listener("response", handle_response)

        return intercepted_data

    def _parse_taobao_api_response(self, data: Dict, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        解析淘系API响应，提取SKU数据

        [改进] 增加对mtop.taobao.pcdetail.data.get API的券后价解析
        """
        skus = []

        try:
            # 处理不同的数据结构
            api_data = data

            # 如果是mtop标准格式 {data: {...}}
            if "data" in data and isinstance(data["data"], dict):
                api_data = data["data"]

            # [新增] 尝试从PC详情页mtop API解析券后价
            # 路径: componentsVO.priceComponent 或 skuCore.sku2info
            coupon_prices = {}  # sku_id -> 券后价
            real_price = None   # 整体到手价

            # 尝试解析 componentsVO.priceComponent（PC详情页主数据）
            if "componentsVO" in api_data:
                comp = api_data["componentsVO"]
                if "priceComponent" in comp:
                    price_comp = comp["priceComponent"]
                    # realPrice 是实际到手价
                    if "realPrice" in price_comp:
                        real_price = price_comp["realPrice"]
                        log.info(f"从priceComponent解析到realPrice: {real_price}", trace_id=trace_id)
                    # extraPrices 可能包含SKU级价格
                    if "extraPrices" in price_comp:
                        for extra in price_comp["extraPrices"]:
                            sku_id = extra.get("skuId")
                            promo_price = extra.get("promotionPrice") or extra.get("price")
                            if sku_id and promo_price:
                                coupon_prices[str(sku_id)] = float(promo_price)

            # 尝试解析 skuCore.sku2info（SKU核心数据）
            if "skuCore" in api_data:
                sku_core = api_data["skuCore"]
                if "sku2info" in sku_core:
                    for sku_id, sku_info in sku_core["sku2info"].items():
                        price_data = sku_info.get("price", {})
                        # 尝试多个券后价字段
                        for field in ["subPrice", "actualPrice", "couponPrice", "dealPrice", "promotionPrice"]:
                            val = price_data.get(field)
                            if val:
                                try:
                                    coupon_prices[sku_id] = float(str(val).replace(",", ""))
                                    log.debug(f"从sku2info.{sku_id}解析到{field}: {val}", trace_id=trace_id)
                                    break
                                except:
                                    pass

            # 查找skuBase或skus字段（多路径尝试）
            sku_base = None
            price_info = None

            # 路径1: data.skuBase
            if "skuBase" in api_data:
                sku_base = api_data["skuBase"]
            # 路径2: data.item.skuBase
            elif "item" in api_data and isinstance(api_data["item"], dict):
                item = api_data["item"]
                if "skuBase" in item:
                    sku_base = item["skuBase"]
                # 路径3: 直接从item获取
                if "skus" in item:
                    sku_base = {"skus": item["skus"]}

            # 查找价格信息
            if "price" in api_data:
                price_info = api_data["price"]
            elif "item" in api_data and isinstance(api_data["item"], dict):
                if "price" in api_data["item"]:
                    price_info = api_data["item"]["price"]

            if not sku_base:
                return []

            # 提取规格属性（颜色、尺码等）
            props = sku_base.get("props", [])
            skus_data = sku_base.get("skus", [])

            # 建立属性值映射 {valueId: valueName}
            value_map = {}
            for prop in props:
                prop_name = prop.get("name", "")
                values = prop.get("values", [])
                for value in values:
                    vid = str(value.get("vid", ""))
                    vname = value.get("name", "")
                    if vid:
                        value_map[vid] = vname

            # 提取价格信息
            default_price = None
            if price_info and isinstance(price_info, dict):
                default_price = price_info.get("price") or price_info.get("nowPrice") or price_info.get("originalPrice")

            # 遍历SKU列表
            for sku_item in skus_data:
                sku_id = str(sku_item.get("skuId", ""))
                prop_path = sku_item.get("propPath", "")

                # 构建SKU名称
                sku_name_parts = []
                if prop_path:
                    # propPath格式: 颜色值ID;尺码值ID 或 1627207:28320;5919063:3266781
                    for part in prop_path.split(";"):
                        if ":" in part:
                            _, vid = part.split(":", 1)
                            if vid in value_map:
                                sku_name_parts.append(value_map[vid])
                        else:
                            # 直接是属性值
                            if part in value_map:
                                sku_name_parts.append(value_map[part])

                sku_name = " / ".join(sku_name_parts) if sku_name_parts else (sku_item.get("name") or f"SKU-{sku_id[-6:] if sku_id else 'unknown'}")

                # 提取价格
                price = None
                original_price = None  # 记录券前价

                # 从sku_item直接获取价格
                price_fields = ["price", "salePrice", "nowPrice", "originalPrice", "promotionPrice"]
                for field in price_fields:
                    if field in sku_item:
                        try:
                            price_val = sku_item[field]
                            if isinstance(price_val, (int, float)):
                                price = float(price_val)
                            elif isinstance(price_val, str):
                                price = float(price_val.replace(",", ""))
                            if price and price > 0:
                                original_price = price  # 这是券前价
                                break
                        except (ValueError, TypeError):
                            continue

                # [新增] 如果有券后价，使用券后价覆盖
                if sku_id in coupon_prices:
                    coupon_price = coupon_prices[sku_id]
                    if coupon_price and coupon_price > 0:
                        price = coupon_price
                        log.info(f"SKU[{sku_name}]使用券后价: {coupon_price}元 (券前价: {original_price}元)", trace_id=trace_id)

                # 如果有整体到手价real_price且没有SKU级券后价，使用real_price
                elif real_price and price:
                    try:
                        rp = float(real_price.replace(",", "") if isinstance(real_price, str) else real_price)
                        if rp > 0 and rp < price:  # 到手价应该小于券前价
                            price = rp
                            log.info(f"SKU[{sku_name}]使用real_price: {rp}元 (券前价: {original_price}元)", trace_id=trace_id)
                    except:
                        pass

                # 如果没有找到价格，使用默认价格
                if price is None and default_price:
                    try:
                        if isinstance(default_price, str):
                            price = float(default_price.replace(",", ""))
                        else:
                            price = float(default_price)
                    except (ValueError, TypeError):
                        pass

                if price is not None and price > 0:
                    skus.append({
                        "name": sku_name,
                        "price": price,
                        "sku_id": sku_id,
                    })

            # 如果没有解析到SKU但有价格，返回默认SKU
            if not skus and default_price:
                try:
                    price = float(default_price.replace(",", "")) if isinstance(default_price, str) else float(default_price)
                    skus.append({
                        "name": "默认SKU",
                        "price": price,
                        "sku_id": None,
                    })
                except:
                    pass

        except Exception as e:
            log.warning(f"API响应解析异常: {e}", trace_id=trace_id)

        return skus

    async def _extract_from_js_hub(self, page: Page, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        通过JavaScript从页面Hub数据提取SKU信息

        淘系页面通常将SKU数据存储在全局变量中
        支持数据源（按优先级）：
        1. __ICE_APP_CONTEXT__ (新版天猫PC详情页)
        2. window.Hub / g_config (传统页面)
        3. Script标签解析
        """
        skus = []

        try:
            # 策略1: 尝试从 __ICE_APP_CONTEXT__ 提取（新版PC详情页）
            ice_skus = await self._extract_from_ice_context(page, trace_id)
            if ice_skus:
                return ice_skus

            # 策略2: 尝试从传统Hub数据提取
            js_script = r"""
            () => {
                // 尝试多个可能的全局变量路径
                const hubs = [
                    window.Hub,
                    window.g_config,
                    window.g_config?.skuval,
                    window.g_config?.skuMap,
                    window.g_skuMap,
                    window.skuMap,
                    window._DATA,
                    window.__INITIAL_STATE__,
                    window.__data,
                ];

                for (const hub of hubs) {
                    if (hub && (hub.skuMap || hub.skuval || hub.skuBase || hub.skus)) {
                        return hub;
                    }
                }

                // 尝试从script标签中提取
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.textContent || '';
                    // 查找包含SKU数据的地方
                    if (text.includes('skuMap') || text.includes('skuBase')) {
                        const match = text.match(/skuMap['"]?:\s*({[^;]+})/);
                        if (match) {
                            try {
                                return JSON.parse(match[1]);
                            } catch (e) {}
                        }
                    }
                }

                return null;
            }
            """

            hub_data = await page.evaluate(js_script)

            if hub_data:
                log.debug(f"从JS Hub获取到数据", trace_id=trace_id, data={"keys": list(hub_data.keys()) if isinstance(hub_data, dict) else "not dict"})

                # 解析Hub数据
                sku_map = hub_data.get("skuMap") or hub_data.get("skuval") or hub_data.get("skuBase")
                if sku_map and isinstance(sku_map, dict):
                    for sku_id, sku_info in sku_map.items():
                        if isinstance(sku_info, dict):
                            price = sku_info.get("price") or sku_info.get("salePrice") or sku_info.get("nowPrice")
                            if price:
                                try:
                                    price_val = float(str(price).replace(",", ""))
                                    skus.append({
                                        "name": sku_info.get("names") or sku_info.get("name") or f"SKU-{sku_id[-6:]}",
                                        "price": price_val,
                                        "sku_id": str(sku_id),
                                    })
                                except:
                                    pass

        except Exception as e:
            log.debug(f"JS Hub提取失败: {e}", trace_id=trace_id)

        return skus

    async def _extract_from_ice_context(self, page: Page, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        从 __ICE_APP_CONTEXT__ 提取SKU数据（新版天猫PC详情页）

        这是2024-2025年新版天猫PC详情页使用的数据结构
        """
        try:
            ice_data = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (!ctx) return null;

                // 提取loaderData中的数据
                const loaderData = ctx.loaderData || {};
                const home = loaderData.home || {};
                const data = home.data || {};
                const res = data.res || {};

                return {
                    hasItem: !!res.item,
                    hasSku: !!res.sku,
                    hasSkuBase: !!res.skuBase,
                    hasSkuCore: !!(res.skuCore && res.skuCore.sku2info),
                    item: res.item,
                    sku: res.sku,
                    skuBase: res.skuBase,
                    skuCore: res.skuCore,
                };
            }""")

            if not ice_data:
                return []

            log.debug(f"从ICE_CONTEXT获取数据", trace_id=trace_id, data={
                "has_item": ice_data.get("hasItem"),
                "has_sku": ice_data.get("hasSku"),
                "has_sku_base": ice_data.get("hasSkuBase"),
                "has_sku_core": ice_data.get("hasSkuCore"),
            })

            skus = []
            sku_base = ice_data.get("skuBase")

            if sku_base and isinstance(sku_base, dict):
                # 提取规格属性
                props = sku_base.get("props", [])
                skus_data = sku_base.get("skus", [])

                log.debug(f"解析skuBase", trace_id=trace_id, data={
                    "props_count": len(props),
                    "skus_count": len(skus_data),
                })

                # 建立属性值映射 {valueId: {name, propName}}
                value_map = {}
                for prop in props:
                    prop_name = prop.get("name", "")
                    values = prop.get("values", [])
                    for value in values:
                        vid = str(value.get("vid", ""))
                        vname = value.get("name", "")
                        if vid:
                            value_map[vid] = {"name": vname, "prop": prop_name}

                # 提取价格信息（从skuCore.sku2info）
                price_map = {}  # skuId -> price

                sku_core = ice_data.get("skuCore")
                if sku_core and isinstance(sku_core, dict):
                    sku2info = sku_core.get("sku2info", {})
                    if sku2info and isinstance(sku2info, dict):
                        for sku_id, sku_info in sku2info.items():
                            if sku_id == "0" or not isinstance(sku_info, dict):
                                continue

                            # 优先从 subPrice 获取到手价（秒杀价/券后价/活动价）
                            sub_price = sku_info.get("subPrice")
                            if sub_price and isinstance(sub_price, dict):
                                sp_text = sub_price.get("priceMoney") or sub_price.get("priceText")
                                if sp_text:
                                    sp_str = str(sp_text).replace(",", "").replace("起", "")
                                    try:
                                        sp_val = float(sp_str)
                                        # priceMoney 是分为单位，priceText 是元
                                        if sub_price.get("priceMoney") and sp_val > 10000:
                                            sp_val = sp_val / 100
                                        if sp_val > 0:
                                            price_map[sku_id] = sp_val
                                            continue
                                    except:
                                        pass

                            # 兜底：从 price 取券前价
                            price_data = sku_info.get("price", {})
                            if price_data:
                                price_text = None
                                price_fields = [
                                    "actualPrice", "couponPrice", "dealPrice",
                                    "finalPrice", "promotionPrice", "priceText",
                                ]
                                for field in price_fields:
                                    val = price_data.get(field)
                                    if val and isinstance(val, (str, float, int)):
                                        price_text = str(val)
                                        break
                                if price_text:
                                    try:
                                        price_val = float(price_text.replace(",", ""))
                                        price_map[sku_id] = price_val
                                    except:
                                        pass

                # 遍历SKU列表
                for sku_item in skus_data:
                    sku_id = str(sku_item.get("skuId", ""))
                    prop_path = sku_item.get("propPath", "")

                    # 构建SKU名称
                    sku_name_parts = []
                    if prop_path:
                        # propPath格式: 颜色值ID;尺码值ID
                        for part in prop_path.split(";"):
                            if ":" in part:
                                _, vid = part.split(":", 1)
                                if vid in value_map:
                                    sku_name_parts.append(value_map[vid]["name"])
                            else:
                                if part in value_map:
                                    sku_name_parts.append(value_map[part]["name"])

                    sku_name = " / ".join(sku_name_parts) if sku_name_parts else f"SKU-{sku_id[-6:] if sku_id else 'unknown'}"

                    # 获取价格
                    price = price_map.get(sku_id)

                    if price is not None and price > 0:
                        skus.append({
                            "name": sku_name,
                            "price": price,
                            "sku_id": sku_id,
                        })

            # 如果从skuBase没有解析到SKU，尝试从item数据提取
            if not skus:
                item = ice_data.get("item")
                if item and isinstance(item, dict):
                    # 尝试提取商品基本价格
                    price_text = item.get("price", "")
                    if not price_text:
                        price_text = item.get("sellPrice", "")

                    if price_text:
                        try:
                            price = float(str(price_text).replace(",", ""))
                            skus.append({
                                "name": "默认SKU",
                                "price": price,
                                "sku_id": None,
                            })
                        except:
                            pass

            if skus:
                log.info(f"ICE_CONTEXT解析成功", trace_id=trace_id, data={"sku_count": len(skus), "prices": list(set(s.get("price") for s in skus))})

            return skus

        except Exception as e:
            log.debug(f"ICE_CONTEXT解析失败: {e}", trace_id=trace_id)
            return []

    async def _extract_coupon_amount(self, page: Page, trace_id: Optional[str]) -> Optional[float]:
        """
        从页面提取优惠券金额
        """
        try:
            # 方法1: 从ICE_CONTEXT中提取优惠券信息
            coupon_data = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (!ctx) return null;

                const res = ctx.loaderData?.home?.data?.res || {};
                const item = res.item || {};
                const skuCore = res.skuCore || {};

                const possibleFields = ['coupon', 'couponAmount', 'couponPrice', 'voucher', 'benefit'];
                for (const field of possibleFields) {
                    if (item[field]) {
                        const val = item[field];
                        if (typeof val === 'number') return val;
                        if (typeof val === 'string') {
                            const match = val.match(/(\\d+)/);
                            if (match) return parseFloat(match[1]);
                        }
                    }
                }

                return null;
            }""")

            if coupon_data and isinstance(coupon_data, (int, float)) and coupon_data > 0:
                log.debug(f"从ICE_CONTEXT获取优惠券: {coupon_data}元", trace_id=trace_id)
                return float(coupon_data)

            return None

        except Exception as e:
            log.debug(f"提取优惠券失败: {e}", trace_id=trace_id)
            return None

    async def _get_current_sku_price(self, page: Page, trace_id: Optional[str]) -> Optional[float]:
        """
        获取当前选中SKU的到手价（券后价）

        策略优先级：
        1. 从DOM元素查找"到手价"、"券后价"标签的价格（最可靠）
        2. 从特定class的价格区域获取（天猫券后价常用class）
        3. 分析所有价格，取最小的（假设到手价是最小价格）
        4. 最后才尝试ICE_CONTEXT（但只取券后价字段，不fallback到priceText）
        """
        try:
            # 策略1: 优先从DOM元素获取券后价（最可靠的方式）
            # 查找包含"到手价"、"券后价"等标签的价格元素
            price_analysis = await page.evaluate(r"""() => {
                const result = {
                    allPrices: [],
                    labeledPrices: [],
                    contextPrices: []
                };

                // 方法1：查找有标签的价格（"到手价"、"券后价"、"实付价"等）
                const priceLabels = ['到手价', '券后价', '实付', '到手', '券后', '优惠后', '折后', '现价', '成交'];
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;

                while (node = walker.nextNode()) {
                    const text = node.textContent?.trim() || '';
                    const parent = node.parentElement;

                    // 检查是否包含价格标签
                    for (const label of priceLabels) {
                        if (text.includes(label)) {
                            // 从包含标签的文本中提取价格
                            const priceMatch = text.match(/¥?\s*(\d+(?:\.\d+)?)/);
                            if (priceMatch) {
                                const price = parseFloat(priceMatch[1]);
                                if (price >= 10 && price <= 10000) {
                                    result.labeledPrices.push({
                                        price: price,
                                        label: label,
                                        text: text.substring(0, 100),
                                        parentClass: parent?.className || ''
                                    });
                                }
                            }
                        }
                    }

                    // 提取所有¥格式价格
                    const matches = text.match(/¥\s*(\d+(?:\.\d+)?)/g);
                    if (matches) {
                        for (const m of matches) {
                            const numMatch = m.match(/\d+(?:\.\d+)?/);
                            if (numMatch) {
                                const price = parseFloat(numMatch[0]);
                                if (price >= 10 && price <= 10000) {
                                    // 获取上下文（前后文本）
                                    const context = parent?.innerText?.substring(0, 150) || text.substring(0, 50);
                                    result.allPrices.push({
                                        price: price,
                                        context: context
                                    });
                                }
                            }
                        }
                    }
                }

                // 方法2：查找特定class的价格区域（天猫/淘宝常用的价格展示class）
                const priceSelectors = [
                    // 天猫券后价/到手价常用选择器（优先级最高）
                    '.Price--real',
                    '.Price--realText',
                    '.ActualPrice--real',
                    '.ActualPrice--realText',
                    '.Content--priceReal',
                    '.Content--priceMain',
                    '[class*="Price--real"]',
                    '[class*="price--real"]',
                    '[class*="ActualPrice"]',
                    '[class*="actualPrice"]',
                    // 其他价格选择器
                    '[class*="PriceReal"]',
                    '[class*="realPrice"]',
                    '[class*="RealPrice"]',
                    '[class*="finalPrice"]',
                    '[class*="FinalPrice"]',
                    '[class*="handPrice"]',
                    '[class*="HandPrice"]',
                    '[class*="dealPrice"]',
                    '[class*="DealPrice"]',
                    '[class*="到手价"]',
                    '[class*="券后价"]',
                    '[class*="priceText"]',
                    '[class*="PriceText"]',
                    '.tm-price',
                    '.tb-price',
                    '#J_StricePrice',
                ];

                for (const sel of priceSelectors) {
                    try {
                        const elements = document.querySelectorAll(sel);
                        for (const el of elements) {
                            const text = el.textContent || '';
                            const nums = text.match(/\d+(?:\.\d+)?/g);
                            if (nums) {
                                for (const n of nums) {
                                    const price = parseFloat(n);
                                    if (price >= 10 && price <= 10000) {
                                        result.contextPrices.push({
                                            price: price,
                                            selector: sel,
                                            className: el.className,
                                            text: text.substring(0, 50)
                                        });
                                    }
                                }
                            }
                        }
                    } catch(e) {}
                }

                // 对价格排序
                result.allPrices.sort((a, b) => a.price - b.price);
                result.labeledPrices.sort((a, b) => a.price - b.price);
                result.contextPrices.sort((a, b) => a.price - b.price);

                return result;
            }""")

            if not price_analysis:
                return None

            # 记录所有找到的价格（调试用）
            all_prices = price_analysis.get("allPrices", [])
            labeled_prices = price_analysis.get("labeledPrices", [])
            context_prices = price_analysis.get("contextPrices", [])

            if all_prices or labeled_prices or context_prices:
                log.debug(f"价格分析结果", trace_id=trace_id, data={
                    "all_prices_count": len(all_prices),
                    "labeled_prices_count": len(labeled_prices),
                    "context_prices_count": len(context_prices),
                    "all_prices": [p.get("price") for p in all_prices[:10]],
                    "labeled_prices": [{"price": p.get("price"), "label": p.get("label")} for p in labeled_prices[:5]],
                    "context_prices": [{"price": p.get("price"), "selector": p.get("selector")} for p in context_prices[:5]],
                })

            # 优先使用有标签的价格（最可靠）
            labeled = price_analysis.get("labeledPrices", [])
            if labeled:
                # 取有标签的最小价格
                for item in labeled:
                    price = item.get("price")
                    if price and price > 0:
                        log.debug(f"使用标签价格", trace_id=trace_id, data={"price": price, "label": item.get("label")})
                        return price

            # 次优先：从特定class获取最小价格
            context_prices = price_analysis.get("contextPrices", [])
            if context_prices:
                for item in context_prices:
                    price = item.get("price")
                    # 检查是否是"到手价"相关class
                    class_name = item.get("className", "") or item.get("selector", "")
                    if any(kw in class_name.lower() for kw in ["real", "actual", "final", "hand", "deal", "到手", "券后"]):
                        if price and price > 0:
                            log.debug(f"使用特定class价格", trace_id=trace_id, data={"price": price, "selector": class_name})
                            return price

            # 最后：分析所有价格，取最小的（假设到手价是最小价格）
            all_prices = price_analysis.get("allPrices", [])
            if all_prices:
                # 过滤掉明显是原价的价格（通常是最大的）
                prices_only = [p.get("price") for p in all_prices if p.get("price")]
                if prices_only:
                    min_price = min(prices_only)

                    # 如果最小价格明显低于其他价格，可能是券后价
                    max_price = max(prices_only)
                    if min_price < max_price * 0.8:  # 券后价通常比原价低20%以上
                        log.debug(f"使用最小价格(疑似券后价)", trace_id=trace_id, data={"min": min_price, "max": max_price})
                        return min_price

                    # 否则返回最小价格
                    return min_price

            # 策略4（最后）：尝试从ICE_CONTEXT获取券后价字段（不fallback到priceText）
            ice_coupon_price = await page.evaluate("""() => {
                const ctx = window.__ICE_APP_CONTEXT__;
                if (!ctx) return null;

                const res = ctx.loaderData?.home?.data?.res || {};
                const skuCore = res.skuCore || {};
                const sku2info = skuCore.sku2info || {};

                // 只尝试券后价字段，不fallback到priceText
                const couponFields = ['actualPrice', 'couponPrice', 'dealPrice', 'finalPrice', 'promotionPrice'];

                for (const skuId in sku2info) {
                    if (skuId === "0") continue;
                    const skuInfo = sku2info[skuId];
                    if (!skuInfo) continue;

                    const priceData = skuInfo.price || {};
                    for (const field of couponFields) {
                        const val = priceData[field];
                        if (val && typeof val !== 'undefined' && val > 0) {
                            return parseFloat(String(val).replace(',', ''));
                        }
                    }
                }

                // 从item获取券后价字段
                const item = res.item || {};
                for (const field of couponFields) {
                    const val = item[field];
                    if (val && typeof val !== 'undefined' && val > 0) {
                        return parseFloat(String(val).replace(',', ''));
                    }
                }

                return null;
            }""")
            if ice_coupon_price and ice_coupon_price > 0 and ice_coupon_price < 10000:
                log.info(f"从ICE_CONTEXT获取券后价字段: {ice_coupon_price}元", trace_id=trace_id)
                return ice_coupon_price

            return None

        except Exception as e:
            log.debug(f"获取当前SKU价格失败: {e}", trace_id=trace_id)
            return None

    async def _get_biggest_font_price(self, page: Page, trace_id: Optional[str], exclude_static: bool = False, prev_price: Optional[float] = None) -> Optional[float]:
        """
        获取页面上字号最大的价格候选值

        天猫详情页设计规范：消费者看到的最醒目价格就是最终到手价
        不依赖任何CSS选择器，只判断字号大小

        Args:
            page: Playwright页面对象
            trace_id: 日志追踪ID
            exclude_static: 是否排除静态价格元素（原价/划线价）
            prev_price: 点击前的价格，用于检测价格变化
        """
        try:
            price_info = await page.evaluate("""() => {
                let allPrices = [];
                let allTexts = [];

                const allElements = document.querySelectorAll('*');
                for (const el of allElements) {
                    if (!el.offsetParent && el.tagName !== 'BODY') continue;

                    const text = (el.innerText || el.textContent || '').trim();

                    if (text.length <= 10 && text.length > 0) {
                        allTexts.push({text: text, tag: el.tagName});
                    }

                    // 匹配价格格式
                    const priceMatch = text.match(/^¥?\\s*(\\d{2,5}(?:\\.\\d{1,2})?)\\s*$/);
                    if (!priceMatch) continue;

                    const price = parseFloat(priceMatch[1]);
                    if (price < 10 || price > 99999) continue;

                    try {
                        const computed = window.getComputedStyle(el);
                        if (computed.display === 'none' || computed.visibility === 'hidden') continue;
                        if (parseFloat(computed.opacity) < 0.1) continue;

                        const fontSize = parseFloat(computed.fontSize);
                        allPrices.push({
                            price: price,
                            fontSize: fontSize
                        });
                    } catch(e) {}
                }

                // 按字号排序（大到小）
                allPrices.sort((a, b) => b.fontSize - a.fontSize);

                return {
                    allPrices: allPrices,
                    allTexts: allTexts.slice(0, 20),
                    // 返回不同价格的列表
                    uniquePrices: [...new Set(allPrices.map(p => p.price))]
                };
            }""")

            all_prices = price_info.get("allPrices", [])
            unique_prices = price_info.get("uniquePrices", [])

            # 详细打印每个价格元素（使用JSON格式便于阅读）
            log.info(f"页面所有价格({len(unique_prices)}个不同): {unique_prices}", trace_id=trace_id)
            for p in all_prices[:5]:
                log.info(f"  价格元素: {p['price']}元 @ {p['fontSize']}px", trace_id=trace_id)

            # 返回最大字号的价格数值（券后价）
            if all_prices:
                biggest = all_prices[0]  # 已按字号排序，第一个是最大字号
                log.info(f"最大字号价格(到手价): {biggest['price']}元 @ {biggest['fontSize']}px", trace_id=trace_id)
                return biggest["price"]

            return None

        except Exception as e:
            log.debug(f"获取最大字号价格失败: {e}", trace_id=trace_id)
            return None

    async def _wait_and_capture_main_price_change(self, page: Page, previous_price: float, trace_id: Optional[str]) -> Optional[float]:
        """
        [多SKU区间价核心方法] 等待主价格区域变化并捕获新价格

        点击SKU后，等待价格区域的文字变化，返回变化后的价格
        """
        try:
            # 等待价格变化（最多5秒）
            new_price = await page.evaluate(r"""(prevPrice) => {
                const mainPriceArea = document.querySelector('[class*="Price--real"]') ||
                                     document.querySelector('[class*="Price--"]') ||
                                     document.querySelector('.tm-price') ||
                                     document.querySelector('[data-spm="price"]');

                if (!mainPriceArea) return null;

                // 获取当前显示的主价格（大字号）
                const allText = mainPriceArea.innerText || '';
                const priceMatch = allText.match(/¥\s*(\d{2,5}(?:\.\d{1,2})?)/);
                if (priceMatch) {
                    const currentPrice = parseFloat(priceMatch[1]);
                    return currentPrice;
                }

                // 如果没有¥符号，尝试直接匹配数字
                const pureMatch = allText.match(/\b(\d{2,5})\b/);
                if (pureMatch) {
                    return parseFloat(pureMatch[1]);
                }

                return null;
            }""", previous_price)

            if new_price and new_price != previous_price:
                log.info(f"主价格区域变化: {previous_price}元 → {new_price}元", trace_id=trace_id)
                return new_price

            # 如果价格没变化，返回None
            log.debug(f"主价格区域未变化，仍为{previous_price}元", trace_id=trace_id)
            return None

        except Exception as e:
            log.debug(f"等待价格变化失败: {e}", trace_id=trace_id)
            return None

    async def _get_all_price_elements_detail(self, page: Page, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        [多SKU区间价核心方法] 获取页面上所有价格元素的详细信息

        返回每个价格元素的：selector、className、price、fontSize、text
        用于对比点击SKU前后的价格变化
        """
        try:
            elements_detail = await page.evaluate(r"""() => {
                const results = [];
                const seenPrices = new Set();

                // [核心改进] 只在价格区域搜索（排除推荐商品、导航等）
                // 天猫价格区域的选择器
                const priceAreaSelectors = [
                    '[class*="Price--"]',
                    '[class*="Content--price"]',
                    '[class*="Info--price"]',
                    '[class*="priceContainer"]',
                    '[class*="PriceContainer"]',
                    '.tm-price',
                    '.tb-price',
                    '#J_PromoPrice',
                    '#J_Price',
                    '[class*="mainPrice"]',
                    '[class*="actualPrice"]',
                    '[class*="realPrice"]',
                    '[data-spm*="price"]',
                ];

                // 找到主价格区域
                const mainPriceArea = document.querySelector('[class*="Price--"]') ||
                                     document.querySelector('[class*="Content--price"]') ||
                                     document.querySelector('.tm-price') ||
                                     document.querySelector('[data-spm="price"]');

                if (!mainPriceArea) {
                    // 如果找不到特定价格区域，使用body范围搜索
                    const fallbackArea = document.body;
                    const allText = fallbackArea.innerText || '';
                    const priceMatches = allText.matchAll(/¥\s*(\d{2,5}(?:\.\d{1,2})?)/g);
                    for (const match of priceMatches) {
                        const price = parseFloat(match[1]);
                        if (price >= 100 && price <= 9999 && !seenPrices.has(price)) {
                            seenPrices.add(price);
                            results.push({
                                price: price,
                                fontSize: 0,
                                text: '¥' + match[1],
                                isVisible: true,
                                className: 'fallback',
                                tagName: 'BODY'
                            });
                        }
                    }
                } else {
                    // 在主价格区域及其相邻元素中搜索
                    const parentArea = mainPriceArea.closest('[class*="Content"]') ||
                                      mainPriceArea.closest('[class*="Info"]') ||
                                      mainPriceArea.parentElement?.parentElement;

                    if (parentArea) {
                        const priceElements = parentArea.querySelectorAll('*');
                        for (const el of priceElements) {
                            const text = (el.innerText || el.textContent || '').trim();
                            if (!text) continue;

                            // 匹配价格
                            const yenMatch = text.match(/¥\s*(\d{2,5}(?:\.\d{1,2})?)/);
                            const pureMatch = text.match(/^\s*(\d{2,5}(?:\.\d{1,2})?)\s*$/);

                            const priceStr = yenMatch ? yenMatch[1] : (pureMatch ? pureMatch[1] : null);
                            if (priceStr) {
                                const price = parseFloat(priceStr);
                                if (price >= 100 && price <= 9999 && !seenPrices.has(price)) {
                                    seenPrices.add(price);
                                    try {
                                        const computed = window.getComputedStyle(el);
                                        const fontSize = parseFloat(computed.fontSize);
                                        const isVisible = computed.display !== 'none' &&
                                                         computed.visibility !== 'hidden';

                                        results.push({
                                            price: price,
                                            fontSize: fontSize,
                                            text: text.substring(0, 20),
                                            isVisible: isVisible,
                                            className: el.className || '',
                                            tagName: el.tagName,
                                            isMainPrice: true
                                        });
                                    } catch(e) {
                                        results.push({
                                            price: price,
                                            fontSize: 0,
                                            text: text.substring(0, 20),
                                            isVisible: true,
                                            className: '',
                                            tagName: el.tagName
                                        });
                                    }
                                }
                            }
                        }
                    }
                }

                // 按价格排序（升序）
                results.sort((a, b) => a.price - b.price);

                return results;
            }""")

            log.info(f"价格元素详情获取完成: {len(elements_detail)}个", trace_id=trace_id)

            # 提取所有价格值
            all_prices = [e["price"] for e in elements_detail]
            unique_prices = sorted(set(all_prices))

            log.info(f"捕获到的所有价格: {unique_prices}", trace_id=trace_id)
            for e in elements_detail[:10]:
                log.info(f"  价格元素: {e['price']}元, {e['text'][:20]}", trace_id=trace_id)

            # 返回带selector字段的数据（兼容后续代码）
            return [{
                "selector": f"price_{e['price']}_{e['tagName']}_{i}",
                "price": e["price"],
                "fontSize": e.get("fontSize", 0),
                "text": e.get("text", ""),
                "className": e.get("className", ""),
                "tagName": e.get("tagName", ""),
                "isVisible": e.get("isVisible", True),
                "isHidden": e.get("isHidden", False),
                "isDataAttr": e.get("isDataAttr", False),
                "index": i
            } for i, e in enumerate(elements_detail)]

        except Exception as e:
            log.debug(f"获取价格元素详情失败: {e}", trace_id=trace_id)
            return []

    async def _get_displayed_price(self, page: Page, trace_id: Optional[str]) -> Optional[float]:
        """
        从页面获取实际显示的价格（券后价）

        遍历页面上所有包含价格数字的元素，找到最终显示的购买价格
        """
        try:
            # 首先尝试从特定元素获取最终价格（更可靠的方式）
            # 淘宝/天猫的券后价通常在特定元素中
            final_price_selectors = [
                ".tm-price",  # 天猫价格
                ".price",  # 通用价格
                "[class*='price']",  # 包含price的class
                "#J_StricePrice",  # 淘宝到手价（旧版）
                ".tb-rmb-num",  # 淘宝价格
            ]

            for selector in final_price_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements:
                        text = await el.inner_text()
                        if text:
                            # 提取数字
                            import re
                            nums = re.findall(r'[\d.]+', text.replace(',', ''))
                            for num in nums:
                                try:
                                    price = float(num)
                                    if 10 <= price <= 10000:
                                        return price
                                except:
                                    pass
                except:
                    pass

            # 回退：遍历页面上所有包含价格数字的元素
            prices = await page.evaluate("""() => {
                const prices = [];

                // 获取页面body中所有可见文本
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
                let node;

                while (node = walker.nextNode()) {
                    const text = node.textContent?.trim();
                    if (!text) continue;

                    // 匹配价格格式：¥数字 或 ￥数字 或 数字元
                    const matches = text.match(/[¥￥]\\s*(\\d+(?:\\.\\d+)?)/g);
                    if (matches) {
                        for (const m of matches) {
                            const numMatch = m.match(/(\\d+(?:\\.\\d+)?)/);
                            if (numMatch) {
                                const price = parseFloat(numMatch[1]);
                                // 只取合理范围的价格 (10-10000)
                                if (price >= 10 && price <= 10000) {
                                    prices.push({
                                        text: text.substring(0, 100),
                                        price: price
                                    });
                                }
                            }
                        }
                    }
                }

                // 返回所有找到的价格，按值排序
                prices.sort((a, b) => a.price - b.price);
                return prices;
            }""")

            if prices and len(prices) > 0:
                # 返回最小的价格（通常是券后价）
                min_price = min(p['price'] for p in prices)
                return min_price

            return None

        except Exception as e:
            log.debug(f"获取显示价格失败: {e}", trace_id=trace_id)
            return None

    async def _extract_from_dom_elements(self, page: Page, platform: str, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        从DOM元素中提取SKU信息

        通过解析页面上的SKU选择器元素
        """
        skus = []

        try:
            # 查找SKU规格容器
            sku_container_selectors = [
                ".tb-sku",  # 淘宝
                ".tm-sku",  # 天猫
                "[class*='Sku']",
                "[class*='sku']",
                ".sku-wrapper",
                ".sku-prop",
            ]

            sku_container = None
            for selector in sku_container_selectors:
                try:
                    container = await page.query_selector(selector)
                    if container:
                        sku_container = container
                        log.debug(f"找到SKU容器", trace_id=trace_id, data={"selector": selector})
                        break
                except:
                    continue

            if not sku_container:
                return []

            # 获取当前显示的价格
            async def get_current_price():
                price_selectors = [
                    ".tm-price",
                    ".tb-rmb-num",
                    ".notranslate",
                    "[class*='price']",
                    ".Price--priceText",
                ]
                for sel in price_selectors:
                    try:
                        el = await page.query_selector(sel)
                        if el:
                            text = await el.inner_text()
                            match = re.search(r'[\d,]+\.?\d*', text)
                            if match:
                                return float(match.group().replace(",", ""))
                    except:
                        continue
                return None

            # 获取SKU选项
            sku_option_selectors = [
                ".tb-sku .tb-prop li",
                ".tb-sku .tb-prop a",
                ".tm-sku .tm-prop li",
                ".sku-prop li",
                "[class*='sku'] [class*='select']",
                "[class*='sku'] li",
            ]

            options = []
            for selector in sku_option_selectors:
                try:
                    opts = await page.query_selector_all(selector)
                    if opts:
                        options = opts
                        log.debug(f"找到SKU选项", trace_id=trace_id, data={"selector": selector, "count": len(opts)})
                        break
                except:
                    continue

            if not options:
                return []

            # 记录已采集的SKU
            collected = set()

            # 遍历选项
            for i, option in enumerate(options[:10]):  # 限制最多10个
                try:
                    # 检查是否可选
                    is_disabled = await option.evaluate("el => el.classList.contains('tb-out-of-stock') || el.disabled || el.getAttribute('disabled')")
                    if is_disabled:
                        continue

                    # 获取SKU名称
                    sku_name = await option.inner_text()
                    sku_name = sku_name.strip()

                    if not sku_name or sku_name in collected:
                        continue

                    # 获取当前价格（作为参考）
                    price = await get_current_price()

                    if price:
                        skus.append({
                            "name": sku_name,
                            "price": price,
                            "sku_id": f"dom-{i}",
                        })
                        collected.add(sku_name)

                except Exception as e:
                    log.debug(f"处理SKU选项失败: {e}", trace_id=trace_id)
                    continue

        except Exception as e:
            log.warning(f"DOM元素提取失败: {e}", trace_id=trace_id)

        return skus

    async def _extract_from_ld_json(self, page: Page, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        从ld+json结构化数据提取价格
        """
        try:
            # 查找ld+json脚本标签
            ld_json_elements = await page.query_selector_all('script[type="application/ld+json"]')

            for element in ld_json_elements:
                content = await element.inner_text()
                try:
                    data = json.loads(content)

                    # 检查是否包含offers
                    if "@type" in data and data["@type"] == "Product":
                        offers = data.get("offers", {})

                        # 处理单个offer
                        if isinstance(offers, dict):
                            price = offers.get("price") or offers.get("lowPrice")
                            if price:
                                log.debug(f"ld+json解析命中", trace_id=trace_id, data={"price": price})
                                return [{
                                    "name": "默认SKU",
                                    "price": float(price),
                                    "sku_id": None,
                                }]

                        # 处理offer数组（多个SKU）
                        if isinstance(offers, list):
                            skus = []
                            for offer in offers:
                                if isinstance(offer, dict):
                                    price = offer.get("price")
                                    sku_name = offer.get("name") or offer.get("sku") or f"SKU-{len(skus)+1}"
                                    if price:
                                        skus.append({
                                            "name": sku_name,
                                            "price": float(price),
                                            "sku_id": offer.get("sku"),
                                        })
                            if skus:
                                return skus

                except json.JSONDecodeError:
                    continue

        except Exception as e:
            log.warning(f"ld+json解析失败: {e}", trace_id=trace_id)

        return []

    async def _extract_from_css_fallback(self, page: Page, trace_id: Optional[str]) -> List[Dict[str, Any]]:
        """
        CSS选择器兜底策略
        """
        try:
            # 淘宝/天猫价格显示区域的选择器
            price_selectors = [
                ".tm-price",
                ".tb-rmb-num",
                ".notranslate",
                "[class*='price']",
                ".Price--priceText",
                "[class*='Price']",
            ]

            for selector in price_selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    # 找最大字号的价格元素（即页面最醒目的价格）
                    max_font_size = 0
                    price_value = None

                    for element in elements:
                        try:
                            font_size = await element.evaluate("el => parseFloat(getComputedStyle(el).fontSize)")
                            text = await element.inner_text()
                            text = text.strip()

                            # 解析价格数值
                            price_match = re.search(r'[\d,.]+', text)
                            if price_match:
                                price_str = price_match.group().replace(',', '')
                                price = float(price_str)

                                if font_size > max_font_size:
                                    max_font_size = font_size
                                    price_value = price

                        except Exception:
                            continue

                    if price_value:
                        log.debug(f"CSS兜底解析命中", trace_id=trace_id, data={"price": price_value})
                        return [{
                            "name": "默认SKU",
                            "price": price_value,
                            "sku_id": None,
                        }]

        except Exception as e:
            log.warning(f"CSS兜底提取失败: {e}", trace_id=trace_id)

        return []

    async def _take_screenshot(
        self,
        page: Page,
        task_id: int,
        trace_id: Optional[str],
        shop_name: Optional[str] = None,
        url: Optional[str] = None,
        product_title: Optional[str] = None
    ) -> Optional[str]:
        """
        截图留证（仅可视区域 + 监控风格时间戳水印）
        """
        try:
            # 生成截图文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screenshot_name = f"task_{task_id}_{timestamp}.png"
            screenshot_path = settings.screenshots_dir / screenshot_name

            # 仅截可视区域（不截全页）
            await page.screenshot(path=str(screenshot_path), full_page=False)

            # 监控风格时间戳水印
            self._add_timestamp_watermark(str(screenshot_path))

            log.debug(
                f"截图完成",
                trace_id=trace_id,
                data={"path": str(screenshot_path), "stored": screenshot_name}
            )
            return screenshot_name

        except Exception as e:
            log.warning(f"截图失败: {e}", trace_id=trace_id)
            return None

    @staticmethod
    def _add_timestamp_watermark(image_path: str) -> None:
        """
        监控风格时间戳水印（左上角白字黑底，类似商场监控视频）
        格式：2026-05-08 22:01:35
        """
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            log.warning("Pillow未安装，跳过水印")
            return

        try:
            img = Image.open(image_path)
            draw = ImageDraw.Draw(img)

            timestamp_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            font_size = max(16, min(img.width // 50, 28))

            # 加载等宽字体（纯 ASCII 无乱码风险）
            font = None
            for fp in [
                "C:/Windows/Fonts/consola.ttf",
                "C:/Windows/Fonts/cour.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                "/System/Library/Fonts/Menlo.ttc",
            ]:
                try:
                    font = ImageFont.truetype(fp, font_size)
                    break
                except Exception:
                    continue
            if font is None:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), timestamp_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad = 6

            # 左上角半透明黑底
            draw.rectangle(
                [(8, 8), (8 + tw + pad * 2, 8 + th + pad * 2)],
                fill=(0, 0, 0, 160),
            )
            draw.text((8 + pad, 8 + pad), timestamp_text, font=font, fill=(255, 255, 255, 230))

            img.save(image_path, quality=95)
        except Exception as e:
            log.warning(f"水印添加失败: {e}")

    def _load_font(self, size: int):
        """加载字体（跨平台兼容）"""
        import platform

        font_paths = []
        system = platform.system()

        if system == "Windows":
            font_paths = [
                "C:/Windows/Fonts/msyh.ttc",
                "C:/Windows/Fonts/simsun.ttc",
                "C:/Windows/Fonts/msyhbd.ttc",
                "C:/Windows/Fonts/simhei.ttf",
            ]
        elif system == "Linux":
            font_paths = [
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
        elif system == "Darwin":
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
            ]

        for font_path in font_paths:
            try:
                return ImageFont.truetype(font_path, size)
            except:
                continue

        try:
            from PIL import ImageFont
            return ImageFont.load_default()
        except:
            return None

    async def parse_product_url(self, url: str) -> Tuple[str, bool]:
        """
        解析商品URL，识别平台
        """
        # 天猫链接识别
        if "tmall.com" in url or "detail.tmall.com" in url:
            return "tmall", True

        # 淘宝链接识别
        if "taobao.com" in url or "item.taobao.com" in url:
            return "taobao", True

        return "unknown", False


# 全局采集引擎实例
_collector_engine: Optional[CollectorEngine] = None


def get_collector_engine() -> CollectorEngine:
    """获取采集引擎实例"""
    global _collector_engine
    if _collector_engine is None:
        _collector_engine = CollectorEngine()
    return _collector_engine
