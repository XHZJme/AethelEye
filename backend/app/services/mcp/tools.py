"""
筱和灵眸(AethelEye) - MCP Tool 定义

每个 Tool = 一个函数，包装了现有 FastAPI 路由逻辑。
Tool 注册到 MCP Server 后，外部 Agent 可以调用。
"""
from typing import Any, Dict, List, Optional
from app.utils.logger import get_logger

log = get_logger("system")


# ── Tool 元数据注册表 ─────────────────────────────

TOOLS_REGISTRY: List[Dict[str, Any]] = []


def mcp_tool(name: str, description: str, parameters: Dict[str, Any]):
    """装饰器：注册 MCP Tool"""
    def decorator(func):
        TOOLS_REGISTRY.append({
            "name": name,
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": parameters,
            },
            "handler": func,
        })
        func._mcp_tool_name = name
        return func
    return decorator


# ── 具体 Tools ────────────────────────────────────

@mcp_tool(
    name="aetheleye.list_tasks",
    description="列出所有监控任务（含状态、URL、平台、下次采集时间）",
    parameters={
        "status": {"type": "string", "description": "筛选状态: active/paused/all", "default": "all"},
        "limit": {"type": "integer", "description": "返回数量上限", "default": 50},
    },
)
async def tool_list_tasks(status: str = "all", limit: int = 50) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.task import MonitorTask
    with get_sync_session() as session:
        query = session.query(MonitorTask)
        if status in {"active", "paused", "error", "need_login"}:
            query = query.filter(MonitorTask.status == status)
        limit = max(1, min(limit, 200))
        tasks = query.limit(limit).all()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "name": t.product_title or f"任务 #{t.id}",
                    "url": t.url,
                    "platform": t.platform,
                    "is_active": t.status == "active",
                    "status": t.status,
                    "last_collected_at": t.last_check_at.isoformat() if t.last_check_at else None,
                }
                for t in tasks
            ]
        }


@mcp_tool(
    name="aetheleye.get_task_detail",
    description="获取指定任务的详情，包含最新SKU价格数据",
    parameters={
        "task_id": {"type": "integer", "description": "任务ID", "required": True},
    },
)
async def tool_get_task_detail(task_id: int) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.task import MonitorTask
    from app.models.price_record import PriceRecord
    from app.models.sku import SKU
    from sqlalchemy import desc
    with get_sync_session() as session:
        task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
        if not task:
            return {"error": f"任务 #{task_id} 不存在"}
        # 最新一批 SKU 记录
        latest_records = (
            session.query(PriceRecord, SKU)
            .join(SKU, PriceRecord.sku_id == SKU.id)
            .filter(PriceRecord.task_id == task_id)
            .order_by(desc(PriceRecord.collected_at))
            .limit(100)
            .all()
        )

        return {
            "task": {
                "id": task.id,
                "name": task.product_title or f"任务 #{task.id}",
                "url": task.url,
                "platform": task.platform,
                "product_title": task.product_title,
                "shop_name": task.shop_name,
                "is_active": task.status == "active",
            },
            "latest_skus": [
                {
                    "sku_name": sku.sku_name,
                    "price": float(record.price) if record.price is not None else None,
                    "collected_at": record.collected_at.isoformat() if record.collected_at else None,
                }
                for record, sku in latest_records
            ],
        }


@mcp_tool(
    name="aetheleye.get_alerts",
    description="获取最近的价格异动记录",
    parameters={
        "limit": {"type": "integer", "description": "返回数量上限", "default": 20},
        "task_id": {"type": "integer", "description": "限定任务ID（可选）"},
    },
)
async def tool_get_alerts(limit: int = 20, task_id: Optional[int] = None) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.alert import Alert
    from sqlalchemy import desc
    with get_sync_session() as session:
        from app.models.sku import SKU
        limit = max(1, min(limit, 200))
        query = (
            session.query(Alert, SKU)
            .join(SKU, Alert.sku_id == SKU.id)
            .order_by(desc(Alert.detected_at))
        )
        if task_id:
            query = query.filter(Alert.task_id == task_id)
        alerts = query.limit(limit).all()
        return {
            "alerts": [
                {
                    "id": alert.id,
                    "task_id": alert.task_id,
                    "sku_name": sku.sku_name,
                    "old_price": float(alert.base_price),
                    "new_price": float(alert.alert_price),
                    "change_type": alert.alert_type,
                    "status": alert.status,
                    "created_at": alert.detected_at.isoformat() if alert.detected_at else None,
                }
                for alert, sku in alerts
            ]
        }


