"""
筱和灵眸(AethelEye) - 浏览器配置模型

浏览器配置表（browser_profiles）
- 浏览器参数配置
- 代理设置
- 平台登录凭证（加密存储）
- Cookie状态管理
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.sql import func
from datetime import datetime

from app.database import Base


class BrowserProfile(Base):
    """浏览器配置表"""
    __tablename__ = "browser_profiles"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(100), nullable=False)  # 配置名称，如"天猫采集账号-01"

    # 浏览器参数
    user_agent = Column(Text, nullable=True)  # User-Agent字符串
    viewport_width = Column(Integer, nullable=False, default=1280)  # 浏览器宽度
    viewport_height = Column(Integer, nullable=False, default=720)  # 浏览器高度
    locale = Column(String(10), nullable=False, default="zh-CN")  # 语言
    timezone = Column(String(50), nullable=False, default="Asia/Shanghai")  # 时区

    # 代理设置
    proxy_type = Column(String(20), nullable=False, default="none")  # none/http/socks5
    proxy_host = Column(String(100), nullable=True)
    proxy_port = Column(Integer, nullable=True)
    proxy_username = Column(String(100), nullable=True)
    proxy_password_enc = Column(Text, nullable=True)  # 代理密码（加密）

    # 平台登录凭证（加密存储）
    platform = Column(String(20), nullable=False, default="tmall")  # tmall/taobao
    login_username_enc = Column(Text, nullable=True)  # 平台账号（加密）
    login_password_enc = Column(Text, nullable=True)  # 平台密码（加密）

    # Cookie状态
    cookies_data_enc = Column(Text, nullable=True)  # Cookie数据（加密JSON）
    cookie_status = Column(String(20), nullable=False, default="unknown")  # valid/expired/unknown
    cookie_expires_at = Column(DateTime, nullable=True)  # Cookie预计过期时间

    # 状态信息
    is_active = Column(Boolean, nullable=False, default=True)  # 是否启用
    last_login_at = Column(DateTime, nullable=True)  # 最后成功登录时间
    last_check_at = Column(DateTime, nullable=True)  # 最后检测时间
    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<BrowserProfile(id={self.id}, name='{self.name}', platform='{self.platform}')>"
