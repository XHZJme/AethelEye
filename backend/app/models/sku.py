"""
筱和灵眸(AethelEye) - SKU模型

SKU表（skus）
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, DECIMAL
from sqlalchemy.sql import func
from datetime import datetime

from app.database import Base


class SKU(Base):
    """SKU表"""
    __tablename__ = "skus"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 关联任务
    task_id = Column(Integer, ForeignKey("monitor_tasks.id"), nullable=False)

    # SKU信息
    sku_name = Column(Text, nullable=False)  # SKU名称/规格
    sku_id_external = Column(String(100), nullable=True)  # 平台SKU编号

    # 价格配置（v1.2简化：只有到手价）
    base_price = Column(DECIMAL(10, 2), nullable=True)  # 基准价
    current_price = Column(DECIMAL(10, 2), nullable=True)  # 最新到手价

    # 监控状态
    is_monitored = Column(Boolean, nullable=False, default=True)  # 是否纳入监控
    status = Column(String(20), nullable=False, default="normal")  # normal/alert/disabled

    # 排序（采集时的原始页面顺序，0-based）
    sort_order = Column(Integer, nullable=False, default=0)

    # 运营备注（自由文本，不限输入，挂载到SKU长期记忆）
    note = Column(Text, nullable=True)

    # 时间信息
    last_updated_at = Column(DateTime, nullable=True)  # 最后更新时间
    created_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self):
        return f"<SKU(id={self.id}, name='{self.sku_name[:20]}...', base_price={self.base_price})>"