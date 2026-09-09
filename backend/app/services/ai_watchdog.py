"""
筱和灵眸(AethelEye) - AI Watchdog（看门狗）

后台常驻服务，定期检查系统健康状态：
  - 采集引擎运行状态
  - 最近N次采集成功率
  - 错误日志模式识别
  - 风控状态
  - 资源占用

根据用户配置的自治级别生成不同强度的本地报告与建议：
  Level 0: 全手动 — 不启动看门狗
  Level 1: 观察模式 — 只生成报告
  Level 2: 保守模式 — 生成非破坏性配置建议，等待人工确认
  Level 3: 激进模式 — 生成高优先级处置建议，等待管理员确认

⚠️ 高危操作（切换引擎/暂停所有任务）仅生成报告和建议，不自动执行。
"""
import asyncio
import json
import time
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.utils.logger import get_logger

log = get_logger("system")

# ── 常量 ──────────────────────────────────────────

CHECK_INTERVAL = 30         # 秒
MEMORY_DIR = settings.data_dir / "ai_memory"
MEMORY_FILE = MEMORY_DIR / "memory.json"
DAILY_SUMMARY_FILE = MEMORY_DIR / "daily_summary.json"


# ── 健康指标 ──────────────────────────────────────

class HealthMetrics:
    """系统健康指标快照"""

    def __init__(self):
        self.timestamp: str = datetime.now().isoformat()
        self.collection_success_rate: float = 1.0     # 最近N次采集成功率
        self.recent_errors: List[str] = []             # 最近错误消息
        self.active_tasks: int = 0
        self.paused_tasks: int = 0
        self.risk_controlled_profiles: int = 0          # 被风控的 profile 数
        self.engine_status: str = "ok"                   # ok / degraded / error
        self.cpu_percent: float = 0.0
        self.memory_mb: float = 0.0
        self.disk_free_gb: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__

    @property
    def severity(self) -> str:
        """计算综合严重程度"""
        if self.collection_success_rate < 0.3 or self.engine_status == "error":
            return "critical"
        if self.collection_success_rate < 0.7 or self.risk_controlled_profiles > 2:
            return "warning"
        return "normal"


# ── 报告 ─────────────────────────────────────────

class WatchdogReport:
    """AI 看门狗生成的报告"""

    def __init__(self, report_type: str, severity: str):
        self.report_type = report_type    # bug / performance / security / suggestion
        self.severity = severity          # normal / warning / critical
        self.timestamp = datetime.now().isoformat()
        self.title = ""
        self.summary = ""
        self.details: Dict[str, Any] = {}
        self.recommendations: List[str] = []
        self.auto_actions_taken: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_type": self.report_type,
            "severity": self.severity,
            "timestamp": self.timestamp,
            "title": self.title,
            "summary": self.summary,
            "details": self.details,
            "recommendations": self.recommendations,
            "auto_actions_taken": self.auto_actions_taken,
        }


# ── ID 生成 ──────────────────────────────────────

def _gen_id(prefix: str = "mem") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ── TTL 解析 ─────────────────────────────────────

_TTL_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}

def _parse_ttl(ttl: Optional[str]) -> Optional[int]:
    """解析 TTL 字符串（如 '2h', '30m', '7d'）为秒数"""
    if not ttl:
        return None
    try:
        unit = ttl[-1].lower()
        return int(ttl[:-1]) * _TTL_UNITS.get(unit, 1)
    except (ValueError, IndexError):
        return None


# ── 文本相关度评分 ────────────────────────────────

def _text_relevance(query: str, text: str) -> float:
    """简单关键词匹配相关度（0~1）"""
    if not query or not text:
        return 0.0
    q = query.lower()
    t = text.lower()
    if q in t:
        return min(1.0, 0.7 + len(q) / max(len(t), 1))
    # 分词匹配
    q_words = set(q.split())
    t_words = set(t.split())
    if not q_words:
        return 0.0
    overlap = q_words & t_words
    return len(overlap) / len(q_words) * 0.6


