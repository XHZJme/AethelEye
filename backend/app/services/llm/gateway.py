"""
筱和灵眸(AethelEye) - LLM 网关核心

职责：
  1. 从 DB 加载 Provider 配置，实例化 Provider
  2. 根据请求模型名自动路由到合适的 Provider
  3. 记录用量日志
  4. 提供统一的 chat / stream 入口
"""
import json
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, AsyncIterator, Type

from app.database import get_sync_session
from app.models.llm_provider import LLMProviderConfig, LLMUsageLog
from app.services.llm.base_provider import (
    BaseLLMProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    StreamChunk,
)
from app.utils.logger import get_logger
from app.utils.encryption import decrypt_secret, encrypt_secret, is_encrypted_secret

log = get_logger("system")

# Provider 类型 → 类映射
_PROVIDER_TYPE_MAP: Dict[str, Type[BaseLLMProvider]] = {}


def _ensure_provider_types():
    """惰性注册 Provider 类型"""
    if _PROVIDER_TYPE_MAP:
        return
    from app.services.llm.openai_provider import OpenAICompatibleProvider
    from app.services.llm.minimax_provider import MiniMaxProvider
    from app.services.llm.anthropic_provider import AnthropicProvider

    _PROVIDER_TYPE_MAP["openai_compatible"] = OpenAICompatibleProvider
    _PROVIDER_TYPE_MAP["minimax"] = MiniMaxProvider
    _PROVIDER_TYPE_MAP["anthropic"] = AnthropicProvider


