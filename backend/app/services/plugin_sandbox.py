"""
筱和灵眸(AethelEye) - 插件沙箱执行器

风险边界：
  - 该模块只提供尽力而为的模块黑名单和超时控制，不是操作系统级安全沙箱。
  - 插件代码仍与服务进程共享 Python 解释器；仅应安装并执行已人工审计的可信代码。
  - ZIP 安装会校验名称、路径、文件数量和解压大小，避免路径穿越与解压炸弹。
"""
import asyncio
import importlib.util
import json
import os
import sys
import traceback
import re
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("system")

PLUGINS_DIR = settings.data_dir / "plugins"
PLUGIN_TIMEOUT = 60  # 秒
MAX_PLUGIN_FILES = 500
MAX_PLUGIN_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_PLUGIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


# ── 受限 builtins ─────────────────────────────────

_BLOCKED_BUILTINS = {
    "exec", "eval", "compile", "__import__",
    "breakpoint", "exit", "quit",
}

_BLOCKED_MODULES = {
    "subprocess", "os", "shutil", "socket", "http", "urllib",
    "ftplib", "smtplib", "telnetlib", "ctypes", "multiprocessing",
    "signal", "webbrowser",
}


def _make_safe_builtins() -> Dict[str, Any]:
    """创建受限 builtins 字典"""
    import builtins
    safe = {}
    for name in dir(builtins):
        if name not in _BLOCKED_BUILTINS:
            safe[name] = getattr(builtins, name)

    # 受限 __import__：只允许安全模块
    original_import = builtins.__import__

    def restricted_import(name, *args, **kwargs):
        top_level = name.split(".")[0]
        if top_level in _BLOCKED_MODULES:
            raise ImportError(f"模块 '{name}' 在插件沙箱中被禁止")
        return original_import(name, *args, **kwargs)

    safe["__import__"] = restricted_import
    return safe


# ── 插件加载与执行 ─────────────────────────────────

class PluginRunner:
    """插件安全执行器"""

    def __init__(self, plugin_name: str, entry: str = "main.py"):
        if not _PLUGIN_NAME_RE.fullmatch(plugin_name):
            raise ValueError("插件名格式无效")
        self._name = plugin_name
        self._entry = entry
        self._dir = PLUGINS_DIR / plugin_name
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def plugin_dir(self) -> Path:
        return self._dir

    def validate_manifest(self) -> Dict[str, Any]:
        """验证插件 manifest.json"""
        manifest_path = self._dir / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"插件 '{self._name}' 缺少 manifest.json")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        required = ["name", "display_name", "version", "type"]
        for key in required:
            if key not in data:
                raise ValueError(f"manifest.json 缺少必填字段: {key}")
        return data

    async def execute(
        self,
        function_name: str = "run",
        kwargs: Optional[Dict[str, Any]] = None,
        timeout: int = PLUGIN_TIMEOUT,
    ) -> Dict[str, Any]:
        """
        在沙箱中执行插件函数。

        Args:
            function_name: 要调用的函数名
            kwargs: 传给函数的参数
            timeout: 超时秒数

        Returns:
            {"success": bool, "result": Any, "error": str}
        """
        entry_path = self._dir / self._entry
        try:
            entry_path.resolve().relative_to(self._dir.resolve())
        except ValueError:
            return {"success": False, "error": "插件入口不能位于插件目录之外"}
        if not entry_path.exists():
            return {"success": False, "error": f"入口文件不存在: {self._entry}"}

        kwargs = kwargs or {}

        log.info(f"[Plugin] 执行: {self._name}.{function_name}", data={
            "kwargs_keys": list(kwargs.keys()),
        })

        try:
            result = await asyncio.wait_for(
                self._run_in_sandbox(entry_path, function_name, kwargs),
                timeout=timeout,
            )
            return {"success": True, "result": result}
        except asyncio.TimeoutError:
            log.warning(f"[Plugin] 超时: {self._name}.{function_name} ({timeout}s)")
            return {"success": False, "error": f"插件执行超时 ({timeout}s)"}
        except Exception as e:
            log.error(f"[Plugin] 执行异常: {self._name}", data={
                "error": str(e), "traceback": traceback.format_exc(),
            })
            return {"success": False, "error": str(e)}

    async def _run_in_sandbox(
        self, entry_path: Path, function_name: str, kwargs: Dict[str, Any],
    ) -> Any:
        """在受限环境中加载并执行插件"""
        # 动态加载模块
        spec = importlib.util.spec_from_file_location(
            f"plugin_{self._name}", str(entry_path),
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载插件模块: {entry_path}")

        module = importlib.util.module_from_spec(spec)

        # 注入受限 builtins
        module.__builtins__ = _make_safe_builtins()

        # 注入插件上下文
        module.__plugin_name__ = self._name
        module.__plugin_dir__ = str(self._dir)

        # 加载模块
        spec.loader.exec_module(module)

        # 获取目标函数
        func = getattr(module, function_name, None)
        if func is None:
            raise AttributeError(f"插件 '{self._name}' 没有函数 '{function_name}'")

        # 执行（支持 async 和 sync）
        if asyncio.iscoroutinefunction(func):
            return await func(**kwargs)
        else:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(**kwargs))


# ── 插件管理辅助 ──────────────────────────────────

def install_plugin_from_zip(zip_path: str, plugin_name: str) -> Dict[str, Any]:
    """从 ZIP 文件安装插件"""
    import zipfile
    if not _PLUGIN_NAME_RE.fullmatch(plugin_name):
        return {"success": False, "error": "插件名只能包含小写字母、数字、下划线和连字符，且最长 64 个字符"}

    target = PLUGINS_DIR / plugin_name
    if target.exists():
        return {"success": False, "error": f"插件 '{plugin_name}' 已存在"}

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.infolist()
            if len(members) > MAX_PLUGIN_FILES:
                raise ValueError(f"插件文件数超过上限（{MAX_PLUGIN_FILES}）")
            total_size = sum(member.file_size for member in members)
            if total_size > MAX_PLUGIN_UNCOMPRESSED_BYTES:
                raise ValueError("插件解压后大小超过 50 MiB 上限")

            target_root = target.resolve()
            for member in members:
                member_path = (target / member.filename).resolve()
                try:
                    member_path.relative_to(target_root)
                except ValueError as exc:
                    raise ValueError(f"ZIP 包含越界路径: {member.filename}") from exc
            zf.extractall(target)
        # 验证
        runner = PluginRunner(plugin_name)
        manifest = runner.validate_manifest()
        return {"success": True, "manifest": manifest}
    except Exception as e:
        # 清理
        import shutil
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        return {"success": False, "error": str(e)}


def uninstall_plugin(plugin_name: str) -> bool:
    """卸载插件（删除目录）"""
    import shutil
    if not _PLUGIN_NAME_RE.fullmatch(plugin_name):
        return False
    target = PLUGINS_DIR / plugin_name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        return True
    return False
