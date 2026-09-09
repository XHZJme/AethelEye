"""
筱和灵眸(AethelEye) - LLM 网关 API 路由

端点：
  POST /api/llm/chat             — 非流式聊天
  POST /api/llm/chat/stream      — 流式聊天（SSE）
  GET  /api/llm/models           — 列出可用模型
  GET  /api/llm/providers        — 列出已配置 Provider
  GET  /api/llm/provider-types   — 列出可用 Provider 类型
  POST /api/llm/providers        — 创建 Provider 配置
  PUT  /api/llm/providers/{id}   — 更新 Provider 配置
  DELETE /api/llm/providers/{id} — 删除 Provider 配置
  GET  /api/llm/usage            — 用量统计
"""
import json
import time
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func as sql_func

from app.database import get_sync_session
from app.models.llm_provider import LLMProviderConfig, LLMUsageLog
from app.models.task import MonitorTask
from app.models.alert import Alert
from app.models.user import User
from app.middleware.permission import require_login, require_admin
from app.services.llm.gateway import get_llm_gateway
from app.services.ai_tools import (
    get_tools_description_text,
    parse_tool_calls_from_text,
    execute_tool,
)
from app.utils.logger import get_logger
from app.utils.encryption import encrypt_secret

log = get_logger("audit")

router = APIRouter(prefix="/api/llm", tags=["LLM网关"])


# ===== Pydantic 模型 =====

