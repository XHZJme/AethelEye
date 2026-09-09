"""
筱和灵眸(AethelEye) - OpenAI 兼容 Provider

支持所有 OpenAI Chat Completions API 兼容服务：
  - OpenAI (gpt-4o, gpt-4o-mini, ...)
  - DeepSeek (deepseek-chat, deepseek-reasoner, ...)
  - 通义千问 (qwen-turbo, qwen-plus, ...)
  - 智谱GLM (glm-4, ...)
  - 任何 OpenAI 兼容端点
"""
import json
import time
import uuid
from typing import Optional, Dict, Any, List, AsyncIterator

import httpx

from app.services.llm.base_provider import (
    BaseLLMProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatChoice,
    ChatMessage,
    UsageInfo,
    StreamChunk,
)
from app.utils.logger import get_logger

log = get_logger("system")

# 默认超时（秒）
DEFAULT_TIMEOUT = 120


class OpenAICompatibleProvider(BaseLLMProvider):
    """
    OpenAI 兼容 Provider

    通过配置不同 base_url 和 api_key 即可对接各种兼容 API。
    """

    PROVIDER_NAME = "openai_compatible"
    PROVIDER_DISPLAY_NAME = "OpenAI 兼容"
    SUPPORTED_MODEL_PREFIXES = [
        "gpt-", "o1-", "o3-",           # OpenAI
        "deepseek-",                      # DeepSeek
        "qwen",                           # 通义千问（含 Qwen3.5-xxx 无连字符写法）
        "glm-",                           # 智谱GLM
        "moonshot-", "kimi-",             # Kimi/Moonshot
        "minimax-",                       # MiniMax
        "yi-",                            # 零一万物
        "ernie-",                         # 百度文心
        "hunyuan-",                       # 腾讯混元
    ]

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs,
    ):
        super().__init__(api_key, base_url, **kwargs)
        self.base_url = (base_url or "https://api.openai.com").rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout, connect=10),
            )
        return self._client

    def _build_payload(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        """构建请求体"""
        messages_payload = []
        for m in request.messages:
            msg: Dict[str, Any] = {"role": m.role, "content": m.content}
            if m.name:
                msg["name"] = m.name
            messages_payload.append(msg)

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": messages_payload,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": request.stream,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.stop:
            payload["stop"] = request.stop
        # tools（function calling）
        if request.extra.get("tools"):
            payload["tools"] = request.extra.pop("tools")
        # 透传扩展字段
        payload.update(request.extra)
        return payload

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """非流式聊天补全"""
        request.stream = False
        payload = self._build_payload(request)
        client = self._get_client()

        try:
            resp = await client.post("/v1/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            log.error("LLM API 错误", data={"status": status})
            raise RuntimeError(f"LLM API 返回 HTTP {status}；响应正文未记录")
        except httpx.RequestError as e:
            log.error("LLM 请求失败", data={"error_type": type(e).__name__})
            raise RuntimeError("LLM 请求失败；请检查网络和服务地址")

        # 解析响应
        choices = []
        for c in data.get("choices", []):
            msg = c.get("message") or {}
            choice = ChatChoice(
                index=c.get("index", 0),
                message=ChatMessage(
                    role=msg.get("role") or "assistant",
                    content=msg.get("content") or "",
                ),
                finish_reason=c.get("finish_reason"),
            )
            # 保留 tool_calls 到 delta 字段供上层处理
            if msg.get("tool_calls"):
                choice.delta = {"tool_calls": msg["tool_calls"]}
            choices.append(choice)

        usage_data = data.get("usage") or {}
        usage = UsageInfo(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletionResponse(
            id=data.get("id", f"chatcmpl-{uuid.uuid4().hex[:12]}"),
            object=data.get("object", "chat.completion"),
            created=data.get("created", int(time.time())),
            model=data.get("model", request.model),
            choices=choices,
            usage=usage,
            raw=data,
        )

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """流式聊天补全（SSE）"""
        request.stream = True
        payload = self._build_payload(request)
        client = self._get_client()

        try:
            async with client.stream(
                "POST", "/v1/chat/completions", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        return
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = []
                    for c in data.get("choices", []):
                        delta = c.get("delta", {})
                        choices.append(ChatChoice(
                            index=c.get("index", 0),
                            delta=delta,
                            finish_reason=c.get("finish_reason"),
                        ))

                    yield StreamChunk(
                        id=data.get("id", ""),
                        object="chat.completion.chunk",
                        created=data.get("created", int(time.time())),
                        model=data.get("model", request.model),
                        choices=choices,
                    )
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            log.error("LLM 流式 API 错误", data={"status": status})
            raise RuntimeError(f"LLM API 返回 HTTP {status}；响应正文未记录")
        except httpx.RequestError as e:
            log.error("LLM 流式请求失败", data={"error_type": type(e).__name__})
            raise RuntimeError("LLM 流式请求失败；请检查网络和服务地址")

    async def list_models(self) -> List[Dict[str, Any]]:
        """列出模型（调用 /v1/models）"""
        client = self._get_client()
        try:
            resp = await client.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
            return [
                {"id": m["id"], "owned_by": m.get("owned_by", "unknown")}
                for m in data.get("data", [])
            ]
        except Exception as e:
            log.warning("获取模型列表失败", data={"error_type": type(e).__name__})
            return []

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
