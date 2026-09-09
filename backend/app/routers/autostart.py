"""
筱和灵眸(AethelEye) - 开机自启API路由
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.models.user import User
from app.middleware.permission import require_admin
from app.services.autostart_service import get_autostart_service
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/autostart", tags=["开机自启"])


class AutostartStatus(BaseModel):
    """自启状态"""
    enabled: bool
    task_name: str
    app_path: str


class AutostartResponse(BaseModel):
    """自启操作响应"""
    success: bool
    message: str


@router.get("/status", response_model=AutostartStatus)
def get_autostart_status(
    admin: User = Depends(require_admin)
):
    """获取开机自启状态"""
    service = get_autostart_service()
    return AutostartStatus(**service.get_status())


@router.post("/enable", response_model=AutostartResponse)
def enable_autostart(
    http_request: Request,
    admin: User = Depends(require_admin)
):
    """启用开机自启"""
    service = get_autostart_service()
    success = service.enable()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"开机自启设置变更",
        data={
            "action": "enable",
            "success": success,
            "triggered_by": admin.username,
            "ip": ip_address,
        }
    )

    if success:
        return AutostartResponse(success=True, message="开机自启已启用")
    else:
        raise HTTPException(status_code=500, detail="启用开机自启失败")


@router.post("/disable", response_model=AutostartResponse)
def disable_autostart(
    http_request: Request,
    admin: User = Depends(require_admin)
):
    """禁用开机自启"""
    service = get_autostart_service()
    success = service.disable()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"开机自启设置变更",
        data={
            "action": "disable",
            "success": success,
            "triggered_by": admin.username,
            "ip": ip_address,
        }
    )

    if success:
        return AutostartResponse(success=True, message="开机自启已禁用")
    else:
        raise HTTPException(status_code=500, detail="禁用开机自启失败")