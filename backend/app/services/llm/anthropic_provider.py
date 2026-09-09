"""
筱和灵眸(AethelEye) - Anthropic (Claude) Provider

Anthropic Messages API → OpenAI 兼容格式适配。
Claude API 格式与 OpenAI 不同，此 Provider 负责协议转换。

默认 base_url: https://api.anthropic.com
模型前缀: claude-
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

ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_TIMEOUT = 120


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic (Claude) Provider

    将 OpenAI 格式请求转为 Anthropic Messages API 格式，
    响应再转回 OpenAI 格式。
    """

    PROVIDER_NAME = "anthropic"
    PROVIDER_DISPLAY_NAME = "Anthropic (Claude)"
    SUPPORTED_MODEL_PREFIXES = ["claude-"]

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        **kwargs,
    ):
        super().__init__(api_key, base_url, **kwargs)
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": ANTHROPIC_API_VERSION,
                    "Content-Type": "application/json",
                },
                timeout=httpx.Timeout(self.timeout, connect=10),
            )
        return self._client

    def _convert_messages(self, request: ChatCompletionRequest):
        """
        OpenAI messages → Anthropic messages 格式

        Anthropic 要求 system 作为顶层参数，非 messages 内。
        """
        system_text = ""
        messages = []
        for m in request.messages:
            if m.role == "system":
                system_text += m.content + "\n"
            else:
                messages.append({"role": m.role, "content": m.content})
        return system_text.strip(), messages

    def _build_payload(self, request: ChatCompletionRequest) -> Dict[str, Any]:
        system_text, messages = self._convert_messages(request)
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "temperature": request.temperature,
            "top_p": request.top_p,
        }
        if system_text:
            payload["system"] = system_text
        if request.stop:
            payload["stop_sequences"] = request.stop
        if request.stream:
            payload["stream"] = True
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
            resp = await client.post("/v1/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            log.error("Claude API 错误", data={"status": status})
            raise RuntimeError(f"Claude API 返回 HTTP {status}；响应正文未记录")
        except httpx.RequestError as e:
            log.error("Claude 请求失败", data={"error_type": type(e).__name__})
            raise RuntimeError("Claude 请求失败；请检查网络和服务地址")

        # Anthropic → OpenAI 格式转换
        content_blocks = data.get("content", [])
        text_content = ""
        for block in content_blocks:
            if block.get("type") == "text":
                text_content += block.get("text", "")

        usage_data = data.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
        )

        stop_reason = data.get("stop_reason", "stop")
        finish_reason_map = {"end_turn": "stop", "max_tokens": "length", "stop_sequence": "stop"}
        finish_reason = finish_reason_map.get(stop_reason, stop_reason)

        return ChatCompletionResponse(
            id=f"chatcmpl-{data.get('id', uuid.uuid4().hex[:12])}",
            object="chat.completion",
            created=int(time.time()),
            model=data.get("model", request.model),
            choices=[ChatChoice(
                index=0,
                message=ChatMessage(role="assistant", content=text_content),
                finish_reason=finish_reason,
            )],
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
                "POST", "/v1/messages", json=payload
            ) as resp:
                resp.raise_for_status()
                completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if not data_str:
                        continue
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    event_type = data.get("type", "")

                    if event_type == "content_block_delta":
                        delta_data = data.get("delta", {})
                        text = delta_data.get("text", "")
                        if text:
                            yield StreamChunk(
                                id=completion_id,
                                object="chat.completion.chunk",
                                created=int(time.time()),
                                model=request.model,
                                choices=[ChatChoice(
                                    index=0,
                                    delta={"role": "assistant", "content": text},
                                )],
                            )

                    elif event_type == "message_stop":
                        yield StreamChunk(
                            id=completion_id,
                            object="chat.completion.chunk",
                            created=int(time.time()),
                            model=request.model,
                            choices=[ChatChoice(
                                index=0,
                                delta={},
                                finish_reason="stop",
                            )],
                        )
                        return

        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            log.error("Claude 流式 API 错误", data={"status": status})
            raise RuntimeError(f"Claude API 返回 HTTP {status}；响应正文未记录")
        except httpx.RequestError as e:
            log.error("Claude 流式请求失败", data={"error_type": type(e).__name__})
            raise RuntimeError("Claude 流式请求失败；请检查网络和服务地址")

    async def list_models(self) -> List[Dict[str, Any]]:
        """Claude 固定模型列表"""
        return [
            {"id": "claude-sonnet-4-20250514", "owned_by": "anthropic"},
            {"id": "claude-3-5-sonnet-20241022", "owned_by": "anthropic"},
            {"id": "claude-3-5-haiku-20241022", "owned_by": "anthropic"},
            {"id": "claude-3-opus-20240229", "owned_by": "anthropic"},
        ]

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
