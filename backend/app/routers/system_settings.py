"""
筱和灵眸(AethelEye) - 系统设置API路由

系统配置管理
- 运行模式（静默/可视化）
- 采集参数
- 录屏配置
- 告警配置
- 数据管理
"""
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pathlib import Path
import os

from app.config import settings
from app.database import get_db_session, get_sync_session
from app.models.settings_model import SystemSettings
from app.models.user import User
from app.middleware.permission import require_admin
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/system-settings", tags=["系统设置"])


# ===== Pydantic模型 =====

class SettingsResponse(BaseModel):
    """系统设置响应"""
    # 通用设置
    port: int
    data_dir: str
    screenshots_dir: str
    recordings_dir: str
    logs_dir: str

    # 采集设置
    running_mode: str  # silent/visual
    collect_timeout: int
    collect_retry: int
    collect_delay_min: int
    collect_delay_max: int

    # 录屏设置
    recording_enabled: bool
    recording_resolution: str
    recording_retention: int
    recording_only_exception: bool

    # 日志设置
    log_level: str
    log_retention: int

    # 告警设置（企微）
    webhook_silent_hours_start: int
    webhook_silent_hours_end: int
    webhook_rate_limit: int

    # 访问限制处理
    risk_control_cooldown_minutes: int


class SettingsUpdateRequest(BaseModel):
    """更新系统设置请求"""
    running_mode: Optional[str] = None
    collect_timeout: Optional[int] = None
    collect_retry: Optional[int] = None
    collect_delay_min: Optional[int] = None
    collect_delay_max: Optional[int] = None
    recording_enabled: Optional[bool] = None
    recording_resolution: Optional[str] = None
    recording_retention: Optional[int] = None
    recording_only_exception: Optional[bool] = None
    log_level: Optional[str] = None
    log_retention: Optional[int] = None
    webhook_silent_hours_start: Optional[int] = None
    webhook_silent_hours_end: Optional[int] = None
    webhook_rate_limit: Optional[int] = None
    risk_control_cooldown_minutes: Optional[int] = None


class StorageInfo(BaseModel):
    """存储信息"""
    database_size_mb: float
    screenshots_size_mb: float
    recordings_size_mb: float
    logs_size_mb: float
    total_size_mb: float


class BackupExportResponse(BaseModel):
    """备份导出响应"""
    backup_path: str
    backup_size_mb: float
    created_at: datetime


# ===== API端点 =====

