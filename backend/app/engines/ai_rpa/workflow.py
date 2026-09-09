"""
筱和灵眸(AethelEye) - Workflow 持久化

Workflow = 探索成功后编译的操作序列。
存储路径：data/ai_memory/workflow_cache/<workflow_id>.json
"""
import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from pathlib import Path

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("system")

# ── 常量 ──────────────────────────────────────────

WORKFLOW_DIR = settings.data_dir / "ai_memory" / "workflow_cache"


# ── 数据模型 ──────────────────────────────────────

@dataclass
class WorkflowStep:
    """单个操作步骤"""
    step: int
    action: str                          # wait_for_selector / screenshot_and_analyze / click / scroll / type / extract
    target: Optional[str] = None         # CSS选择器 或 元素描述
    value: Optional[str] = None          # 输入值（type 动作用）
    prompt: Optional[str] = None         # 发给 LLM 的 prompt（explore 用）
    timeout_ms: int = 10000
    expected_elements: Optional[List[str]] = None
    extract_fields: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class WorkflowValidation:
    """结果验证规则"""
    min_skus: int = 1
    price_format: str = r"^\d+(\.\d{1,2})?$"
    must_have_title: bool = True


@dataclass
class Workflow:
    """探索成功后编译的可回放操作序列"""
    id: str                               # wf_<platform>_<task_type>_v<n>
    platform: str                         # tmall / taobao / jd
    task_type: str = "sku_price_collection"
    url_pattern: Optional[str] = None     # 匹配 URL 的正则（用于自动选择 Workflow）
    created_at: str = ""
    updated_at: str = ""
    success_count: int = 0
    fail_count: int = 0
    steps: List[WorkflowStep] = field(default_factory=list)
    validation: WorkflowValidation = field(default_factory=WorkflowValidation)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not self.updated_at:
            self.updated_at = self.created_at

    def record_success(self):
        self.success_count += 1
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    def record_failure(self):
        self.fail_count += 1
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        steps_raw = data.pop("steps", [])
        validation_raw = data.pop("validation", {})
        steps = [WorkflowStep(**s) for s in steps_raw]
        validation = WorkflowValidation(**validation_raw)
        return cls(steps=steps, validation=validation, **data)


# ── 持久化 ────────────────────────────────────────

class WorkflowStore:
    """Workflow 文件存储"""

    def __init__(self, base_dir: Path = WORKFLOW_DIR):
        self._dir = base_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, workflow_id: str) -> Path:
        safe = workflow_id.replace("/", "_").replace("\\", "_")
        return self._dir / f"{safe}.json"

    def save(self, wf: Workflow) -> None:
        wf.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        path = self._path(wf.id)
        path.write_text(json.dumps(wf.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        log.info(f"Workflow已保存: {wf.id}", data={"path": str(path), "steps": len(wf.steps)})

    def load(self, workflow_id: str) -> Optional[Workflow]:
        path = self._path(workflow_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Workflow.from_dict(data)
        except Exception as e:
            log.warning(f"Workflow加载失败: {workflow_id}", data={"error": str(e)})
            return None

    def find_by_platform(self, platform: str) -> List[Workflow]:
        """按平台查找所有 Workflow，按成功率降序"""
        results = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                wf = Workflow.from_dict(data)
                if wf.platform == platform:
                    results.append(wf)
            except Exception:
                continue
        results.sort(key=lambda w: w.success_rate, reverse=True)
        return results

    def find_best_for_url(self, url: str, platform: str) -> Optional[Workflow]:
        """为给定 URL 找到最佳匹配 Workflow"""
        import re
        candidates = self.find_by_platform(platform)
        for wf in candidates:
            if wf.url_pattern:
                try:
                    if re.search(wf.url_pattern, url):
                        return wf
                except re.error:
                    continue
        # 没有 URL 匹配的，返回同平台最优
        return candidates[0] if candidates else None

    def delete(self, workflow_id: str) -> bool:
        path = self._path(workflow_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有 Workflow 的摘要"""
        results = []
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                results.append({
                    "id": data.get("id"),
                    "platform": data.get("platform"),
                    "task_type": data.get("task_type"),
                    "success_count": data.get("success_count", 0),
                    "fail_count": data.get("fail_count", 0),
                    "steps_count": len(data.get("steps", [])),
                    "updated_at": data.get("updated_at"),
                })
            except Exception:
                continue
        return results


# ── 全局单例 ──────────────────────────────────────

_store: Optional[WorkflowStore] = None


def get_workflow_store() -> WorkflowStore:
    global _store
    if _store is None:
        _store = WorkflowStore()
    return _store
