"""
筱和灵眸(AethelEye) - 告警服务

价格异动检测和告警推送
- 价格低于基准价判定
- 企微Webhook推送
- 告警防重复
- 静默时段检测
- 采集失败告警
- 账号异常告警
"""
import asyncio
from types import SimpleNamespace
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any, List
import httpx
import json
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.database import get_sync_session
from app.models.alert import Alert
from app.models.sku import SKU
from app.models.task import MonitorTask
from app.models.webhook import WebhookConfig
from app.utils.encryption import decrypt_secret
from app.utils.logger import get_logger

# 日志
log = get_logger("alert")


class AlertService:
    """
    告警服务

    处理价格异动检测和告警推送
    """

    def __init__(self):
        """初始化告警服务"""
        self._http_client = httpx.AsyncClient(timeout=30.0)
        # SQLite单写模型下，串行化告警写入可显著降低锁冲突
        self._db_write_lock = asyncio.Lock()
        self._deferred_alert_queue: asyncio.Queue = asyncio.Queue()
        self._deferred_retry_keys = set()
        self._deferred_worker_task: Optional[asyncio.Task] = None

        # 防重复推送缓存
        # 结构：{sku_id: last_alert_price}
        self._alert_cache: Dict[int, float] = {}
        # 告警写入失败冷却，避免短时间内反复打库放大锁冲突
        self._failed_alert_cooldown: Dict[int, datetime] = {}

        # 静默时段配置（默认凌晨0-8点）
        self._silent_hours_start = 0
        self._silent_hours_end = 8

    async def close(self) -> None:
        """关闭HTTP客户端"""
        if self._deferred_worker_task and not self._deferred_worker_task.done():
            self._deferred_worker_task.cancel()
        await self._http_client.aclose()

    async def check_price_alert(
        self,
        sku: SKU,
        current_price: float,
        webhook_config: Optional[WebhookConfig],
        screenshot_path: Optional[str],
        trace_id: Optional[str] = None
    ) -> bool:
        """
        检查价格异动并触发告警

        Args:
            sku: SKU对象
            current_price: 当前到手价
            webhook_config: Webhook配置
            screenshot_path: 截图路径
            trace_id: 追踪ID

        Returns:
            True: 触发了告警
            False: 未触发告警
        """
        # 检查基准价是否存在
        if not sku.base_price:
            log.debug(f"SKU未配置基准价，跳过检测", sku_id=sku.id, trace_id=trace_id)
            return False

        base_price = float(sku.base_price)

        # 计算价差
        price_diff = current_price - base_price
        price_diff_pct = (price_diff / base_price) * 100

        log.debug(
            f"价格比对",
            sku_id=sku.id,
            trace_id=trace_id,
            data={
                "sku_name": sku.sku_name,
                "current_price": current_price,
                "base_price": base_price,
                "price_diff": price_diff,
                "price_diff_pct": price_diff_pct,
            }
        )

        # 判断是否异动（价格低于基准）
        if price_diff >= 0:
            # 价格正常，清除告警状态
            if sku.status == "alert":
                log.info(
                    f"价格恢复正常",
                    sku_id=sku.id,
                    trace_id=trace_id,
                    data={"sku_name": sku.sku_name, "current_price": current_price}
                )
                # 更新SKU状态
                with get_sync_session() as session:
                    sku_obj = session.query(SKU).filter(SKU.id == sku.id).first()
                    if sku_obj:
                        sku_obj.status = "normal"
                        session.commit()

            # 清除防重复缓存
            if sku.id in self._alert_cache:
                del self._alert_cache[sku.id]

            return False

        # 价格低于基准，触发异动
        cooldown_until = self._failed_alert_cooldown.get(sku.id)
        if cooldown_until and datetime.now() < cooldown_until:
            log.debug(
                "告警写入处于冷却期，跳过本次尝试",
                sku_id=sku.id,
                trace_id=trace_id,
                data={"cooldown_until": cooldown_until.strftime("%Y-%m-%d %H:%M:%S")}
            )
            return False

        # 检查防重复推送
        if sku.id in self._alert_cache:
            last_alert_price = self._alert_cache[sku.id]
            # 如果价格还在同一个异动区间（低于基准），不重复推送
            if current_price < base_price and last_alert_price < base_price:
                log.debug(
                    f"该SKU已有未恢复异动，不重复告警",
                    sku_id=sku.id,
                    trace_id=trace_id
                )
                return False

        # DB级别去重：避免进程重启后内存缓存丢失导致重复告警
        with get_sync_session() as session:
            existing_unresolved = session.query(Alert).filter(
                Alert.sku_id == sku.id,
                Alert.alert_type == "price_drop",
                Alert.status.in_(["new", "confirmed"])
            ).order_by(Alert.detected_at.desc()).first()
            if existing_unresolved:
                log.debug(
                    "该SKU存在未关闭异动，跳过重复创建",
                    sku_id=sku.id,
                    trace_id=trace_id,
                    data={"existing_alert_id": existing_unresolved.id}
                )
                return False

        # 检查静默时段
        if self._is_silent_hours():
            log.debug(
                f"当前为静默时段，异动已记录但不推送",
                trace_id=trace_id,
                data={"current_time": datetime.now().strftime("%H:%M")}
            )
            # 创建异动记录但不推送
            await self._create_alert_record(
                sku=sku,
                current_price=current_price,
                webhook_config=None,  # 不推送
                screenshot_path=screenshot_path,
                trace_id=trace_id
            )
            return True

        # 创建异动记录并推送（失败不阻断采集主流程）
        try:
            await self._create_alert_record(
                sku=sku,
                current_price=current_price,
                webhook_config=webhook_config,
                screenshot_path=screenshot_path,
                trace_id=trace_id
            )
        except OperationalError as e:
            if "database is locked" in str(e).lower():
                await self._enqueue_deferred_alert(
                    sku=sku,
                    current_price=current_price,
                    webhook_config=webhook_config,
                    screenshot_path=screenshot_path,
                    trace_id=trace_id,
                    reason="database_locked"
                )
                log.warning(
                    "告警写入遇到数据库锁，已转入补偿队列",
                    trace_id=trace_id,
                    data={"sku_id": sku.id, "sku_name": sku.sku_name}
                )
                return False
            raise
        except Exception as e:
            await self._enqueue_deferred_alert(
                sku=sku,
                current_price=current_price,
                webhook_config=webhook_config,
                screenshot_path=screenshot_path,
                trace_id=trace_id,
                reason="runtime_error"
            )
            log.error(
                f"创建告警失败，已转入补偿队列: {e}",
                trace_id=trace_id,
                data={"sku_id": sku.id, "sku_name": sku.sku_name, "error": str(e)}
            )
            return False

        # 写入成功后清理失败冷却
        if sku.id in self._failed_alert_cooldown:
            del self._failed_alert_cooldown[sku.id]

        # 更新防重复缓存
        self._alert_cache[sku.id] = current_price

        return True

    async def _ensure_deferred_worker(self) -> None:
        """确保告警补偿worker已启动（仅启动一次）"""
        if self._deferred_worker_task and not self._deferred_worker_task.done():
            return
        self._deferred_worker_task = asyncio.create_task(self._deferred_alert_worker())

    def _build_retry_key(self, sku_id: int, current_price: float) -> str:
        return f"{sku_id}:{round(float(current_price), 2)}"

    async def _enqueue_deferred_alert(
        self,
        sku: SKU,
        current_price: float,
        webhook_config: Optional[WebhookConfig],
        screenshot_path: Optional[str],
        trace_id: Optional[str],
        reason: str
    ) -> None:
        await self._ensure_deferred_worker()
        retry_key = self._build_retry_key(sku.id, current_price)
        if retry_key in self._deferred_retry_keys:
            return
        self._deferred_retry_keys.add(retry_key)
        await self._deferred_alert_queue.put({
            "retry_key": retry_key,
            "retry_count": 0,
            "sku_id": sku.id,
            "sku_name": sku.sku_name,
            "task_id": sku.task_id,
            "base_price": float(sku.base_price) if sku.base_price else 0.0,
            "status": sku.status,
            "current_price": current_price,
            "webhook_config": webhook_config,
            "screenshot_path": screenshot_path,
            "trace_id": trace_id,
            "reason": reason,
        })
        log.warning(
            "告警已加入补偿队列",
            trace_id=trace_id,
            data={"sku_id": sku.id, "retry_key": retry_key, "reason": reason}
        )

    async def _deferred_alert_worker(self) -> None:
        """串行执行告警补偿重试，避免高并发反复打库"""
        while True:
            item = await self._deferred_alert_queue.get()
            retry_key = item["retry_key"]
            retry_count = int(item.get("retry_count", 0))
            try:
                # 指数退避：2s, 4s, 8s
                if retry_count > 0:
                    await asyncio.sleep(2 ** retry_count)

                sku_snapshot = SimpleNamespace(
                    id=item["sku_id"],
                    sku_name=item["sku_name"],
                    task_id=item["task_id"],
                    base_price=item["base_price"],
                    status=item["status"],
                )
                await self._create_alert_record(
                    sku=sku_snapshot,
                    current_price=item["current_price"],
                    webhook_config=item["webhook_config"],
                    screenshot_path=item["screenshot_path"],
                    trace_id=item["trace_id"]
                )
                self._alert_cache[sku_snapshot.id] = item["current_price"]
                self._failed_alert_cooldown.pop(sku_snapshot.id, None)
                self._deferred_retry_keys.discard(retry_key)
                log.info(
                    "告警补偿重试成功",
                    trace_id=item["trace_id"],
                    data={"sku_id": sku_snapshot.id, "retry_count": retry_count}
                )
            except Exception as e:
                if retry_count >= 3:
                    self._deferred_retry_keys.discard(retry_key)
                    self._failed_alert_cooldown[item["sku_id"]] = datetime.now() + timedelta(minutes=10)
                    log.error(
                        f"告警补偿重试最终失败: {e}",
                        trace_id=item["trace_id"],
                        data={"sku_id": item["sku_id"], "retry_count": retry_count}
                    )
                else:
                    item["retry_count"] = retry_count + 1
                    await self._deferred_alert_queue.put(item)
                    log.warning(
                        "告警补偿重试失败，准备下次重试",
                        trace_id=item["trace_id"],
                        data={
                            "sku_id": item["sku_id"],
                            "retry_count": item["retry_count"],
                            "error": str(e)
                        }
                    )
            finally:
                self._deferred_alert_queue.task_done()

    async def _create_alert_record(
        self,
        sku: SKU,
        current_price: float,
        webhook_config: Optional[WebhookConfig],
        screenshot_path: Optional[str],
        trace_id: Optional[str]
    ) -> Any:
        """
        创建异动记录并推送告警

        Args:
            sku: SKU对象
            current_price: 当前价格
            webhook_config: Webhook配置
            screenshot_path: 截图路径
            trace_id: 追踪ID

        Returns:
            Alert对象
        """
        base_price = float(sku.base_price)
        price_diff = current_price - base_price
        price_diff_pct = (price_diff / base_price) * 100

        alert_id: Optional[int] = None
        alert_detected_at: Optional[datetime] = None
        task_snapshot: Optional[SimpleNamespace] = None

        async with self._db_write_lock:
            # SQLite并发写入时可能短暂锁库，增加重试可显著降低丢告警概率
            for attempt in range(3):
                try:
                    with get_sync_session() as session:
                        task = session.query(MonitorTask).filter(MonitorTask.id == sku.task_id).first()
                        if task:
                            task_snapshot = SimpleNamespace(
                                id=task.id,
                                shop_name=task.shop_name,
                                product_title=task.product_title,
                                platform=task.platform,
                            )

                        alert = Alert(
                            sku_id=sku.id,
                            task_id=sku.task_id,
                            alert_type="price_drop",
                            base_price=base_price,
                            alert_price=current_price,
                            price_diff=price_diff,
                            price_diff_pct=price_diff_pct,
                            screenshot_path=screenshot_path,
                            status="new",
                            webhook_sent=False,
                            detected_at=datetime.now(),
                        )

                        session.add(alert)
                        session.commit()
                        session.refresh(alert)
                        alert_id = alert.id
                        alert_detected_at = alert.detected_at
                    break
                except OperationalError as e:
                    is_locked = "database is locked" in str(e).lower()
                    if is_locked and attempt < 2:
                        await asyncio.sleep(0.8 * (attempt + 1))
                        continue
                    raise

        if not alert_id:
            raise RuntimeError("创建异动记录失败")

        alert_snapshot = SimpleNamespace(
            id=alert_id,
            base_price=base_price,
            alert_price=current_price,
            price_diff=price_diff,
            price_diff_pct=price_diff_pct,
            detected_at=alert_detected_at or datetime.now(),
        )

        log.info(
            f"异动记录已创建",
            alert_id=alert_id,
            trace_id=trace_id,
            data={
                "sku_name": sku.sku_name,
                "base_price": base_price,
                "alert_price": current_price,
                "price_diff_pct": round(price_diff_pct, 2),
            }
        )

        # 推送Webhook放到事务外，避免持有数据库连接等待网络
        if webhook_config and webhook_config.is_active and task_snapshot:
            push_success = await self._push_webhook(
                alert=alert_snapshot,
                task=task_snapshot,
                sku=sku,
                webhook_config=webhook_config,
                trace_id=trace_id
            )

            if push_success:
                with get_sync_session() as session:
                    alert_obj = session.query(Alert).filter(Alert.id == alert_id).first()
                    if alert_obj:
                        alert_obj.webhook_sent = True
                        alert_obj.webhook_sent_at = datetime.now()
                        session.commit()

        return alert_snapshot

    async def _push_webhook(
        self,
        alert: Alert,
        task: Any,
        sku: SKU,
        webhook_config: WebhookConfig,
        trace_id: Optional[str]
    ) -> bool:
        """
        推送企微Webhook告警

        Args:
            alert: 异动记录
            task: 监控任务
            sku: SKU
            webhook_config: Webhook配置
            trace_id: 追踪ID

        Returns:
            True: 推送成功
            False: 推送失败
        """
        # 构建Markdown消息
        message = self._build_price_alert_message(alert, task, sku)
        webhook_url = decrypt_secret(webhook_config.webhook_url)
        if not webhook_url:
            log.error("Webhook 地址无法解密，已跳过推送", trace_id=trace_id, data={"alert_id": alert.id})
            return False

        log.info(
            f"Webhook推送发出",
            trace_id=trace_id,
            data={
                "webhook_name": webhook_config.name,
                "alert_id": alert.id,
            }
        )

        try:
            # 解析@人列表（JSON数组字符串 → list）
            import json as _json
            mentioned_list = []
            mentioned_mobile_list = []
            if webhook_config.mentioned_list:
                try:
                    mentioned_list = _json.loads(webhook_config.mentioned_list)
                except Exception:
                    pass
            if webhook_config.mentioned_mobile_list:
                try:
                    mentioned_mobile_list = _json.loads(webhook_config.mentioned_mobile_list)
                except Exception:
                    pass

            # 关键词前缀（部分机器人要求消息体含指定关键词才能发送）
            keyword = getattr(webhook_config, 'keyword', None) or ''
            if keyword and keyword not in message:
                message = f"{keyword}\n{message}"

            # 根据 webhook 类型和消息类型构建不同 payload
            msg_type = getattr(webhook_config, 'msg_type', 'markdown') or 'markdown'

            if webhook_config.webhook_type == "dingtalk":
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "title": "价格异动告警",
                        "text": message,
                    }
                }
                # 钉钉@人
                if mentioned_mobile_list:
                    payload["at"] = {
                        "atMobiles": mentioned_mobile_list,
                        "isAtAll": "@all" in mentioned_mobile_list,
                    }
            elif webhook_config.webhook_type == "wecom":
                if msg_type == "text":
                    # 企业微信 text 类型：支持 mentioned_list / mentioned_mobile_list
                    payload = {
                        "msgtype": "text",
                        "text": {
                            "content": message,
                        }
                    }
                    if mentioned_list:
                        payload["text"]["mentioned_list"] = mentioned_list
                    if mentioned_mobile_list:
                        payload["text"]["mentioned_mobile_list"] = mentioned_mobile_list
                else:
                    # 企业微信 markdown 类型：通过 <@userid> 语法@人
                    at_suffix = ""
                    if mentioned_list:
                        at_suffix = "\n" + " ".join(f"<@{uid}>" for uid in mentioned_list if uid != "@all")
                        if "@all" in mentioned_list:
                            at_suffix += " @所有人"
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {
                            "content": message + at_suffix
                        }
                    }
            else:
                # 自定义 webhook
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": message
                    }
                }

            response = await self._http_client.post(
                webhook_url,
                json=payload,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("errcode") == 0:
                    log.info(
                        f"Webhook推送成功",
                        trace_id=trace_id,
                        data={"alert_id": alert.id, "status_code": response.status_code}
                    )
                    return True
                else:
                    log.warning(
                        f"Webhook推送失败: 企微返回错误",
                        trace_id=trace_id,
                        data={"errcode": result.get("errcode"), "errmsg": result.get("errmsg")}
                    )
                    return False
            else:
                log.error(
                    f"Webhook推送失败: HTTP错误",
                    trace_id=trace_id,
                    data={"status_code": response.status_code}
                )
                return False

        except Exception as e:
            log.error(
                f"Webhook推送异常",
                trace_id=trace_id,
                data={"error": str(e)}
            )
            return False

    def _build_price_alert_message(
        self,
        alert: Alert,
        task: MonitorTask,
        sku: SKU
    ) -> str:
        """
        构建价格异动告警消息（Markdown格式）

        Args:
            alert: 异动记录
            task: 监控任务
            sku: SKU

        Returns:
            Markdown消息内容
        """
        # 构建消息
        message = f"""### 🔴 价格异动告警

> **店铺**：{task.shop_name or '未知店铺'}
> **商品**：{task.product_title or '未知商品'}
> **SKU**：{sku.sku_name}
> **平台**：{task.platform}

| 项目 | 金额 |
|------|------|
| 基准价 | ¥{alert.base_price:.2f} |
| 当前到手价 | ¥{alert.alert_price:.2f} |
| **差额** | **-¥{abs(alert.price_diff):.2f}（{abs(alert.price_diff_pct):.1f}%）** |

⏰ 发现时间：{alert.detected_at.strftime('%Y-%m-%d %H:%M:%S')}
🔗 [查看详情](http://localhost:{settings.port}/tasks/{task.id})
"""
        return message

    @staticmethod
    def _build_webhook_payload(webhook_config: WebhookConfig, title: str, message: str) -> dict:
        """根据 webhook 类型构建正确的 payload 格式"""
        if webhook_config.webhook_type == "dingtalk":
            return {"msgtype": "markdown", "markdown": {"title": title, "text": message}}
        return {"msgtype": "markdown", "markdown": {"content": message}}

    def _is_silent_hours(self) -> bool:
        """
        检查当前是否在静默时段

        Returns:
            True: 在静默时段
            False: 不在静默时段
        """
        current_hour = datetime.now().hour
        return self._silent_hours_start <= current_hour < self._silent_hours_end

    async def create_collect_fail_alert(
        self,
        task_id: int,
        error_message: str,
        webhook_config: Optional[WebhookConfig],
        trace_id: Optional[str] = None
    ) -> Optional[Alert]:
        """
        创建采集失败告警

        Args:
            task_id: 任务ID
            error_message: 错误信息
            webhook_config: Webhook配置
            trace_id: 追踪ID

        Returns:
            Alert对象
        """
        with get_sync_session() as session:
            task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
            if not task:
                return None

            # 检查是否已有未处理的采集失败告警
            existing = session.query(Alert).filter(
                Alert.task_id == task_id,
                Alert.alert_type == "collect_fail",
                Alert.status == "new"
            ).first()

            if existing:
                log.debug(f"已有未处理的采集失败告警，跳过", task_id=task_id, trace_id=trace_id)
                return None

            # 创建告警记录
            alert = Alert(
                sku_id=0,  # 采集失败不关联具体SKU
                task_id=task_id,
                alert_type="collect_fail",
                base_price=0,
                alert_price=0,
                price_diff=0,
                price_diff_pct=0,
                status="new",
                webhook_sent=False,
                detected_at=datetime.now(),
            )

            session.add(alert)
            session.commit()
            session.refresh(alert)

            log.info(
                f"采集失败告警已创建",
                alert_id=alert.id,
                task_id=task_id,
                trace_id=trace_id,
                data={"error": error_message}
            )

            # 推送Webhook
            if webhook_config and webhook_config.is_active and not self._is_silent_hours():
                message = f"""### ⚠️ 采集异常告警

> **商品**：{task.product_title or '未知商品'}
> **店铺**：{task.shop_name or '未知店铺'}
> **异常类型**：采集失败
> **错误信息**：{error_message}

⏰ 发生时间：{alert.detected_at.strftime('%Y-%m-%d %H:%M:%S')}
🔗 [查看详情](http://localhost:{settings.port}/tasks/{task.id})
"""

                payload = self._build_webhook_payload(webhook_config, "采集异常告警", message)
                webhook_url = decrypt_secret(webhook_config.webhook_url)
                if not webhook_url:
                    log.error("Webhook 地址无法解密，已跳过采集失败告警推送", trace_id=trace_id)
                    return alert

                try:
                    response = await self._http_client.post(
                        webhook_url,
                        json=payload
                    )
                    if response.status_code == 200:
                        alert.webhook_sent = True
                        alert.webhook_sent_at = datetime.now()
                        session.commit()
                        log.info(f"采集失败告警已推送", trace_id=trace_id)
                except Exception as e:
                    log.error(f"采集失败告警推送异常: {e}", trace_id=trace_id)

        return alert

    async def create_account_issue_alert(
        self,
        profile_id: int,
        issue_type: str,
        issue_message: str,
        affected_task_count: int,
        webhook_config: Optional[WebhookConfig],
        trace_id: Optional[str] = None
    ) -> Optional[Alert]:
        """
        创建账号异常告警

        Args:
            profile_id: 浏览器配置ID
            issue_type: 异常类型（captcha/login_expired/blocked）
            issue_message: 异常信息
            affected_task_count: 受影响的任务数
            webhook_config: Webhook配置
            trace_id: 追踪ID

        Returns:
            Alert对象
        """
        with get_sync_session() as session:
            from app.models.browser import BrowserProfile

            profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
            if not profile:
                return None

            # 异常类型映射
            type_map = {
                "captcha": "需要验证码",
                "login_expired": "登录态过期",
                "blocked": "账号被封禁",
                "unknown": "未知异常",
            }

            # 创建告警记录
            alert = Alert(
                sku_id=0,
                task_id=0,
                alert_type="account_issue",
                base_price=0,
                alert_price=0,
                price_diff=0,
                price_diff_pct=0,
                status="new",
                webhook_sent=False,
                detected_at=datetime.now(),
            )

            session.add(alert)
            session.commit()
            session.refresh(alert)

            log.warning(
                f"账号异常告警已创建",
                alert_id=alert.id,
                profile_id=profile_id,
                trace_id=trace_id,
                data={"issue_type": issue_type, "issue_message": issue_message}
            )

            # 推送Webhook
            if webhook_config and webhook_config.is_active and not self._is_silent_hours():
                message = f"""### 🔑 账号异常告警

> **配置名称**：{profile.name}
> **异常类型**：{type_map.get(issue_type, issue_type)}
> **影响任务**：{affected_task_count}个监控任务已暂停

⏰ 发生时间：{alert.detected_at.strftime('%Y-%m-%d %H:%M:%S')}
🛠 请尽快登录后台处理
🔗 [前往处理](http://localhost:{settings.port}/browser)
"""

                payload = self._build_webhook_payload(webhook_config, "账号异常告警", message)
                webhook_url = decrypt_secret(webhook_config.webhook_url)
                if not webhook_url:
                    log.error("Webhook 地址无法解密，已跳过账号异常告警推送", trace_id=trace_id)
                    return alert

                try:
                    response = await self._http_client.post(
                        webhook_url,
                        json=payload
                    )
                    if response.status_code == 200:
                        alert.webhook_sent = True
                        alert.webhook_sent_at = datetime.now()
                        session.commit()
                        log.info(f"账号异常告警已推送", trace_id=trace_id)
                except Exception as e:
                    log.error(f"账号异常告警推送异常: {e}", trace_id=trace_id)

        return alert


# 全局告警服务实例
_alert_service: Optional[AlertService] = None


def get_alert_service() -> AlertService:
    """
    获取告警服务实例

    Returns:
        AlertService实例
    """
    global _alert_service
    if _alert_service is None:
        _alert_service = AlertService()
    return _alert_service
