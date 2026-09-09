"""
筱和灵眸(AethelEye) - MCP/Skill 安装注册表

管理外部 MCP Server 连接 和 外部 Skill 安装。
参考 cc-switch 的统一 MCP 管理面板设计。

持久化存储：
  data/mcp_registry.json        - MCP Server / Skill 配置
  data/installed-skills/<name>/ - 已安装的 Skill 文件
"""
import json
import re
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.config import settings
from app.utils.encryption import encrypt_secret
from app.utils.logger import get_logger

log = get_logger("system")

DATA_DIR = settings.data_dir
REGISTRY_FILE = DATA_DIR / "mcp_registry.json"
SKILLS_DIR = DATA_DIR / "installed-skills"
MAX_SKILL_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_SKILL_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_SKILL_FILES = 500
_SAFE_SKILL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SAFE_GITHUB_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


def _load_registry() -> Dict[str, Any]:
    """加载注册表"""
    if not REGISTRY_FILE.exists():
        return {"mcp_servers": [], "installed_skills": []}
    try:
        registry = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        # 兼容旧版：MCP 请求头可能含 Bearer Token，首次读取时迁移为密文。
        changed = False
        for server in registry.get("mcp_servers", []):
            headers = server.get("headers")
            if isinstance(headers, dict):
                payload = json.dumps(headers, ensure_ascii=False, separators=(",", ":"))
                server["headers"] = encrypt_secret(payload) if headers else ""
                changed = True
        if changed:
            _save_registry(registry)
        return registry
    except Exception:
        return {"mcp_servers": [], "installed_skills": []}


