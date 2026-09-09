"""
筱和灵眸(AethelEye) - MCP Server

实现 Model Context Protocol (MCP) 规范的 SSE Server。
端口 8687，独立于主 FastAPI 应用。

协议参考：https://modelcontextprotocol.io/docs/spec

MCP 通信格式：
  客户端发送 JSON-RPC 2.0 请求 → POST /mcp
  服务端返回 JSON-RPC 2.0 响应

支持的方法：
  - initialize → 返回 server info + capabilities
  - tools/list → 返回所有注册的 Tools
  - tools/call → 执行指定 Tool
"""
import asyncio
import json
import hashlib
import secrets
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.services.mcp.tools import TOOLS_REGISTRY
from app.utils.logger import get_logger

log = get_logger("system")

MCP_PORT = 8687

# ── MCP Server FastAPI 实例 ───────────────────────

mcp_app = FastAPI(
    title="AethelEye MCP Server",
    description="筱和灵眸 MCP Server — 暴露采集/监控/告警能力给外部 Agent",
    version="1.0.0",
)

mcp_app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8686",
        "http://localhost:8686",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Token 认证 ────────────────────────────────────

_mcp_tokens: set = set()


def generate_mcp_token() -> str:
    """生成 MCP 认证 Token"""
    token = secrets.token_urlsafe(32)
    _mcp_tokens.add(token)
    return token


def validate_mcp_token(token: str) -> bool:
    """验证 MCP Token"""
    if not _mcp_tokens:
        # 未配置 Token 时允许本地访问
        return True
    return token in _mcp_tokens


def _check_auth(authorization: Optional[str]) -> None:
    """检查请求授权"""
    if not _mcp_tokens:
        return  # 未配置认证，允许访问
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = authorization.replace("Bearer ", "")
    if not validate_mcp_token(token):
        raise HTTPException(status_code=403, detail="Invalid MCP token")


# ── MCP 协议处理 ──────────────────────────────────

SERVER_INFO = {
    "name": "aetheleye",
    "version": "2.0.0",
    "description": "筱和灵眸(AethelEye) — 电商SKU到手价智能监控平台",
}

SERVER_CAPABILITIES = {
    "tools": {"listChanged": False},
}


def _build_jsonrpc_response(id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _build_jsonrpc_error(id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


@mcp_app.post("/mcp")
async def mcp_endpoint(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    MCP JSON-RPC 2.0 端点。
    接收客户端请求，分发到对应 handler。
    """
    _check_auth(authorization)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_build_jsonrpc_error(None, -32700, "Parse error"), status_code=400)

    req_id = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {})

    log.info(f"[MCP] 收到请求: {method}", data={"id": req_id})

    # 路由
    if method == "initialize":
        return JSONResponse(_build_jsonrpc_response(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": SERVER_INFO,
            "capabilities": SERVER_CAPABILITIES,
        }))

    elif method == "tools/list":
        tools = []
        for t in TOOLS_REGISTRY:
            tools.append({
                "name": t["name"],
                "description": t["description"],
                "inputSchema": t["inputSchema"],
            })
        return JSONResponse(_build_jsonrpc_response(req_id, {"tools": tools}))

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        return await _handle_tool_call(req_id, tool_name, arguments)

    elif method == "ping":
        return JSONResponse(_build_jsonrpc_response(req_id, {}))

    else:
        return JSONResponse(_build_jsonrpc_error(req_id, -32601, f"Method not found: {method}"))


async def _handle_tool_call(req_id: Any, tool_name: str, arguments: Dict[str, Any]) -> JSONResponse:
    """执行 Tool 调用"""
    # 查找 Tool
    tool = None
    for t in TOOLS_REGISTRY:
        if t["name"] == tool_name:
            tool = t
            break

    if tool is None:
        return JSONResponse(_build_jsonrpc_error(req_id, -32602, f"Tool not found: {tool_name}"))

    handler = tool["handler"]

    try:
        result = await handler(**arguments)
        return JSONResponse(_build_jsonrpc_response(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
        }))
    except Exception as e:
        log.error(f"[MCP] Tool 执行失败: {tool_name}", data={"error": str(e)})
        return JSONResponse(_build_jsonrpc_error(req_id, -32000, f"Tool execution error: {str(e)}"))


# ── 健康检查 ──────────────────────────────────────

@mcp_app.get("/health")
async def health():
    return {"status": "ok", "server": "aetheleye-mcp", "tools_count": len(TOOLS_REGISTRY)}


# ── Skill 导出（OpenClaw / Claude Code / Hermes 兼容） ──

@mcp_app.get("/skill")
async def skill_manifest():
    """返回 Skill 元信息 JSON（Hermes兼容 + OpenClaw info）"""
    from app.services.mcp.skill_exporter import get_skill_info
    return get_skill_info()


@mcp_app.get("/skill/preview")
async def skill_preview():
    """预览生成的 SKILL.md 内容（OpenClaw/Claude Code 格式）"""
    from app.services.mcp.skill_exporter import generate_skill_md
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(generate_skill_md(), media_type="text/markdown")


@mcp_app.post("/skill/export")
async def skill_export():
    """导出 SKILL.md 到磁盘 data/skill-export/"""
    from app.services.mcp.skill_exporter import export_skill_to_disk
    path = export_skill_to_disk()
    return {"message": "Skill 已导出", "path": path}


@mcp_app.get("/tools")
async def list_tools():
    """返回所有注册的 MCP Tools（供前端展示）"""
    return {
        "tools": [
            {"name": t["name"], "description": t["description"]}
            for t in TOOLS_REGISTRY
        ]
    }


# ── 启动辅助 ─────────────────────────────────────

def start_mcp_server_background():
    """在后台线程启动 MCP Server"""
    import threading
    import uvicorn

    def _run():
        uvicorn.run(
            mcp_app,
            host="127.0.0.1",
            port=MCP_PORT,
            log_level="warning",
        )

    thread = threading.Thread(target=_run, daemon=True, name="mcp-server")
    thread.start()
    log.info(f"[MCP] Server 已在后台启动: http://127.0.0.1:{MCP_PORT}/mcp")
    return thread
