"""
筱和灵眸(AethelEye) - 采集执行服务

封装完整的采集执行流程
- 获取任务和配置
- 执行采集
- 处理结果
- 触发异动检测
- 更新任务状态
"""
import asyncio
import re
import uuid
import json
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_sync_session
from app.models.task import MonitorTask
from app.models.browser import BrowserProfile
from app.models.sku import SKU
from app.models.price_record import PriceRecord
from app.models.sku_change_event import SKUChangeEvent
from app.models.alert import Alert
from app.models.webhook import WebhookConfig
from app.services.browser_manager import get_browser_manager
from app.services.engine_base import CollectionResult
from app.services.engine_registry import get_engine
from app.services.alert_service import get_alert_service
from app.services.sku_note_memory_service import get_sku_note_memory_service
from app.utils.logger import get_logger

# 日志
log = get_logger("collector")


class CollectionExecutor:
    """
    采集执行器

    封装完整的采集执行流程
    """

    def __init__(self):
        """初始化执行器"""
        self.browser_manager = get_browser_manager()
        self.alert_service = get_alert_service()

    @property
    def collector_engine(self):
        """通过引擎注册中心获取当前活跃引擎（支持运行时切换）"""
        return get_engine()

    async def execute_task(self, task_id: int) -> Dict[str, Any]:
        """
        执行指定任务的采集

        Args:
            task_id: 任务ID

        Returns:
            执行结果字典
        """
        # 生成trace_id用于日志追踪
        trace_id = str(uuid.uuid4())[:8]

        log.info(
            f"采集任务开始执行",
            task_id=task_id,
            trace_id=trace_id,
        )

        result = {
            "success": False,
            "task_id": task_id,
            "trace_id": trace_id,
            "skus_updated": 0,
            "alerts_triggered": 0,
            "error": None,
        }

        try:
            # 获取任务信息
            with get_sync_session() as session:
                task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
                if not task:
                    log.error(f"任务不存在", task_id=task_id, trace_id=trace_id)
                    result["error"] = "任务不存在"
                    return result

                if task.status != "active":
                    log.warning(f"任务已暂停，跳过采集", task_id=task_id, trace_id=trace_id)
                    result["error"] = "任务已暂停"
                    return result

                # 获取浏览器配置
                profile = None
                if task.browser_profile_id:
                    profile = session.query(BrowserProfile).filter(
                        BrowserProfile.id == task.browser_profile_id
                    ).first()

                if not profile:
                    log.error(
                        f"任务未配置浏览器",
                        task_id=task_id,
                        trace_id=trace_id
                    )
                    result["error"] = "未配置浏览器"
                    self._update_task_error(session, task, "未配置浏览器")
                    return result

                # 检查浏览器配置是否活跃
                if not profile.is_active:
                    log.warning(
                        f"浏览器配置已禁用",
                        task_id=task_id,
                        trace_id=trace_id,
                        profile_id=profile.id
                    )
                    result["error"] = "浏览器配置已禁用"
                    self._update_task_error(session, task, "浏览器配置已禁用")
                    return result

                # 获取Webhook配置（用于告警）
                webhook_config = None
                if task.webhook_config_id:
                    webhook_config = session.query(WebhookConfig).filter(
                        WebhookConfig.id == task.webhook_config_id
                    ).first()

                # 保存任务信息用于后续处理
                task_info = {
                    "id": task.id,
                    "url": task.url,
                    "platform": task.platform,
                    "recording_enabled": task.recording_enabled,
                    "webhook_config": webhook_config,
                }
                profile_id = profile.id

            # 执行采集
            collection_result = await self._do_collection(
                task_info=task_info,
                profile_id=profile_id,
                trace_id=trace_id
            )

            # 语义兜底：避免“success=true 但没有任何有效价格”的假成功
            if collection_result.success:
                has_priced_sku = self._has_priced_sku(collection_result.skus)
                suspicious_title = self._is_suspicious_page_title(collection_result.product_title)
                if suspicious_title:
                    collection_result.success = False
                    collection_result.error = (
                        f"检测到登录/身份验证页面：{collection_result.product_title or '未知标题'}，"
                        "Cookie可能已失效"
                    )
                elif not has_priced_sku:
                    collection_result.success = False
                    collection_result.error = "未提取到任何SKU价格（疑似反爬或页面结构变化）"

            if not collection_result.success:
                log.error(
                    f"采集失败",
                    task_id=task_id,
                    trace_id=trace_id,
                    data={"error": collection_result.error}
                )
                result["error"] = collection_result.error

                # 更新任务错误状态
                with get_sync_session() as session:
                    task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()

                    # 先判断是否风控，再更新错误状态（避免 _update_task_error 提前改 status 导致后续查询遗漏）
                    is_risk_control = self._should_mark_cookie_expired(
                        error=collection_result.error,
                        page_title=collection_result.product_title,
                    )
                    if is_risk_control:
                        self._mark_cookie_expired(session, profile_id, trace_id, collection_result.error)
                        # 风控检测：暂停该 profile 下所有活跃/need_login 任务，防止继续重试加剧封禁
                        affected_tasks = session.query(MonitorTask).filter(
                            MonitorTask.browser_profile_id == profile_id,
                            MonitorTask.status.in_(["active", "need_login"]),
                        ).all()
                        affected_count = len(affected_tasks)
                        for t in affected_tasks:
                            t.status = "paused"
                            t.last_error = f"[风控自动暂停] {collection_result.error or '检测到反爬拦截'}"
                            # 记录原始 profile（仅首次风控时记录，后续切换不覆盖）
                            if not t.original_browser_profile_id:
                                t.original_browser_profile_id = t.browser_profile_id
                            t.risk_control_retries = (t.risk_control_retries or 0) + 1
                        session.commit()
                        log.warning(
                            f"风控检测：已自动暂停 {affected_count} 个任务",
                            profile_id=profile_id,
                            trace_id=trace_id,
                            data={
                                "affected_task_ids": [t.id for t in affected_tasks],
                                "retry_counts": {t.id: t.risk_control_retries for t in affected_tasks},
                            },
                        )
                        # 发送账号异常告警（含 Webhook 推送）
                        issue_type = "captcha" if self._is_suspicious_page_title(collection_result.product_title) else "login_expired"
                        await self.alert_service.create_account_issue_alert(
                            profile_id=profile_id,
                            issue_type=issue_type,
                            issue_message=collection_result.error or "检测到反爬拦截",
                            affected_task_count=affected_count,
                            webhook_config=task_info.get("webhook_config"),
                            trace_id=trace_id,
                        )
                    else:
                        # 非风控：走普通错误更新（need_login / error 等状态）
                        self._update_task_error(session, task, collection_result.error)
                        # 非风控的普通采集失败告警
                        if collection_result.error:
                            await self.alert_service.create_collect_fail_alert(
                                task_id=task_id,
                                error_message=collection_result.error,
                                webhook_config=task_info.get("webhook_config"),
                                trace_id=trace_id
                            )

                return result

            # 处理采集结果
            alerts_triggered = await self._process_collection_result(
                task_id=task_id,
                collection_result=collection_result,
                webhook_config=task_info.get("webhook_config"),
                trace_id=trace_id
            )

            # 仅在有异动时保留截图，否则删除以节省磁盘
            if alerts_triggered == 0 and collection_result.screenshot_path:
                try:
                    screenshot_file = settings.screenshots_dir / collection_result.screenshot_path
                    if screenshot_file.exists():
                        screenshot_file.unlink()
                        log.debug(
                            f"无异动，已删除截图",
                            task_id=task_id,
                            trace_id=trace_id,
                            data={"deleted": collection_result.screenshot_path}
                        )
                except Exception as e:
                    log.warning(f"删除截图失败: {e}", trace_id=trace_id)

            result["success"] = True
            result["skus_updated"] = len(collection_result.skus)

            # 更新任务成功状态
            with get_sync_session() as session:
                task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
                task.last_check_at = datetime.now()
                task.next_check_at = datetime.now() + timedelta(minutes=task.frequency_minutes)
                task.status = "active"
                task.last_error = None
                # 采集成功 → 重置风控重试计数，还原原始 profile
                if task.risk_control_retries and task.risk_control_retries > 0:
                    log.info(
                        f"采集成功，重置风控重试计数",
                        task_id=task_id,
                        trace_id=trace_id,
                        data={
                            "old_retries": task.risk_control_retries,
                            "current_profile": task.browser_profile_id,
                            "original_profile": task.original_browser_profile_id,
                        }
                    )
                    task.risk_control_retries = 0
                    # 如果当前用的是备用 profile，恢复到原始 profile
                    if task.original_browser_profile_id and task.original_browser_profile_id != task.browser_profile_id:
                        task.browser_profile_id = task.original_browser_profile_id
                    task.original_browser_profile_id = None
                session.commit()

            log.info(
                f"采集任务执行完成",
                task_id=task_id,
                trace_id=trace_id,
                data={
                    "success": True,
                    "skus_updated": result["skus_updated"],
                }
            )

        except Exception as e:
            log.error(
                f"采集执行异常",
                task_id=task_id,
                trace_id=trace_id,
                data={"error": str(e)}
            )
            result["error"] = str(e)

            # 更新任务错误状态
            with get_sync_session() as session:
                task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
                if task:
                    self._update_task_error(session, task, str(e))

        return result

    async def _do_collection(
        self,
        task_info: Dict[str, Any],
        profile_id: int,
        trace_id: str
    ) -> CollectionResult:
        """
        执行实际采集

        Args:
            task_info: 任务信息字典
            profile_id: 浏览器配置ID
            trace_id: 追踪ID

        Returns:
            CollectionResult采集结果
        """
        # 创建临时任务对象用于采集引擎
        class TempTask:
            id = task_info["id"]
            url = task_info["url"]
            platform = task_info["platform"]
            recording_enabled = task_info.get("recording_enabled", False)

        temp_task = TempTask()

        # 重新获取浏览器配置（在新的session中）
        with get_sync_session() as session:
            profile = session.query(BrowserProfile).filter(
                BrowserProfile.id == profile_id
            ).first()

            if not profile:
                log.error(f"浏览器配置不存在", profile_id=profile_id, trace_id=trace_id)
                return CollectionResult(
                    success=False,
                    error="浏览器配置不存在"
                )

        # 读取运行模式设置：silent=无头(后台), visual=有头(显示窗口)
        headless = False  # 默认有头模式
        try:
            from app.models.settings_model import SystemSettings
            with get_sync_session() as s:
                mode_setting = s.query(SystemSettings).filter(SystemSettings.key == "running_mode").first()
                if mode_setting and mode_setting.value == "silent":
                    headless = True
        except Exception:
            pass

        # 同 profile 串行：通过 engine 的 profile 锁，与 parse-url 互斥
        async with self.collector_engine._get_profile_lock(profile_id):
            result = await self.collector_engine.collect(
                task=temp_task,
                profile_id=profile_id,
                headless=headless,
                record_video=temp_task.recording_enabled,
                trace_id=trace_id
            )

        return result

    async def _process_collection_result(
        self,
        task_id: int,
        collection_result: CollectionResult,
        webhook_config: Optional[WebhookConfig],
        trace_id: str
    ) -> int:
        """
        处理采集结果

        - 更新商品信息
        - 更新SKU价格
        - 创建价格记录
        - 触发异动检测

        Args:
            task_id: 任务ID
            collection_result: 采集结果
            existing_sku_map: 已有SKU映射
            webhook_config: Webhook配置
            trace_id: 追踪ID
        """
        with get_sync_session() as session:
            task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
            # 在当前会话中读取SKU，避免跨会话对象导致Detached错误
            existing_skus = session.query(SKU).filter(SKU.task_id == task_id).all()
            existing_sku_map = {sku.sku_name: sku for sku in existing_skus}
            # 辅助匹配：按 sku_id_external 查找（不同策略名称可能不同，但 skuId 稳定）
            existing_sku_by_ext_id = {}
            for sku in existing_skus:
                if sku.sku_id_external:
                    existing_sku_by_ext_id[str(sku.sku_id_external)] = sku
            # 辅助匹配：按归一化名称查找（忽略空格、分隔符差异）
            def _normalize_sku_name(name: str) -> str:
                """归一化SKU名称用于模糊匹配"""
                # 去掉前后空格，统一分隔符，去掉属性名前缀(如"颜色:")
                parts = re.split(r'\s*/\s*', name.strip())
                cleaned = []
                for p in parts:
                    # 去掉 "属性名:" 前缀
                    if ':' in p:
                        p = p.split(':', 1)[1]
                    cleaned.append(p.strip())
                return ' / '.join(cleaned)

            existing_sku_by_normalized = {}
            for sku in existing_skus:
                norm = _normalize_sku_name(sku.sku_name)
                existing_sku_by_normalized[norm] = sku

            memory_service = get_sku_note_memory_service()
            has_priced_sku = self._has_priced_sku(collection_result.skus)
            suspicious_title = self._is_suspicious_page_title(collection_result.product_title)

            # 更新商品信息
            if collection_result.product_title and has_priced_sku and not suspicious_title:
                task.product_title = collection_result.product_title
            if collection_result.shop_name and has_priced_sku and not suspicious_title:
                task.shop_name = collection_result.shop_name
            if collection_result.screenshot_path:
                # 保存最新截图路径（可选）
                pass

            # 处理SKU价格（先写DB，再异步告警，避免长事务锁库）
            alerts_triggered = 0
            alert_candidates: List[Dict[str, Any]] = []

            for idx, sku_data in enumerate(collection_result.skus):
                sku_name = sku_data.get("name", "默认SKU")
                current_price = sku_data.get("price")
                collected_ext_id = sku_data.get("sku_id")

                if current_price is None:
                    continue

                # 查找已有SKU：精确名称 → sku_id_external → 归一化名称
                sku = existing_sku_map.get(sku_name)
                if not sku and collected_ext_id:
                    sku = existing_sku_by_ext_id.get(str(collected_ext_id))
                    if sku:
                        log.info(f"SKU通过sku_id_external匹配: {sku.sku_name} → {sku_name}",
                                 task_id=task_id, trace_id=trace_id)
                        # 更新SKU名称为最新采集到的名称
                        old_name = sku.sku_name
                        sku.sku_name = sku_name
                        existing_sku_map.pop(old_name, None)
                        existing_sku_map[sku_name] = sku
                if not sku:
                    norm_name = _normalize_sku_name(sku_name)
                    sku = existing_sku_by_normalized.get(norm_name)
                    if sku:
                        log.info(f"SKU通过归一化名称匹配: {sku.sku_name} → {sku_name}",
                                 task_id=task_id, trace_id=trace_id)
                        old_name = sku.sku_name
                        sku.sku_name = sku_name
                        existing_sku_map.pop(old_name, None)
                        existing_sku_map[sku_name] = sku
                if not sku:
                    # 创建新SKU
                    sku = SKU(
                        task_id=task_id,
                        sku_name=sku_name,
                        sku_id_external=sku_data.get("sku_id"),
                        current_price=current_price,
                        is_monitored=True,
                        status="normal",
                        sort_order=idx,
                        last_updated_at=datetime.now(),
                    )
                    session.add(sku)
                    # 立即刷新以拿到自增ID，避免后续价格记录写入sku_id=0
                    session.flush()

                    # 保守自动匹配备注记忆（仅自动填充，不覆盖人工已有值）
                    memory_match = memory_service.match_note(
                        session=session,
                        platform=task.platform,
                        shop_name=task.shop_name,
                        sku_name=sku_name,
                    )
                    if memory_match.get("note"):
                        sku.note = memory_match["note"]
                    elif memory_match.get("conflict"):
                        log.warning(
                            "SKU备注记忆冲突，需人工核查",
                            task_id=task_id,
                            sku_id=sku.id,
                            trace_id=trace_id,
                            data={
                                "sku_name": sku_name,
                                "candidates": memory_match.get("candidates", []),
                            }
                        )

                    log.info(
                        f"新SKU已创建",
                        task_id=task_id,
                        trace_id=trace_id,
                        data={
                            "sku_name": sku_name,
                            "price": current_price,
                            "note": sku.note,
                        }
                    )

                    session.add(
                        SKUChangeEvent(
                            task_id=task_id,
                            sku_id=sku.id,
                            sku_name=sku_name,
                            source="collector",
                            change_type="created",
                            changed_fields="current_price,note",
                            old_values=json.dumps({}, ensure_ascii=False),
                            new_values=json.dumps(
                                {
                                    "current_price": float(current_price),
                                    "note": (sku.note or "").strip(),
                                },
                                ensure_ascii=False,
                            ),
                            changed_by=None,
                            changed_at=datetime.now(),
                        )
                    )
                else:
                    # 更新价格和排序
                    old_price = sku.current_price
                    sku.current_price = current_price
                    sku.sort_order = idx
                    sku.last_updated_at = datetime.now()
                    # 同步 sku_id_external（首次采集可能没有，后续策略可能获取到）
                    if collected_ext_id and not sku.sku_id_external:
                        sku.sku_id_external = str(collected_ext_id)

                    # 价格异常波动校验：偏差超50%记录警告
                    if old_price and current_price and old_price > 0:
                        diff_pct = abs(float(current_price) - float(old_price)) / float(old_price)
                        if diff_pct > 0.5:
                            log.warning(
                                f"价格异常波动: {sku_name} {old_price}→{current_price} (偏差{diff_pct:.0%})",
                                task_id=task_id,
                                trace_id=trace_id,
                                data={
                                    "sku_name": sku_name,
                                    "old_price": old_price,
                                    "new_price": current_price,
                                    "diff_pct": round(diff_pct * 100, 1),
                                }
                            )

                    # 仅在当前SKU没有备注时自动补齐
                    if not (sku.note or "").strip():
                        memory_match = memory_service.match_note(
                            session=session,
                            platform=task.platform,
                            shop_name=task.shop_name,
                            sku_name=sku_name,
                        )
                        if memory_match.get("note"):
                            sku.note = memory_match["note"]
                        elif memory_match.get("conflict"):
                            log.warning(
                                "SKU备注记忆冲突，需人工核查",
                                task_id=task_id,
                                sku_id=sku.id,
                                trace_id=trace_id,
                                data={
                                    "sku_name": sku_name,
                                    "candidates": memory_match.get("candidates", []),
                                }
                            )

                    log.debug(
                        f"SKU价格已更新",
                        task_id=task_id,
                        trace_id=trace_id,
                        data={
                            "sku_name": sku_name,
                            "old_price": old_price,
                            "new_price": current_price
                        }
                    )

                    old_price_num = float(old_price) if old_price is not None else None
                    new_price_num = float(current_price) if current_price is not None else None
                    if old_price_num != new_price_num:
                        session.add(
                            SKUChangeEvent(
                                task_id=task_id,
                                sku_id=sku.id,
                                sku_name=sku_name,
                                source="collector",
                                change_type="price_update",
                                changed_fields="current_price",
                                old_values=json.dumps({"current_price": old_price_num}, ensure_ascii=False),
                                new_values=json.dumps({"current_price": new_price_num}, ensure_ascii=False),
                                changed_by=None,
                                changed_at=datetime.now(),
                            )
                        )

                # 创建价格记录
                if not sku.id:
                    # 正常情况下flush后一定有ID，这里作为兜底防御
                    session.flush()
                if not sku.id:
                    continue
                price_record = PriceRecord(
                    sku_id=sku.id,
                    task_id=task_id,
                    price=current_price,
                    screenshot_path=collection_result.screenshot_path,
                    recording_path=collection_result.recording_path,
                    collected_at=datetime.now(),
                )
                session.add(price_record)

                # 收集异动检测候选，事务外执行告警
                if sku.is_monitored and sku.base_price:
                    alert_candidates.append({
                        "sku_id": sku.id,
                        "sku_name": sku.sku_name,
                        "task_id": sku.task_id,
                        "base_price": float(sku.base_price),
                        "status": sku.status,
                        "current_price": current_price,
                    })

            session.commit()

        alerted_sku_ids: List[int] = []
        for candidate in alert_candidates:
            sku_snapshot = SimpleNamespace(
                id=candidate["sku_id"],
                sku_name=candidate["sku_name"],
                task_id=candidate["task_id"],
                base_price=candidate["base_price"],
                status=candidate["status"],
            )
            is_alert = await self.alert_service.check_price_alert(
                sku=sku_snapshot,
                current_price=candidate["current_price"],
                webhook_config=webhook_config,
                screenshot_path=collection_result.screenshot_path,
                trace_id=trace_id
            )
            if is_alert:
                alerts_triggered += 1
                alerted_sku_ids.append(candidate["sku_id"])

        if alerted_sku_ids:
            with get_sync_session() as session:
                session.query(SKU).filter(SKU.id.in_(alerted_sku_ids)).update(
                    {"status": "alert"},
                    synchronize_session=False
                )

        log.info(
            f"采集结果处理完成",
            task_id=task_id,
            trace_id=trace_id,
            data={
                "skus_processed": len(collection_result.skus),
                "alerts_triggered": alerts_triggered,
            }
        )

        return alerts_triggered

    def _update_task_error(self, session: Session, task: MonitorTask, error: str) -> None:
        """
        更新任务错误状态

        Args:
            session: 数据库会话
            task: 任务对象
            error: 错误信息
        """
        task.last_error = error
        task.last_check_at = datetime.now()
        if task.status in ("active", "need_login") and task.frequency_minutes:
            task.next_check_at = datetime.now() + timedelta(minutes=task.frequency_minutes)

        # 检查是否需要标记为异常状态
        if self._is_login_related_error(error):
            task.status = "need_login"

        session.commit()

    @staticmethod
    def _has_priced_sku(skus: List[Dict[str, Any]]) -> bool:
        for sku in skus or []:
            price = sku.get("price")
            if price is None:
                continue
            try:
                if float(price) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    @staticmethod
    def _is_suspicious_page_title(title: Optional[str]) -> bool:
        if not title:
            return False
        text = (title or "").strip().lower()
        keywords = (
            "身份验证",
            "安全验证",
            "请完成验证",
            "验证码",
            "阿里巴巴集团",
            "登录",
            "verification",
            "captcha",
            "login",
            "滑块",
            "punish",
            "拦截",
            "forbidden",
        )
        return any(k in text for k in keywords)

    @staticmethod
    def _is_login_related_error(error: Optional[str]) -> bool:
        if not error:
            return False
        text = (error or "").strip().lower()

        non_login_markers = (
            "未提取到任何sku价格",
            "页面结构变化",
            "反爬",
            "选择器",
            "dom",
        )
        if any(marker in text for marker in non_login_markers):
            return False

        login_markers = (
            "login.taobao.com",
            "login.tmall.com",
            "请登录",
            "亲，请登录",
            "二维码登录",
            "cookie已失效",
            "cookie 失效",
            "重新登录",
            "身份验证",
            "安全验证",
            "验证码",
            "风控拦截",
            "captcha",
            "punish",
            "login",
            "verification",
            "sec.taobao",
        )
        return any(marker in text for marker in login_markers)

    def _should_mark_cookie_expired(
        self,
        error: Optional[str],
        page_title: Optional[str],
    ) -> bool:
        if self._is_suspicious_page_title(page_title):
            return True
        return self._is_login_related_error(error)

    def _mark_cookie_expired(
        self,
        session: Session,
        profile_id: int,
        trace_id: str,
        reason: Optional[str],
    ) -> None:
        profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
        if not profile:
            return
        profile.cookie_status = "expired"
        profile.last_check_at = datetime.now()

        # 同平台其他 cookie_status=valid 但 last_login_at 超过7天的 profile 降级为 unknown，
        # 防止风控恢复时盲目切换到实际已过期但 DB 标记未更新的 profile
        stale_cutoff = datetime.now() - timedelta(days=7)
        stale_profiles = session.query(BrowserProfile).filter(
            BrowserProfile.platform == profile.platform,
            BrowserProfile.id != profile_id,
            BrowserProfile.cookie_status == "valid",
            (BrowserProfile.last_login_at < stale_cutoff) | (BrowserProfile.last_login_at.is_(None)),
        ).all()
        for sp in stale_profiles:
            sp.cookie_status = "unknown"
            log.info(
                "同平台Profile cookie标记降级为unknown（登录态超过7天未确认）",
                profile_id=sp.id,
                trace_id=trace_id,
            )

        session.commit()
        log.warning(
            "检测到登录态异常，浏览器Cookie状态已标记为expired",
            profile_id=profile_id,
            trace_id=trace_id,
            data={"reason": reason, "stale_downgraded": [sp.id for sp in stale_profiles]},
        )


# 全局采集执行器实例
_collection_executor: Optional[CollectionExecutor] = None


def get_collection_executor() -> CollectionExecutor:
    """
    获取采集执行器实例

    Returns:
        CollectionExecutor实例
    """
    global _collection_executor
    if _collection_executor is None:
        _collection_executor = CollectionExecutor()
    return _collection_executor
