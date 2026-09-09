"""
筱和灵眸(AethelEye) - AI 服务→模型 解析器

职责：
  根据 service_name（如 "ai_rpa"、"chat"）查询 ai_service_bindings 表，
  解析出应该使用的 (provider_config_id, model) 组合。

  如果服务未绑定或 Provider 不可用，自动 fallback 到 LLM Gateway 的默认路由。

设计原则：
  - 不修改已有 gateway.py / base_provider.py
  - 本模块是 gateway 上层的"胶水"：服务名 → 模型名 → gateway 路由
"""
from typing import Optional, Tuple

from app.database import get_sync_session
from app.models.ai_service_binding import AIServiceBinding
from app.utils.logger import get_logger

log = get_logger("system")


def resolve_service_model(service_name: str) -> Optional[Tuple[Optional[int], str]]:
    """
    根据 service_name 解析绑定的 (provider_config_id, model)

    Returns:
        (provider_config_id, model) 如果已绑定且启用
        None 如果未绑定或未启用
    """
    try:
        with get_sync_session() as session:
            binding = session.query(AIServiceBinding).filter(
                AIServiceBinding.service_name == service_name,
                AIServiceBinding.is_enabled == True,
            ).first()

            if binding is None or not binding.model:
                return None

            return (binding.provider_config_id, binding.model)
    except Exception as e:
        log.warning(f"解析AI服务绑定失败: {service_name}", data={"error": str(e)})
        return None


def is_service_enabled(service_name: str) -> bool:
    """检查指定AI服务是否已启用且已绑定模型"""
    result = resolve_service_model(service_name)
    return result is not None


def get_service_model_or_default(service_name: str, fallback_model: str) -> str:
    """
    获取服务绑定的模型，如果未绑定则返回 fallback_model

    用于 AI RPA 引擎、Watchdog 等需要调 LLM 的模块：
      model = get_service_model_or_default("ai_rpa", "abab6.5s-chat")
      response = await gateway.chat(messages, model=model, source="ai_rpa")
    """
    result = resolve_service_model(service_name)
    if result:
        _, model = result
        return model
    return fallback_model