class ChatMessageDTO(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: List[ChatMessageDTO]
    temperature: float = Field(0.7, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=128000)
    stream: bool = False


class ProviderCreateRequest(BaseModel):
    provider_type: str
    display_name: str
    api_key: str
    base_url: Optional[str] = None
    model_prefixes: Optional[List[str]] = None
    default_model: Optional[str] = None
    priority: int = 100
    rate_limit_rpm: int = 0
    note: Optional[str] = None


class ProviderUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model_prefixes: Optional[List[str]] = None
    default_model: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None
    rate_limit_rpm: Optional[int] = None
    note: Optional[str] = None


# ===== 系统提示词 =====

_SYSTEM_PROMPT_BASE = """你是「筱和灵眸(AethelEye)」的内置 AI 助手。
筱和灵眸是一款电商价格监控与竞品分析系统，具备以下核心功能：
- 淘宝/天猫商品价格自动采集与监控
- SKU 级别的价格异动检测与 Webhook 告警
- 价格趋势分析与可视化
- 浏览器配置与 Cookie 维护
- AI 驱动的运营建议与数据解读

## 技术栈
- 后端: Python + FastAPI + SQLAlchemy + SQLite，端口 8686
- 前端: Vue 3 + Element Plus + Vite，端口 5173/5174
- 采集引擎: Playwright（有头浏览器模式，非 requests/BeautifulSoup）
- AI网关: 兼容 OpenAI / Anthropic / 国产大模型（MiniMax/GLM）
- MCP Server: 端口 8687，JSON-RPC 2.0

## 采集引擎架构（可插拔）
系统使用 BaseCollectionEngine 抽象基类（services/engine_base.py），所有引擎必须实现：
- collect(task, profile_id, ...) → CollectionResult(success, product_title, shop_name, skus, screenshot_path, error, duration_ms)
- collect_for_parse(url, profile_id, ...) → dict（轻量解析，创建任务前预览）
- parse_product_url(url) → (platform, is_valid)
当前内置引擎：Playwright引擎（collector_engine.py）+ AI RPA引擎（engines/ai_rpa/）
引擎通过 engine_registry 管理注册与切换，支持外部引擎包（manifest.json 规范）。

## 插件系统
插件存放于 data/plugins/<name>/，每个插件包含：
- manifest.json（必须有 name, display_name, version, type 字段）
- main.py（入口文件，默认调用 run() 函数）
- type 可选: engine / analysis / alert / tool / mcp / skill

插件与后端共享 Python 进程；模块黑名单和 60 秒超时只是尽力而为的限制，不构成操作系统级安全沙箱。只允许上传、审核并启用来源可信且已经人工审计的插件。

插件 API: POST /api/plugins/upload, POST /api/plugins/{id}/execute 等。
用户如果要写插件，必须遵循上述规范，不能写独立脚本。

## 回答规则
- 用中文回答，风格简洁专业
- 回答时直接给出数据和结论，不要说"你可以去某个页面查看"
- 当数据已在下方提供时，请直接引用
- 如果用户问的信息不在下方数据摘要中，再建议用户去对应页面查看
- 如果用户要求写代码（插件/引擎），必须基于上述系统架构，不能给出脱离系统的独立脚本
- 采集相关代码必须使用 Playwright（浏览器自动化），不要用 requests/BeautifulSoup"""


def _build_system_context() -> str:
    """查询数据库，构建实时系统数据摘要注入到系统提示词"""
    sections = []
    try:
        with get_sync_session() as session:
            now = datetime.now()
            # ---- 任务总览 ----
            total = session.query(MonitorTask).count()
            active = session.query(MonitorTask).filter(MonitorTask.status == "active").count()
            paused = session.query(MonitorTask).filter(MonitorTask.status == "paused").count()
            error = session.query(MonitorTask).filter(MonitorTask.status.in_(["error", "need_login"])).count()
            sections.append(f"## 任务总览\n总任务数: {total} | 运行中: {active} | 暂停: {paused} | 异常: {error}")

            # ---- 最近失败的任务（last_error 非空，最近24h内更新过）----
            cutoff_24h = now - timedelta(hours=24)
            failed_tasks = session.query(MonitorTask).filter(
                MonitorTask.last_error.isnot(None),
                MonitorTask.last_error != "",
                MonitorTask.updated_at >= cutoff_24h,
            ).order_by(MonitorTask.updated_at.desc()).limit(5).all()

            if failed_tasks:
                lines = []
                for t in failed_tasks:
                    title = (t.product_title or "未命名")[:30]
                    err = (t.last_error or "")[:80]
                    check_time = t.last_check_at.strftime("%m-%d %H:%M") if t.last_check_at else "无"
                    lines.append(f"- [ID {t.id}] {title} | 状态: {t.status} | 最后采集: {check_time} | 错误: {err}")
                sections.append("## 最近24h采集失败/异常的任务\n" + "\n".join(lines))
            else:
                sections.append("## 最近24h采集失败/异常的任务\n无失败记录，所有任务运行正常。")

            # ---- 最近告警 ----
            recent_alerts = session.query(Alert).filter(
                Alert.detected_at >= cutoff_24h,
            ).order_by(Alert.detected_at.desc()).limit(5).all()

            if recent_alerts:
                lines = []
                for a in recent_alerts:
                    det_time = a.detected_at.strftime("%m-%d %H:%M") if a.detected_at else "?"
                    lines.append(f"- [告警ID {a.id}] 任务ID {a.task_id} | 类型: {a.alert_type} | "
                                 f"基准价: {a.base_price} → 异动价: {a.alert_price} | 差额: {a.price_diff} ({a.price_diff_pct}%) | "
                                 f"状态: {a.status} | 时间: {det_time}")
                sections.append("## 最近24h告警\n" + "\n".join(lines))
            else:
                sections.append("## 最近24h告警\n无告警记录。")

            # ---- 最近成功采集的任务 ----
            recent_ok = session.query(MonitorTask).filter(
                MonitorTask.last_check_at >= cutoff_24h,
                MonitorTask.status == "active",
            ).order_by(MonitorTask.last_check_at.desc()).limit(5).all()

            if recent_ok:
                lines = []
                for t in recent_ok:
                    title = (t.product_title or "未命名")[:30]
                    check_time = t.last_check_at.strftime("%m-%d %H:%M") if t.last_check_at else "无"
                    next_time = t.next_check_at.strftime("%m-%d %H:%M") if t.next_check_at else "无"
                    lines.append(f"- [ID {t.id}] {title} | 最后采集: {check_time} | 下次: {next_time}")
                sections.append("## 最近成功采集的任务\n" + "\n".join(lines))

    except Exception as e:
        log.warning(f"构建AI上下文失败", data={"error": str(e)})
        sections.append("（系统数据暂时不可用）")

    return "\n\n".join(sections)


def _ensure_system_prompt(messages: list) -> list:
    """确保消息列表开头有系统提示词 + 实时数据摘要 + 工具描述"""
    if messages and messages[0].get("role") == "system":
        return messages
    context = _build_system_context()
    tools_desc = get_tools_description_text()
    full_prompt = (
        _SYSTEM_PROMPT_BASE
        + f"\n\n{tools_desc}"
        + f"\n\n---\n以下是系统实时数据摘要（当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}）：\n\n{context}"
    )
    return [{"role": "system", "content": full_prompt}] + messages


def _execute_tool_calls_from_text(text: str) -> Optional[str]:
    """解析 AI 回复中的工具调用并执行，返回结果文本（无调用返回 None）"""
    calls = parse_tool_calls_from_text(text)
    if not calls:
        return None

    results = []
    for call in calls:
        log.info(f"[AI Tool] 执行: {call['name']}", data={"args": call.get("arguments", {})})
        result = execute_tool(call["name"], call.get("arguments", {}))
        if result["success"]:
            results.append(f"✅ 工具 `{call['name']}` 执行成功：\n{result['result']}")
        else:
            results.append(f"❌ 工具 `{call['name']}` 执行失败：{result['error']}")

    return "\n\n---\n\n".join(results)


# ===== 聊天端点 =====

@router.post("/chat", summary="非流式聊天")
async def chat(request: ChatRequest, user: User = Depends(require_login)):
    """发送聊天请求（非流式），返回完整响应"""
    gateway = get_llm_gateway()
    try:
        raw_messages = [{"role": m.role, "content": m.content} for m in request.messages]
        response = await gateway.chat(
            messages=_ensure_system_prompt(raw_messages),
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            source="chat",
        )
        # 转为 dict
        return {
            "id": response.id,
            "object": response.object,
            "created": response.created,
            "model": response.model,
            "choices": [
                {
                    "index": c.index,
                    "message": {"role": c.message.role, "content": c.message.content} if c.message else None,
                    "finish_reason": c.finish_reason,
                }
                for c in response.choices
            ],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            } if response.usage else None,
        }
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        log.error(f"LLM 聊天失败", data={"error": str(e), "model": request.model})
        raise HTTPException(status_code=500, detail=f"LLM 请求异常: {e}")


