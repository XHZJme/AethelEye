"""
筱和灵眸(AethelEye) - 配置管理

管理服务端口、数据路径、JWT配置等全局设置
"""
import os
import sys
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import Optional


def _detect_base_dir() -> Path:
    """
    检测应用根目录：
    - PyInstaller 打包后：exe 所在目录即为安装目录（如 C:/Program Files/AethelEye/）
    - 开发模式：从 backend/app/config.py 定位到仓库根目录
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后，sys.executable = AethelEye.exe 的完整路径
        return Path(sys.executable).resolve().parent
    else:
        # 开发模式：config.py 在 backend/app/config.py
        return Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """应用配置类"""

    # 服务配置
    app_name: str = "筱和灵眸(AethelEye)"
    app_version: str = "2.0.0"
    # 默认仅监听本机，确需局域网访问时再通过环境变量 HOST 显式覆盖。
    host: str = "127.0.0.1"
    port: int = 8686

    # 数据路径配置
    # 打包后：{install_dir}/data/   开发时：{project_root}/data/
    base_dir: Path = _detect_base_dir()
    data_dir: Path = base_dir / "data"
    database_path: Path = data_dir / "database.db"
    logs_dir: Path = data_dir / "logs"
    screenshots_dir: Path = data_dir / "screenshots"
    recordings_dir: Path = data_dir / "recordings"

    # JWT配置（密钥在启动时自动生成，见下方 _load_or_generate_jwt_secret）
    jwt_secret_key: str = ""  # 占位，实际值由 _load_or_generate_jwt_secret() 设置
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7天
    jwt_remember_me_days: int = 30  # "记住我"30天

    # 密码配置
    bcrypt_rounds: int = 12  # bcrypt加密轮数

    # 日志配置
    log_level: str = "INFO"
    log_retention_days: int = 90
    log_max_size_mb: int = 50

    # 时区配置
    timezone: str = "Asia/Shanghai"

    # 采集配置（后续Phase使用）
    collect_timeout_seconds: int = 60
    collect_retry_count: int = 2
    collect_delay_min_seconds: int = 5
    collect_delay_max_seconds: int = 12

    # 前端静态文件路径
    # 打包后：{install_dir}/dist/   开发时：{code_dir}/dist/
    frontend_dist_dir: Path = base_dir / "dist"

    def ensure_data_dirs(self) -> None:
        """确保所有数据目录存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.screenshots_dir.mkdir(parents=True, exist_ok=True)
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        # 创建日志分类目录
        for category in ["system", "collector", "network", "browser", "audit", "alert"]:
            (self.logs_dir / category).mkdir(parents=True, exist_ok=True)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


def _load_or_generate_jwt_secret(data_dir: Path) -> str:
    """
    自动生成JWT密钥并持久化到文件

    首次启动时生成256位随机密钥保存到 data/jwt_secret.key，
    后续启动从文件读取，确保Token跨重启有效。
    """
    secret_file = data_dir / "jwt_secret.key"
    if secret_file.exists():
        return secret_file.read_text(encoding="utf-8").strip()

    # 首次启动，生成随机密钥
    secret_key = secrets.token_hex(32)  # 256位
    data_dir.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret_key, encoding="utf-8")
    return secret_key


# 全局配置实例
settings = Settings()

# 启动时确保目录存在
settings.ensure_data_dirs()

# 自动生成并加载JWT密钥
settings.jwt_secret_key = _load_or_generate_jwt_secret(settings.data_dir)
