"""
筱和灵眸(AethelEye) - 监控任务模型

监控任务表（monitor_tasks）
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, DECIMAL
from sqlalchemy.sql import func
from datetime import datetime

from app.database import Base


class MonitorTask(Base):
    """监控任务表"""
    __tablename__ = "monitor_tasks"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 商品信息
    url = Column(Text, nullable=False)  # 商品链接
    platform = Column(String(20), nullable=False)  # tmall/taobao
    product_title = Column(Text, nullable=True)  # 商品标题
    shop_name = Column(String(200), nullable=True)  # 店铺名称
    product_image = Column(Text, nullable=True)  # 主图路径

    # 监控配置
    frequency_minutes = Column(Integer, nullable=False, default=120)  # 监控频率（分钟）
    browser_profile_id = Column(Integer, ForeignKey("browser_profiles.id"), nullable=True)
    webhook_config_id = Column(Integer, ForeignKey("webhook_configs.id"), nullable=True)
    note = Column(Text, nullable=True)  # 备注

    # 任务状态
    status = Column(String(20), nullable=False, default="active")  # active/paused/error/need_login
    last_check_at = Column(DateTime, nullable=True)  # 最后采集时间
    next_check_at = Column(DateTime, nullable=True)  # 下次采集时间
    last_error = Column(Text, nullable=True)  # 最后错误信息

    # 风控自动切换：记录任务原始绑定的profile，以便风控恢复后还原
    original_browser_profile_id = Column(Integer, nullable=True)  # 风控前的原始profile
    risk_control_retries = Column(Integer, nullable=False, default=0)  # 连续风控重试次数

    # 录屏配置
    recording_enabled = Column(Boolean, nullable=False, default=False)  # 是否录屏

    # 创建信息
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        title = (self.product_title or "未命名商品")
        title_preview = title[:20] + ("..." if len(title) > 20 else "")
        return f"<MonitorTask(id={self.id}, product='{title_preview}', status='{self.status}')>"
