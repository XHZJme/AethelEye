"""
筱和灵眸(AethelEye) - 系统设置模型

系统设置表（system_settings）
- key-value结构存储
- 支持JSON复杂值
"""
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base


class SystemSettings(Base):
    """系统设置表"""
    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True, nullable=False)
    value = Column(Text, nullable=False)  # 存储JSON字符串或简单值
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<SystemSettings(key='{self.key}', value='{self.value}')>"