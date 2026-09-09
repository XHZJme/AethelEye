"""
筱和灵眸(AethelEye) - AI 服务绑定模型

存储「哪个AI服务用哪个Provider+模型」的配置。
例如：ai_rpa → minimax/abab6.5s, ai_coding → openai/deepseek-coder

与已有 LLMProviderConfig 的关系：
  - LLMProviderConfig 管理 Provider 连接信息（API Key / Base URL）
  - AIServiceBinding 管理 服务→模型 的映射关系
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.sql import func

from app.database import Base


class AIServiceBinding(Base):
    """AI 服务→模型 绑定配置表"""
    __tablename__ = "ai_service_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 服务标识（ai_rpa / ai_coding / ai_analysis / ai_watchdog / chat）
    service_name = Column(String(50), nullable=False, unique=True)
    # 用户可读的服务描述
    service_display_name = Column(String(100), nullable=False)
    # 关联的 Provider 配置 ID（外键到 llm_provider_configs.id）
    provider_config_id = Column(Integer, nullable=True)
    # 指定使用的模型名称
    model = Column(String(100), nullable=True)
    # 是否启用此服务
    is_enabled = Column(Boolean, default=True, nullable=False)
    # 备注
    note = Column(Text, nullable=True)

    created_at = Column(DateTime, nullable=False, default=func.now())
    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<AIServiceBinding(service='{self.service_name}', model='{self.model}')>"


class EngineConfig(Base):
    """引擎配置表（引擎选择策略 + 各引擎参数）"""
    __tablename__ = "engine_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # 引擎选择策略: default / manual / hardcoded_only / ai_only
    engine_strategy = Column(String(30), nullable=False, default="default")
    # AI RPA 引擎最大探索轮数
    ai_rpa_max_explore_rounds = Column(Integer, default=10, nullable=False)
    # AI RPA 单次超时（秒）
    ai_rpa_timeout_seconds = Column(Integer, default=60, nullable=False)
    # AI 自治级别: 0=全手动 / 1=观察 / 2=保守 / 3=激进
    ai_autonomy_level = Column(Integer, default=1, nullable=False)

    updated_at = Column(DateTime, nullable=False, default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<EngineConfig(strategy='{self.engine_strategy}', autonomy={self.ai_autonomy_level})>"
