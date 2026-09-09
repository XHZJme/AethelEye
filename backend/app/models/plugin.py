"""
筱和灵眸(AethelEye) - 插件模型

存储已安装插件的元数据和审核状态。
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text
from app.database import Base


class Plugin(Base):
    __tablename__ = "plugins"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)             # 插件标识（目录名）
    display_name = Column(String(200), nullable=False)
    version = Column(String(20), default="1.0.0")
    plugin_type = Column(String(50), default="tool")                     # engine / analysis / alert / tool / mcp / skill
    description = Column(Text, default="")
    author = Column(String(100), default="")
    entry = Column(String(200), default="main.py")                       # 入口文件
    permissions = Column(Text, default="[]")                             # JSON 权限列表
    config_schema = Column(Text, default="{}")                           # JSON 配置schema
    config_values = Column(Text, default="{}")                           # JSON 用户配置值

    # 审核与状态
    status = Column(String(20), default="pending")                       # pending / approved / rejected / disabled
    reviewed_by = Column(String(100), default="")
    reviewed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, default="")

    is_installed = Column(Boolean, default=True)
    is_enabled = Column(Boolean, default=False)                          # 审核通过后才可启用

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