# ── AI 三层记忆系统 ──────────────────────────────

class AIMemory:
    """
    三层记忆架构：
      1. 短期记忆 (short_term)  — 最近上下文、采集事件，带 TTL 自动过期
      2. 长期记忆 (patterns + decisions) — 合并巩固的模式和决策
      3. 实体图谱 (entities) — 自动提取的关键实体及关联
    """

    def __init__(self):
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if MEMORY_FILE.exists():
            try:
                raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                # 兼容旧格式：补齐新字段
                raw.setdefault("short_term", [])
                raw.setdefault("entities", [])
                raw.setdefault("patterns", [])
                raw.setdefault("decisions", [])
                raw.setdefault("reports", [])
                raw.setdefault("daily_stats", {})
                return raw
            except Exception:
                pass
        return {
            "short_term": [],
            "patterns": [],
            "decisions": [],
            "reports": [],
            "daily_stats": {},
            "entities": [],
        }

    def save(self):
        MEMORY_FILE.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    # ── 短期记忆 ──────────────────────────────────

    def add_short_term(self, content: str, source: str = "system", ttl: str = "2h") -> Dict[str, Any]:
        """添加短期记忆条目"""
        now = datetime.now()
        ttl_seconds = _parse_ttl(ttl)
        expires_at = (now + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
        entry = {
            "id": _gen_id("st"),
            "content": content,
            "source": source,
            "ttl": ttl,
            "created_at": now.isoformat(),
            "expires_at": expires_at,
        }
        self._data["short_term"].append(entry)
        self._data["short_term"] = self._data["short_term"][-200:]
        self.save()
        return entry

    def expire_short_term(self):
        """清理已过期的短期记忆"""
        now = datetime.now().isoformat()
        before = len(self._data["short_term"])
        self._data["short_term"] = [
            m for m in self._data["short_term"]
            if not m.get("expires_at") or m["expires_at"] > now
        ]
        if len(self._data["short_term"]) < before:
            self.save()

    def get_short_term(self) -> List[Dict[str, Any]]:
        self.expire_short_term()
        return list(reversed(self._data["short_term"][-20:]))

    # ── 长期记忆：模式 ───────────────────────────

    def record_pattern(self, pattern: str, count: int = 1, confidence: float = 0.0):
        """记录识别到的模式"""
        for p in self._data["patterns"]:
            if p["pattern"] == pattern:
                p["count"] = p.get("count", 0) + count
                p["last_seen"] = datetime.now().isoformat()
                if confidence:
                    p["confidence"] = confidence
                self.save()
                return
        self._data["patterns"].append({
            "id": _gen_id("pat"),
            "pattern": pattern,
            "count": count,
            "confidence": confidence,
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
        })
        self._data["patterns"] = self._data["patterns"][-100:]
        self.save()

    # ── 长期记忆：决策 ───────────────────────────

    def record_decision(self, action: str, reason: str, autonomy_level: int, outcome: str = ""):
        """记录自治决策"""
        self._data["decisions"].append({
            "id": _gen_id("dec"),
            "action": action,
            "reason": reason,
            "autonomy_level": autonomy_level,
            "outcome": outcome,
            "timestamp": datetime.now().isoformat(),
        })
        self._data["decisions"] = self._data["decisions"][-200:]
        self.save()

    # ── 长期记忆：报告 ───────────────────────────

    def record_report(self, report: WatchdogReport):
        """记录报告摘要"""
        self._data["reports"].append({
            "type": report.report_type,
            "severity": report.severity,
            "title": report.title,
            "timestamp": report.timestamp,
        })
        self._data["reports"] = self._data["reports"][-500:]
        self.save()

    # ── 每日统计 ─────────────────────────────────

    def update_daily_stats(self, metrics: HealthMetrics):
        """更新每日统计"""
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in self._data["daily_stats"]:
            self._data["daily_stats"][today] = {
                "checks": 0, "warnings": 0, "criticals": 0,
                "auto_actions": 0,
            }
        stats = self._data["daily_stats"][today]
        stats["checks"] += 1
        if metrics.severity == "warning":
            stats["warnings"] += 1
        elif metrics.severity == "critical":
            stats["criticals"] += 1
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        self._data["daily_stats"] = {
            k: v for k, v in self._data["daily_stats"].items() if k >= cutoff
        }
        self.save()

    # ── 实体图谱 ─────────────────────────────────

    def upsert_entity(self, name: str, entity_type: str,
                      properties: Optional[Dict] = None,
                      relations: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """创建或更新实体"""
        for ent in self._data["entities"]:
            if ent["name"] == name and ent["entity_type"] == entity_type:
                if properties:
                    ent.setdefault("properties", {}).update(properties)
                if relations:
                    existing_rels = ent.get("relations", [])
                    existing_rels.extend(relations)
                    ent["relations"] = existing_rels[-50:]
                ent["relations_count"] = len(ent.get("relations", []))
                ent["updated_at"] = datetime.now().isoformat()
                self.save()
                return ent

        entity = {
            "id": _gen_id("ent"),
            "name": name,
            "entity_type": entity_type,
            "properties": properties or {},
            "relations": relations or [],
            "relations_count": len(relations) if relations else 0,
            "updated_at": datetime.now().isoformat(),
        }
        self._data["entities"].append(entity)
        self._data["entities"] = self._data["entities"][-500:]
        self.save()
        return entity

    def get_entities(self) -> List[Dict[str, Any]]:
        return list(reversed(self._data["entities"][-20:]))

    # ── 跨层搜索 ─────────────────────────────────

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """语义搜索（关键词匹配 + 相关度排序）"""
        self.expire_short_term()
        results: List[Dict[str, Any]] = []

        # 搜索短期记忆
        for m in self._data["short_term"]:
            rel = _text_relevance(query, m.get("content", ""))
            if rel > 0.1:
                results.append({**m, "layer": "short_term", "relevance": rel})

        # 搜索长期模式
        for p in self._data["patterns"]:
            rel = _text_relevance(query, p.get("pattern", ""))
            if rel > 0.1:
                results.append({
                    "id": p.get("id", ""),
                    "content": p["pattern"],
                    "layer": "long_term",
                    "relevance": rel,
                    "updated_at": p.get("last_seen", ""),
                })

        # 搜索长期决策
        for d in self._data["decisions"]:
            rel = _text_relevance(query, d.get("action", "") + " " + d.get("reason", ""))
            if rel > 0.1:
                results.append({
                    "id": d.get("id", ""),
                    "content": d["action"],
                    "layer": "long_term",
                    "relevance": rel,
                    "updated_at": d.get("timestamp", ""),
                })

        # 搜索实体
        for e in self._data["entities"]:
            text = e.get("name", "") + " " + e.get("entity_type", "") + " " + json.dumps(e.get("properties", {}), ensure_ascii=False)
            rel = _text_relevance(query, text)
            if rel > 0.1:
                results.append({
                    "id": e.get("id", ""),
                    "content": f"{e['name']} ({e['entity_type']})",
                    "layer": "entity",
                    "relevance": rel,
                    "updated_at": e.get("updated_at", ""),
                })

        results.sort(key=lambda x: x.get("relevance", 0), reverse=True)
        return results[:limit]

    # ── 记忆提升（短期→长期） ────────────────────

    def promote(self, memory_id: str) -> bool:
        """将短期记忆提升为长期模式"""
        for i, m in enumerate(self._data["short_term"]):
            if m.get("id") == memory_id:
                content = m["content"]
                self._data["short_term"].pop(i)
                self.record_pattern(content, count=1, confidence=0.5)
                return True
        return False

    # ── 删除记忆 ─────────────────────────────────

    def delete(self, memory_id: str) -> bool:
        """按 ID 删除任意层级的记忆条目"""
        for layer_key in ("short_term", "patterns", "decisions", "entities"):
            layer = self._data.get(layer_key, [])
            for i, item in enumerate(layer):
                if item.get("id") == memory_id:
                    layer.pop(i)
                    self.save()
                    return True
        return False

    # ── 汇总 ─────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        self.expire_short_term()
        return {
            "total_patterns": len(self._data["patterns"]),
            "total_decisions": len(self._data["decisions"]),
            "total_reports": len(self._data["reports"]),
            "recent_patterns": self._data["patterns"][-5:],
            "recent_decisions": self._data["decisions"][-5:],
            "short_term": self.get_short_term(),
            "entities": self.get_entities(),
        }


# ── Watchdog 主服务 ───────────────────────────────

class AIWatchdog:
    """AI 看门狗后台服务"""

    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._memory = AIMemory()
        self._autonomy_level = 1  # 默认观察模式
        self._reports: List[WatchdogReport] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def autonomy_level(self) -> int:
        return self._autonomy_level

    @property
    def recent_reports(self) -> List[Dict[str, Any]]:
        return [r.to_dict() for r in self._reports[-20:]]

    @property
    def memory(self) -> AIMemory:
        return self._memory

    @property
    def memory_summary(self) -> Dict[str, Any]:
        return self._memory.get_summary()

    def start(self):
        """启动看门狗"""
        if self._running:
            return
        self._load_autonomy_level()
        if self._autonomy_level == 0:
            log.info("[Watchdog] 自治级别=0（全手动），看门狗不启动")
            return
        self._running = True
        self._task = asyncio.ensure_future(self._watch_loop())
        log.info(f"[Watchdog] 已启动，自治级别={self._autonomy_level}")

    def stop(self):
        """停止看门狗"""
        self._running = False
        if self._task:
            self._task.cancel()
        log.info("[Watchdog] 已停止")

    def _load_autonomy_level(self):
        """从 DB 加载自治级别"""
        try:
            from app.database import get_sync_session
            from app.models.ai_service_binding import EngineConfig
            with get_sync_session() as session:
                config = session.query(EngineConfig).first()
                if config:
                    self._autonomy_level = config.ai_autonomy_level or 1
        except Exception:
            pass

    async def _watch_loop(self):
        """主监控循环"""
        log.info("[Watchdog] 监控循环已启动")
        while self._running:
            try:
                metrics = await self._collect_metrics()
                self._memory.update_daily_stats(metrics)

                # 自动写入短期记忆：每次检查都记录关键指标
                self._memory.add_short_term(
                    f"健康检查: 成功率={metrics.collection_success_rate:.0%}, "
                    f"活跃任务={metrics.active_tasks}, 引擎={metrics.engine_status}, "
                    f"级别={metrics.severity}",
                    source="watchdog",
                    ttl="1h",
                )

                # 自动维护实体图谱
                self._memory.upsert_entity(
                    "采集引擎", "engine",
                    properties={"status": metrics.engine_status,
                                "active_tasks": metrics.active_tasks,
                                "success_rate": round(metrics.collection_success_rate, 3)},
                )
                if metrics.risk_controlled_profiles > 0:
                    self._memory.upsert_entity(
                        "风控拦截", "risk",
                        properties={"blocked_profiles": metrics.risk_controlled_profiles},
                    )

                if metrics.severity != "normal":
                    report = self._analyze_and_report(metrics)
                    if report:
                        self._reports.append(report)
                        self._memory.record_report(report)
                        await self._take_action(report, metrics)

            except Exception as e:
                log.error(f"[Watchdog] 监控循环异常", data={
                    "error": str(e), "traceback": traceback.format_exc(),
                })

            await asyncio.sleep(CHECK_INTERVAL)

    async def _collect_metrics(self) -> HealthMetrics:
        """收集健康指标"""
        metrics = HealthMetrics()

        try:
            from app.database import get_sync_session
            from app.models.task import MonitorTask

            with get_sync_session() as session:
                # 任务统计
                active = session.query(MonitorTask).filter(MonitorTask.status == "active").count()
                paused = session.query(MonitorTask).filter(MonitorTask.status == "paused").count()
                metrics.active_tasks = active
                metrics.paused_tasks = paused

                # 最近采集成功率（从最近50条日志）
                from app.models.price_record import PriceRecord
                since = datetime.now() - timedelta(hours=6)
                recent_records = session.query(PriceRecord).filter(
                    PriceRecord.collected_at >= since
                ).count()
                # 简化：有记录即认为成功率较高
                metrics.collection_success_rate = min(1.0, recent_records / max(active, 1))

        except Exception as e:
            metrics.engine_status = "error"
            metrics.recent_errors.append(str(e))

        # 系统资源
        try:
            import psutil
            metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
            mem = psutil.virtual_memory()
            metrics.memory_mb = mem.used / (1024 * 1024)
            disk = psutil.disk_usage("/")
            metrics.disk_free_gb = disk.free / (1024 * 1024 * 1024)
        except ImportError:
            pass  # psutil 可能未安装
        except Exception:
            pass

        return metrics

    def _analyze_and_report(self, metrics: HealthMetrics) -> Optional[WatchdogReport]:
        """分析指标，生成报告"""
        if metrics.severity == "critical":
            report = WatchdogReport("bug", "critical")
            report.title = "采集系统严重异常"
            report.summary = (
                f"成功率: {metrics.collection_success_rate:.0%}, "
                f"引擎状态: {metrics.engine_status}, "
                f"错误数: {len(metrics.recent_errors)}"
            )
            report.details = metrics.to_dict()
            report.recommendations = [
                "检查采集引擎是否正常运行",
                "检查是否被风控拦截",
                "考虑切换到 AI RPA 引擎",
            ]
            self._memory.record_pattern("critical_health", 1)
            return report

        elif metrics.severity == "warning":
            report = WatchdogReport("performance", "warning")
            report.title = "采集系统性能警告"
            report.summary = (
                f"成功率: {metrics.collection_success_rate:.0%}, "
                f"被风控Profile: {metrics.risk_controlled_profiles}"
            )
            report.details = metrics.to_dict()
            report.recommendations = [
                "检查被风控的 Profile，考虑更换 Cookie",
                "调整采集频率，减少风控触发",
            ]
            self._memory.record_pattern("warning_health", 1)
            return report

        return None

    async def _take_action(self, report: WatchdogReport, metrics: HealthMetrics):
        """根据自治级别采取行动"""
        level = self._autonomy_level

        if level <= 1:
            # 观察模式：只记录
            log.info(f"[Watchdog] 报告生成（观察模式）: {report.title}")
            self._try_enqueue_report(report)
            return

        if level >= 2 and report.severity == "warning":
            # 保守模式：记录非破坏性配置建议，不直接修改配置
            log.info(f"[Watchdog] 保守模式生成配置建议")
            # 示例：如果成功率低，建议延长采集间隔
            if metrics.collection_success_rate < 0.5:
                action = "延长采集间隔（建议人工确认）"
                report.auto_actions_taken.append(action)
                self._memory.record_decision(action, report.summary, level)

        if level >= 3 and report.severity == "critical":
            # 激进模式：检测严重问题后生成高优先级建议，不直接执行高危操作
            log.warning(f"[Watchdog] 激进模式检测到严重问题，生成切换建议")
            report.recommendations.insert(0, "⚠️ 建议立即切换到 AI RPA 引擎（需管理员确认）")
            self._memory.record_decision(
                "建议切换引擎（未自动执行）", report.summary, level,
            )

        self._try_enqueue_report(report)

    def _try_enqueue_report(self, report: WatchdogReport):
        """开源版仅在本地记录报告，不上传运行数据。"""
        log.info(
            "[Watchdog] 本地报告",
            data={
                "report_type": report.report_type,
                "severity": report.severity,
                "title": report.title,
            },
        )


# ── 全局单例 ──────────────────────────────────────

_watchdog: Optional[AIWatchdog] = None


def get_watchdog() -> AIWatchdog:
    global _watchdog
    if _watchdog is None:
        _watchdog = AIWatchdog()
    return _watchdog
