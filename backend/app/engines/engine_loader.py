"""
筱和灵眸(AethelEye) - 引擎动态加载器

职责：
  1. 扫描 engines/ 目录下的引擎包（含 manifest.json）
  2. 校验 manifest 完整性
  3. 动态导入引擎类并注册到 EngineRegistry
  4. 提供引擎元信息查询 API

设计原则：
  - 增量叠加：不修改已有 engine_registry.py / engine_base.py
  - 内置引擎（Playwright）仍由 engine_registry._register_builtin_engines 管理
  - 本模块仅处理 engines/ 目录下的 **外部引擎包**
"""
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.services.engine_base import BaseCollectionEngine
from app.utils.logger import get_logger

log = get_logger("system")

# 引擎包目录（相对于 backend/）
ENGINES_DIR = Path(__file__).parent  # backend/app/engines/

# manifest.json 必填字段
MANIFEST_REQUIRED_FIELDS = [
    "name",
    "display_name",
    "version",
    "engine_class",
]


class EngineManifest:
    """引擎包清单"""

    def __init__(self, data: Dict[str, Any], engine_dir: Path):
        self.name: str = data["name"]
        self.display_name: str = data["display_name"]
        self.version: str = data["version"]
        self.engine_class: str = data["engine_class"]  # "engine.AIRPAEngine"
        self.description: str = data.get("description", "")
        self.author: str = data.get("author", "")
        self.min_app_version: str = data.get("min_app_version", "1.0.0")
        self.requires_ai: bool = data.get("requires_ai", False)
        self.supported_platforms: List[str] = data.get("supported_platforms", [])
        self.priority: int = data.get("priority", 100)
        self.capabilities: List[str] = data.get("capabilities", [])
        self.engine_dir: Path = engine_dir

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "min_app_version": self.min_app_version,
            "requires_ai": self.requires_ai,
            "supported_platforms": self.supported_platforms,
            "priority": self.priority,
            "capabilities": self.capabilities,
            "engine_dir": str(self.engine_dir),
        }


def _validate_manifest(data: Dict[str, Any], manifest_path: Path) -> Optional[str]:
    """
    校验 manifest.json 完整性

    Returns:
        None 如果合法，否则返回错误信息
    """
    for field in MANIFEST_REQUIRED_FIELDS:
        if field not in data:
            return f"manifest.json 缺少必填字段 '{field}': {manifest_path}"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return f"manifest.json 'name' 不能为空: {manifest_path}"
    if not isinstance(data["engine_class"], str) or "." not in data["engine_class"]:
        return f"manifest.json 'engine_class' 格式应为 'module.ClassName': {manifest_path}"
    return None


def _load_engine_class(manifest: EngineManifest) -> Optional[type]:
    """
    动态加载引擎类

    engine_class 格式: "engine.AIRPAEngine" → 从引擎目录/engine.py 中导入 AIRPAEngine
    """
    try:
        module_name, class_name = manifest.engine_class.rsplit(".", 1)
        module_file = manifest.engine_dir / f"{module_name}.py"

        if not module_file.exists():
            log.error(f"引擎模块文件不存在: {module_file}")
            return None

        # 动态导入模块
        spec = importlib.util.spec_from_file_location(
            f"engines.{manifest.name}.{module_name}",
            str(module_file),
        )
        if spec is None or spec.loader is None:
            log.error(f"无法加载引擎模块 spec: {module_file}")
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        engine_cls = getattr(module, class_name, None)
        if engine_cls is None:
            log.error(f"引擎类 '{class_name}' 不存在于 {module_file}")
            return None

        if not issubclass(engine_cls, BaseCollectionEngine):
            log.error(f"引擎类 '{class_name}' 未继承 BaseCollectionEngine")
            return None

        return engine_cls

    except Exception as e:
        log.error(f"动态加载引擎失败: {manifest.name}", data={"error": str(e)})
        return None


def scan_engine_packages() -> List[EngineManifest]:
    """
    扫描 engines/ 目录，返回所有合法引擎的 manifest

    仅扫描，不注册。调用方决定是否注册到 EngineRegistry。
    """
    manifests = []

    if not ENGINES_DIR.exists():
        return manifests

    for item in ENGINES_DIR.iterdir():
        if not item.is_dir() or item.name.startswith("_"):
            continue

        manifest_path = item / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.warning(f"引擎包 manifest 读取失败: {manifest_path}", data={"error": str(e)})
            continue

        error = _validate_manifest(data, manifest_path)
        if error:
            log.warning(error)
            continue

        manifests.append(EngineManifest(data, item))

    return manifests


def load_and_register_engines(registry) -> List[str]:
    """
    扫描引擎包 → 加载引擎类 → 注册到 EngineRegistry

    Args:
        registry: EngineRegistry 实例

    Returns:
        成功注册的引擎名称列表
    """
    manifests = scan_engine_packages()
    registered = []

    for manifest in manifests:
        # 跳过已注册的（内置引擎可能同名）
        existing = [e["name"] for e in registry.list_engines()]
        if manifest.name in existing:
            log.info(f"引擎 '{manifest.name}' 已注册（内置），跳过外部加载")
            continue

        engine_cls = _load_engine_class(manifest)
        if engine_cls is None:
            continue

        try:
            registry.register(engine_cls)
            registered.append(manifest.name)
            log.info(
                f"外部引擎已加载并注册: {manifest.display_name} v{manifest.version}",
                data=manifest.to_dict(),
            )
        except Exception as e:
            log.error(f"引擎注册失败: {manifest.name}", data={"error": str(e)})

    return registered


def get_all_engine_manifests() -> List[Dict[str, Any]]:
    """
    获取所有引擎包的元信息（含内置 + 外部）

    用于 API 端点展示。
    """
    from app.services.engine_registry import get_engine_registry

    registry = get_engine_registry()
    builtin_engines = registry.list_engines()

    # 外部引擎 manifest
    external_manifests = scan_engine_packages()
    external_map = {m.name: m.to_dict() for m in external_manifests}

    result = []
    for eng in builtin_engines:
        info = {
            **eng,
            "source": "builtin",
            "version": "内置",
            "description": "",
            "capabilities": [],
        }
        # 如果外部包同名有更丰富的元数据，合并
        if eng["name"] in external_map:
            ext = external_map.pop(eng["name"])
            info.update({
                "version": ext.get("version", "内置"),
                "description": ext.get("description", ""),
                "capabilities": ext.get("capabilities", []),
                "author": ext.get("author", ""),
                "source": "builtin+package",
            })
        result.append(info)

    # 已扫描但未注册的外部引擎（可能加载失败）
    for name, ext in external_map.items():
        ext["source"] = "external"
        ext["is_active"] = False
        result.append(ext)

    return result
