"""
筱和灵眸(AethelEye) - 异动记录模型

异动记录表（alerts）
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, DECIMAL, Boolean
from sqlalchemy.sql import func

from app.database import Base


class Alert(Base):
    """异动记录表"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 关联
    sku_id = Column(Integer, ForeignKey("skus.id"), nullable=False)
    task_id = Column(Integer, ForeignKey("monitor_tasks.id"), nullable=False)

    # 异动类型
    alert_type = Column(String(30), nullable=False)  # price_drop/collect_fail/account_issue

    # 价格快照
    base_price = Column(DECIMAL(10, 2), nullable=False)  # 基准价（快照）
    alert_price = Column(DECIMAL(10, 2), nullable=False)  # 异动到手价
    price_diff = Column(DECIMAL(10, 2), nullable=False)  # 价差
    price_diff_pct = Column(DECIMAL(10, 4), nullable=False)  # 价差百分比

    # 证据
    screenshot_path = Column(Text, nullable=True)  # 截图路径

    # 处理状态
    status = Column(String(20), nullable=False, default="new")  # new/confirmed/resolved/false_alarm
    resolved_note = Column(Text, nullable=True)  # 处理备注
    confirmed_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # 确认人
    resolved_at = Column(DateTime, nullable=True)  # 处理时间

    # 推送状态
    webhook_sent = Column(Boolean, nullable=False, default=False)  # 是否已推送
    webhook_sent_at = Column(DateTime, nullable=True)  # 推送时间

    # 发现时间
    detected_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self):
        return f"<Alert(id={self.id}, type='{self.alert_type}', status='{self.status}')>"