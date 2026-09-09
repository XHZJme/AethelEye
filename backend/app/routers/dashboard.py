"""
筱和灵眸(AethelEye) - Dashboard API路由

首页数据汇总展示
- 核心数据卡片
- 最新异动列表
- 异动趋势图数据
- 店铺违规排行
"""
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db_session
from app.models.task import MonitorTask
from app.models.alert import Alert
from app.models.sku import SKU
from app.models.price_record import PriceRecord
from app.models.browser import BrowserProfile
from app.models.user import User
from app.middleware.permission import require_login

# 路由
router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])


# ===== Pydantic模型 =====

class DashboardStats(BaseModel):
    """Dashboard统计数据"""
    total_tasks: int
    alert_sku_count: int
    today_new_alerts: int
    collect_success_rate: float
    account_status: str  # normal/warning/error


class AlertSummary(BaseModel):
    """异动摘要"""
    id: int
    detected_at: datetime
    shop_name: Optional[str]
    product_title: Optional[str]
    sku_name: Optional[str]
    price_diff_pct: float
    platform: Optional[str]

    class Config:
        from_attributes = True


class TrendData(BaseModel):
    """趋势数据"""
    date: str
    count: int


class ShopRank(BaseModel):
    """店铺排行"""
    shop_name: str
    alert_count: int
    platform: str


class ErrorTaskSummary(BaseModel):
    """异常任务摘要"""
    id: int
    product_title: Optional[str]
    shop_name: Optional[str]
    platform: str
    status: str
    last_error: Optional[str]
    last_check_at: Optional[datetime]

    class Config:
        from_attributes = True


class DashboardResponse(BaseModel):
    """Dashboard响应"""
    stats: DashboardStats
    latest_alerts: List[AlertSummary]
    trend_7days: List[TrendData]
    shop_rank: List[ShopRank]
    error_tasks: List[ErrorTaskSummary]


# ===== API端点 =====

