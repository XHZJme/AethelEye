"""
筱和灵眸(AethelEye) - AI 工具执行器

让内置 AI 助手能够直接在系统中执行操作：
  - 创建/安装插件
  - 查询任务详情
  - 触发立即采集
  - 管理任务（暂停/恢复）

工具通过 OpenAI Function Calling 协议集成，
同时支持简单文本标记方式（兼容不支持 function calling 的模型）。
"""
import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.database import get_sync_session
from app.models.task import MonitorTask
from app.models.alert import Alert
from app.models.plugin import Plugin
from app.utils.logger import get_logger

log = get_logger("system")

PLUGINS_DIR = settings.data_dir / "plugins"


# ============================================================
# 工具定义（OpenAI Function Calling 格式）
# ============================================================

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_plugin",
            "description": "在系统中生成一个待审核插件。自动创建目录、写入 manifest.json 和入口文件并注册到数据库，必须由管理员审计后才能启用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "插件标识名（英文，如 jd_collector）"
                    },
                    "display_name": {
                        "type": "string",
                        "description": "插件显示名称（中文，如 京东商品采集插件）"
                    },
                    "plugin_type": {
                        "type": "string",
                        "enum": ["engine", "analysis", "alert", "tool", "mcp", "skill"],
                        "description": "插件类型"
                    },
                    "description": {
                        "type": "string",
                        "description": "插件功能描述"
                    },
                    "version": {
                        "type": "string",
                        "description": "版本号，如 1.0.0"
                    },
                    "code": {
                        "type": "string",
                        "description": "main.py 的完整 Python 代码"
                    },
                },
                "required": ["name", "display_name", "plugin_type", "code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_task_detail",
            "description": "获取指定监控任务的详细信息，包括状态、最后采集时间、错误信息等",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "任务ID"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "列出所有监控任务，可按状态筛选",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["active", "paused", "error", "need_login", "all"],
                        "description": "按状态筛选，默认 all"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回数量限制，默认 20"
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_plugins",
            "description": "列出已安装的插件",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "pause_task",
            "description": "暂停指定的监控任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "要暂停的任务ID"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "resume_task",
            "description": "恢复（启动）指定的已暂停监控任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "integer",
                        "description": "要恢复的任务ID"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_plugin",
            "description": "执行已安装插件的指定函数。插件必须已启用。可用于运行采集、分析、工具等各类插件功能。",
            "parameters": {
                "type": "object",
                "properties": {
                    "plugin_name": {
                        "type": "string",
                        "description": "插件标识名（如 jd_collector）"
                    },
                    "function_name": {
                        "type": "string",
                        "description": "要执行的函数名，默认 run"
                    },
                    "kwargs": {
                        "type": "object",
                        "description": "传递给函数的参数字典"
                    }
                },
                "required": ["plugin_name"]
            }
        }
    },
]


# ============================================================
# 工具执行器
# ============================================================

