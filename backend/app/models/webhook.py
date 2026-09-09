"""
筱和灵眸(AethelEye) - Webhook配置模型

Webhook配置表（webhook_configs）
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func

from app.database import Base


class WebhookConfig(Base):
    """Webhook配置表"""
    __tablename__ = "webhook_configs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 名称，如"控价监控群"
    webhook_url = Column(Text, nullable=False)  # Webhook地址（应用层加密存储）
    webhook_type = Column(String(20), nullable=False, default="wecom")  # wecom/dingtalk/custom
    is_default = Column(Boolean, nullable=False, default=False)  # 是否默认
    is_active = Column(Boolean, nullable=False, default=True)  # 是否启用
    created_at = Column(DateTime, nullable=False, default=func.now())

    # 企业微信高级配置
    secret = Column(Text, nullable=True)  # 签名密钥（应用层加密存储）
    mentioned_list = Column(Text, nullable=True)  # @用户ID列表（JSON数组，如["userid1","userid2","@all"]）
    mentioned_mobile_list = Column(Text, nullable=True)  # @手机号列表（JSON数组，如["138****1111","@all"]）
    msg_type = Column(String(20), nullable=False, default="markdown")  # 消息类型: text/markdown
    keyword = Column(String(200), nullable=True)  # 关键词（部分机器人需要消息含关键词才能发出）

    def __repr__(self):
        return f"<WebhookConfig(id={self.id}, name='{self.name}', type='{self.webhook_type}')>"