@mcp_tool(
    name="aetheleye.collect_now",
    description="立即触发指定任务的一次采集",
    parameters={
        "task_id": {"type": "integer", "description": "任务ID", "required": True},
    },
)
async def tool_collect_now(task_id: int) -> Dict[str, Any]:
    from app.services.scheduler_service import get_scheduler_service
    scheduler = get_scheduler_service()
    try:
        await scheduler._enqueue_collection_task(task_id)
        return {"success": True, "message": f"任务 #{task_id} 已触发采集"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp_tool(
    name="aetheleye.create_task",
    description="创建新的监控任务",
    parameters={
        "name": {"type": "string", "description": "任务名称", "required": True},
        "url": {"type": "string", "description": "商品URL", "required": True},
        "frequency_minutes": {"type": "integer", "description": "采集间隔（分钟）", "default": 240},
    },
)
async def tool_create_task(name: str, url: str, frequency_minutes: int = 240) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.task import MonitorTask
    # 简单 URL 平台识别
    platform = "unknown"
    url_lower = url.lower()
    if "tmall.com" in url_lower:
        platform = "tmall"
    elif "taobao.com" in url_lower:
        platform = "taobao"
    frequency_minutes = max(5, min(frequency_minutes, 30 * 24 * 60))

    with get_sync_session() as session:
        task = MonitorTask(
            url=url,
            platform=platform,
            product_title=name,
            frequency_minutes=frequency_minutes,
            status="active",
        )
        session.add(task)
        session.commit()
        return {"success": True, "task_id": task.id, "message": f"任务 '{name}' 已创建"}


@mcp_tool(
    name="aetheleye.get_price_trend",
    description="获取指定SKU的价格趋势数据",
    parameters={
        "task_id": {"type": "integer", "description": "任务ID", "required": True},
        "sku_name": {"type": "string", "description": "SKU名称（模糊匹配）"},
        "days": {"type": "integer", "description": "查询天数", "default": 7},
    },
)
async def tool_get_price_trend(task_id: int, sku_name: str = "", days: int = 7) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.price_record import PriceRecord
    from app.models.sku import SKU
    from datetime import datetime, timedelta
    with get_sync_session() as session:
        days = max(1, min(days, 365))
        since = datetime.now() - timedelta(days=days)
        query = (
            session.query(PriceRecord, SKU)
            .join(SKU, PriceRecord.sku_id == SKU.id)
            .filter(
                PriceRecord.task_id == task_id,
                PriceRecord.collected_at >= since,
            )
        )
        if sku_name:
            query = query.filter(SKU.sku_name.contains(sku_name))
        records = query.order_by(PriceRecord.collected_at).all()
        return {
            "trend": [
                {
                    "sku_name": sku.sku_name,
                    "price": float(record.price) if record.price is not None else None,
                    "collected_at": record.collected_at.isoformat() if record.collected_at else None,
                }
                for record, sku in records
            ]
        }


@mcp_tool(
    name="aetheleye.export_data",
    description="导出任务数据摘要",
    parameters={
        "task_id": {"type": "integer", "description": "任务ID", "required": True},
    },
)
async def tool_export_data(task_id: int) -> Dict[str, Any]:
    from app.database import get_sync_session
    from app.models.task import MonitorTask
    from app.models.price_record import PriceRecord
    from app.models.alert import Alert
    with get_sync_session() as session:
        task = session.query(MonitorTask).filter(MonitorTask.id == task_id).first()
        if not task:
            return {"error": f"任务 #{task_id} 不存在"}
        record_count = session.query(PriceRecord).filter(PriceRecord.task_id == task_id).count()
        alert_count = session.query(Alert).filter(Alert.task_id == task_id).count()
        return {
            "task_name": task.product_title or f"任务 #{task.id}",
            "url": task.url,
            "total_price_records": record_count,
            "total_alerts": alert_count,
            "product_title": task.product_title,
            "shop_name": task.shop_name,
        }
