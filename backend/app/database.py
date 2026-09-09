"""
筱和灵眸(AethelEye) - 数据库初始化

SQLite + SQLAlchemy ORM配置
- 异步引擎
- Session管理
- Base模型类
- 自动创建表结构
"""
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from contextlib import contextmanager, asynccontextmanager
from typing import Generator, AsyncGenerator
from pathlib import Path
from fastapi import HTTPException

from app.config import settings
from app.utils.logger import get_logger

# 日志
log = get_logger("system")

# 同步引擎（用于初始化）
sync_engine = create_engine(
    f"sqlite:///{settings.database_path}",
    echo=False,  # 不打印SQL
    connect_args={
        "check_same_thread": False,  # SQLite多线程支持
        "timeout": 30,  # 缓解并发写入时的database is locked
    },
)

# 异步引擎（用于API）
async_engine = create_async_engine(
    f"sqlite+aiosqlite:///{settings.database_path}",
    echo=False,
    connect_args={"timeout": 30},
)

# Session工厂
SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)
AsyncSessionLocal = sessionmaker(bind=async_engine, class_=AsyncSession, autocommit=False, autoflush=False)

# Base模型类
Base = declarative_base()


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """
    同步Session上下文管理器

    用法：
    with get_sync_session() as session:
        user = session.query(User).first()
    """
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        log.error(f"数据库操作失败: {str(e)}")
        raise
    finally:
        session.close()


def get_db_session() -> Generator[Session, None, None]:
    """
    FastAPI依赖注入专用Session生成器

    用法（在路由/中间件中）：
    def my_route(session: Session = Depends(get_db_session)):
        user = session.query(User).first()

    注意：此函数不使用@contextmanager装饰器，
    这是FastAPI Depends()要求的generator dependency格式。
    """
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as e:
        session.rollback()
        log.error(f"数据库操作失败: {str(e)}")
        raise
    finally:
        session.close()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """
    异步Session上下文管理器

    用法：
    async with get_async_session() as session:
        user = await session.execute(select(User))
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        log.error(f"数据库操作失败: {e}")
        raise
    finally:
        await session.close()


def init_database() -> None:
    """
    初始化数据库

    - 创建数据库文件
    - 创建所有表结构
    - 初始化系统设置
    """
    # 确保数据库文件目录存在
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)

    # 导入所有模型（确保Base.metadata包含所有表）
    from app.models import user, settings_model, browser, task, sku, price_record, webhook, alert, sku_note_memory, sku_change_event, llm_provider, ai_service_binding, plugin

    # 创建表结构
    Base.metadata.create_all(bind=sync_engine)

    # SQLite并发优化：WAL + 正常同步级别，减少写锁冲突
    with sync_engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        conn.execute(text("PRAGMA synchronous=NORMAL;"))
        conn.execute(text("PRAGMA busy_timeout=30000;"))
        conn.commit()

    log.info(
        "数据库初始化完成",
        data={
            "database_path": str(settings.database_path),
            "tables": list(Base.metadata.tables.keys()),
        }
    )

    # 数据库平滑迁移：检查并添加新列（SQLite的create_all不会修改已有表）
    _run_migrations(sync_engine)

    # 初始化默认系统设置
    init_default_settings()


def _run_migrations(engine) -> None:
    """
    安全的数据库迁移

    SQLite的CREATE TABLE IF NOT EXISTS不会添加新列到已有表，
    所以需要手动检查并ALTER TABLE添加缺失列。
    """
    migrations = [
        # (表名, 列名, 列类型SQL)
        ("skus", "note", "VARCHAR(500)"),
        ("monitor_tasks", "original_browser_profile_id", "INTEGER"),
        ("monitor_tasks", "risk_control_retries", "INTEGER DEFAULT 0"),
        ("webhook_configs", "secret", "VARCHAR(200)"),
        ("webhook_configs", "mentioned_list", "TEXT"),
        ("webhook_configs", "mentioned_mobile_list", "TEXT"),
        ("webhook_configs", "msg_type", "VARCHAR(20) DEFAULT 'markdown'"),
        ("webhook_configs", "keyword", "VARCHAR(200)"),
    ]

    with engine.connect() as conn:
        for table_name, column_name, column_type in migrations:
            try:
                # 检查列是否已存在
                result = conn.execute(text(f"PRAGMA table_info({table_name})"))
                existing_columns = [row[1] for row in result.fetchall()]
                if column_name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))
                    conn.commit()
                    log.info(f"数据库迁移：已添加 {table_name}.{column_name} 列")
            except Exception as e:
                log.warning(f"数据库迁移警告 ({table_name}.{column_name}): {e}")


def init_default_settings() -> None:
    """
    初始化默认系统设置
    """
    from app.models.settings_model import SystemSettings

    with get_sync_session() as session:
        # 检查是否已存在设置
        existing = session.query(SystemSettings).first()
        if existing:
            log.info("系统设置已存在，跳过初始化")
            return

        # 创建默认设置
        default_settings = [
            ("port", str(settings.port)),
            ("log_level", settings.log_level),
            ("log_retention_days", str(settings.log_retention_days)),
            ("collect_timeout_seconds", str(settings.collect_timeout_seconds)),
            ("collect_retry_count", str(settings.collect_retry_count)),
            ("collect_delay_min_seconds", str(settings.collect_delay_min_seconds)),
            ("collect_delay_max_seconds", str(settings.collect_delay_max_seconds)),
            ("running_mode", "silent"),  # 默认静默模式
            ("recording_enabled", "false"),  # 默认关闭录屏
            ("recording_retention_days", "7"),
            ("recording_resolution", "1280x720"),
        ]

        for key, value in default_settings:
            setting = SystemSettings(key=key, value=value)
            session.add(setting)

        log.info("默认系统设置已初始化", data={"count": len(default_settings)})


def check_admin_exists() -> bool:
    """
    检查是否存在管理员账号

    Returns:
        True: 存在管理员
        False: 不存在管理员（需要首次初始化）
    """
    from app.models.user import User

    with get_sync_session() as session:
        admin = session.query(User).filter(User.role == "admin").first()
        return admin is not None
