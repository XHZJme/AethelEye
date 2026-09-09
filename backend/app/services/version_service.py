"""
筱和灵眸(AethelEye) - 版本管理服务

升级检测和数据迁移
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from app.config import settings
from app.utils.logger import get_logger

# 日志
log = get_logger("system")


class VersionService:
    """
    版本管理服务

    处理版本检测、升级和数据迁移
    """

    VERSION_FILE = "version.json"
    MIGRATION_DIR = "migrations"

    def __init__(self):
        """初始化版本服务"""
        self._current_version = settings.app_version
        self._version_file = settings.data_dir / self.VERSION_FILE
        self._migrations_dir = settings.base_dir / self.MIGRATION_DIR

    def get_current_version(self) -> str:
        """获取当前版本"""
        return self._current_version

    def get_installed_version(self) -> Optional[str]:
        """
        获取已安装版本（从数据目录读取）

        Returns:
            版本字符串，首次安装返回None
        """
        if not self._version_file.exists():
            return None

        try:
            with open(self._version_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version")
        except Exception as e:
            log.warning(f"读取已安装版本失败: {e}")
            return None

    def save_version(self) -> None:
        """保存当前版本到数据目录"""
        try:
            data = {
                "version": self._current_version,
                "installed_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
            }

            with open(self._version_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)

            log.info(f"版本信息已保存: {self._current_version}")

        except Exception as e:
            log.error(f"保存版本信息失败: {e}")

    def check_upgrade_needed(self) -> bool:
        """
        检查是否需要升级

        Returns:
            True: 需要升级
            False: 无需升级
        """
        installed = self.get_installed_version()

        if not installed:
            # 首次安装
            return False

        return installed != self._current_version

    def get_upgrade_info(self) -> Dict[str, Any]:
        """
        获取升级信息

        Returns:
            升级信息字典
        """
        installed = self.get_installed_version()

        return {
            "current_version": self._current_version,
            "installed_version": installed,
            "upgrade_needed": self.check_upgrade_needed(),
            "first_install": installed is None,
        }

    def perform_migration(self) -> bool:
        """
        执行数据迁移

        Returns:
            True: 成功
            False: 失败
        """
        installed = self.get_installed_version()

        if not installed:
            # 首次安装，无需迁移
            self.save_version()
            return True

        if installed == self._current_version:
            # 版本相同，无需迁移
            return True

        log.info(f"开始数据迁移: {installed} -> {self._current_version}")

        try:
            # 执行迁移脚本（如果有）
            # 这里可以添加版本间的数据库迁移逻辑
            # 例如：表结构变更、数据格式转换等

            # 示例：检查是否有迁移目录
            if self._migrations_dir.exists():
                # 执行迁移脚本
                self._run_migrations(installed, self._current_version)

            # 保存新版本
            self.save_version()

            log.info(f"数据迁移完成")
            return True

        except Exception as e:
            log.error(f"数据迁移失败: {e}")
            return False

    def _run_migrations(self, from_version: str, to_version: str) -> None:
        """
        执行迁移脚本

        Args:
            from_version: 原版本
            to_version: 目标版本
        """
        # 遍历迁移目录，执行需要的迁移
        # 迁移文件命名格式: migrate_1.0.0_to_1.1.0.py
        pass  # 实际迁移逻辑根据需要添加


# 全局版本服务实例
_version_service: Optional[VersionService] = None


def get_version_service() -> VersionService:
    """获取版本服务实例"""
    global _version_service
    if _version_service is None:
        _version_service = VersionService()
    return _version_service