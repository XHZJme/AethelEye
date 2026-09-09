"""
筱和灵眸(AethelEye) - 引擎管理 + AI服务绑定 API

端点：
  GET  /api/engines                  — 列出所有引擎（内置+外部）
  GET  /api/engines/active           — 获取当前活跃引擎
  PUT  /api/engines/active           — 切换活跃引擎
  GET  /api/engines/config           — 获取引擎配置（策略/超时/自治级别）
  PUT  /api/engines/config           — 更新引擎配置
  GET  /api/engines/service-bindings — 列出AI服务绑定
  PUT  /api/engines/service-bindings/{service_name} — 更新服务绑定
  POST /api/engines/reload           — 重新扫描外部引擎
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.ai_service_binding import AIServiceBinding, EngineConfig
from app.services.engine_registry import get_engine_registry
from app.engines.engine_loader import get_all_engine_manifests, load_and_register_engines
from app.middleware.permission import require_admin
from app.utils.logger import get_logger

log = get_logger("system")
router = APIRouter(prefix="/api/engines", tags=["engines"])


# ── 请求模型 ────────────────────────────────────

class SetActiveEngineRequest(BaseModel):
    engine_name: str


class EngineConfigUpdate(BaseModel):
    engine_strategy: Optional[str] = None  # default / manual / hardcoded_only / ai_only
    ai_rpa_max_explore_rounds: Optional[int] = None
    ai_rpa_timeout_seconds: Optional[int] = None
    ai_autonomy_level: Optional[int] = None


class ServiceBindingUpdate(BaseModel):
    provider_config_id: Optional[int] = None
    model: Optional[str] = None
    is_enabled: Optional[bool] = None
    note: Optional[str] = None


# ── 引擎列表 ────────────────────────────────────

@router.get("")
def list_engines(current_user=Depends(require_admin)):
    """列出所有引擎（内置 + 外部引擎包）"""
    return {"engines": get_all_engine_manifests()}


@router.get("/active")
def get_active_engine(current_user=Depends(require_admin)):
    """获取当前活跃引擎"""
    registry = get_engine_registry()
    active = registry.active_name
    engines = registry.list_engines()
    active_info = next((e for e in engines if e["name"] == active), None)
    return {"active_engine": active_info}


@router.put("/active")
def set_active_engine(req: SetActiveEngineRequest, current_user=Depends(require_admin)):
    """切换活跃引擎"""
    registry = get_engine_registry()
    try:
        registry.set_active(req.engine_name)
        return {"message": f"活跃引擎已切换为: {req.engine_name}"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reload")
def reload_engines(current_user=Depends(require_admin)):
    """重新扫描并加载外部引擎包"""
    registry = get_engine_registry()
    registered = load_and_register_engines(registry)
    return {
        "message": f"外部引擎扫描完成",
        "newly_registered": registered,
        "all_engines": registry.list_engines(),
    }


# ── 引擎配置 ────────────────────────────────────

def _get_or_create_engine_config(session: Session) -> EngineConfig:
    """获取或创建引擎配置单例"""
    config = session.query(EngineConfig).first()
    if config is None:
        config = EngineConfig(
            engine_strategy="default",
            ai_rpa_max_explore_rounds=10,
            ai_rpa_timeout_seconds=60,
            ai_autonomy_level=1,
        )
        session.add(config)
        session.flush()
    return config


@router.get("/config")
def get_engine_config(
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """获取引擎配置"""
    config = _get_or_create_engine_config(session)
    return {
        "engine_strategy": config.engine_strategy,
        "ai_rpa_max_explore_rounds": config.ai_rpa_max_explore_rounds,
        "ai_rpa_timeout_seconds": config.ai_rpa_timeout_seconds,
        "ai_autonomy_level": config.ai_autonomy_level,
    }


@router.put("/config")
def update_engine_config(
    req: EngineConfigUpdate,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """更新引擎配置"""
    config = _get_or_create_engine_config(session)

    if req.engine_strategy is not None:
        valid_strategies = ["default", "manual", "hardcoded_only", "ai_only"]
        if req.engine_strategy not in valid_strategies:
            raise HTTPException(status_code=400, detail=f"无效策略，可选: {valid_strategies}")
        config.engine_strategy = req.engine_strategy

    if req.ai_rpa_max_explore_rounds is not None:
        config.ai_rpa_max_explore_rounds = max(1, min(50, req.ai_rpa_max_explore_rounds))

    if req.ai_rpa_timeout_seconds is not None:
        config.ai_rpa_timeout_seconds = max(10, min(300, req.ai_rpa_timeout_seconds))

    if req.ai_autonomy_level is not None:
        if req.ai_autonomy_level not in (0, 1, 2, 3):
            raise HTTPException(status_code=400, detail="自治级别只能是 0/1/2/3")
        config.ai_autonomy_level = req.ai_autonomy_level

    return {"message": "引擎配置已更新", "config": {
        "engine_strategy": config.engine_strategy,
        "ai_rpa_max_explore_rounds": config.ai_rpa_max_explore_rounds,
        "ai_rpa_timeout_seconds": config.ai_rpa_timeout_seconds,
        "ai_autonomy_level": config.ai_autonomy_level,
    }}


# ── AI 服务绑定 ─────────────────────────────────

# 预定义的服务列表
DEFAULT_SERVICE_BINDINGS = [
    ("chat", "AI 对话"),
    ("ai_rpa", "AI RPA引擎（视觉推理）"),
    ("ai_coding", "AI 编程（插件开发）"),
    ("ai_analysis", "AI 数据分析"),
    ("ai_watchdog", "AI 自治引擎（看门狗）"),
]


def _ensure_default_bindings(session: Session) -> None:
    """确保默认服务绑定存在"""
    existing = {b.service_name for b in session.query(AIServiceBinding).all()}
    for name, display_name in DEFAULT_SERVICE_BINDINGS:
        if name not in existing:
            binding = AIServiceBinding(
                service_name=name,
                service_display_name=display_name,
            )
            session.add(binding)
    session.flush()


@router.get("/service-bindings")
def list_service_bindings(
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """列出所有AI服务绑定"""
    _ensure_default_bindings(session)
    bindings = session.query(AIServiceBinding).all()
    return {
        "bindings": [
            {
                "service_name": b.service_name,
                "service_display_name": b.service_display_name,
                "provider_config_id": b.provider_config_id,
                "model": b.model,
                "is_enabled": b.is_enabled,
                "note": b.note,
            }
            for b in bindings
        ]
    }


@router.put("/service-bindings/{service_name}")
def update_service_binding(
    service_name: str,
    req: ServiceBindingUpdate,
    session: Session = Depends(get_db_session),
    current_user=Depends(require_admin),
):
    """更新指定服务的模型绑定"""
    _ensure_default_bindings(session)

    binding = session.query(AIServiceBinding).filter(
        AIServiceBinding.service_name == service_name
    ).first()

    if binding is None:
        raise HTTPException(status_code=404, detail=f"服务 '{service_name}' 不存在")

    if req.provider_config_id is not None:
        binding.provider_config_id = req.provider_config_id
    if req.model is not None:
        binding.model = req.model
    if req.is_enabled is not None:
        binding.is_enabled = req.is_enabled
    if req.note is not None:
        binding.note = req.note

    return {
        "message": f"服务 '{service_name}' 绑定已更新",
        "binding": {
            "service_name": binding.service_name,
            "provider_config_id": binding.provider_config_id,
            "model": binding.model,
            "is_enabled": binding.is_enabled,
        },
    }


# ── Workflow 管理 ─────────────────────────────────

@router.get("/workflows")
def list_workflows(current_user=Depends(require_admin)):
    """列出所有 AI RPA Workflow 缓存"""
    from app.engines.ai_rpa.workflow import get_workflow_store
    store = get_workflow_store()
    return {"workflows": store.list_all()}


@router.delete("/workflows/{workflow_id}")
def delete_workflow(workflow_id: str, current_user=Depends(require_admin)):
    """删除指定 Workflow"""
    from app.engines.ai_rpa.workflow import get_workflow_store
    store = get_workflow_store()
    if store.delete(workflow_id):
        return {"message": f"Workflow '{workflow_id}' 已删除"}
    raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' 不存在")