@router.get("", response_model=DashboardResponse)
def get_dashboard(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取Dashboard数据"""
    # 1. 核心数据卡片
    stats = _get_stats(session)

    # 2. 最新异动列表（最近10条）
    latest_alerts = _get_latest_alerts(session, limit=10)

    # 3. 异动趋势（近7天）
    trend_7days = _get_7days_trend(session)

    # 4. 店铺违规排行（TOP 10）
    shop_rank = _get_shop_rank(session, limit=10)

    # 5. 异常任务列表
    error_tasks = _get_error_tasks(session)

    return DashboardResponse(
        stats=stats,
        latest_alerts=latest_alerts,
        trend_7days=trend_7days,
        shop_rank=shop_rank,
        error_tasks=error_tasks,
    )


@router.get("/stats", response_model=DashboardStats)
def get_stats_only(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """仅获取统计数据"""
    return _get_stats(session)


def _get_error_tasks(session: Session) -> List[ErrorTaskSummary]:
    """获取异常任务列表"""
    tasks = session.query(MonitorTask).filter(
        MonitorTask.status != "deleted",
        (
            # 有非空错误且任务仍在活跃/异常状态（排除用户手动暂停的正常任务）
            (MonitorTask.last_error.isnot(None)) & (MonitorTask.last_error != "")
            & MonitorTask.status.in_(["active", "error", "need_login"])
        ) | (
            MonitorTask.status.in_(["error", "need_login"])
        ) | (
            # 风控自动暂停的任务（不含用户手动暂停）
            (MonitorTask.status == "paused")
            & MonitorTask.last_error.like("[风控%")
        )
    ).order_by(MonitorTask.last_check_at.desc()).limit(20).all()

    result = []
    for t in tasks:
        result.append(ErrorTaskSummary(
            id=t.id,
            product_title=t.product_title,
            shop_name=t.shop_name,
            platform=t.platform,
            status=t.status,
            last_error=t.last_error,
            last_check_at=t.last_check_at,
        ))
    return result


def _get_stats(session: Session) -> DashboardStats:
    """获取统计数据"""
    # 总任务数
    total_tasks = session.query(MonitorTask).filter(MonitorTask.status != "deleted").count()

    # 异动SKU数量（当前状态为alert的SKU）
    alert_sku_count = session.query(SKU).filter(SKU.status == "alert").count()

    # 今日新增异动
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_new_alerts = session.query(Alert).filter(
        Alert.detected_at >= today,
        Alert.alert_type == "price_drop"
    ).count()

    # 采集成功率（近24小时）：按采集事件统计，避免任务级口径导致假绿
    # 成功事件：price_records（有价格记录）
    # 失败事件：alerts.alert_type = collect_fail
    yesterday = datetime.now() - timedelta(hours=24)
    successful_collect_events = session.query(PriceRecord).filter(
        PriceRecord.collected_at >= yesterday,
        PriceRecord.price.isnot(None),
    ).count()
    failed_collect_events = session.query(Alert).filter(
        Alert.detected_at >= yesterday,
        Alert.alert_type == "collect_fail",
    ).count()
    checked_tasks_query = session.query(MonitorTask).filter(
        MonitorTask.last_check_at.isnot(None),
        MonitorTask.last_check_at >= yesterday,
        MonitorTask.status != "deleted",
    )
    checked_tasks = checked_tasks_query.count()
    failed_task_samples = checked_tasks_query.filter(
        MonitorTask.last_error.isnot(None),
        MonitorTask.last_error != "",
    ).count()
    successful_checks = checked_tasks - failed_task_samples

    effective_failed_events = max(failed_collect_events, failed_task_samples)
    total_collect_events = successful_collect_events + effective_failed_events

    if total_collect_events > 0:
        collect_success_rate = round(successful_collect_events / total_collect_events * 100, 1)
    else:
        collect_success_rate = round(successful_checks / checked_tasks * 100, 1) if checked_tasks > 0 else 100.0

    # 账号状态（检查浏览器配置的Cookie状态）
    total_profiles = session.query(BrowserProfile).filter(BrowserProfile.is_active == True).count()
    expired_profiles = session.query(BrowserProfile).filter(
        BrowserProfile.is_active == True,
        BrowserProfile.cookie_status == "expired"
    ).count()

    if expired_profiles > 0:
        account_status = "warning"
    elif total_profiles == 0:
        account_status = "error"
    else:
        account_status = "normal"

    return DashboardStats(
        total_tasks=total_tasks,
        alert_sku_count=alert_sku_count,
        today_new_alerts=today_new_alerts,
        collect_success_rate=collect_success_rate,
        account_status=account_status,
    )


def _get_latest_alerts(session: Session, limit: int) -> List[AlertSummary]:
    """获取最新异动列表"""
    alerts = session.query(Alert).filter(
        Alert.alert_type == "price_drop",
        Alert.status != "false_alarm"
    ).order_by(Alert.detected_at.desc()).limit(limit).all()

    result = []
    for alert in alerts:
        # 获取关联信息
        task = session.query(MonitorTask).filter(MonitorTask.id == alert.task_id).first()
        sku = session.query(SKU).filter(SKU.id == alert.sku_id).first()

        result.append(AlertSummary(
            id=alert.id,
            detected_at=alert.detected_at,
            shop_name=task.shop_name if task else None,
            product_title=task.product_title if task else None,
            sku_name=sku.sku_name if sku else None,
            price_diff_pct=float(alert.price_diff_pct),
            platform=task.platform if task else None,
        ))

    return result


def _get_7days_trend(session: Session) -> List[TrendData]:
    """获取近7天异动趋势"""
    result = []
    for i in range(6, -1, -1):
        date = datetime.now() - timedelta(days=i)
        date_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date_end = date_start + timedelta(days=1)

        count = session.query(Alert).filter(
            Alert.detected_at >= date_start,
            Alert.detected_at < date_end,
            Alert.alert_type == "price_drop"
        ).count()

        result.append(TrendData(
            date=date.strftime("%Y-%m-%d"),
            count=count,
        ))

    return result


def _get_shop_rank(session: Session, limit: int) -> List[ShopRank]:
    """获取店铺违规排行"""
    # 按店铺统计异动数量
    query = session.query(
        MonitorTask.shop_name,
        MonitorTask.platform,
        func.count(Alert.id).label("alert_count")
    ).join(
        Alert, MonitorTask.id == Alert.task_id
    ).filter(
        Alert.alert_type == "price_drop",
        MonitorTask.shop_name != None
    ).group_by(
        MonitorTask.shop_name,
        MonitorTask.platform
    ).order_by(
        func.count(Alert.id).desc()
    ).limit(limit)

    result = []
    for row in query:
        result.append(ShopRank(
            shop_name=row.shop_name or "未知店铺",
            alert_count=row.alert_count,
            platform=row.platform,
        ))

    return result