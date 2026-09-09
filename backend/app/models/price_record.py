"""
筱和灵眸(AethelEye) - 价格记录模型

价格记录表（price_records）
v1.2简化：只记录到手价
"""
from sqlalchemy import Column, Integer, DateTime, Text, ForeignKey, DECIMAL
from sqlalchemy.sql import func

from app.database import Base


class PriceRecord(Base):
    """价格记录表"""
    __tablename__ = "price_records"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 关联
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("monitor_tasks.id"), nullable=False)

    # 价格数据（v1.2简化：只有到手价）
    price = Column(DECIMAL(10, 2), nullable=False)  # 到手价

    # 证据文件
    screenshot_path = Column(Text, nullable=True)  # 截图路径
    recording_path = Column(Text, nullable=True)  # 录屏路径

    # 采集时间
    collected_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self):
        return f"<PriceRecord(id={self.id}, price={self.price}, collected_at='{self.collected_at}')>"