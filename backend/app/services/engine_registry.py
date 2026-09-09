"""
筱和灵眸(AethelEye) - 引擎注册中心

管理采集引擎的注册、切换和获取。
支持运行时通过配置或 API 切换引擎。

使用方式：
    from app.services.engine_registry import get_engine, get_engine_registry

    # 获取当前活跃引擎
    engine = get_engine()

    # 切换引擎
    registry = get_engine_registry()
    registry.set_active("ai_rpa")
"""
from typing import Dict, Optional, Type

from app.services.engine_base import BaseCollectionEngine
from app.utils.logger import get_logger

log = get_logger("system")


class EngineRegistry:
    """
    引擎注册中心

    - register(): 注册引擎类（或实例）
    - set_active(): 按名称切换活跃引擎
    - get_active(): 获取活跃引擎实例
    - list_engines(): 列出所有已注册引擎
    """

    def __init__(self):
        # name → engine class
        self._engine_classes: Dict[str, Type[BaseCollectionEngine]] = {}
        # name → singleton instance (惰性创建)
        self._instances: Dict[str, BaseCollectionEngine] = {}
        self._active_name: Optional[str] = None

    def register(self, engine_cls: Type[BaseCollectionEngine]) -> None:
        """
        注册引擎类

        Args:
            engine_cls: 继承 BaseCollectionEngine 的引擎类
        """
        name = engine_cls.ENGINE_NAME
        self._engine_classes[name] = engine_cls
        log.info(f"引擎已注册: {name} ({engine_cls.ENGINE_DISPLAY_NAME})")

        # 第一个注册的自动成为默认
        if self._active_name is None:
            self._active_name = name

    def set_active(self, name: str) -> None:
        """
        切换活跃引擎

        Args:
            name: 引擎名称（ENGINE_NAME）

        Raises:
            ValueError: 引擎未注册
        """
        if name not in self._engine_classes:
            available = list(self._engine_classes.keys())
            raise ValueError(f"引擎 '{name}' 未注册。可用引擎: {available}")
        self._active_name = name
        log.info(f"活跃引擎已切换: {name}")

    def get_active(self) -> BaseCollectionEngine:
        """
        获取当前活跃引擎实例（单例，惰性创建）

        Returns:
            BaseCollectionEngine 实例

        Raises:
            RuntimeError: 无引擎注册
        """
        if self._active_name is None:
            raise RuntimeError("没有注册任何采集引擎")

        if self._active_name not in self._instances:
            cls = self._engine_classes[self._active_name]
            self._instances[self._active_name] = cls()
            log.info(f"引擎实例已创建: {self._active_name}")

        return self._instances[self._active_name]

    def get_engine(self, name: str) -> BaseCollectionEngine:
        """
        按名称获取引擎实例

        Args:
            name: 引擎名称

        Returns:
            BaseCollectionEngine 实例
        """
        if name not in self._engine_classes:
            available = list(self._engine_classes.keys())
            raise ValueError(f"引擎 '{name}' 未注册。可用引擎: {available}")

        if name not in self._instances:
            cls = self._engine_classes[name]
            self._instances[name] = cls()

        return self._instances[name]

    def list_engines(self):
        """
        列出所有已注册引擎

        Returns:
            [{"name": ..., "display_name": ..., "is_active": bool}, ...]
        """
        result = []
        for name, cls in self._engine_classes.items():
            result.append({
                "name": name,
                "display_name": cls.ENGINE_DISPLAY_NAME,
                "is_active": name == self._active_name,
            })
        return result

    @property
    def active_name(self) -> Optional[str]:
        return self._active_name


# ── 全局单例 ──────────────────────────────────────────────

_registry: Optional[EngineRegistry] = None


def get_engine_registry() -> EngineRegistry:
    """获取引擎注册中心单例"""
    global _registry
    if _registry is None:
        _registry = EngineRegistry()
        _register_builtin_engines(_registry)
    return _registry


def get_engine() -> BaseCollectionEngine:
    """快捷方式：获取当前活跃引擎"""
    return get_engine_registry().get_active()


def _register_builtin_engines(registry: EngineRegistry) -> None:
    """注册内置引擎"""
    # Playwright 采集引擎（当前唯一实现）
    from app.services.collector_engine import CollectorEngine
    registry.register(CollectorEngine)

    # 自动加载已安装且启用的 engine 类型插件
    _load_plugin_engines(registry)


def _load_plugin_engines(registry: EngineRegistry) -> None:
    """从数据库扫描已启用的 engine 类型插件并注册（最佳努力）"""
    try:
        from app.database import get_sync_session
        from app.models.plugin import Plugin

        with get_sync_session() as session:
            engine_plugins = session.query(Plugin).filter(
                Plugin.plugin_type == "engine",
                Plugin.is_enabled == True,
                Plugin.status == "approved",
            ).all()

            for p in engine_plugins:
                if p.name in [e["name"] for e in registry.list_engines()]:
                    continue  # 已注册，跳过
                log.info(f"发现引擎插件: {p.display_name} ({p.name})，将在首次使用时加载")
    except Exception as e:
        log.warning(f"加载引擎插件列表失败: {e}")
