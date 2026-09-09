"""
筱和灵眸(AethelEye) - 价格趋势API

SKU到手价历史趋势数据
"""
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.price_record import PriceRecord
from app.models.sku import SKU
from app.models.user import User
from app.middleware.permission import require_login

# 路由
router = APIRouter(prefix="/api/trends", tags=["价格趋势"])


# ===== Pydantic模型 =====

class TrendPoint(BaseModel):
    """趋势点"""
    date: str
    price: float
    collected_at: str


class TrendResponse(BaseModel):
    """趋势响应"""
    sku_id: int
    sku_name: str
    base_price: float
    points: List[TrendPoint]


class SKUTrendList(BaseModel):
    """SKU趋势列表"""
    sku_id: int
    sku_name: str
    base_price: Optional[float]
    current_price: Optional[float]


# ===== API端点 =====

@router.get("/sku/{sku_id}", response_model=TrendResponse)
def get_sku_trend(
    sku_id: int,
    days: int = 7,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取单个SKU的价格趋势"""
    sku = session.query(SKU).filter(SKU.id == sku_id).first()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU不存在")

    # 查询价格记录
    start_date = datetime.now() - timedelta(days=days)
    records = session.query(PriceRecord).filter(
        PriceRecord.sku_id == sku_id,
        PriceRecord.collected_at >= start_date
    ).order_by(PriceRecord.collected_at).all()

    points = []
    for record in records:
        points.append(TrendPoint(
            date=record.collected_at.strftime("%Y-%m-%d"),
            price=float(record.price),
            collected_at=record.collected_at.strftime("%Y-%m-%d %H:%M"),
        ))

    return TrendResponse(
        sku_id=sku_id,
        sku_name=sku.sku_name,
        base_price=float(sku.base_price) if sku.base_price else 0,
        points=points,
    )


@router.get("/task/{task_id}")
def get_task_sku_trends(
    task_id: int,
    days: int = 7,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取任务下所有SKU的趋势数据"""
    skus = session.query(SKU).filter(SKU.task_id == task_id).all()

    result = []
    for sku in skus:
        start_date = datetime.now() - timedelta(days=days)
        records = session.query(PriceRecord).filter(
            PriceRecord.sku_id == sku.id,
            PriceRecord.collected_at >= start_date
        ).order_by(PriceRecord.collected_at).all()

        points = []
        for record in records:
            points.append({
                "date": record.collected_at.strftime("%Y-%m-%d"),
                "price": float(record.price),
            })

        result.append({
            "sku_id": sku.id,
            "sku_name": sku.sku_name,
            "base_price": float(sku.base_price) if sku.base_price else None,
            "current_price": float(sku.current_price) if sku.current_price else None,
            "points": points,
        })

    return {"task_id": task_id, "skus": result}


@router.get("/task/{task_id}/skus")
def get_task_sku_list(
    task_id: int,
    session: Session = Depends(get_db_session),
    user: User = Depends(require_login)
):
    """获取任务下的SKU列表（用于选择查看趋势）"""
    skus = session.query(SKU).filter(SKU.task_id == task_id).all()

    result = []
    for sku in skus:
        result.append(SKUTrendList(
            sku_id=sku.id,
            sku_name=sku.sku_name,
            base_price=float(sku.base_price) if sku.base_price else None,
            current_price=float(sku.current_price) if sku.current_price else None,
        ))

    return {"task_id": task_id, "skus": result}