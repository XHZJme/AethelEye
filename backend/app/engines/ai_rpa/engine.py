"""
筱和灵眸(AethelEye) - AI RPA 采集引擎

继承 BaseCollectionEngine，实现 Skyvern 风格的探索-编译-回放范式。
核心流程：
  1. 有缓存 Workflow → Replay → 成功返回 / 失败自愈 / 自愈失败 → Explore
  2. 无缓存 → Explore → 编译 Workflow → 返回结果

⚠️ 参考 Skyvern 逻辑自行实现，未使用任何 AGPL 代码。
"""
import time
import traceback
import re
from typing import Any, Dict, Optional, Tuple

from app.services.engine_base import BaseCollectionEngine, CollectionResult
from app.engines.ai_rpa.replayer import replay_or_explore
from app.engines.ai_rpa.workflow import get_workflow_store
from app.utils.logger import get_logger

log = get_logger("system")


class AIRPAEngine(BaseCollectionEngine):
    """
    AI RPA 采集引擎

    - ENGINE_NAME = "ai_rpa"
    - 需要 AI 服务绑定（ai_rpa → provider + model）
    - 需要多模态 LLM（截图 + 文本）
    """

    ENGINE_NAME = "ai_rpa"
    ENGINE_DISPLAY_NAME = "AI RPA引擎（Skyvern风格）"

    def __init__(self):
        super().__init__()
        self._max_explore_rounds = 10
        self._timeout_seconds = 60

    def configure(self, max_explore_rounds: int = 10, timeout_seconds: int = 60):
        """运行时配置（从 EngineConfig DB 读取）"""
        self._max_explore_rounds = max_explore_rounds
        self._timeout_seconds = timeout_seconds

    async def collect(
        self,
        task,
        profile_id: int,
        headless: bool = True,
        record_video: bool = False,
        trace_id: Optional[str] = None,
    ) -> CollectionResult:
        """
        执行 AI RPA 采集。

        流程：
          1. 通过 BrowserManager 获取 Page
          2. 导航到目标 URL
          3. replay_or_explore 进行数据提取
          4. 将提取数据转为 CollectionResult
        """
        start = time.time()
        url = task.url
        platform = getattr(task, "platform", "unknown")

        log.info(f"[AI-RPA] collect 开始", data={
            "task_id": task.id, "url": url, "platform": platform,
            "profile_id": profile_id, "trace_id": trace_id,
        })

        # 获取浏览器 Page
        try:
            from app.services.browser_manager import get_browser_manager
            bm = get_browser_manager()
            context = await bm.get_context(profile_id, headless=headless)
            page = await context.new_page()
        except Exception as e:
            return CollectionResult(
                success=False,
                error=f"浏览器启动失败: {str(e)}",
                duration_ms=int((time.time() - start) * 1000),
            )

        try:
            # 导航
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)  # 等待动态内容加载

            # 加载引擎配置
            self._load_config_from_db()

            # 核心：Replay or Explore
            data, workflow = await replay_or_explore(
                page=page,
                url=url,
                platform=platform,
                max_explore_rounds=self._max_explore_rounds,
                timeout_seconds=self._timeout_seconds,
                trace_id=trace_id,
            )

            if data is None:
                return CollectionResult(
                    success=False,
                    error="AI RPA引擎未能提取数据（Explore + Replay 均失败）",
                    duration_ms=int((time.time() - start) * 1000),
                )

            # 转换数据格式为 CollectionResult
            result = self._convert_to_result(data, start)

            # 截图存档
            try:
                screenshot_path = f"screenshots/ai_rpa_{task.id}_{int(time.time())}.png"
                await page.screenshot(path=screenshot_path)
                result.screenshot_path = screenshot_path
            except Exception:
                pass

            return result

        except Exception as e:
            log.error(f"[AI-RPA] collect 异常", data={
                "error": str(e), "traceback": traceback.format_exc(),
                "trace_id": trace_id,
            })
            return CollectionResult(
                success=False,
                error=f"AI RPA引擎异常: {str(e)}",
                duration_ms=int((time.time() - start) * 1000),
            )
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def collect_for_parse(
        self,
        url: str,
        profile_id: int,
        headless: bool = True,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        轻量解析（创建任务前预览商品信息）

        AI RPA 引擎的 collect_for_parse 使用 Explore 模式快速提取基础信息。
        """
        platform, is_valid = await self.parse_product_url(url)
        if not is_valid:
            return {"success": False, "error": f"不支持的URL: {url}"}

        try:
            from app.services.browser_manager import get_browser_manager
            bm = get_browser_manager()
            context = await bm.get_context(profile_id, headless=headless)
            page = await context.new_page()
        except Exception as e:
            return {"success": False, "error": f"浏览器启动失败: {str(e)}"}

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)

            self._load_config_from_db()

            data, _ = await replay_or_explore(
                page=page,
                url=url,
                platform=platform,
                max_explore_rounds=min(self._max_explore_rounds, 5),  # 轻量模式限制轮数
                timeout_seconds=min(self._timeout_seconds, 30),
                trace_id=trace_id,
            )

            if data:
                return {
                    "success": True,
                    "title": data.get("title", data.get("product_title", "")),
                    "shop_name": data.get("shop_name", ""),
                    "skus": data.get("skus", []),
                }
            else:
                return {"success": False, "error": "AI RPA引擎未能解析页面"}

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def parse_product_url(self, url: str) -> Tuple[str, bool]:
        """解析商品URL，识别平台"""
        url_lower = url.lower()
        if "tmall.com" in url_lower:
            return "tmall", True
        elif "taobao.com" in url_lower:
            return "taobao", True
        elif "jd.com" in url_lower:
            return "jd", True
        elif "item.m.jd.com" in url_lower:
            return "jd", True
        else:
            return "unknown", False

    def _load_config_from_db(self):
        """从 EngineConfig 表加载配置"""
        try:
            from app.database import get_sync_session
            from app.models.ai_service_binding import EngineConfig
            with get_sync_session() as session:
                config = session.query(EngineConfig).first()
                if config:
                    self._max_explore_rounds = config.ai_rpa_max_explore_rounds or 10
                    self._timeout_seconds = config.ai_rpa_timeout_seconds or 60
        except Exception:
            pass  # 使用默认值

    def _convert_to_result(self, data: Dict[str, Any], start_time: float) -> CollectionResult:
        """将 AI 提取的原始数据转为 CollectionResult"""
        skus = data.get("skus", [])
        # 确保 SKU 格式统一
        formatted_skus = []
        for sku in skus:
            if isinstance(sku, dict):
                formatted_skus.append({
                    "name": sku.get("name", sku.get("sku_name", "")),
                    "price": sku.get("price", sku.get("到手价", 0)),
                    "sku_id": sku.get("sku_id", ""),
                })
            elif isinstance(sku, str):
                formatted_skus.append({"name": sku, "price": 0, "sku_id": ""})

        return CollectionResult(
            success=len(formatted_skus) > 0,
            product_title=data.get("title", data.get("product_title", "")),
            shop_name=data.get("shop_name", ""),
            skus=formatted_skus,
            error=None if formatted_skus else "未提取到任何SKU",
            duration_ms=int((time.time() - start_time) * 1000),
        )
