"""
筱和灵眸(AethelEye) - SKU变更事件模型

记录SKU字段变更，用于任务详情中的状态节点展示
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func

from app.database import Base


class SKUChangeEvent(Base):
    """SKU变更事件表"""
    __tablename__ = "sku_change_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    task_id = Column(Integer, ForeignKey("monitor_tasks.id"), nullable=False)
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=True)

    sku_name = Column(String(500), nullable=False)
    source = Column(String(30), nullable=False, default="collector")  # collector/manual/system
    change_type = Column(String(50), nullable=False, default="update")
    changed_fields = Column(String(500), nullable=False, default="")

    old_values = Column(Text, nullable=True)
    new_values = Column(Text, nullable=True)

    changed_by = Column(Integer, nullable=True)
    changed_at = Column(DateTime, nullable=False, default=func.now())