@router.get("", response_model=SettingsResponse)
def get_settings(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """获取系统设置"""
    # 从数据库读取设置
    def get_setting(key: str, default: str) -> str:
        setting = session.query(SystemSettings).filter(SystemSettings.key == key).first()
        return setting.value if setting else default

    return SettingsResponse(
        # 通用设置（从配置文件）
        port=settings.port,
        data_dir=str(settings.data_dir),
        screenshots_dir=str(settings.screenshots_dir),
        recordings_dir=str(settings.recordings_dir),
        logs_dir=str(settings.logs_dir),

        # 采集设置
        running_mode=get_setting("running_mode", "silent"),
        collect_timeout=int(get_setting("collect_timeout_seconds", "30")),
        collect_retry=int(get_setting("collect_retry_count", "2")),
        collect_delay_min=int(get_setting("collect_delay_min_seconds", "5")),
        collect_delay_max=int(get_setting("collect_delay_max_seconds", "12")),

        # 录屏设置
        recording_enabled=get_setting("recording_enabled", "false") == "true",
        recording_resolution=get_setting("recording_resolution", "1280x720"),
        recording_retention=int(get_setting("recording_retention_days", "7")),
        recording_only_exception=get_setting("recording_only_exception", "true") == "true",

        # 日志设置
        log_level=get_setting("log_level", "INFO"),
        log_retention=int(get_setting("log_retention_days", "90")),

        # 告警设置
        webhook_silent_hours_start=int(get_setting("webhook_silent_hours_start", "0")),
        webhook_silent_hours_end=int(get_setting("webhook_silent_hours_end", "8")),
        webhook_rate_limit=int(get_setting("webhook_rate_limit", "10")),

        # 默认禁用自动恢复，需管理员显式开启。
        risk_control_cooldown_minutes=int(get_setting("risk_control_cooldown_minutes", "0")),
    )


@router.put("")
async def update_settings(
    request: SettingsUpdateRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """更新系统设置"""
    # 更新设置到数据库
    def update_setting(key: str, value: str) -> None:
        setting = session.query(SystemSettings).filter(SystemSettings.key == key).first()
        if setting:
            setting.value = value
            setting.updated_at = datetime.now()
        else:
            setting = SystemSettings(key=key, value=value)
            session.add(setting)

    # 更新各个设置
    if request.running_mode:
        if request.running_mode not in ("silent", "visual"):
            raise HTTPException(status_code=400, detail="运行模式必须是 silent/visual")
        update_setting("running_mode", request.running_mode)

        # 模式变更时关闭所有已缓存的浏览器上下文，强制下次采集重建
        try:
            from app.services.browser_manager import get_browser_manager
            bm = get_browser_manager()
            for pid in list(bm._contexts.keys()):
                await bm.close_context(pid)
            log.info(f"运行模式切换为 {request.running_mode}，已关闭所有浏览器上下文")
        except Exception as e:
            log.warning(f"关闭浏览器上下文失败: {e}")

    if request.collect_timeout:
        if request.collect_timeout < 10 or request.collect_timeout > 120:
            raise HTTPException(status_code=400, detail="采集超时需在10-120秒之间")
        update_setting("collect_timeout_seconds", str(request.collect_timeout))

    if request.collect_retry:
        if request.collect_retry < 1 or request.collect_retry > 5:
            raise HTTPException(status_code=400, detail="重试次数需在1-5之间")
        update_setting("collect_retry_count", str(request.collect_retry))

    if request.collect_delay_min:
        update_setting("collect_delay_min_seconds", str(request.collect_delay_min))

    if request.collect_delay_max:
        update_setting("collect_delay_max_seconds", str(request.collect_delay_max))

    if request.recording_enabled is not None:
        update_setting("recording_enabled", "true" if request.recording_enabled else "false")

    if request.recording_resolution:
        if request.recording_resolution not in ("1280x720", "1920x1080"):
            raise HTTPException(status_code=400, detail="录屏分辨率必须是 1280x720/1920x1080")
        update_setting("recording_resolution", request.recording_resolution)

    if request.recording_retention:
        if request.recording_retention < 1 or request.recording_retention > 30:
            raise HTTPException(status_code=400, detail="录屏保留天数需在1-30之间")
        update_setting("recording_retention_days", str(request.recording_retention))

    if request.recording_only_exception is not None:
        update_setting("recording_only_exception", "true" if request.recording_only_exception else "false")

    if request.log_level:
        if request.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            raise HTTPException(status_code=400, detail="日志级别必须是 DEBUG/INFO/WARNING/ERROR")
        update_setting("log_level", request.log_level)

    if request.log_retention:
        if request.log_retention < 7 or request.log_retention > 365:
            raise HTTPException(status_code=400, detail="日志保留天数需在7-365之间")
        update_setting("log_retention_days", str(request.log_retention))

    if request.webhook_silent_hours_start:
        update_setting("webhook_silent_hours_start", str(request.webhook_silent_hours_start))

    if request.webhook_silent_hours_end:
        update_setting("webhook_silent_hours_end", str(request.webhook_silent_hours_end))

    if request.webhook_rate_limit:
        update_setting("webhook_rate_limit", str(request.webhook_rate_limit))

    if request.risk_control_cooldown_minutes is not None:
        if request.risk_control_cooldown_minutes < 0 or request.risk_control_cooldown_minutes > 1440:
            raise HTTPException(status_code=400, detail="访问限制冷却时间需在0-1440分钟之间（0=禁用自动恢复）")
        update_setting("risk_control_cooldown_minutes", str(request.risk_control_cooldown_minutes))

    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"系统设置已更新",
        data={
            "updated_by": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "设置已保存"}


@router.get("/storage", response_model=StorageInfo)
def get_storage_info(
    admin: User = Depends(require_admin)
):
    """获取存储空间信息"""
    def get_path_size(path: Path) -> float:
        if not path.exists():
            return 0
        if path.is_file():
            return path.stat().st_size / (1024 * 1024)
        total = 0
        for file in path.rglob("*"):
            if file.is_file():
                total += file.stat().st_size
        return total / (1024 * 1024)  # MB

    database_size = 0.0
    for db_file in ("database.db", "database.db-wal", "database.db-shm"):
        database_size += get_path_size(settings.data_dir / db_file)
    screenshots_size = get_path_size(settings.screenshots_dir)
    recordings_size = get_path_size(settings.recordings_dir)
    logs_size = get_path_size(settings.logs_dir)
    total_size = database_size + screenshots_size + recordings_size + logs_size

    return StorageInfo(
        database_size_mb=round(database_size, 2),
        screenshots_size_mb=round(screenshots_size, 2),
        recordings_size_mb=round(recordings_size, 2),
        logs_size_mb=round(logs_size, 2),
        total_size_mb=round(total_size, 2),
    )


@router.post("/cleanup")
def cleanup_old_data(
    days: int = 30,
    include_screenshots: bool = True,
    include_recordings: bool = True,
    include_logs: bool = False,
    http_request: Request = None,
    admin: User = Depends(require_admin)
):
    """清理旧数据"""
    from datetime import timedelta

    cutoff_date = datetime.now() - timedelta(days=days)
    deleted_count = 0

    # 清理截图
    if include_screenshots and settings.screenshots_dir.exists():
        for file in settings.screenshots_dir.glob("*.png"):
            file_date = datetime.fromtimestamp(file.stat().st_mtime)
            if file_date < cutoff_date:
                file.unlink()
                deleted_count += 1

    # 清理录屏
    if include_recordings and settings.recordings_dir.exists():
        for file in settings.recordings_dir.glob("*.webm"):
            file_date = datetime.fromtimestamp(file.stat().st_mtime)
            if file_date < cutoff_date:
                file.unlink()
                deleted_count += 1

    # 清理日志（需要特别小心）
    if include_logs and settings.logs_dir.exists():
        for log_dir in settings.logs_dir.iterdir():
            if log_dir.is_dir():
                for file in log_dir.glob("*.log.gz"):
                    file_date = datetime.fromtimestamp(file.stat().st_mtime)
                    if file_date < cutoff_date:
                        file.unlink()
                        deleted_count += 1

    ip_address = http_request.client.host if http_request and http_request.client else "unknown"
    log.info(
        f"旧数据已清理",
        data={
            "days": days,
            "deleted_count": deleted_count,
            "cleaned_by": admin.username,
            "ip": ip_address,
        }
    )

    return {
        "message": f"已清理{deleted_count}个文件",
        "deleted_count": deleted_count,
        "cutoff_days": days,
    }


@router.post("/backup")
def create_backup(
    http_request: Request,
    admin: User = Depends(require_admin)
):
    """创建数据备份"""
    import zipfile
    import tempfile

    # 创建临时备份文件
    backup_dir = settings.data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"backup_{timestamp}.zip"

    with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 备份数据库
        db_path = settings.data_dir / "database.db"
        if db_path.exists():
            zf.write(db_path, "database.db")

        # 备份系统设置
        with get_sync_session() as session:
            settings_data = {}
            for setting in session.query(SystemSettings).all():
                settings_data[setting.key] = setting.value

            zf.writestr("settings.json", json.dumps(settings_data))

    backup_size = backup_path.stat().st_size / (1024 * 1024)

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"数据备份已创建",
        data={
            "backup_path": str(backup_path),
            "backup_size_mb": round(backup_size, 2),
            "created_by": admin.username,
            "ip": ip_address,
        }
    )

    return {
        "backup_path": str(backup_path),
        "backup_size_mb": round(backup_size, 2),
        "created_at": datetime.now(),
    }


@router.get("/scheduler-status")
def get_scheduler_status(
    admin: User = Depends(require_admin)
):
    """获取调度器状态"""
    from app.services.scheduler_service import get_scheduler_service

    scheduler = get_scheduler_service()
    return scheduler.get_scheduler_status()


@router.post("/scheduler/reload")
def reload_scheduler(
    http_request: Request,
    admin: User = Depends(require_admin)
):
    """重新加载所有任务到调度器"""
    from app.services.scheduler_service import get_scheduler_service

    scheduler = get_scheduler_service()
    scheduler.load_all_tasks()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"调度器已重新加载",
        data={
            "triggered_by": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "调度器已重新加载所有任务"}


import json

from app.services.engine_registry import get_engine_registry


@router.get("/engines", summary="获取已注册引擎列表")
async def list_engines(admin: User = Depends(require_admin)):
    """返回所有已注册的采集引擎及当前活跃引擎"""
    registry = get_engine_registry()
    return {
        "engines": registry.list_engines(),
        "active": registry.active_name,
    }


class SwitchEngineRequest(BaseModel):
    engine_name: str


@router.post("/engines/switch", summary="切换活跃引擎")
async def switch_engine(
    request: SwitchEngineRequest,
    admin: User = Depends(require_admin),
):
    """切换当前活跃的采集引擎"""
    registry = get_engine_registry()
    try:
        registry.set_active(request.engine_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    log.info(f"引擎切换", data={"engine": request.engine_name, "by": admin.username})
    return {"message": f"已切换到引擎: {request.engine_name}", "active": request.engine_name}