def _save_registry(data: Dict[str, Any]):
    """保存注册表"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _encode_headers(headers: Optional[Dict[str, str]]) -> str:
    """将可能含鉴权令牌的请求头整体加密。"""
    if not headers:
        return ""
    return encrypt_secret(json.dumps(headers, ensure_ascii=False, separators=(",", ":")))


def _public_server(entry: Dict[str, Any]) -> Dict[str, Any]:
    """生成可返回给前端的脱敏副本。"""
    public = dict(entry)
    stored_headers = public.pop("headers", "")
    public["headers"] = {}
    public["headers_configured"] = bool(stored_headers)
    return public


def _validate_skill_name(name: str) -> str:
    name = name.strip()
    if not _SAFE_SKILL_NAME.fullmatch(name):
        raise ValueError("Skill 名称只能包含字母、数字、点、下划线和连字符，且最长 64 个字符")
    return name


def _skill_target(name: str) -> Path:
    """返回已验证且位于安装根目录内的 Skill 目标路径。"""
    safe_name = _validate_skill_name(name)
    root = SKILLS_DIR.resolve()
    target = (SKILLS_DIR / safe_name).resolve()
    target.relative_to(root)
    return target


# ── MCP Server 管理 ──────────────────────────────────


def list_mcp_servers() -> List[Dict]:
    """列出所有已注册的外部 MCP Server"""
    reg = _load_registry()
    return [_public_server(server) for server in reg.get("mcp_servers", [])]


def add_mcp_server(
    name: str,
    url: str,
    transport: str = "streamable-http",
    headers: Optional[Dict[str, str]] = None,
    description: str = "",
) -> Dict:
    """注册一个外部 MCP Server"""
    reg = _load_registry()
    server_id = str(uuid.uuid4())[:8]

    # 检查重名
    for s in reg["mcp_servers"]:
        if s["name"] == name:
            raise ValueError(f"MCP Server '{name}' 已存在")

    entry = {
        "id": server_id,
        "name": name,
        "url": url,
        "transport": transport,
        "headers": _encode_headers(headers),
        "description": description,
        "enabled": True,
        "installed_at": datetime.now().isoformat(),
        "last_connected": None,
        "status": "unknown",
    }
    reg["mcp_servers"].append(entry)
    _save_registry(reg)
    log.info(f"[MCP Registry] 添加 MCP Server: {name}")
    return _public_server(entry)


def remove_mcp_server(server_id: str) -> bool:
    """移除一个 MCP Server"""
    reg = _load_registry()
    original_len = len(reg["mcp_servers"])
    reg["mcp_servers"] = [s for s in reg["mcp_servers"] if s["id"] != server_id]
    if len(reg["mcp_servers"]) < original_len:
        _save_registry(reg)
        log.info(f"[MCP Registry] 移除 MCP Server: {server_id}")
        return True
    return False


def toggle_mcp_server(server_id: str) -> Optional[Dict]:
    """启用/禁用 MCP Server"""
    reg = _load_registry()
    for s in reg["mcp_servers"]:
        if s["id"] == server_id:
            s["enabled"] = not s["enabled"]
            _save_registry(reg)
            log.info(f"[MCP Registry] MCP Server {s['name']} {'启用' if s['enabled'] else '禁用'}")
            return _public_server(s)
    return None


def update_mcp_server(server_id: str, **kwargs) -> Optional[Dict]:
    """更新 MCP Server 配置"""
    reg = _load_registry()
    for s in reg["mcp_servers"]:
        if s["id"] == server_id:
            for key in ("name", "url", "transport", "headers", "description"):
                if key in kwargs and kwargs[key] is not None:
                    s[key] = _encode_headers(kwargs[key]) if key == "headers" else kwargs[key]
            _save_registry(reg)
            return _public_server(s)
    return None


async def test_mcp_connection(url: str, transport: str = "streamable-http", headers: Optional[Dict] = None) -> Dict:
    """测试 MCP Server 连接"""
    import httpx

    try:
        test_url = url.rstrip("/")
        # 对于 streamable-http，尝试发送一个 ping
        if transport == "streamable-http":
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "ping",
                "params": {},
            }
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(test_url, json=payload, headers=headers or {})
                if resp.status_code == 200:
                    return {"success": True, "message": "连接成功"}
                else:
                    return {"success": False, "message": f"HTTP {resp.status_code}；响应正文未返回"}
        elif transport == "sse":
            # SSE 只需要验证端点可达
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(test_url, headers=headers or {})
                return {"success": resp.status_code < 400, "message": f"HTTP {resp.status_code}"}
        else:
            return {"success": False, "message": f"不支持的传输协议: {transport}"}
    except httpx.ConnectError:
        return {"success": False, "message": "连接失败：无法连接到目标地址"}
    except httpx.TimeoutException:
        return {"success": False, "message": "连接超时"}
    except Exception as e:
        return {"success": False, "message": f"连接异常: {str(e)}"}


# ── Skill 安装管理 ───────────────────────────────────


def list_installed_skills() -> List[Dict]:
    """列出所有已安装的 Skill"""
    reg = _load_registry()
    return reg.get("installed_skills", [])


def install_skill_from_zip(zip_path: Path, name: Optional[str] = None) -> Dict:
    """从 ZIP 文件安装 Skill"""
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)

    if not zipfile.is_zipfile(zip_path):
        raise ValueError("无效的 ZIP 文件")
    if zip_path.stat().st_size > MAX_SKILL_ARCHIVE_BYTES:
        raise ValueError("ZIP 文件不得超过 10 MiB")

    with zipfile.ZipFile(zip_path, "r") as zf:
        members = zf.infolist()
        if len(members) > MAX_SKILL_FILES:
            raise ValueError(f"Skill 文件数超过上限（{MAX_SKILL_FILES}）")
        if sum(member.file_size for member in members) > MAX_SKILL_UNCOMPRESSED_BYTES:
            raise ValueError("Skill 解压后大小超过 50 MiB 上限")

        file_list = [member.filename.replace("\\", "/") for member in members]
        if len(file_list) != len(set(file_list)):
            raise ValueError("ZIP 包含重复文件路径")
        member_lookup = {member.filename.replace("\\", "/"): member for member in members}
        for member_name in file_list:
            pure = PurePosixPath(member_name)
            if (
                not member_name
                or "\x00" in member_name
                or pure.is_absolute()
                or ".." in pure.parts
                or (pure.parts and ":" in pure.parts[0])
            ):
                raise ValueError(f"ZIP 包含越界或非法路径: {member_name}")

        root_prefix = _find_zip_root(file_list)
        skill_md_path = next(
            (
                member_name
                for member_name in file_list
                if (member_name[len(root_prefix):] if root_prefix else member_name) == "SKILL.md"
            ),
            None,
        )
        if not skill_md_path:
            raise ValueError("Skill ZIP 根目录缺少 SKILL.md")

        # 确定 skill 名称
        if name:
            skill_name = _validate_skill_name(name)
        else:
            # 从 SKILL.md frontmatter 提取 name
            content = zf.read(member_lookup[skill_md_path]).decode("utf-8")
            skill_name = _validate_skill_name(_extract_skill_name(content) or zip_path.stem)

        # 解压到目标目录
        target_dir = _skill_target(skill_name)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        # 解压（处理根目录层级）
        target_root = target_dir.resolve()
        for member_name in file_list:
            if member_name.endswith("/"):
                continue
            relative = member_name[len(root_prefix):] if root_prefix else member_name
            if not relative:
                continue
            dest = (target_dir / relative).resolve()
            try:
                dest.relative_to(target_root)
            except ValueError as exc:
                raise ValueError(f"ZIP 包含越界路径: {member_name}") from exc
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member_lookup[member_name]) as src, open(dest, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)

    # 读取 SKILL.md 元信息
    skill_md_file = target_dir / "SKILL.md"
    description = ""
    version = "unknown"
    if skill_md_file.exists():
        content = skill_md_file.read_text(encoding="utf-8")
        description = _extract_skill_field(content, "description") or ""
        version = _extract_skill_field(content, "version") or "unknown"

    # 注册
    skill_id = str(uuid.uuid4())[:8]
    entry = {
        "id": skill_id,
        "name": skill_name,
        "description": description,
        "version": version,
        "source": "zip",
        "source_url": zip_path.name,
        "path": str(SKILLS_DIR / skill_name),
        "has_skill_md": skill_md_file.exists(),
        "enabled": True,
        "installed_at": datetime.now().isoformat(),
    }

    reg = _load_registry()
    # 移除同名旧安装
    reg["installed_skills"] = [s for s in reg["installed_skills"] if s["name"] != skill_name]
    reg["installed_skills"].append(entry)
    _save_registry(reg)
    log.info(f"[MCP Registry] Skill 已安装: {skill_name} (from ZIP)")
    return entry


async def install_skill_from_github(repo_url: str) -> Dict:
    """从 GitHub 仓库安装 Skill（下载 ZIP 并安装）"""
    import httpx
    import tempfile

    # 仅接受规范的 https://github.com/<owner>/<repo> 仓库根地址。
    repo_url = repo_url.strip().rstrip("/")
    parsed = urlparse(repo_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or parsed.hostname != "github.com" or len(parts) != 2:
        raise ValueError("仅支持 https://github.com/<owner>/<repo> 格式")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not _SAFE_GITHUB_PART.fullmatch(owner) or not _SAFE_GITHUB_PART.fullmatch(repo):
        raise ValueError("GitHub 仓库地址包含非法字符")
    skill_name = _validate_skill_name(repo)
    repo_url = f"https://github.com/{owner}/{repo}"
    zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"

    # 下载 ZIP
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        tmp_dir = Path(tempfile.mkdtemp())
        tmp_zip = tmp_dir / f"{repo}.zip"
        try:
            for branch in ("main", "master"):
                zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
                async with client.stream("GET", zip_url) as resp:
                    if resp.status_code == 404:
                        continue
                    if resp.status_code != 200:
                        raise ValueError(f"下载失败: HTTP {resp.status_code}")
                    content_length = int(resp.headers.get("content-length", "0") or 0)
                    if content_length > MAX_SKILL_ARCHIVE_BYTES:
                        raise ValueError("ZIP 文件不得超过 10 MiB")
                    downloaded = 0
                    with open(tmp_zip, "wb") as dst:
                        async for chunk in resp.aiter_bytes(1024 * 1024):
                            downloaded += len(chunk)
                            if downloaded > MAX_SKILL_ARCHIVE_BYTES:
                                raise ValueError("ZIP 文件不得超过 10 MiB")
                            dst.write(chunk)
                    break
            else:
                raise ValueError("下载失败: 仓库没有 main 或 master 分支")

            result = install_skill_from_zip(tmp_zip, name=skill_name)
            result["source"] = "github"
            result["source_url"] = repo_url
            # 更新注册表中的 source
            reg = _load_registry()
            for s in reg["installed_skills"]:
                if s["id"] == result["id"]:
                    s["source"] = "github"
                    s["source_url"] = repo_url
            _save_registry(reg)
            return result
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def uninstall_skill(skill_id: str) -> bool:
    """卸载 Skill"""
    reg = _load_registry()
    target = None
    for s in reg["installed_skills"]:
        if s["id"] == skill_id:
            target = s
            break
    if not target:
        return False

    # 删除文件
    try:
        skill_dir = _skill_target(target["name"])
    except ValueError:
        log.error("[MCP Registry] 注册表中的 Skill 名称无效，拒绝删除")
        return False
    if skill_dir.exists():
        shutil.rmtree(skill_dir, ignore_errors=True)

    reg["installed_skills"] = [s for s in reg["installed_skills"] if s["id"] != skill_id]
    _save_registry(reg)
    log.info(f"[MCP Registry] Skill 已卸载: {target['name']}")
    return True


def toggle_skill(skill_id: str) -> Optional[Dict]:
    """启用/禁用 Skill"""
    reg = _load_registry()
    for s in reg["installed_skills"]:
        if s["id"] == skill_id:
            s["enabled"] = not s["enabled"]
            _save_registry(reg)
            return s
    return None


# ── 辅助函数 ──────────────────────────────────────────


def _extract_skill_name(content: str) -> Optional[str]:
    """从 SKILL.md frontmatter 提取 name"""
    return _extract_skill_field(content, "name")


def _extract_skill_field(content: str, field: str) -> Optional[str]:
    """从 YAML frontmatter 提取字段"""
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end < 0:
        return None
    frontmatter = content[3:end]
    for line in frontmatter.strip().splitlines():
        line = line.strip()
        if line.startswith(f"{field}:"):
            val = line[len(field) + 1:].strip().strip('"').strip("'")
            return val if val else None
    return None


def _find_zip_root(file_list: List[str]) -> str:
    """找到 ZIP 中的根目录前缀（如 repo-main/）"""
    if not file_list:
        return ""
    first = file_list[0]
    if "/" in first:
        prefix = first.split("/")[0] + "/"
        if all(f.startswith(prefix) for f in file_list if f):
            return prefix
    return ""
