"""
筱和灵眸(AethelEye) - OpenClaw / Claude Code / Codex CLI 兼容 Skill 导出器

生成 SKILL.md（YAML frontmatter + Markdown说明），
供 OpenClaw / Claude Code / Codex CLI 等 Agent 平台直接安装使用。

参考规范：https://github.com/openclaw/clawhub/blob/main/docs/skill-format.md

磁盘布局：
  data/skill-export/aetheleye-price-monitor/
    ├── SKILL.md         (frontmatter + 使用说明)
    └── .clawhub/        (可选)
"""
import json
from pathlib import Path
from typing import Any, Dict, List

from app.config import settings
from app.services.mcp.tools import TOOLS_REGISTRY

SKILL_NAME = "aetheleye-price-monitor"
SKILL_VERSION = "2.0.0"
SKILL_DESCRIPTION = "电商SKU到手价智能监控 — 支持天猫/淘宝，MCP协议暴露采集/告警/趋势能力"
SKILL_HOMEPAGE = "https://github.com/XHZJme/AethelEye"
SKILL_EMOJI = "👁️"

EXPORT_DIR = settings.data_dir / "skill-export" / SKILL_NAME


def _build_frontmatter() -> str:
    """构建 YAML frontmatter（OpenClaw / Claude Code 兼容）"""
    tool_names = [t["name"] for t in TOOLS_REGISTRY]

    lines = [
        "---",
        f"name: {SKILL_NAME}",
        f"description: {SKILL_DESCRIPTION}",
        f"version: {SKILL_VERSION}",
        "metadata:",
        "  openclaw:",
        "    requires:",
        "      env: []",
        "      bins: []",
        f"    emoji: \"{SKILL_EMOJI}\"",
        f"    homepage: {SKILL_HOMEPAGE}",
        "    envVars:",
        "      - name: AETHELEYE_MCP_TOKEN",
        "        required: false",
        "        description: Optional authentication token for AethelEye MCP Server.",
        "---",
    ]
    return "\n".join(lines)


def _build_body() -> str:
    """构建 Markdown 正文"""
    tool_lines = []
    for t in TOOLS_REGISTRY:
        tool_lines.append(f"- **`{t['name']}`** — {t['description']}")

    tools_section = "\n".join(tool_lines)

    body = f"""# {SKILL_NAME}

{SKILL_DESCRIPTION}

## 前置条件

1. 确保筱和灵眸(AethelEye) 后端正在运行
2. MCP Server 监听在 `http://127.0.0.1:8687/mcp`
3. 如已设置 Token 认证，需配置环境变量 `AETHELEYE_MCP_TOKEN`

## 可用 MCP Tools

{tools_section}

## 使用示例

通过 MCP 协议调用：

```json
{{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {{
    "name": "aetheleye.list_tasks",
    "arguments": {{}}
  }}
}}
```

## MCP 端点

- **协议**: JSON-RPC 2.0
- **地址**: `http://127.0.0.1:8687/mcp`
- **健康检查**: `GET http://127.0.0.1:8687/health`
- **Skill清单**: `GET http://127.0.0.1:8687/skill`

## 兼容平台

| 平台 | 支持 |
|------|------|
| OpenClaw | ✅ SKILL.md + MCP bridge |
| Claude Code | ✅ symlink 到 ~/.claude/skills/ |
| Codex CLI | ✅ SKILL.md 兼容 |
| Hermes Agent | ✅ /skill JSON 端点 |
"""
    return body


def generate_skill_md() -> str:
    """生成完整 SKILL.md 内容"""
    return _build_frontmatter() + "\n\n" + _build_body()


def export_skill_to_disk() -> str:
    """导出 Skill 到磁盘（data/skill-export/）"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    skill_path = EXPORT_DIR / "SKILL.md"
    content = generate_skill_md()
    skill_path.write_text(content, encoding="utf-8")
    return str(EXPORT_DIR.resolve())


def get_skill_info() -> Dict[str, Any]:
    """返回 Skill 元信息（供 API 使用）"""
    return {
        "name": SKILL_NAME,
        "description": SKILL_DESCRIPTION,
        "version": SKILL_VERSION,
        "emoji": SKILL_EMOJI,
        "homepage": SKILL_HOMEPAGE,
        "tools": [t["name"] for t in TOOLS_REGISTRY],
        "mcp_endpoint": "http://127.0.0.1:8687/mcp",
        "export_dir": str(EXPORT_DIR),
        "formats": ["openclaw", "claude_code", "codex_cli", "hermes"],
    }
