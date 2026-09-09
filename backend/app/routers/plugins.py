"""
筱和灵眸(AethelEye) - 插件市场 API

端点：
  GET    /api/plugins              — 列出所有插件
  POST   /api/plugins/upload       — 上传插件 ZIP
  PUT    /api/plugins/{id}/review  — 审核插件（approve/reject）
  PUT    /api/plugins/{id}/toggle  — 启用/禁用插件
  DELETE /api/plugins/{id}         — 卸载插件
  POST   /api/plugins/{id}/execute — 执行插件函数
  GET    /api/plugins/{id}/config  — 获取插件配置
  PUT    /api/plugins/{id}/config  — 更新插件配置
"""
import json
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.plugin import Plugin
from app.services.plugin_sandbox import PluginRunner, install_plugin_from_zip, uninstall_plugin
from app.middleware.permission import require_admin
from app.utils.logger import get_logger

log = get_logger("system")
router = APIRouter(prefix="/api/plugins", tags=["plugins"])


# ── 请求模型 ──────────────────────────────────────

class ReviewRequest(BaseModel):
    action: str  # approve / reject
    reason: Optional[str] = ""


class ToggleRequest(BaseModel):
    is_enabled: bool


class ExecuteRequest(BaseModel):
    function_name: str = "run"
    kwargs: Optional[dict] = None


class ConfigUpdate(BaseModel):
    config_values: dict


# ── 列表 ─────────────────────────────────────────

@router.get("")
def list_plugins(
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """列出所有已安装插件"""
    plugins = session.query(Plugin).all()
    return {
        "plugins": [
            {
                "id": p.id,
                "name": p.name,
                "display_name": p.display_name,
                "version": p.version,
                "plugin_type": p.plugin_type,
                "description": p.description,
                "author": p.author,
                "status": p.status,
                "is_enabled": p.is_enabled,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in plugins
        ]
    }


# ── 上传 ─────────────────────────────────────────

@router.post("/upload")
async def upload_plugin(
    file: UploadFile = File(...),
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """上传插件 ZIP 文件。插件执行不是强安全隔离，仅接受已审计的可信代码。"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 文件")

    # 保存到临时文件
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="插件 ZIP 不能超过 10 MiB")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp.write(content)
    tmp.close()

    try:
        # 从文件名推断插件名
        plugin_name = file.filename[:-4].replace(" ", "_").lower()

        # 检查是否已存在
        existing = session.query(Plugin).filter(Plugin.name == plugin_name).first()
        if existing:
            raise HTTPException(status_code=409, detail=f"插件 '{plugin_name}' 已存在")

        # 安装
        result = install_plugin_from_zip(tmp.name, plugin_name)
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["error"])

        manifest = result["manifest"]

        # 写入数据库
        plugin = Plugin(
            name=plugin_name,
            display_name=manifest.get("display_name", plugin_name),
            version=manifest.get("version", "1.0.0"),
            plugin_type=manifest.get("type", "tool"),
            description=manifest.get("description", ""),
            author=manifest.get("author", ""),
            entry=manifest.get("entry", "main.py"),
            permissions=json.dumps(manifest.get("permissions", [])),
            config_schema=json.dumps(manifest.get("config_schema", {})),
            status="pending",  # 需要管理员审核
            is_installed=True,
            is_enabled=False,
        )
        session.add(plugin)

        return {"message": f"插件 '{plugin_name}' 已上传，等待审核", "plugin_id": plugin.id}

    finally:
        os.unlink(tmp.name)


# ── 审核 ─────────────────────────────────────────

@router.put("/{plugin_id}/review")
def review_plugin(
    plugin_id: int,
    req: ReviewRequest,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """审核插件（approve / reject）"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    if req.action == "approve":
        plugin.status = "approved"
        plugin.is_enabled = True
        plugin.reviewed_by = getattr(current_user, "username", "admin")
        import datetime
        plugin.reviewed_at = datetime.datetime.now()
        return {"message": f"插件 '{plugin.display_name}' 已审核通过"}

    elif req.action == "reject":
        plugin.status = "rejected"
        plugin.is_enabled = False
        plugin.rejection_reason = req.reason or ""
        plugin.reviewed_by = getattr(current_user, "username", "admin")
        import datetime
        plugin.reviewed_at = datetime.datetime.now()
        return {"message": f"插件 '{plugin.display_name}' 已被拒绝"}

    else:
        raise HTTPException(status_code=400, detail="action 必须是 approve 或 reject")


# ── 启用/禁用 ────────────────────────────────────

@router.put("/{plugin_id}/toggle")
def toggle_plugin(
    plugin_id: int,
    req: ToggleRequest,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """启用/禁用插件"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    if req.is_enabled and plugin.status != "approved":
        raise HTTPException(status_code=400, detail="只有审核通过的插件才能启用")

    plugin.is_enabled = req.is_enabled
    return {"message": f"插件已{'启用' if req.is_enabled else '禁用'}"}


# ── 卸载 ─────────────────────────────────────────

@router.delete("/{plugin_id}")
def delete_plugin(
    plugin_id: int,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """卸载插件"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    # 删除文件
    uninstall_plugin(plugin.name)
    # 删除DB记录
    session.delete(plugin)
    return {"message": f"插件 '{plugin.display_name}' 已卸载"}


# ── 执行 ─────────────────────────────────────────

@router.post("/{plugin_id}/execute")
async def execute_plugin(
    plugin_id: int,
    req: ExecuteRequest,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """在当前服务进程中执行已审核插件；这不是操作系统级安全沙箱。"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    if not plugin.is_enabled:
        raise HTTPException(status_code=403, detail="插件未启用，请先审核并启用")

    runner = PluginRunner(plugin.name, plugin.entry)
    result = await runner.execute(
        function_name=req.function_name,
        kwargs=req.kwargs,
    )

    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["error"])

    return result


# ── 配置 ─────────────────────────────────────────

@router.get("/{plugin_id}/config")
def get_plugin_config(
    plugin_id: int,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """获取插件配置"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    return {
        "config_schema": json.loads(plugin.config_schema or "{}"),
        "config_values": json.loads(plugin.config_values or "{}"),
    }


@router.put("/{plugin_id}/config")
def update_plugin_config(
    plugin_id: int,
    req: ConfigUpdate,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """更新插件配置"""
    plugin = session.query(Plugin).filter(Plugin.id == plugin_id).first()
    if not plugin:
        raise HTTPException(status_code=404, detail="插件不存在")

    plugin.config_values = json.dumps(req.config_values, ensure_ascii=False)
    return {"message": "配置已更新"}
