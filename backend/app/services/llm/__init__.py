"""
筱和灵眸(AethelEye) - LLM 网关模块

内嵌式 LLM 网关，提供：
  - 多 Provider 统一接口（OpenAI / MiniMax / Anthropic 等）
  - OpenAI Chat Completions 兼容 API
  - SSE 流式响应
  - API Key 管理 & 用量追踪
  - 模型路由 & 负载均衡
"""
