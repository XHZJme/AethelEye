"""
筱和灵眸(AethelEye) - 浏览器管理服务

管理Playwright浏览器实例
- 代理配置
- Cookie管理
- 登录态检测
"""
import asyncio
import sys
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from pathlib import Path

from app.config import settings
from app.models.browser import BrowserProfile
from app.utils.logger import get_logger
from app.utils.encryption import decrypt_data, decrypt_json, encrypt_json

# 日志
log = get_logger("browser")


def get_browser_path() -> Optional[str]:
    """
    获取Chromium浏览器路径

    打包后使用内部的ms-playwright目录

    Returns:
        浏览器路径或None
    """
    # 检查是否在打包环境中
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后
        exe_dir = Path(sys._MEIPASS)
        playwright_dir = exe_dir / 'ms-playwright'

        if playwright_dir.exists():
            # 查找chromium目录下的 chrome.exe
            for item in playwright_dir.iterdir():
                if item.name.startswith('chromium-'):
                    chrome_exe = item / 'chrome-win' / 'chrome.exe'
                    if chrome_exe.exists():
                        return str(chrome_exe)
                    # 兼容其他可能的目录结构
                    for exe in item.rglob('chrome.exe'):
                        return str(exe)
            log.warning(f"打包目录中未找到Chromium: {playwright_dir}")
        else:
            log.warning(f"打包目录中未找到ms-playwright: {playwright_dir}")

    return None


