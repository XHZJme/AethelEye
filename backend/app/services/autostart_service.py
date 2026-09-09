"""
筱和灵眸(AethelEye) - 开机自启服务

Windows任务计划注册
- 创建启动任务
- 删除启动任务
- 检查任务状态
"""
import subprocess
from typing import Optional
from pathlib import Path

from app.config import settings
from app.utils.logger import get_logger

# 日志
log = get_logger("system")


class AutostartService:
    """
    开机自启服务

    使用Windows任务计划程序实现开机自启动
    """

    TASK_NAME = "AethelEye_AutoStart"

    def __init__(self):
        """初始化自启服务"""
        self._app_path = self._get_app_path()

    def _get_app_path(self) -> Path:
        """获取应用路径"""
        # 打包后的exe路径
        # 开发模式下返回run.py路径
        base_dir = settings.base_dir
        exe_path = base_dir / "AethelEye.exe"

        if exe_path.exists():
            return exe_path

        # 开发模式
        return base_dir / "backend" / "run.py"

    def enable(self) -> bool:
        """
        启用开机自启

        创建Windows任务计划

        Returns:
            True: 成功
            False: 失败
        """
        try:
            # 任务计划命令
            #schtasks /create /tn "AethelEye_AutoStart" /tr "C:\\AethelEye\\AethelEye.exe" /sc onlogon /rl highest /f

            command = [
                "schtasks",
                "/create",
                "/tn", self.TASK_NAME,
                "/tr", str(self._app_path),
                "/sc", "onlogon",  # 用户登录时启动
                "/rl", "highest",  # 最高权限
                "/f",  # 强制创建（覆盖已有）
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                log.info(f"开机自启已启用")
                return True
            else:
                log.error(f"启用开机自启失败: {result.stderr}")
                return False

        except Exception as e:
            log.error(f"启用开机自启异常: {e}")
            return False

    def disable(self) -> bool:
        """
        禁用开机自启

        删除Windows任务计划

        Returns:
            True: 成功
            False: 失败
        """
        try:
            command = [
                "schtasks",
                "/delete",
                "/tn", self.TASK_NAME,
                "/f",  # 强制删除
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                log.info(f"开机自启已禁用")
                return True
            else:
                # 任务不存在也算成功
                if "not found" in result.stderr.lower() or "无法找到" in result.stderr:
                    log.info(f"开机自启任务不存在")
                    return True
                log.error(f"禁用开机自启失败: {result.stderr}")
                return False

        except Exception as e:
            log.error(f"禁用开机自启异常: {e}")
            return False

    def is_enabled(self) -> bool:
        """
        检查开机自启是否已启用

        Returns:
            True: 已启用
            False: 未启用
        """
        try:
            command = [
                "schtasks",
                "/query",
                "/tn", self.TASK_NAME,
            ]

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=10,
            )

            return result.returncode == 0

        except Exception as e:
            log.warning(f"检查开机自启状态异常: {e}")
            return False

    def get_status(self) -> dict:
        """
        获取开机自启状态详情

        Returns:
            状态信息字典
        """
        return {
            "enabled": self.is_enabled(),
            "task_name": self.TASK_NAME,
            "app_path": str(self._app_path),
        }


# 全局自启服务实例
_autostart_service: Optional[AutostartService] = None


def get_autostart_service() -> AutostartService:
    """获取自启服务实例"""
    global _autostart_service
    if _autostart_service is None:
        _autostart_service = AutostartService()
    return _autostart_service