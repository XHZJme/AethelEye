"""
筱和灵眸(AethelEye) - MCP/Skill 管理 API

提供 MCP Server 和 Skill 的 CRUD 端点。
"""
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.mcp.mcp_registry import (
    add_mcp_server,
    install_skill_from_github,
    install_skill_from_zip,
    list_installed_skills,
    list_mcp_servers,
    remove_mcp_server,
    test_mcp_connection,
    toggle_mcp_server,
    toggle_skill,
    uninstall_skill,
    update_mcp_server,
)
from app.middleware.permission import require_admin

router = APIRouter(
    prefix="/api/mcp",
    tags=["MCP"],
    dependencies=[Depends(require_admin)],
)


# ── 请求模型 ──────────────────────────────────────────


class AddMcpServerRequest(BaseModel):
    name: str
    url: str
    transport: str = "streamable-http"
    headers: Optional[dict] = None
    description: str = ""


class UpdateMcpServerRequest(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    transport: Optional[str] = None
    headers: Optional[dict] = None
    description: Optional[str] = None


class TestConnectionRequest(BaseModel):
    url: str
    transport: str = "streamable-http"
    headers: Optional[dict] = None


class InstallSkillGithubRequest(BaseModel):
    repo_url: str


# ── MCP Server 端点 ──────────────────────────────────


@router.get("/servers")
async def get_mcp_servers():
    """列出所有已注册的外部 MCP Server"""
    return {"servers": list_mcp_servers()}


@router.post("/servers")
async def create_mcp_server(req: AddMcpServerRequest):
    """注册一个外部 MCP Server"""
    try:
        entry = add_mcp_server(
            name=req.name,
            url=req.url,
            transport=req.transport,
            headers=req.headers,
            description=req.description,
        )
        return entry
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/servers/{server_id}")
async def delete_mcp_server(server_id: str):
    """移除 MCP Server"""
    if remove_mcp_server(server_id):
        return {"message": "已移除"}
    raise HTTPException(status_code=404, detail="MCP Server 不存在")


@router.put("/servers/{server_id}/toggle")
async def toggle_server(server_id: str):
    """启用/禁用 MCP Server"""
    result = toggle_mcp_server(server_id)
    if result:
        return result
    raise HTTPException(status_code=404, detail="MCP Server 不存在")


@router.put("/servers/{server_id}")
async def update_server(server_id: str, req: UpdateMcpServerRequest):
    """更新 MCP Server 配置"""
    result = update_mcp_server(server_id, **req.dict(exclude_none=True))
    if result:
        return result
    raise HTTPException(status_code=404, detail="MCP Server 不存在")


@router.post("/servers/test")
async def test_connection(req: TestConnectionRequest):
    """测试 MCP Server 连接"""
    result = await test_mcp_connection(
        url=req.url,
        transport=req.transport,
        headers=req.headers,
    )
    return result


# ── Skill 安装端点 ───────────────────────────────────


@router.get("/skills")
async def get_installed_skills():
    """列出所有已安装的 Skill"""
    return {"skills": list_installed_skills()}


@router.post("/skills/install/zip")
async def install_skill_zip(file: UploadFile = File(...)):
    """从 ZIP 文件安装 Skill"""
    if not file.filename or not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 文件")

    tmp_dir = Path(tempfile.mkdtemp())
    tmp_path = tmp_dir / file.filename
    try:
        content = await file.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="ZIP 文件不得超过 10 MiB")
        tmp_path.write_bytes(content)
        result = install_skill_from_zip(tmp_path)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"安装失败: {str(e)}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@router.post("/skills/install/github")
async def install_skill_github(req: InstallSkillGithubRequest):
    """从 GitHub 仓库安装 Skill"""
    try:
        result = await install_skill_from_github(req.repo_url)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"安装失败: {str(e)}")


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    """卸载 Skill"""
    if uninstall_skill(skill_id):
        return {"message": "已卸载"}
    raise HTTPException(status_code=404, detail="Skill 不存在")


@router.put("/skills/{skill_id}/toggle")
async def toggle_skill_endpoint(skill_id: str):
    """启用/禁用 Skill"""
    result = toggle_skill(skill_id)
    if result:
        return result
    raise HTTPException(status_code=404, detail="Skill 不存在")