def execute_tool(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    执行指定的工具，返回结果

    Returns:
        {"success": bool, "result": str, "error": str}
    """
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return {"success": False, "error": f"未知工具: {name}"}

    try:
        result = handler(**arguments)
        return {"success": True, "result": result}
    except Exception as e:
        log.warning(f"[AI Tool] 执行失败: {name}", data={
            "error": str(e), "traceback": traceback.format_exc()
        })
        return {"success": False, "error": str(e)}


# ---- 各工具的实现 ----

def _tool_create_plugin(
    name: str,
    display_name: str,
    plugin_type: str,
    code: str,
    description: str = "",
    version: str = "1.0.0",
) -> str:
    """创建待审核插件；AI 生成代码不得绕过管理员审计。"""
    # 校验名称
    if not name.isidentifier():
        raise ValueError(f"插件名 '{name}' 不合法，必须是合法的 Python 标识符")

    plugin_dir = PLUGINS_DIR / name
    if plugin_dir.exists():
        raise FileExistsError(f"插件 '{name}' 已存在于 {plugin_dir}")

    # 创建目录
    plugin_dir.mkdir(parents=True, exist_ok=True)

    # 写 manifest.json
    manifest = {
        "name": name,
        "display_name": display_name,
        "version": version,
        "type": plugin_type,
        "description": description,
        "author": "AI Assistant",
        "entry": "main.py",
    }
    (plugin_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 写 main.py
    (plugin_dir / "main.py").write_text(code, encoding="utf-8")

    # 注册为待审核状态；AI 生成的可执行代码不得自动批准或启用。
    with get_sync_session() as session:
        existing = session.query(Plugin).filter(Plugin.name == name).first()
        if existing:
            return f"插件 '{display_name}' 文件已创建，但数据库中已有同名记录（ID: {existing.id}）"

        plugin = Plugin(
            name=name,
            display_name=display_name,
            version=version,
            plugin_type=plugin_type,
            description=description,
            author="AI Assistant",
            entry="main.py",
            status="pending",
            is_installed=True,
            is_enabled=False,
        )
        session.add(plugin)
        session.commit()
        plugin_id = plugin.id

    return (
        f"✅ 插件草稿已创建，等待管理员审核。\n"
        f"- 名称: {display_name}\n"
        f"- ID: {plugin_id}\n"
        f"- 目录: data/plugins/{name}/\n"
        f"- 状态: ⏳ 待审核 | ⛔ 未启用\n"
        f"- 文件: manifest.json + main.py\n"
        f"\n请先在「应用市场」中人工审计代码并审核通过；审核前不能执行。"
    )


def _tool_get_task_detail(task_id: int) -> str:
    """获取任务详情"""
    with get_sync_session() as session:
        task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
        if not task:
            return f"未找到 ID 为 {task_id} 的任务"

        info = [
            f"任务ID: {task.id}",
            f"商品标题: {task.product_title or '未命名'}",
            f"店铺: {task.shop_name or '未知'}",
            f"平台: {task.platform}",
            f"URL: {task.url}",
            f"状态: {task.status}",
            f"采集频率: 每 {task.frequency_minutes} 分钟",
            f"最后采集: {task.last_check_at.strftime('%Y-%m-%d %H:%M') if task.last_check_at else '从未'}",
            f"下次采集: {task.next_check_at.strftime('%Y-%m-%d %H:%M') if task.next_check_at else '未安排'}",
            f"最后错误: {task.last_error or '无'}",
            f"浏览器Profile: {task.browser_profile_id or '未绑定'}",
            f"备注: {task.note or '无'}",
        ]
        return "\n".join(info)


def _tool_list_tasks(status: str = "all", limit: int = 20) -> str:
    """列出任务"""
    with get_sync_session() as session:
        q = session.query(MonitorTask)
        if status and status != "all":
            q = q.filter(MonitorTask.status == status)
        tasks = q.order_by(MonitorTask.id.desc()).limit(limit).all()

        if not tasks:
            return f"没有找到{'状态为 ' + status + ' 的' if status != 'all' else ''}任务"

        lines = [f"共 {len(tasks)} 个任务:"]
        for t in tasks:
            title = (t.product_title or "未命名")[:25]
            check = t.last_check_at.strftime("%m-%d %H:%M") if t.last_check_at else "从未"
            lines.append(f"- [ID {t.id}] {title} | {t.platform} | 状态: {t.status} | 最后采集: {check}")

        return "\n".join(lines)


def _tool_list_plugins() -> str:
    """列出已安装插件"""
    with get_sync_session() as session:
        plugins = session.query(Plugin).all()

        if not plugins:
            return "当前没有已安装的插件"

        lines = [f"共 {len(plugins)} 个插件:"]
        for p in plugins:
            lines.append(
                f"- [{p.id}] {p.display_name} (v{p.version}) | "
                f"类型: {p.plugin_type} | 状态: {p.status} | "
                f"{'✅ 已启用' if p.is_enabled else '❌ 未启用'}"
            )
        return "\n".join(lines)


def _tool_pause_task(task_id: int) -> str:
    """暂停任务"""
    with get_sync_session() as session:
        task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
        if not task:
            return f"未找到 ID 为 {task_id} 的任务"
        if task.status == "paused":
            return f"任务 [{task_id}] 已经是暂停状态"

        old_status = task.status
        task.status = "paused"
        session.commit()
        return f"✅ 任务 [{task_id}] 已暂停（之前状态: {old_status}）"


def _tool_resume_task(task_id: int) -> str:
    """恢复任务"""
    with get_sync_session() as session:
        task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
        if not task:
            return f"未找到 ID 为 {task_id} 的任务"
        if task.status == "active":
            return f"任务 [{task_id}] 已经是运行状态"

        old_status = task.status
        task.status = "active"
        task.last_error = None
        task.risk_control_retries = 0
        task.original_browser_profile_id = None
        session.commit()
        return f"✅ 任务 [{task_id}] 已恢复运行（之前状态: {old_status}）"


def _tool_execute_plugin(
    plugin_name: str,
    function_name: str = "run",
    kwargs: Optional[Dict[str, Any]] = None,
) -> str:
    """执行插件函数"""
    from app.services.plugin_sandbox import PluginRunner

    with get_sync_session() as session:
        plugin = session.query(Plugin).filter(Plugin.name == plugin_name).first()
        if not plugin:
            return f"未找到名为 '{plugin_name}' 的插件"
        if not plugin.is_enabled:
            return f"插件 '{plugin.display_name}' 未启用，请先在应用市场启用"
        entry = plugin.entry or "main.py"

    runner = PluginRunner(plugin_name, entry)
    # PluginRunner.execute 是 async，需要在同步上下文中运行
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(
                    asyncio.run,
                    runner.execute(function_name=function_name, kwargs=kwargs or {})
                ).result(timeout=70)
        else:
            result = loop.run_until_complete(
                runner.execute(function_name=function_name, kwargs=kwargs or {})
            )
    except Exception as e:
        return f"插件执行异常: {str(e)}"

    if not result.get("success"):
        return f"插件执行失败: {result.get('error', '未知错误')}"

    output = result.get("result", "")
    if isinstance(output, dict):
        output = json.dumps(output, ensure_ascii=False, indent=2)
    return f"✅ 插件 '{plugin_name}' 函数 '{function_name}' 执行成功：\n{output}"


def _try_register_engine_plugin(plugin_name: str) -> str:
    """尝试将引擎类型插件注册到 engine_registry（最佳努力）"""
    try:
        from app.services.engine_registry import get_engine_registry
        registry = get_engine_registry()
        # 检查是否已注册
        existing = [e["name"] for e in registry.list_engines()]
        if plugin_name in existing:
            return f"引擎 '{plugin_name}' 已在注册中心"
        log.info(f"[AI Tool] 引擎插件 '{plugin_name}' 已创建，需重启后自动加载到引擎注册中心")
        return "引擎文件已就位，重启后端后将自动加载到引擎注册中心"
    except Exception as e:
        log.warning(f"[AI Tool] 引擎注册尝试失败: {e}")
        return f"引擎注册跳过: {e}"


# 工具名 → 处理函数 映射
_TOOL_HANDLERS = {
    "create_plugin": _tool_create_plugin,
    "get_task_detail": _tool_get_task_detail,
    "list_tasks": _tool_list_tasks,
    "list_plugins": _tool_list_plugins,
    "pause_task": _tool_pause_task,
    "resume_task": _tool_resume_task,
    "execute_plugin": _tool_execute_plugin,
}


# ============================================================
# 工具描述（纯文本，给不支持 function calling 的模型用）
# ============================================================

def get_tools_description_text() -> str:
    """生成工具列表的纯文本描述，用于注入系统提示词"""
    lines = [
        "## 你可以调用的工具",
        "当你需要执行操作时，在回复中输出以下格式的 JSON 块（必须用 ```tool 包裹）：",
        "",
        "```tool",
        '{"tool": "工具名", "args": {参数}}',
        "```",
        "",
        "系统会自动执行并返回结果。可用工具：",
        "",
    ]
    for td in TOOL_DEFINITIONS:
        func = td["function"]
        params = func["parameters"].get("properties", {})
        required = func["parameters"].get("required", [])
        param_desc = []
        for pname, pinfo in params.items():
            req = "必填" if pname in required else "可选"
            param_desc.append(f"    - {pname} ({req}): {pinfo.get('description', '')}")

        lines.append(f"### {func['name']}")
        lines.append(f"{func['description']}")
        if param_desc:
            lines.append("参数:")
            lines.extend(param_desc)
        lines.append("")

    lines.append("**重要规则**:")
    lines.append("- 用户要求生成扩展插件 → 调用 create_plugin 创建待审核草稿")
    lines.append("- AI 生成的插件不能自动审核或启用；必须由管理员在应用市场中完成人工代码审计")
    lines.append("- 用户说\"暂停任务1\" → 调用 pause_task")
    lines.append("- 不得在同一次回复中创建并执行插件，审核前 execute_plugin 会拒绝运行")
    lines.append("- 工具执行结果会自动附加在你的回复之后，用户可以直接看到")
    lines.append("- 创建插件时代码必须遵循系统架构（Playwright采集、插件沙箱限制等）")

    return "\n".join(lines)


def parse_tool_calls_from_text(text: str) -> List[Dict[str, Any]]:
    """
    从 AI 回复文本中解析 tool 调用块

    格式: ```tool
    {"tool": "xxx", "args": {...}}
    ```

    Returns:
        [{"name": str, "arguments": dict}, ...]
    """
    import re
    calls = []
    pattern = r'```tool\s*\n(.*?)\n```'
    matches = re.findall(pattern, text, re.DOTALL)

    for match in matches:
        try:
            data = json.loads(match.strip())
            if isinstance(data, dict) and "tool" in data:
                calls.append({
                    "name": data["tool"],
                    "arguments": data.get("args", {}),
                })
        except json.JSONDecodeError:
            continue

    return calls