@router.post("/chat/stream", summary="流式聊天 (SSE)")
async def chat_stream(request: ChatRequest, user: User = Depends(require_login)):
    """发送聊天请求（流式），返回 SSE 流"""
    gateway = get_llm_gateway()

    async def event_generator():
        try:
            raw_messages = [{"role": m.role, "content": m.content} for m in request.messages]
            full_text = ""  # 缓存完整回复用于工具解析
            last_chunk_data = None

            async for chunk in gateway.chat_stream(
                messages=_ensure_system_prompt(raw_messages),
                model=request.model,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                source="chat",
            ):
                data = {
                    "id": chunk.id,
                    "object": chunk.object,
                    "created": chunk.created,
                    "model": chunk.model,
                    "choices": [
                        {
                            "index": c.index,
                            "delta": c.delta or {},
                            "finish_reason": c.finish_reason,
                        }
                        for c in chunk.choices
                    ],
                }
                last_chunk_data = data
                # 累积文本
                for c in chunk.choices:
                    if c.delta and c.delta.get("content"):
                        full_text += c.delta["content"]
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

            # ---- 流式结束后，检测并执行工具调用 ----
            tool_result = _execute_tool_calls_from_text(full_text)
            if tool_result:
                # 发送分隔标记
                sep_chunk = {
                    "id": (last_chunk_data or {}).get("id", ""),
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"content": "\n\n---\n**🔧 工具执行结果：**\n\n"}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(sep_chunk, ensure_ascii=False)}\n\n"

                # 分块发送工具结果
                result_chunk = {
                    "id": (last_chunk_data or {}).get("id", ""),
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {"content": tool_result}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(result_chunk, ensure_ascii=False)}\n\n"

                # 发送结束标记
                done_chunk = {
                    "id": (last_chunk_data or {}).get("id", ""),
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(done_chunk, ensure_ascii=False)}\n\n"

            yield "data: [DONE]\n\n"
        except RuntimeError as e:
            error_data = {"error": {"message": str(e), "type": "upstream_error"}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_data = {"error": {"message": str(e), "type": "internal_error"}}
            yield f"data: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ===== 模型端点 =====

@router.get("/models", summary="列出可用模型")
async def list_models(user: User = Depends(require_login)):
    """列出所有已配置 Provider 支持的模型"""
    gateway = get_llm_gateway()
    return {"models": gateway.list_all_models()}


@router.get("/provider-types", summary="列出可用 Provider 类型")
async def list_provider_types(user: User = Depends(require_login)):
    """列出系统支持的 Provider 类型"""
    gateway = get_llm_gateway()
    return {"types": gateway.get_provider_types()}


# ===== Provider 管理端点（仅管理员） =====

@router.get("/providers", summary="列出已配置 Provider")
async def list_providers(admin: User = Depends(require_admin)):
    """列出所有 Provider 配置"""
    with get_sync_session() as session:
        configs = session.query(LLMProviderConfig).order_by(
            LLMProviderConfig.priority
        ).all()
        return {
            "providers": [
                {
                    "id": c.id,
                    "provider_type": c.provider_type,
                    "display_name": c.display_name,
                    "base_url": c.base_url,
                    "model_prefixes": json.loads(c.model_prefixes) if c.model_prefixes else None,
                    "default_model": c.default_model,
                    "is_active": c.is_active,
                    "priority": c.priority,
                    "rate_limit_rpm": c.rate_limit_rpm,
                    "note": c.note,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                    # 不回显前缀、后缀或密文，减少界面截图和日志泄露面。
                    "api_key_masked": "••••••••（已配置）" if c.api_key else "未配置",
                }
                for c in configs
            ]
        }


@router.post("/providers", summary="创建 Provider 配置")
async def create_provider(
    request: ProviderCreateRequest,
    admin: User = Depends(require_admin),
):
    """创建新的 LLM Provider 配置"""
    # 验证 provider_type
    gateway = get_llm_gateway()
    valid_types = [t["type"] for t in gateway.get_provider_types()]
    if request.provider_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的 Provider 类型: {request.provider_type}。可选: {valid_types}"
        )

    with get_sync_session() as session:
        config = LLMProviderConfig(
            provider_type=request.provider_type,
            display_name=request.display_name,
            api_key=encrypt_secret(request.api_key.strip()),
            base_url=request.base_url,
            model_prefixes=json.dumps(request.model_prefixes) if request.model_prefixes else None,
            default_model=request.default_model,
            priority=request.priority,
            rate_limit_rpm=request.rate_limit_rpm,
            note=request.note,
        )
        session.add(config)
        session.commit()
        config_id = config.id

    # 重新加载 Provider
    gateway.reload()

    log.info(f"LLM Provider 已创建", data={
        "config_id": config_id,
        "type": request.provider_type,
        "name": request.display_name,
        "by": admin.username,
    })

    return {"id": config_id, "message": f"Provider '{request.display_name}' 已创建"}


