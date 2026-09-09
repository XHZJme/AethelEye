"""
筱和灵眸(AethelEye) - 异动记录API路由

异动记录查询、状态更新、导出
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from pathlib import Path

from app.config import settings
from app.database import get_db_session
from app.models.alert import Alert
from app.models.task import MonitorTask
from app.models.sku import SKU
from app.models.user import User
from app.middleware.permission import require_login, require_operator
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/alerts", tags=["异动记录"])


# ===== Pydantic模型 =====

class AlertResponse(BaseModel):
    """异动记录响应"""
    id: int
    task_id: int
    sku_id: int
    alert_type: str
    base_price: float
    alert_price: float
    price_diff: float
    price_diff_pct: float
    screenshot_path: Optional[str]
    status: str
    resolved_note: Optional[str]
    webhook_sent: bool
    detected_at: datetime
    resolved_at: Optional[datetime]

    # 关联信息
    product_title: Optional[str] = None
    shop_name: Optional[str] = None
    sku_name: Optional[str] = None
    platform: Optional[str] = None
    age_minutes: Optional[int] = None

    class Config:
        from_attributes = True


class AlertListResponse(BaseModel):
    """异动记录列表响应"""
    total: int
    alerts: List[AlertResponse]


class AlertStatusUpdate(BaseModel):
    """异动状态更新请求"""
    status: str  # confirmed/resolved/false_alarm
    resolved_note: Optional[str] = None


class AlertBatchDeleteRequest(BaseModel):
    """批量删除异动请求"""
    alert_ids: List[int]


# ===== API端点 =====

@router.get("", response_model=AlertListResponse)
def list_alerts(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    alert_type: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    recent_hours: Optional[int] = Query(None, ge=1, le=168),
    search: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取异动记录列表"""
    query = session.query(Alert)

    # 筛选
    if status:
        query = query.filter(Alert.status == status)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)

    # 时间范围
    if start_date:
        query = query.filter(Alert.detected_at >= start_date)
    if end_date:
        query = query.filter(Alert.detected_at <= end_date)
    if recent_hours:
        cutoff = datetime.now() - timedelta(hours=recent_hours)
        query = query.filter(Alert.detected_at >= cutoff)

    # 搜索（通过关联任务和SKU）
    if search:
        # 需要关联查询
        query = query.join(SKU, Alert.sku_id == SKU.id, isouter=True)
        query = query.join(MonitorTask, Alert.task_id == MonitorTask.id, isouter=True)
        query = query.filter(
            (MonitorTask.product_title.contains(search)) |
            (MonitorTask.shop_name.contains(search)) |
            (SKU.sku_name.contains(search))
        )

    # 平台筛选
    if platform:
        query = query.join(MonitorTask, Alert.task_id == MonitorTask.id)
        query = query.filter(MonitorTask.platform == platform)

    # 统计总数
    total = query.count()

    # 分页
    alerts = query.order_by(Alert.detected_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    # 补充关联信息
    alert_responses = []
    for alert in alerts:
        task = session.query(MonitorTask).filter(MonitorTask.id == alert.task_id).first() if alert.task_id else None
        sku = session.query(SKU).filter(SKU.id == alert.sku_id).first() if alert.sku_id else None

        alert_dict = AlertResponse.model_validate(alert).model_dump()
        alert_dict["product_title"] = task.product_title if task else "[商品信息缺失]"
        alert_dict["shop_name"] = task.shop_name if task else "[任务已删除]"
        alert_dict["sku_name"] = sku.sku_name if sku else "[SKU信息缺失]"
        alert_dict["platform"] = task.platform if task else "unknown"
        alert_dict["age_minutes"] = max(int((datetime.now() - alert.detected_at).total_seconds() // 60), 0)

        alert_responses.append(AlertResponse(**alert_dict))

    return AlertListResponse(total=total, alerts=alert_responses)


@router.get("/statistics")
def get_alert_statistics(
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取异动统计数据"""
    from sqlalchemy import func
    from datetime import timedelta

    # 今日新增
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = session.query(Alert).filter(Alert.detected_at >= today).count()

    # 最近7天
    seven_days_ago = datetime.now() - timedelta(days=7)
    seven_days_count = session.query(Alert).filter(Alert.detected_at >= seven_days_ago).count()

    # 各状态统计
    status_counts = session.query(
        Alert.status,
        func.count(Alert.id)
    ).group_by(Alert.status).all()

    status_stats = {str(s): c for s, c in status_counts}

    # 未处理数量
    new_count = session.query(Alert).filter(Alert.status == "new").count()

    return {
        "today_new": today_count,
        "last_7_days": seven_days_count,
        "unprocessed": new_count,
        "status_distribution": status_stats,
    }


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: int,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取单个异动记录详情"""
    alert = session.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="异动记录不存在")

    task = session.query(MonitorTask).filter(MonitorTask.id == alert.task_id).first() if alert.task_id else None
    sku = session.query(SKU).filter(SKU.id == alert.sku_id).first() if alert.sku_id else None

    alert_dict = AlertResponse.model_validate(alert).model_dump()
    alert_dict["product_title"] = task.product_title if task else "[商品信息缺失]"
    alert_dict["shop_name"] = task.shop_name if task else "[任务已删除]"
    alert_dict["sku_name"] = sku.sku_name if sku else "[SKU信息缺失]"
    alert_dict["platform"] = task.platform if task else "unknown"

    return AlertResponse(**alert_dict)


@router.put("/{alert_id}/status")
def update_alert_status(
    alert_id: int,
    request: AlertStatusUpdate,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """更新异动记录处理状态"""
    alert = session.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="异动记录不存在")

    # 验证状态
    if request.status not in ("confirmed", "resolved", "false_alarm"):
        raise HTTPException(status_code=400, detail="状态必须是 confirmed/resolved/false_alarm")

    old_status = alert.status
    alert.status = request.status
    alert.resolved_note = request.resolved_note
    alert.resolved_at = datetime.now()
    alert.confirmed_by = user.id

    # 如果标记为误报或已处理,恢复SKU状态
    if request.status in ("resolved", "false_alarm") and alert.sku_id:
        sku = session.query(SKU).filter(SKU.id == alert.sku_id).first()
        if sku and sku.status == "alert":
            sku.status = "normal"

    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"异动状态已更新",
        user_id=user.id,
        data={
            "alert_id": alert_id,
            "old_status": old_status,
            "new_status": request.status,
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return {"message": "状态已更新"}


@router.get("/screenshot/file")
def get_alert_screenshot(
    path: str,
    user: User = Depends(require_login)
):
    """查看异动截图文件"""
    if not path:
        raise HTTPException(status_code=400, detail="截图路径不能为空")

    screenshot_root = settings.screenshots_dir.resolve()
    target = Path(path)
    if not target.is_absolute():
        target = screenshot_root / target
    target = target.resolve()

    if not str(target).startswith(str(screenshot_root)):
        raise HTTPException(status_code=400, detail="非法截图路径")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")

    return FileResponse(target, media_type="image/png", filename=target.name)


@router.delete("/{alert_id}")
def delete_alert(
    alert_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """删除单条异动"""
    alert = session.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="异动记录不存在")

    session.delete(alert)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        "异动记录已删除",
        user_id=user.id,
        data={
            "alert_id": alert_id,
            "operator": user.username,
            "ip": ip_address,
        }
    )
    return {"message": "异动记录已删除"}


@router.post("/batch-delete")
def batch_delete_alerts(
    request: AlertBatchDeleteRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_operator)
):
    """批量删除异动"""
    ids = sorted(list({int(i) for i in request.alert_ids if int(i) > 0}))
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要删除的异动记录")

    deleted_count = session.query(Alert).filter(Alert.id.in_(ids)).delete(synchronize_session=False)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        "异动记录批量删除",
        user_id=user.id,
        data={
            "alert_ids": ids,
            "deleted_count": deleted_count,
            "operator": user.username,
            "ip": ip_address,
        }
    )
    return {"message": "批量删除完成", "deleted_count": deleted_count}