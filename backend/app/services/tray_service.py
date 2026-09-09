"""
筱和灵眸(AethelEye) - 系统托盘服务

pystray系统托盘图标
- 启动/停止服务
- 打开后台
- 切换运行模式
- 查看日志/录屏
"""
import threading
from typing import Optional, Callable
from pathlib import Path

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

from app.config import settings
from app.utils.logger import get_logger
from app.database import get_sync_session
from app.models.settings_model import SystemSettings

# 日志
log = get_logger("system")


class TrayService:
    """
    系统托盘服务

    提供Windows任务栏托盘图标和菜单
    """

    def __init__(self):
        """初始化托盘服务"""
        self._icon: Optional[pystray.Icon] = None
        self._running = False
        self._running_mode = "silent"  # silent/visual

    def start(self) -> None:
        """启动托盘服务"""
        if not HAS_PYSTRAY:
            log.warning("pystray未安装，跳过托盘服务")
            return

        if self._running:
            return

        # 创建图标
        icon_image = self._create_icon()

        # 创建菜单
        menu = self._create_menu()

        # 创建托盘图标
        self._icon = pystray.Icon(
            name="aetheleye",
            icon=icon_image,
            title="筱和灵眸(AethelEye)",
            menu=menu,
        )

        # 在独立线程运行
        thread = threading.Thread(target=self._icon.run, daemon=True)
        thread.start()

        self._running = True

        # 读取当前运行模式
        self._load_running_mode()

        log.info("系统托盘服务已启动")

    def stop(self) -> None:
        """停止托盘服务"""
        if not self._running or not self._icon:
            return

        self._icon.stop()
        self._running = False
        log.info("系统托盘服务已停止")

    def update_mode(self, mode: str) -> None:
        """更新运行模式"""
        self._running_mode = mode
        self._update_icon_color()
        log.info(f"托盘运行模式已更新: {mode}")

    def _create_icon(self) -> Image.Image:
        """创建托盘图标"""
        # 创建64x64图标
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # 根据模式选择颜色
        color = self._get_mode_color()

        # 绘制圆形图标
        margin = 8
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color,
            outline=(255, 255, 255, 255),
            width=2,
        )

        # 绘制中心字母"E"（Eye）
        draw.text(
            (size // 2 - 8, size // 2 - 12),
            "E",
            fill=(255, 255, 255, 255),
        )

        return image

    def _get_mode_color(self) -> tuple:
        """根据模式返回图标颜色"""
        if self._running_mode == "visual":
            return (100, 150, 255, 255)  # 蓝色 - 可视化模式
        else:
            return (100, 200, 100, 255)  # 绿色 - 静默模式

    def _update_icon_color(self) -> None:
        """更新图标颜色"""
        if self._icon:
            new_image = self._create_icon()
            self._icon.icon = new_image

    def _create_menu(self) -> pystray.Menu:
        """创建托盘菜单"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda text: f"运行模式: {self._get_mode_display()}",
                lambda: None,
                enabled=False,
            ),
            pystray.MenuItem(
                "切换到可视化模式",
                lambda: self._switch_mode("visual"),
                checked=lambda item: self._running_mode == "visual",
            ),
            pystray.MenuItem(
                "切换到静默模式",
                lambda: self._switch_mode("silent"),
                checked=lambda item: self._running_mode == "silent",
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "打开后台",
                lambda: self._open_dashboard(),
            ),
            pystray.MenuItem(
                "查看日志",
                lambda: self._open_logs(),
            ),
            pystray.MenuItem(
                "查看录屏",
                lambda: self._open_recordings(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "服务状态: 运行中",
                lambda: None,
                enabled=False,
            ),
            pystray.MenuItem(
                "重启服务",
                lambda: self._restart_service(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "关于",
                lambda: self._show_about(),
            ),
            pystray.MenuItem(
                "退出",
                lambda: self._exit_app(),
            ),
        )

    def _get_mode_display(self) -> str:
        """获取模式显示文本"""
        return "可视化" if self._running_mode == "visual" else "静默"

    def _load_running_mode(self) -> None:
        """从数据库加载运行模式"""
        try:
            with get_sync_session() as session:
                setting = session.query(SystemSettings).filter(
                    SystemSettings.key == "running_mode"
                ).first()
                if setting:
                    self._running_mode = setting.value
                    self._update_icon_color()
        except Exception as e:
            log.warning(f"加载运行模式失败: {e}")

    def _switch_mode(self, mode: str) -> None:
        """切换运行模式"""
        try:
            # 保存到数据库
            with get_sync_session() as session:
                setting = session.query(SystemSettings).filter(
                    SystemSettings.key == "running_mode"
                ).first()
                if setting:
                    setting.value = mode
                else:
                    setting = SystemSettings(key="running_mode", value=mode)
                    session.add(setting)
                session.commit()

            self._running_mode = mode
            self._update_icon_color()

            log.info(f"运行模式已切换: {mode}")

        except Exception as e:
            log.error(f"切换运行模式失败: {e}")

    def _open_dashboard(self) -> None:
        """打开后台页面"""
        import webbrowser
        url = f"http://localhost:{settings.port}"
        webbrowser.open(url)
        log.info(f"打开后台: {url}")

    def _open_logs(self) -> None:
        """打开日志目录"""
        import subprocess
        log_dir = settings.logs_dir
        if log_dir.exists():
            subprocess.Popen(['explorer', str(log_dir)])
            log.info(f"打开日志目录: {log_dir}")

    def _open_recordings(self) -> None:
        """打开录屏目录"""
        import subprocess
        recordings_dir = settings.recordings_dir
        if recordings_dir.exists():
            subprocess.Popen(['explorer', str(recordings_dir)])
            log.info(f"打开录屏目录: {recordings_dir}")

    def _restart_service(self) -> None:
        """重启服务"""
        log.info("请求重启服务")
        # 这个功能需要外部进程管理，暂不实现

    def _show_about(self) -> None:
        """显示关于信息"""
        log.info(f"关于: {settings.app_name} v{settings.app_version}")
        # 可以弹出一个对话框，但pystray不支持，仅日志记录

    def _exit_app(self) -> None:
        """退出应用"""
        log.info("用户请求退出应用")
        # 停止托盘
        self.stop()
        # 实际退出需要由主程序处理


# 全局托盘服务实例
_tray_service: Optional[TrayService] = None


def get_tray_service() -> TrayService:
    """获取托盘服务实例"""
    global _tray_service
    if _tray_service is None:
        _tray_service = TrayService()
    return _tray_service