@router.put("/providers/{provider_id}", summary="更新 Provider 配置")
async def update_provider(
    provider_id: int,
    request: ProviderUpdateRequest,
    admin: User = Depends(require_admin),
):
    """更新 Provider 配置"""
    with get_sync_session() as session:
        config = session.query(LLMProviderConfig).filter(
            LLMProviderConfig.id == provider_id
        ).first()
        if not config:
            raise HTTPException(status_code=404, detail="Provider 配置不存在")

        if request.display_name is not None:
            config.display_name = request.display_name
        if request.api_key is not None:
            if not request.api_key.strip():
                raise HTTPException(status_code=400, detail="API Key 不能为空")
            config.api_key = encrypt_secret(request.api_key.strip())
        if request.base_url is not None:
            config.base_url = request.base_url or None
        if request.model_prefixes is not None:
            config.model_prefixes = json.dumps(request.model_prefixes)
        if request.default_model is not None:
            config.default_model = request.default_model
        if request.is_active is not None:
            config.is_active = request.is_active
        if request.priority is not None:
            config.priority = request.priority
        if request.rate_limit_rpm is not None:
            config.rate_limit_rpm = request.rate_limit_rpm
        if request.note is not None:
            config.note = request.note

        session.commit()

    # 重新加载
    get_llm_gateway().reload()

    log.info(f"LLM Provider 已更新", data={"config_id": provider_id, "by": admin.username})
    return {"message": f"Provider #{provider_id} 已更新"}


