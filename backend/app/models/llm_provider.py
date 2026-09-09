"""
筱和灵眸(AethelEye) - LLM Provider 模型

存储 LLM Provider 配置（API Key、Base URL、模型映射等）
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float
from sqlalchemy.sql import func

from app.database import Base


class LLMProviderConfig(Base):
    """LLM Provider 配置表"""
    __tablename__ = "llm_provider_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Provider 标识（openai_compatible / minimax / anthropic）
    provider_type = Column(String(50), nullable=False)
    # 用户自定义名称（如“主用 OpenAI”“备用 DeepSeek”）
    display_name = Column(String(100), nullable=False)
    # API Key（Fernet 认证加密，字段名为兼容既有数据库而保留）
    api_key = Column(Text, nullable=False)
    # API Base URL（可选覆盖）
    base_url = Column(String(500), nullable=True)
    # 支持的模型前缀（JSON数组，覆盖Provider默认值）
    model_prefixes = Column(Text, nullable=True)  # JSON: ["gpt-", "o1-"]
    # 默认模型
    default_model = Column(String(100), nullable=True)
    # 是否启用
    is_active = Column(Boolean, default=True, nullable=False)
    # 优先级（越小越优先，用于同模型多Provider时的路由）
    priority = Column(Integer, default=100, nullable=False)
    # 每分钟请求限制（0=无限制）
    rate_limit_rpm = Column(Integer, default=0, nullable=False)
    # 备注
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<LLMProviderConfig(id={self.id}, type='{self.provider_type}', name='{self.display_name}')>"


class LLMUsageLog(Base):
    """LLM 用量记录表"""
    __tablename__ = "llm_usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider_config_id = Column(Integer, nullable=False)
    model = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    # 耗时（毫秒）
    duration_ms = Column(Integer, default=0, nullable=False)
    # 请求来源（chat / ai_engine / system）
    source = Column(String(50), default="chat", nullable=False)
    # 是否成功
    success = Column(Boolean, default=True, nullable=False)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())

    def __repr__(self):
        return f"<LLMUsageLog(id={self.id}, model='{self.model}', tokens={self.total_tokens})>"
