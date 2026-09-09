"""
筱和灵眸(AethelEye) - 日志系统

基于loguru的6分类JSON结构化日志系统：
- system: 系统运行日志
- collector: 采集引擎日志
- network: 网络请求日志
- browser: 浏览器环境日志
- audit: 业务操作日志
- alert: 价格异动日志

特性：
- JSON结构化格式
- 按日期+大小轮转
- 各分类独立文件
- 超过3天自动gzip压缩
"""
import sys
import json
import re
from datetime import datetime
from pathlib import Path
from loguru import logger
from typing import Optional, Dict, Any

from app.config import settings


# 日志分类
LOG_CATEGORIES = ["system", "collector", "network", "browser", "audit", "alert"]

_SENSITIVE_LOG_KEYS = {
    "authorization", "cookie", "cookies", "cookie_data", "headers",
    "password", "password_hash", "proxy_password", "login_password",
    "api_key", "secret", "token", "access_token", "refresh_token",
    "webhook_url",
}
_URL_SECRET_RE = re.compile(
    r"(?i)([?&](?:api[_-]?key|access[_-]?token|token|key|secret|signature|sign)=)[^&#\s]+"
)
_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]+=*")


def _redact_log_value(value: Any, key: Optional[str] = None) -> Any:
    """递归遮蔽日志字段和 URL 查询串中的常见秘密值。"""
    normalized_key = (key or "").lower()
    if (
        normalized_key in _SENSITIVE_LOG_KEYS
        or normalized_key.endswith(("_password", "_secret", "_token", "_api_key"))
    ):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {item_key: _redact_log_value(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact_log_value(item) for item in value]
    if isinstance(value, str):
        value = _URL_SECRET_RE.sub(r"\1[REDACTED]", value)
        return _BEARER_RE.sub(r"\1[REDACTED]", value)
    return value


def _redact_record(record: Dict[str, Any]) -> None:
    """Loguru patcher：所有 sink 写入前统一脱敏。"""
    record["message"] = _redact_log_value(record.get("message", ""))
    record["extra"] = _redact_log_value(record.get("extra", {}))


def json_serializer(record: Dict) -> str:
    """
    JSON结构化日志序列化器

    输出格式：
    {
        "timestamp": "2026-04-12T14:30:00.123+08:00",
        "level": "INFO",
        "category": "collector",
        "module": "price_extractor",
        "message": "SKU到手价提取成功",
        "task_id": 123,
        "sku_id": 456,
        "data": {...},
        "duration_ms": 1523,
        "trace_id": "abc-123-def"
    }
    """
    # 安全获取time字段
    try:
        time_val = record.get("time")
        if time_val and hasattr(time_val, "strftime"):
            timestamp = time_val.strftime("%Y-%m-%dT%H:%M:%S.%f%z")
        else:
            timestamp = datetime.now().isoformat()
    except Exception:
        timestamp = datetime.now().isoformat()

    # 基础字段 - 只用简单的方式获取，避免触发format_map问题
    level_str = "INFO"
    try:
        level_val = record.get("level")
        if hasattr(level_val, "name"):
            level_str = level_val.name
    except:
        pass

    category_str = "system"
    try:
        extra = record.get("extra")
        if extra and isinstance(extra, dict):
            category_str = extra.get("category", "system")
    except:
        pass

    module_str = "unknown"
    try:
        module_str = record.get("name", "unknown")
    except:
        pass

    message_str = ""
    try:
        message_str = record.get("message", "")
    except:
        pass

    log_data = {
        "timestamp": timestamp,
        "level": level_str,
        "category": category_str,
        "module": module_str,
        "message": message_str,
    }

    # 可选字段
    try:
        extra = record.get("extra")
        if extra and isinstance(extra, dict):
            optional_fields = [
                "task_id", "sku_id", "user_id", "ip",
                "trace_id", "duration_ms", "error_stack"
            ]
            for field in optional_fields:
                if field in extra:
                    log_data[field] = extra[field]

            # data字段（附加数据）
            if "data" in extra:
                log_data["data"] = extra["data"]
    except:
        pass

    return json.dumps(log_data, ensure_ascii=False)


# 兼容旧函数名
json_formatter = json_serializer


def setup_logger() -> None:
    """
    配置loguru日志系统

    - 移除默认handler
    - 添加控制台输出（彩色）
    - 添加各分类文件输出（JSON格式）
    """
    # 所有输出统一经过秘密值遮蔽，再进入控制台或文件 sink。
    logger.configure(patcher=_redact_record)

    # 移除默认handler
    logger.remove()

    # 控制台输出（彩色，开发调试用）
    if settings.log_level == "DEBUG":
        logger.add(
            sys.stderr,
            level="DEBUG",
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                   "<level>{level: <8}</level> | "
                   "<cyan>{extra[category]}</cyan> | "
                   "<level>{message}</level>",
            colorize=True,
        )

    # 各分类文件输出
    for category in LOG_CATEGORIES:
        log_path = settings.logs_dir / category / f"aetheleye_{category}_{{time:YYYY-MM-DD}}.log"

        logger.add(
            str(log_path),
            level=settings.log_level,
            serialize=True,
            rotation=f"{settings.log_max_size_mb} MB",  # 按大小轮转
            retention=f"{settings.log_retention_days} days",  # 保留天数
            compression="gz",  # 自动gzip压缩
            encoding="utf-8",
            filter=lambda record, cat=category: record["extra"].get("category") == cat,
        )

    # 系统启动日志
    logger.bind(category="system").info(
        "AethelEye服务启动",
        data={
            "version": settings.app_version,
            "port": settings.port,
            "data_dir": str(settings.data_dir),
        }
    )


def get_logger(category: str = "system") -> Any:
    """
    获取指定分类的logger

    Args:
        category: 日志分类，必须是LOG_CATEGORIES之一

    Returns:
        绑定了category的logger实例
    """
    if category not in LOG_CATEGORIES:
        category = "system"
    return logger.bind(category=category)


# 初始化日志系统
setup_logger()