@router.delete("/providers/{provider_id}", summary="删除 Provider 配置")
async def delete_provider(
    provider_id: int,
    admin: User = Depends(require_admin),
):
    """删除 Provider 配置"""
    with get_sync_session() as session:
        config = session.query(LLMProviderConfig).filter(
            LLMProviderConfig.id == provider_id
        ).first()
        if not config:
            raise HTTPException(status_code=404, detail="Provider 配置不存在")
        session.delete(config)
        session.commit()

    get_llm_gateway().reload()
    log.info(f"LLM Provider 已删除", data={"config_id": provider_id, "by": admin.username})
    return {"message": f"Provider #{provider_id} 已删除"}


# ===== 连通性测试 =====

@router.post("/providers/{provider_id}/test", summary="测试 Provider 连通性")
async def test_provider_connection(
    provider_id: int,
    admin: User = Depends(require_admin),
):
    """
    向 Provider 发送一条测试消息，验证 API Key 和网络连通性。
    返回响应延迟和模型信息。
    """
    gateway = get_llm_gateway()
    gateway.reload()

    with get_sync_session() as session:
        config = session.query(LLMProviderConfig).filter(
            LLMProviderConfig.id == provider_id
        ).first()
        if not config:
            raise HTTPException(status_code=404, detail="Provider 配置不存在")
        test_model = config.default_model
        if not test_model:
            # 取模型前缀列表的第一个作为测试模型
            prefixes = json.loads(config.model_prefixes) if config.model_prefixes else []
            test_model = prefixes[0] + "test" if prefixes else None

    if not test_model:
        raise HTTPException(status_code=400, detail="该 Provider 未配置默认模型或模型前缀，无法测试")

    start = time.time()
    try:
        response = await gateway.chat(
            messages=[{"role": "user", "content": "Hi, this is a connectivity test. Reply with 'OK'."}],
            model=test_model,
            temperature=0,
            max_tokens=10,
            source="connectivity_test",
        )
        latency_ms = int((time.time() - start) * 1000)
        content = ""
        if response.choices and response.choices[0].message:
            content = response.choices[0].message.content or ""
        return {
            "success": True,
            "latency_ms": latency_ms,
            "model": response.model,
            "response": content[:100],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
        }
    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "error": str(e),
        }


# ===== 用量统计 =====

@router.get("/usage", summary="用量统计")
async def get_usage(
    days: int = Query(7, ge=1, le=90),
    admin: User = Depends(require_admin),
):
    """获取 LLM 用量统计"""
    since = datetime.now() - timedelta(days=days)

    with get_sync_session() as session:
        # 总计
        total = session.query(
            sql_func.count(LLMUsageLog.id).label("requests"),
            sql_func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
            sql_func.sum(LLMUsageLog.prompt_tokens).label("prompt_tokens"),
            sql_func.sum(LLMUsageLog.completion_tokens).label("completion_tokens"),
            sql_func.avg(LLMUsageLog.duration_ms).label("avg_duration_ms"),
        ).filter(LLMUsageLog.created_at >= since).first()

        # 按模型分组
        by_model = session.query(
            LLMUsageLog.model,
            sql_func.count(LLMUsageLog.id).label("requests"),
            sql_func.sum(LLMUsageLog.total_tokens).label("total_tokens"),
        ).filter(
            LLMUsageLog.created_at >= since
        ).group_by(LLMUsageLog.model).all()

        # 错误数
        errors = session.query(
            sql_func.count(LLMUsageLog.id)
        ).filter(
            LLMUsageLog.created_at >= since,
            LLMUsageLog.success == False,
        ).scalar() or 0

        return {
            "period_days": days,
            "summary": {
                "requests": total.requests or 0,
                "total_tokens": int(total.total_tokens or 0),
                "prompt_tokens": int(total.prompt_tokens or 0),
                "completion_tokens": int(total.completion_tokens or 0),
                "avg_duration_ms": int(total.avg_duration_ms or 0),
                "errors": errors,
            },
            "by_model": [
                {
                    "model": row.model,
                    "requests": row.requests,
                    "total_tokens": int(row.total_tokens or 0),
                }
                for row in by_model
            ],
        }
