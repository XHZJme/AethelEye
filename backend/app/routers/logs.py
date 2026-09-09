"""
筱和灵眸(AethelEye) - 日志查看API

查询和筛选日志文件
- 分类筛选
- 级别筛选
- 任务关联
- 时间范围
- 关键词搜索
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from pathlib import Path
import json
import gzip

from app.config import settings
from app.models.user import User
from app.middleware.permission import require_admin
from app.utils.logger import get_logger, LOG_CATEGORIES

# 路由
router = APIRouter(prefix="/api/logs", tags=["日志查看"])


# ===== Pydantic模型 =====

class LogEntry(BaseModel):
    """日志条目"""
    timestamp: str
    level: str
    category: str
    module: str
    message: str
    task_id: Optional[int] = None
    sku_id: Optional[int] = None
    user_id: Optional[int] = None
    trace_id: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


class LogListResponse(BaseModel):
    """日志列表响应"""
    total: int
    logs: List[LogEntry]


class LogCategories(BaseModel):
    """日志分类信息"""
    categories: List[str]


# ===== API端点 =====


def _parse_plain_log_line(line: str, category: str) -> Optional[LogEntry]:
    """兼容旧格式日志行：YYYY-MM-DD HH:mm:ss.SSS | LEVEL | category | message"""
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 4:
        return None
    timestamp = parts[0]
    level = parts[1]
    cat = parts[2] or category
    message = "|".join(parts[3:]).strip()
    if not timestamp or not level:
        return None
    return LogEntry(
        timestamp=_normalize_timestamp(timestamp),
        level=level,
        category=cat,
        module="legacy",
        message=message,
        task_id=None,
        sku_id=None,
        trace_id=None,
        data=None,
    )


def _normalize_timestamp(timestamp: Any) -> str:
    """统一时间格式为 ISO8601（YYYY-MM-DDTHH:mm:ss.sss+08:00）"""
    if not timestamp:
        return ""
    text = str(timestamp).strip()
    # 兼容 +0800 / -0500 时区写法
    if len(text) >= 5 and (text[-5] in ('+', '-')) and text[-3] != ':':
        text = f"{text[:-2]}:{text[-2:]}"
    # 兼容 'YYYY-MM-DD HH:mm:ss' => 'YYYY-MM-DDTHH:mm:ss'
    if ' ' in text and 'T' not in text:
        text = text.replace(' ', 'T', 1)
    try:
        return datetime.fromisoformat(text).isoformat()
    except Exception:
        return text


def _normalize_json_log_entry(raw_entry: Dict[str, Any], category: str) -> LogEntry:
    """兼容两种JSON日志结构：自定义平铺结构 / loguru serialize=True 结构"""
    record = raw_entry.get("record") if isinstance(raw_entry.get("record"), dict) else raw_entry
    extra = record.get("extra") if isinstance(record.get("extra"), dict) else {}

    level_obj = record.get("level")
    if isinstance(level_obj, dict):
        level = level_obj.get("name", "INFO")
    else:
        level = level_obj or raw_entry.get("level", "INFO")

    category_val = extra.get("category") or record.get("category") or raw_entry.get("category") or category
    module_val = record.get("name") or raw_entry.get("module", "")
    message_val = record.get("message") or raw_entry.get("message") or (raw_entry.get("text") or "").strip()

    timestamp_val = record.get("time")
    if isinstance(timestamp_val, dict):
        timestamp_val = timestamp_val.get("repr") or timestamp_val.get("timestamp")
    if not timestamp_val:
        timestamp_val = raw_entry.get("timestamp", "")

    task_id_val = extra.get("task_id", raw_entry.get("task_id"))
    sku_id_val = extra.get("sku_id", raw_entry.get("sku_id"))
    user_id_val = extra.get("user_id", raw_entry.get("user_id"))
    trace_id_val = extra.get("trace_id", raw_entry.get("trace_id"))
    data_val = extra.get("data", raw_entry.get("data"))

    return LogEntry(
        timestamp=_normalize_timestamp(timestamp_val),
        level=str(level or "INFO"),
        category=str(category_val),
        module=str(module_val),
        message=str(message_val),
        task_id=task_id_val,
        sku_id=sku_id_val,
        user_id=user_id_val,
        trace_id=trace_id_val,
        data=data_val,
    )

@router.get("/categories", response_model=LogCategories)
def get_log_categories(
    user: User = Depends(require_admin)
):
    """获取日志分类列表"""
    return LogCategories(categories=LOG_CATEGORIES)


@router.get("", response_model=LogListResponse)
def list_logs(
    category: Optional[str] = None,
    level: Optional[str] = None,
    task_id: Optional[int] = None,
    trace_id: Optional[str] = None,
    date: Optional[str] = None,  # YYYY-MM-DD
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(require_admin)
):
    """
    查询日志

    支持分类、级别、任务、追踪ID、日期、关键词筛选
    """
    # 默认查询今天
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    logs = []
    total = 0

    # 遍历日志文件
    for cat in LOG_CATEGORIES:
        # 如果指定了分类，只查询该分类
        if category and cat != category:
            continue

        log_file = settings.logs_dir / cat / f"aetheleye_{cat}_{date}.log"

        # 尝试gzip文件
        if not log_file.exists():
            gzip_file = Path(str(log_file) + ".gz")
            if gzip_file.exists():
                log_file = gzip_file

        if not log_file.exists():
            continue

        # 读取日志
        try:
            if str(log_file).endswith(".gz"):
                with gzip.open(log_file, "rt", encoding="utf-8") as f:
                    content = f.readlines()
            else:
                with open(log_file, "r", encoding="utf-8") as f:
                    content = f.readlines()

            for line in content:
                try:
                    raw_entry = json.loads(line.strip())
                    entry = _normalize_json_log_entry(raw_entry, cat)

                    # 级别筛选
                    if level and entry.level != level:
                        continue

                    # 任务ID筛选
                    if task_id and entry.task_id != task_id:
                        continue

                    # trace_id筛选
                    if trace_id and entry.trace_id != trace_id:
                        continue

                    # 关键词搜索
                    if search:
                        message = entry.message or ""
                        if search.lower() not in message.lower():
                            continue

                    logs.append(entry)

                except json.JSONDecodeError:
                    legacy_entry = _parse_plain_log_line(line.strip(), cat)
                    if not legacy_entry:
                        continue

                    if level and legacy_entry.level != level:
                        continue
                    if search and search.lower() not in (legacy_entry.message or "").lower():
                        continue
                    logs.append(legacy_entry)

        except Exception as e:
            continue

    # 按时间排序（最新的在前）
    logs.sort(key=lambda x: x.timestamp, reverse=True)

    # 统计总数
    total = len(logs)

    # 分页
    logs = logs[(page - 1) * page_size:page * page_size]

    return LogListResponse(total=total, logs=logs)


@router.get("/trace/{trace_id}", response_model=LogListResponse)
def get_trace_logs(
    trace_id: str,
    user: User = Depends(require_admin)
):
    """
    查询同一trace_id的所有日志

    用于追踪一次采集的完整链路
    """
    logs = []

    # 遍历所有分类
    for cat in LOG_CATEGORIES:
        # 遍历最近7天的日志文件
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            log_file = settings.logs_dir / cat / f"aetheleye_{cat}_{date}.log"

            if not log_file.exists():
                gzip_file = Path(str(log_file) + ".gz")
                if gzip_file.exists():
                    log_file = gzip_file

            if not log_file.exists():
                continue

            try:
                if str(log_file).endswith(".gz"):
                    with gzip.open(log_file, "rt", encoding="utf-8") as f:
                        content = f.readlines()
                else:
                    with open(log_file, "r", encoding="utf-8") as f:
                        content = f.readlines()

                for line in content:
                    try:
                        raw_entry = json.loads(line.strip())
                        entry = _normalize_json_log_entry(raw_entry, cat)
                        if entry.trace_id == trace_id:
                            logs.append(entry)
                    except json.JSONDecodeError:
                        continue

            except Exception:
                continue

    # 按时间排序
    logs.sort(key=lambda x: x.timestamp)

    return LogListResponse(total=len(logs), logs=logs)