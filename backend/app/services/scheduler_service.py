"""
筱和灵眸(AethelEye) - 调度服务

基于APScheduler的定时任务调度
- 监控任务定时采集
- 任务注册/移除
- 调度状态管理
"""
import asyncio
from typing import Optional, Dict, Any, Set
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

from app.config import settings
from app.utils.logger import get_logger
from app.database import get_sync_session
from app.models.task import MonitorTask

# 日志
log = get_logger("system")


class SchedulerService:
    """
    调度服务

    管理采集任务的定时调度
    """

    # 最大并发采集数（每个任务在独立 tab 中执行，受信号量控制）
    MAX_CONCURRENT_COLLECTIONS = 3

    def __init__(self):
        """初始化调度器"""
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running = False
        # 并发控制：信号量限制同时运行的采集任务数
        self._semaphore: Optional[asyncio.Semaphore] = None
        # 防止同一任务重复派发
        self._running_task_ids: Set[int] = set()

    def start(self) -> None:
        """
        启动调度器
        """
        if self._running:
            log.warning("调度器已运行，跳过启动")
            return

        # 创建调度器配置
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': AsyncIOExecutor()
        }

        # 创建调度器
        self._scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            timezone=settings.timezone,
        )
        self._scheduler.add_listener(
            self._on_job_event,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR
        )

        # 启动调度器
        self._scheduler.start()
        self._running = True
        self._semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_COLLECTIONS)

        # 注册自动清理任务（每小时检查一次，按保留天数清理旧录屏和截图）
        self._scheduler.add_job(
            func=self._auto_cleanup,
            trigger=IntervalTrigger(hours=1, timezone=settings.timezone),
            id="auto_cleanup",
            name="自动清理旧录屏/截图",
            max_instances=1,
            coalesce=True,
        )

        # 注册风控冷却自动恢复检查（每5分钟）
        self._scheduler.add_job(
            func=self._risk_control_cooldown_check,
            trigger=IntervalTrigger(minutes=5, timezone=settings.timezone),
            id="risk_control_cooldown",
            name="风控冷却自动恢复",
            max_instances=1,
            coalesce=True,
        )

        log.info(
            "调度器启动完成",
            data={
                "timezone": settings.timezone,
            }
        )

    def stop(self) -> None:
        """
        停止调度器
        """
        if not self._running:
            return

        if self._scheduler:
            self._scheduler.shutdown(wait=True)
            self._scheduler = None
        self._semaphore = None
        self._running_task_ids.clear()

        self._running = False
        log.info("调度器已停止")

    def register_task(self, task: MonitorTask) -> None:
        """
        注册监控任务到调度器

        Args:
            task: 监控任务对象
        """
        if not self._running:
            log.warning("调度器未启动，无法注册任务")
            return

        job_id = f"task_{task.id}"

        # 移除已有任务（如果有）
        self.remove_task(task.id)

        # 只注册活跃任务
        if task.status != "active":
            log.debug(f"任务状态为{task.status}，跳过注册", task_id=task.id)
            return

        # 创建触发器（间隔执行）
        trigger = IntervalTrigger(
            minutes=task.frequency_minutes,
            timezone=settings.timezone,
        )

        # 注册任务
        self._scheduler.add_job(
            func=self._enqueue_collection_task,
            trigger=trigger,
            id=job_id,
            args=[task.id],
            name=f"采集任务-{task.id}",
            max_instances=3,  # 入队动作轻量，允许短暂重叠避免调度跳过
            coalesce=False,  # 不合并错过的任务，确保周期触发可排队
            misfire_grace_time=300,  # 重启/抖动后允许补偿入队
        )

        # 同步 DB 的 next_check_at，使前端显示与调度器实际触发时间一致
        actual_next = self._scheduler.get_job(job_id).next_run_time
        if actual_next:
            from datetime import datetime
            # APScheduler 返回 aware datetime，转为 naive 以匹配 DB
            next_naive = actual_next.replace(tzinfo=None)
            try:
                with get_sync_session() as session:
                    db_task = session.query(MonitorTask).filter(
                        MonitorTask.id == task.id
                    ).first()
                    if db_task and db_task.next_check_at != next_naive:
                        db_task.next_check_at = next_naive
                        session.commit()
            except Exception as e:
                log.warning(f"同步next_check_at失败: {e}", task_id=task.id)

        log.info(
            f"监控任务已注册到调度器",
            task_id=task.id,
            data={
                "frequency_minutes": task.frequency_minutes,
                "next_run_time": str(actual_next),
            }
        )

    def remove_task(self, task_id: int) -> None:
        """
        从调度器移除任务

        Args:
            task_id: 任务ID
        """
        if not self._running:
            return

        job_id = f"task_{task_id}"

        try:
            job = self._scheduler.get_job(job_id)
            if job:
                self._scheduler.remove_job(job_id)
                log.info(f"任务已从调度器移除", task_id=task_id)
        except Exception as e:
            log.warning(f"移除任务失败: {e}", task_id=task_id)

    def update_task_frequency(self, task_id: int, frequency_minutes: int) -> None:
        """
        更新任务频率

        Args:
            task_id: 任务ID
            frequency_minutes: 新频率（分钟）
        """
        # 移除旧任务并重新注册
        with get_sync_session() as session:
            task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
            if task:
                task.frequency_minutes = frequency_minutes
                session.commit()
                self.register_task(task)

    def load_all_tasks(self) -> None:
        """
        加载所有活跃任务到调度器

        从数据库读取所有status=active的任务并注册
        """
        if not self._running:
            log.warning("调度器未启动，无法加载任务")
            return

        with get_sync_session() as session:
            tasks = session.query(MonitorTask).filter(
                MonitorTask.status == "active"
            ).all()

            for task in tasks:
                self.register_task(task)

        log.info(
            f"所有活跃任务已加载到调度器",
            data={
                "task_count": len(tasks),
            }
        )

    def get_scheduler_status(self) -> Dict[str, Any]:
        """
        获取调度器状态

        Returns:
            状态信息字典
        """
        if not self._running:
            return {
                "running": False,
                "jobs_count": 0,
                "jobs": [],
            }

        jobs = []
        for job in self._scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time) if job.next_run_time else None,
            })

        return {
            "running": True,
            "jobs_count": len(jobs),
            "jobs": jobs,
        }

    async def _enqueue_collection_task(self, task_id: int) -> None:
        """
        调度触发时直接派发并发任务（受信号量控制并发数）
        """
        if task_id in self._running_task_ids:
            log.debug("任务已在执行中，跳过重复派发", task_id=task_id)
            return

        self._running_task_ids.add(task_id)
        running_count = len(self._running_task_ids)
        log.info(
            "调度触发采集任务派发",
            task_id=task_id,
            data={"running_count": running_count, "max_concurrent": self.MAX_CONCURRENT_COLLECTIONS}
        )
        asyncio.create_task(self._run_with_semaphore(task_id))

    async def _run_with_semaphore(self, task_id: int) -> None:
        """并发控制包装器：通过信号量限制同时运行的采集任务数"""
        if not self._semaphore:
            self._running_task_ids.discard(task_id)
            return
        try:
            async with self._semaphore:
                from app.services.collection_executor import get_collection_executor
                log.info(
                    "并发采集开始",
                    task_id=task_id,
                    data={"running_count": len(self._running_task_ids)}
                )
                executor = get_collection_executor()
                await executor.execute_task(task_id)
        except Exception as e:
            log.error(
                "并发采集任务失败",
                task_id=task_id,
                error=str(e)
            )
        finally:
            self._running_task_ids.discard(task_id)

    async def _auto_cleanup(self) -> None:
        """
        自动清理旧录屏和截图（类似监控摄像头TF卡循环覆盖）

        读取 system_settings 中的保留天数配置，删除超期文件
        """
        from datetime import datetime, timedelta
        from app.models.settings_model import SystemSettings

        try:
            with get_sync_session() as session:
                # 读取录屏保留天数
                rec_setting = session.query(SystemSettings).filter(
                    SystemSettings.key == "recording_retention_days"
                ).first()
                recording_days = int(rec_setting.value) if rec_setting else 7

                # 截图也按同样天数清理（异动截图）
                screenshot_days = recording_days

            now = datetime.now()
            deleted_recordings = 0
            deleted_screenshots = 0

            # 清理旧录屏
            if settings.recordings_dir.exists():
                rec_cutoff = now - timedelta(days=recording_days)
                for f in settings.recordings_dir.glob("*.webm"):
                    if datetime.fromtimestamp(f.stat().st_mtime) < rec_cutoff:
                        f.unlink()
                        deleted_recordings += 1

            # 清理旧截图
            if settings.screenshots_dir.exists():
                ss_cutoff = now - timedelta(days=screenshot_days)
                for f in settings.screenshots_dir.glob("*.png"):
                    if datetime.fromtimestamp(f.stat().st_mtime) < ss_cutoff:
                        f.unlink()
                        deleted_screenshots += 1

            if deleted_recordings > 0 or deleted_screenshots > 0:
                log.info(
                    "自动清理完成",
                    data={
                        "deleted_recordings": deleted_recordings,
                        "deleted_screenshots": deleted_screenshots,
                        "recording_retention_days": recording_days,
                    }
                )

        except Exception as e:
            log.error("自动清理异常", data={"error": str(e)})

    # 连续风控重试上限：超过此次数彻底暂停，不再自动恢复
    MAX_RISK_CONTROL_RETRIES = 3

    async def _risk_control_cooldown_check(self) -> None:
        """
        访问限制冷却后进行有限次数的同配置重试

        流程：
        1. 查找因风控暂停且已过冷却期的任务
        2. 超过重试上限 → 保持暂停并通知管理员
        3. 未超过上限 → 使用原浏览器配置恢复一次

        本开源版不会自动切换账号或修改浏览器指纹。使用者应遵守目标
        平台的服务条款、robots 规则、访问频率限制和授权范围。
        """
        from datetime import datetime, timedelta
        from app.models.settings_model import SystemSettings

        try:
            with get_sync_session() as session:
                # 读取冷却时间配置
                cooldown_setting = session.query(SystemSettings).filter(
                    SystemSettings.key == "risk_control_cooldown_minutes"
                ).first()
                cooldown_minutes = int(cooldown_setting.value) if cooldown_setting else 30

                if cooldown_minutes <= 0:
                    return

                cutoff = datetime.now() - timedelta(minutes=cooldown_minutes)

                # 查找因风控暂停且已过冷却期的任务
                paused_tasks = session.query(MonitorTask).filter(
                    MonitorTask.status == "paused",
                    MonitorTask.last_error.like("[风控自动暂停]%"),
                    MonitorTask.updated_at <= cutoff,
                ).all()

                if not paused_tasks:
                    return

                resumed_tasks = []
                permanent_paused_tasks = []
                for task in paused_tasks:
                    retries = task.risk_control_retries or 0

                    # ---- 超过重试上限 → 彻底暂停 ----
                    if retries >= self.MAX_RISK_CONTROL_RETRIES:
                        task.last_error = (
                            f"[风控彻底暂停] 已连续{retries}次风控重试失败，"
                            "请手动处理（更换Cookie/检查账号状态）"
                        )
                        permanent_paused_tasks.append(task)
                        continue

                    task.status = "active"
                    task.last_error = None
                    log.info(
                        f"[访问限制恢复重试] 第{retries+1}次重试，"
                        f"继续使用原浏览器配置#{task.browser_profile_id}",
                        task_id=task.id,
                    )
                    resumed_tasks.append(task)

                session.commit()

                # 重新注册恢复的任务到调度器
                for task in resumed_tasks:
                    self.register_task(task)

                if resumed_tasks:
                    log.info(
                        f"风控冷却恢复：{len(resumed_tasks)} 个任务已恢复",
                        data={
                            "resumed": [
                                {"task_id": t.id, "profile_id": t.browser_profile_id, "retries": t.risk_control_retries}
                                for t in resumed_tasks
                            ],
                            "cooldown_minutes": cooldown_minutes,
                        }
                    )

                if permanent_paused_tasks:
                    log.warning(
                        f"风控彻底暂停：{len(permanent_paused_tasks)} 个任务超过重试上限",
                        data={
                            "task_ids": [t.id for t in permanent_paused_tasks],
                        }
                    )
                    # 对彻底暂停的任务推送 Webhook 告警
                    await self._send_permanent_pause_alerts(session, permanent_paused_tasks)

        except Exception as e:
            log.error("风控冷却检查异常", data={"error": str(e)})

    @staticmethod
    def _try_switch_to_fallback_profile(
        session, task: MonitorTask, current_profile_id: int, cache: dict
    ) -> bool:
        """
        尝试将任务切换到同平台的备用 BrowserProfile

        只选择 cookie_status='valid' 且 last_login_at 在7天内的 profile，
        避免切换到实际已过期但 DB 标记未更新的 profile。

        Returns:
            True 如果成功切换，False 如果无可用备用
        """
        from datetime import datetime, timedelta
        from app.models.browser import BrowserProfile

        # 获取当前 profile 的平台
        current_profile = session.query(BrowserProfile).filter(
            BrowserProfile.id == current_profile_id
        ).first()
        if not current_profile:
            return False

        platform = current_profile.platform
        if platform not in cache:
            # Cookie 有效期门槛：只信任 7 天内确认过的 valid 状态
            freshness_cutoff = datetime.now() - timedelta(days=7)
            cache[platform] = session.query(BrowserProfile).filter(
                BrowserProfile.platform == platform,
                BrowserProfile.is_active == True,
                BrowserProfile.cookie_status == "valid",
                BrowserProfile.last_login_at >= freshness_cutoff,
                BrowserProfile.id != current_profile_id,
            ).order_by(BrowserProfile.last_login_at.desc()).all()

        fallback_list = cache[platform]
        if not fallback_list:
            return False

        # 选择最近验证过的备用 profile
        fallback = fallback_list[0]
        task.browser_profile_id = fallback.id
        # 从候选列表中轮转（下次选下一个）
        cache[platform] = fallback_list[1:] + [fallback]
        return True

    async def _send_permanent_pause_alerts(self, session, tasks: list) -> None:
        """为彻底暂停的任务发送 Webhook 告警"""
        from app.models.webhook import WebhookConfig
        from app.services.alert_service import get_alert_service

        alert_service = get_alert_service()
        for task in tasks:
            webhook_config = None
            if task.webhook_config_id:
                webhook_config = session.query(WebhookConfig).filter(
                    WebhookConfig.id == task.webhook_config_id
                ).first()
            if webhook_config and webhook_config.is_active:
                try:
                    await alert_service.create_account_issue_alert(
                        profile_id=task.browser_profile_id,
                        issue_type="blocked",
                        issue_message=(
                            f"任务#{task.id}已连续{task.risk_control_retries}次风控重试失败，"
                            "已彻底暂停，请人工介入处理"
                        ),
                        affected_task_count=1,
                        webhook_config=webhook_config,
                        trace_id=f"permanent_pause_{task.id}",
                    )
                except Exception as e:
                    log.error(f"彻底暂停告警推送失败: {e}", data={"task_id": task.id})

    def _on_job_event(self, event) -> None:
        """记录调度任务执行结果，便于排障"""
        if event.exception:
            log.error(
                "调度任务执行异常",
                data={
                    "job_id": event.job_id,
                    "exception": str(event.exception),
                }
            )
            return

        log.info(
            "调度任务执行完成",
            data={"job_id": event.job_id}
        )


# 全局调度服务实例
_scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    """
    获取调度服务实例

    Returns:
        SchedulerService实例
    """
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service