class BrowserManager:
    """
    浏览器管理器

    管理Playwright浏览器实例的生命周期
    """

    def __init__(self):
        """初始化浏览器管理器"""
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._contexts: Dict[int, BrowserContext] = {}  # profile_id -> context
        self._headless: bool = True  # 当前浏览器模式
        self._user_data_base = settings.data_dir / "browser_profiles"  # 持久化目录

    async def _ensure_playwright(self) -> None:
        """确保 Playwright 引擎已启动（不再创建共享 Browser 实例）"""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            log.info("Playwright引擎启动")

    async def restart_playwright(self) -> None:
        """
        完全重启Playwright引擎（用于驱动进程崩溃后恢复）

        强制停止当前Playwright实例并重新创建，解决NotImplementedError等驱动死亡问题
        """
        log.warning("正在完全重启Playwright引擎...")
        # 清理所有上下文引用（不await close，驱动可能已死）
        self._contexts = {}
        self._browser = None
        # 尝试停止旧实例
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._playwright = None
        # 重新启动
        self._playwright = await async_playwright().start()
        log.info("Playwright引擎重启完成")

    async def start(self, headless: bool = True) -> None:
        """
        启动Playwright

        创建浏览器实例，优先使用打包内部的Chromium

        Args:
            headless: 是否无界面模式
        """
        # 如果模式变化，需要先关闭所有持久化上下文
        if self._headless != headless and self._contexts:
            for pid in list(self._contexts.keys()):
                await self.close_context(pid)

        self._headless = headless
        await self._ensure_playwright()

    async def stop(self) -> None:
        """
        停止Playwright

        关闭所有上下文和浏览器
        """
        # 关闭所有上下文
        for profile_id, context in self._contexts.items():
            try:
                await context.close()
                log.debug(f"关闭浏览器上下文: profile_id={profile_id}")
            except Exception as e:
                log.warning(f"关闭上下文失败: {e}")

        # 关闭浏览器
        if self._browser:
            try:
                await self._browser.close()
                log.info("Playwright浏览器关闭")
            except Exception as e:
                log.warning(f"关闭浏览器失败: {e}")

        # 停止Playwright
        if self._playwright:
            try:
                await self._playwright.stop()
                log.info("Playwright停止")
            except Exception as e:
                log.warning(f"停止Playwright失败: {e}")

        self._playwright = None
        self._browser = None
        self._contexts = {}

    async def get_context(
        self,
        profile_id: int,
        headless: bool = True,
    ) -> BrowserContext:
        """
        获取或创建持久化浏览器上下文

        始终返回 persistent context（常驻模式），录屏通过 CDP screencast 实现。

        Args:
            profile_id: 浏览器配置ID
            headless: 是否无界面运行

        Returns:
            BrowserContext实例
        """
        # 确保 Playwright 引擎已启动，并处理 headless 模式切换
        await self._ensure_playwright()
        if self._headless != headless and self._contexts:
            for pid in list(self._contexts.keys()):
                await self.close_context(pid)
        self._headless = headless

        # 从数据库获取最新的profile配置（在session内复制属性）
        from app.database import get_sync_session
        with get_sync_session() as session:
            profile = session.query(BrowserProfile).filter(
                BrowserProfile.id == profile_id
            ).first()
            if not profile:
                raise Exception(f"浏览器配置不存在: {profile_id}")

            # 复制所有需要的属性到本地变量（避免session关闭后访问detached对象）
            profile_name = profile.name
            profile_viewport_width = profile.viewport_width
            profile_viewport_height = profile.viewport_height
            profile_locale = profile.locale
            profile_timezone = profile.timezone
            profile_user_agent = profile.user_agent
            profile_cookies_data_enc = profile.cookies_data_enc
            profile_proxy_type = profile.proxy_type
            profile_proxy_host = profile.proxy_host
            profile_proxy_port = profile.proxy_port
            profile_proxy_username = profile.proxy_username
            profile_proxy_password_enc = profile.proxy_password_enc

        # 检查是否已有该配置的上下文
        if profile_id in self._contexts:
            context = self._contexts[profile_id]
            # 用真正的异步操作检测上下文是否还活着
            try:
                await context.cookies()
                log.debug(f"复用现有上下文: profile_id={profile_id}")
                return context
            except Exception as e:
                log.warning(f"上下文已失效，重新创建: {e}")
                try:
                    await context.close()
                except Exception:
                    pass
                del self._contexts[profile_id]

        # 持久化用户数据目录（每个 profile 独立）
        user_data_dir = self._user_data_base / f"profile_{profile_id}"
        user_data_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"创建持久化浏览器上下文: profile_id={profile_id}, name={profile_name}, dir={user_data_dir}")

        # 获取打包后的浏览器路径
        browser_path = get_browser_path()

        # 构建启动参数
        launch_args = []
        if sys.platform != 'win32':
            launch_args.append('--disable-dev-shm-usage')
        if not headless and sys.platform == 'win32':
            launch_args.extend([
                '--window-position=0,0',
                '--window-size=1280,720',
            ])

        # 构建上下文参数
        context_args: Dict[str, Any] = {
            "viewport": {
                "width": profile_viewport_width,
                "height": profile_viewport_height,
            },
            "locale": profile_locale,
            "timezone_id": profile_timezone,
            "headless": headless,
            "args": launch_args,
        }
        if profile_user_agent:
            context_args["user_agent"] = profile_user_agent
        if browser_path:
            context_args["executable_path"] = browser_path

        # 代理配置
        if profile_proxy_type and profile_proxy_type != "none":
            proxy_url = f"{profile_proxy_host}:{profile_proxy_port}"
            proxy_password = decrypt_data(profile_proxy_password_enc) if profile_proxy_password_enc else ""
            if profile_proxy_username:
                proxy_url = f"{profile_proxy_username}:{proxy_password}@{proxy_url}"
            context_args["proxy"] = {"server": f"http://{proxy_url}"}

        # 使用 launch_persistent_context：所有浏览器状态（Cookie、localStorage、IndexedDB）持久化到磁盘
        log.info(
            f"启动持久化浏览器: profile_id={profile_id}, headless={headless}, "
            f"viewport={profile_viewport_width}x{profile_viewport_height}"
        )
        context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            **context_args
        )

        # 首次启动时如果DB有Cookie且磁盘目录是新建的，注入一次
        cookie_marker = user_data_dir / ".cookies_imported"
        if profile_cookies_data_enc and not cookie_marker.exists():
            cookies = decrypt_json(profile_cookies_data_enc)
            if cookies:
                await context.add_cookies(cookies)
                log.info(f"首次导入DB Cookie到持久化上下文: profile_id={profile_id}, count={len(cookies)}")
            cookie_marker.touch()

        # 保存上下文
        self._contexts[profile_id] = context

        return context


    async def close_context(self, profile_id: int) -> None:
        """
        关闭指定配置的持久化浏览器上下文

        Args:
            profile_id: 浏览器配置ID
        """
        if profile_id in self._contexts:
            try:
                await self._contexts[profile_id].close()
                log.info(f"关闭浏览器上下文: profile_id={profile_id}")
            except Exception as e:
                log.warning(f"关闭上下文失败: {e}")
            del self._contexts[profile_id]

    async def save_cookies(self, profile: BrowserProfile, context: BrowserContext) -> None:
        """
        保存Cookie到配置

        Args:
            profile: 浏览器配置
            context: 浏览器上下文
        """
        cookies = await context.cookies()
        encrypted_cookies = encrypt_json(cookies)

        # 更新数据库（需要在服务层处理）
        log.info(
            f"Cookie已保存",
            data={
                "profile_id": profile.id,
                "cookie_count": len(cookies),
            }
        )

        return encrypted_cookies

    async def check_login_status(self, context: BrowserContext, platform: str) -> bool:
        """
        检测登录态是否有效

        Args:
            context: 浏览器上下文
            platform: 平台（tmall/taobao）

        Returns:
            True: 登录态有效
            False: 需要重新登录
        """
        try:
            page = await context.new_page()

            # 访问检测页面
            if platform == "tmall":
                check_url = "https://www.tmall.com"
            else:
                check_url = "https://www.taobao.com"

            await page.goto(check_url, wait_until="networkidle", timeout=15000)

            # 检查是否有登录态
            # 查找登录相关元素
            try:
                # 检查是否显示用户名或会员信息
                login_element = await page.query_selector('.site-nav-user')
                if login_element:
                    text = await login_element.inner_text()
                    if "登录" not in text:
                        log.info(f"登录态检测: 有效")
                        await page.close()
                        return True
            except Exception:
                pass

            log.warning(f"登录态检测: 需要重新登录")
            await page.close()
            return False

        except Exception as e:
            log.error(f"登录态检测失败: {e}", error_stack=str(e))
            return False


# 全局浏览器管理器实例
_browser_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    """
    获取浏览器管理器实例

    Returns:
        BrowserManager实例
    """
    global _browser_manager
    if _browser_manager is None:
        _browser_manager = BrowserManager()
    return _browser_manager
