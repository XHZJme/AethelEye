"""
筱和灵眸(AethelEye) - SKU备注记忆模型

用于跨任务、跨链接记忆SKU备注/货号
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.database import Base


class SKUNoteMemory(Base):
    """SKU备注记忆表"""
    __tablename__ = "sku_note_memories"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "shop_name_normalized",
            "sku_name_normalized",
            name="uq_sku_note_memory_key"
        ),
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 匹配键（保守策略：平台 + 店铺 + SKU规格）
    platform = Column(String(20), nullable=False)
    shop_name_normalized = Column(String(200), nullable=False, default="")
    sku_name_normalized = Column(String(500), nullable=False)

    # 展示信息
    shop_name_display = Column(String(200), nullable=True)
    sku_name_display = Column(String(500), nullable=False)

    # 记忆内容（自由文本备注，挂载到SKU长期记忆）
    note = Column(Text, nullable=False)

    # 审计辅助
    created_by = Column(Integer, nullable=True)
    updated_by = Column(Integer, nullable=True)
    last_task_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())