class LLMGateway:
    """
    LLM 网关

    管理多 Provider 实例，根据模型名自动路由。
    """

    def __init__(self):
        # config_id → Provider 实例
        self._providers: Dict[int, BaseLLMProvider] = {}
        # config_id → default_model
        self._default_models: Dict[int, Optional[str]] = {}
        # 已加载的配置版本（updated_at 列表，用于检测变更）
        self._config_version: Optional[str] = None

    def _load_providers(self) -> None:
        """从 DB 加载活跃 Provider 配置并实例化"""
        _ensure_provider_types()

        with get_sync_session() as session:
            configs = session.query(LLMProviderConfig).filter(
                LLMProviderConfig.is_active == True
            ).order_by(LLMProviderConfig.priority).all()

            # 兼容旧数据库：首次读取旧版明文 Key 后立即在本地迁移为加密格式。
            migrated = False
            for config in configs:
                if config.api_key and not is_encrypted_secret(config.api_key):
                    config.api_key = encrypt_secret(config.api_key)
                    migrated = True
            if migrated:
                session.commit()

            # 计算配置指纹
            version = "|".join(
                f"{c.id}:{c.updated_at}" for c in configs
            )
            if version == self._config_version:
                return  # 未变更，跳过

            # 关闭旧 Provider
            for p in self._providers.values():
                if hasattr(p, "close"):
                    import asyncio
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            loop.create_task(p.close())
                        else:
                            loop.run_until_complete(p.close())
                    except Exception:
                        pass

            self._providers.clear()
            self._default_models.clear()

            for cfg in configs:
                provider_cls = _PROVIDER_TYPE_MAP.get(cfg.provider_type)
                if not provider_cls:
                    log.warning(f"未知 Provider 类型: {cfg.provider_type}", data={"config_id": cfg.id})
                    continue

                try:
                    kwargs = {}
                    if cfg.base_url:
                        kwargs["base_url"] = cfg.base_url

                    api_key = decrypt_secret(cfg.api_key)
                    if not api_key:
                        log.warning("LLM Provider 的 API Key 无法解密，已跳过", data={"config_id": cfg.id})
                        continue
                    provider = provider_cls(api_key=api_key, **kwargs)

                    # 覆盖模型前缀
                    if cfg.model_prefixes:
                        try:
                            prefixes = json.loads(cfg.model_prefixes)
                            if isinstance(prefixes, list):
                                provider.SUPPORTED_MODEL_PREFIXES = prefixes
                        except json.JSONDecodeError:
                            pass

                    self._providers[cfg.id] = provider
                    self._default_models[cfg.id] = cfg.default_model
                    log.info(f"LLM Provider 已加载: {cfg.display_name}",
                             data={"config_id": cfg.id, "type": cfg.provider_type})
                except Exception as e:
                    log.error(f"LLM Provider 初始化失败: {e}",
                              data={"config_id": cfg.id, "type": cfg.provider_type})

            self._config_version = version
            log.info(f"LLM 网关加载完成", data={"provider_count": len(self._providers)})

    def reload(self) -> None:
        """强制重新加载"""
        self._config_version = None
        self._load_providers()

    def _find_provider(self, model: str) -> tuple:
        """
        根据模型名找到最佳 Provider

        Returns:
            (config_id, provider) 或 raise RuntimeError
        """
        self._load_providers()

        for config_id, provider in self._providers.items():
            if provider.supports_model(model):
                return config_id, provider

        available = []
        for cid, p in self._providers.items():
            available.extend(p.SUPPORTED_MODEL_PREFIXES)
        raise RuntimeError(
            f"没有 Provider 支持模型 '{model}'。已配置的模型前缀: {available}"
        )

    def _log_usage(
        self,
        config_id: int,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        duration_ms: int,
        source: str,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """记录用量日志"""
        try:
            with get_sync_session() as session:
                usage = LLMUsageLog(
                    provider_config_id=config_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    duration_ms=duration_ms,
                    source=source,
                    success=success,
                    error=error,
                )
                session.add(usage)
                session.commit()
        except Exception as e:
            log.warning(f"LLM 用量记录失败: {e}")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        source: str = "chat",
        **kwargs,
    ) -> ChatCompletionResponse:
        """
        非流式聊天

        Args:
            messages: [{"role": "user", "content": "..."}]
            model: 模型名
            temperature: 温度
            max_tokens: 最大token
            source: 请求来源
        """
        config_id, provider = self._find_provider(model)

        request = ChatCompletionRequest(
            model=model,
            messages=[ChatMessage(role=m["role"], content=m["content"]) for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra=kwargs,
        )

        start_time = time.time()
        error_msg = None
        response = None
        try:
            response = await provider.chat_completion(request)
            return response
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            usage = response.usage if error_msg is None and response else None
            self._log_usage(
                config_id=config_id,
                model=model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
                duration_ms=duration_ms,
                source=source,
                success=error_msg is None,
                error=error_msg,
            )

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        source: str = "chat",
        **kwargs,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式聊天

        Yields: StreamChunk（OpenAI 兼容 SSE 格式）
        """
        config_id, provider = self._find_provider(model)

        request = ChatCompletionRequest(
            model=model,
            messages=[ChatMessage(role=m["role"], content=m["content"]) for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            extra=kwargs,
        )

        start_time = time.time()
        error_msg = None
        try:
            async for chunk in provider.chat_completion_stream(request):
                yield chunk
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            duration_ms = int((time.time() - start_time) * 1000)
            self._log_usage(
                config_id=config_id,
                model=model,
                prompt_tokens=0,  # 流式模式无法精确计算 token
                completion_tokens=0,
                total_tokens=0,
                duration_ms=duration_ms,
                source=source,
                success=error_msg is None,
                error=error_msg,
            )

    def list_all_models(self) -> List[Dict[str, Any]]:
        """列出所有已配置 Provider 支持的模型前缀"""
        self._load_providers()
        result = []
        for config_id, provider in self._providers.items():
            result.append({
                "config_id": config_id,
                "provider": provider.PROVIDER_NAME,
                "display_name": provider.PROVIDER_DISPLAY_NAME,
                "prefixes": provider.SUPPORTED_MODEL_PREFIXES,
                "default_model": self._default_models.get(config_id),
            })
        return result

    def get_provider_types(self) -> List[Dict[str, Any]]:
        """列出所有可用 Provider 类型"""
        _ensure_provider_types()
        return [
            {
                "type": name,
                "display_name": cls.PROVIDER_DISPLAY_NAME,
                "default_prefixes": cls.SUPPORTED_MODEL_PREFIXES,
            }
            for name, cls in _PROVIDER_TYPE_MAP.items()
        ]


# ── 全局单例 ──────────────────────────────────────

_gateway: Optional[LLMGateway] = None


def get_llm_gateway() -> LLMGateway:
    """获取 LLM 网关单例"""
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
