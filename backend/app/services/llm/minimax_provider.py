"""
筱和灵眸(AethelEye) - MiniMax Provider

MiniMax ChatCompletion Pro API（OpenAI 兼容格式）。
MiniMax 官方 v2 API 已兼容 OpenAI 格式，直接复用 OpenAI Provider 即可。

默认 base_url: https://api.minimax.chat
模型前缀: minimax-、abab-、MiniMax-Text-
"""
from typing import Optional, List

from app.services.llm.openai_provider import OpenAICompatibleProvider


class MiniMaxProvider(OpenAICompatibleProvider):
    """
    MiniMax Provider

    MiniMax v2 API 兼容 OpenAI Chat Completions 格式，
    仅覆盖 PROVIDER 元信息和默认 base_url。
    """

    PROVIDER_NAME = "minimax"
    PROVIDER_DISPLAY_NAME = "MiniMax (海螺AI)"
    SUPPORTED_MODEL_PREFIXES = [
        "minimax-",
        "abab-",
        "MiniMax-Text-",
    ]

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url or "https://api.minimax.chat",
            **kwargs,
        )

    async def list_models(self) -> List[dict]:
        """MiniMax 固定模型列表（API 不提供 /v1/models）"""
        return [
            {"id": "MiniMax-Text-01", "owned_by": "minimax"},
            {"id": "abab6.5s-chat", "owned_by": "minimax"},
            {"id": "abab6.5-chat", "owned_by": "minimax"},
            {"id": "abab5.5-chat", "owned_by": "minimax"},
        ]
