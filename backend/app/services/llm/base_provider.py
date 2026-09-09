"""
筱和灵眸(AethelEye) - LLM Provider 抽象基类

所有 LLM Provider 必须实现此接口。
网关通过 Provider 注册表动态路由请求。
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List, AsyncIterator


@dataclass
class ChatMessage:
    """聊天消息"""
    role: str  # system / user / assistant / tool
    content: str
    name: Optional[str] = None


@dataclass
class ChatCompletionRequest:
    """聊天补全请求（OpenAI 兼容格式）"""
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    top_p: float = 1.0
    max_tokens: Optional[int] = None
    stream: bool = False
    stop: Optional[List[str]] = None
    # 扩展字段（各 Provider 透传）
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatChoice:
    """补全选项"""
    index: int = 0
    message: Optional[ChatMessage] = None
    delta: Optional[Dict[str, str]] = None  # 流式增量
    finish_reason: Optional[str] = None


@dataclass
class UsageInfo:
    """用量统计"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionResponse:
    """聊天补全响应（OpenAI 兼容格式）"""
    id: str = ""
    object: str = "chat.completion"
    created: int = 0
    model: str = ""
    choices: List[ChatChoice] = field(default_factory=list)
    usage: Optional[UsageInfo] = None
    # Provider 原始响应（调试用）
    raw: Optional[Dict[str, Any]] = None


@dataclass
class StreamChunk:
    """流式响应块"""
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = 0
    model: str = ""
    choices: List[ChatChoice] = field(default_factory=list)


class BaseLLMProvider(ABC):
    """
    LLM Provider 抽象基类

    每个 Provider 对应一个上游 LLM 服务。
    """

    # 子类覆盖
    PROVIDER_NAME: str = "base"
    PROVIDER_DISPLAY_NAME: str = "基础 Provider"
    # 该 Provider 支持的模型列表（前缀匹配）
    SUPPORTED_MODEL_PREFIXES: List[str] = []

    def __init__(self, api_key: str, base_url: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.base_url = base_url

    def supports_model(self, model: str) -> bool:
        """判断该 Provider 是否支持指定模型（大小写不敏感）"""
        m = model.lower()
        return any(m.startswith(prefix.lower()) for prefix in self.SUPPORTED_MODEL_PREFIXES)

    @abstractmethod
    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """非流式聊天补全"""
        ...

    @abstractmethod
    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式聊天补全（SSE）"""
        ...

    @abstractmethod
    async def list_models(self) -> List[Dict[str, Any]]:
        """列出该 Provider 可用模型"""
        ...

    def get_provider_info(self) -> Dict[str, Any]:
        """返回 Provider 元信息"""
        return {
            "name": self.PROVIDER_NAME,
            "display_name": self.PROVIDER_DISPLAY_NAME,
            "supported_prefixes": self.SUPPORTED_MODEL_PREFIXES,
        }
