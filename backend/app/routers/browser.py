"""
筱和灵眸(AethelEye) - 浏览器配置API路由

浏览器配置的CRUD操作
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.browser import BrowserProfile
from app.middleware.permission import require_admin
from app.models.user import User
from app.utils.logger import get_logger
from app.utils.encryption import encrypt_data, decrypt_data

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/browser", tags=["浏览器管理"])


# ===== Pydantic模型 =====

class BrowserProfileCreate(BaseModel):
    """创建浏览器配置请求"""
    name: str
    platform: str = "tmall"

    # 浏览器参数
    user_agent: Optional[str] = None
    viewport_width: int = 1280
    viewport_height: int = 720
    locale: str = "zh-CN"
    timezone: str = "Asia/Shanghai"

    # 代理
    proxy_type: str = "none"
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None

    # 登录凭证
    login_username: Optional[str] = None
    login_password: Optional[str] = None


class BrowserProfileUpdate(BaseModel):
    """更新浏览器配置请求"""
    name: Optional[str] = None
    user_agent: Optional[str] = None
    viewport_width: Optional[int] = None
    viewport_height: Optional[int] = None
    proxy_type: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_port: Optional[int] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    login_username: Optional[str] = None
    login_password: Optional[str] = None
    is_active: Optional[bool] = None


class BrowserProfileResponse(BaseModel):
    """浏览器配置响应"""
    id: int
    name: str
    platform: str
    user_agent: Optional[str]
    viewport_width: int
    viewport_height: int
    locale: str
    timezone: str
    proxy_type: str
    proxy_host: Optional[str]
    proxy_port: Optional[int]
    cookie_status: str
    is_active: bool
    last_login_at: Optional[datetime]
    created_at: datetime
    has_login_credentials: bool = False

    class Config:
        from_attributes = True


def _profile_to_response(profile: BrowserProfile) -> "BrowserProfileResponse":
    data = BrowserProfileResponse.model_validate(profile)
    data.has_login_credentials = bool(profile.login_username_enc and profile.login_password_enc)
    return data


class BrowserProfileListResponse(BaseModel):
    """浏览器配置列表响应"""
    total: int
    profiles: List[BrowserProfileResponse]


# ===== API端点 =====

@router.get("", response_model=BrowserProfileListResponse)
def list_profiles(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    获取浏览器配置列表（仅管理员）
    """
    profiles = session.query(BrowserProfile).order_by(BrowserProfile.id).all()
    return BrowserProfileListResponse(
        total=len(profiles),
        profiles=[_profile_to_response(p) for p in profiles]
    )


@router.post("", response_model=BrowserProfileResponse)
def create_profile(
    request: BrowserProfileCreate,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    创建浏览器配置（仅管理员）
    """
    # 验证名称唯一
    existing = session.query(BrowserProfile).filter(BrowserProfile.name == request.name).first()
    if existing:
        raise HTTPException(status_code=400, detail="配置名称已存在")

    # 验证平台
    if request.platform not in ("tmall", "taobao"):
        raise HTTPException(status_code=400, detail="平台必须是 tmall/taobao")

    # 创建配置
    profile = BrowserProfile(
        name=request.name,
        platform=request.platform,
        user_agent=request.user_agent,
        viewport_width=request.viewport_width,
        viewport_height=request.viewport_height,
        locale=request.locale,
        timezone=request.timezone,
        proxy_type=request.proxy_type,
        proxy_host=request.proxy_host,
        proxy_port=request.proxy_port,
        proxy_username=request.proxy_username,
    )

    # 加密敏感字段
    if request.proxy_password:
        profile.proxy_password_enc = encrypt_data(request.proxy_password)
    if request.login_username:
        profile.login_username_enc = encrypt_data(request.login_username)
    if request.login_password:
        profile.login_password_enc = encrypt_data(request.login_password)

    session.add(profile)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"浏览器配置已创建",
        user_id=admin.id,
        data={
            "profile_id": profile.id,
            "name": profile.name,
            "platform": profile.platform,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return _profile_to_response(profile)


@router.get("/{profile_id}", response_model=BrowserProfileResponse)
def get_profile(
    profile_id: int,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    获取单个浏览器配置详情（仅管理员）
    """
    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")
    return BrowserProfileResponse.model_validate(profile)


@router.put("/{profile_id}", response_model=BrowserProfileResponse)
def update_profile(
    profile_id: int,
    request: BrowserProfileUpdate,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    更新浏览器配置（仅管理员）
    """
    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    # 更新字段
    if request.name:
        # 检查名称唯一
        existing = session.query(BrowserProfile).filter(
            BrowserProfile.name == request.name,
            BrowserProfile.id != profile_id
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="配置名称已存在")
        profile.name = request.name

    if request.user_agent:
        profile.user_agent = request.user_agent
    if request.viewport_width:
        profile.viewport_width = request.viewport_width
    if request.viewport_height:
        profile.viewport_height = request.viewport_height
    if request.proxy_type:
        profile.proxy_type = request.proxy_type
    if request.proxy_host:
        profile.proxy_host = request.proxy_host
    if request.proxy_port:
        profile.proxy_port = request.proxy_port
    if request.proxy_username:
        profile.proxy_username = request.proxy_username
    if request.proxy_password:
        profile.proxy_password_enc = encrypt_data(request.proxy_password)
    if request.login_username:
        profile.login_username_enc = encrypt_data(request.login_username)
    if request.login_password:
        profile.login_password_enc = encrypt_data(request.login_password)
    if request.is_active is not None:
        profile.is_active = request.is_active

    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"浏览器配置已更新",
        user_id=admin.id,
        data={
            "profile_id": profile_id,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return _profile_to_response(profile)


@router.delete("/{profile_id}")
def delete_profile(
    profile_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    删除浏览器配置（仅管理员）
    """
    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    # 检查是否有任务在使用
    from app.models.task import MonitorTask
    tasks_using = session.query(MonitorTask).filter(MonitorTask.browser_profile_id == profile_id).count()
    if tasks_using > 0:
        raise HTTPException(
            status_code=400,
            detail=f"该配置被{tasks_using}个任务使用，无法删除"
        )

    session.delete(profile)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"浏览器配置已删除",
        user_id=admin.id,
        data={
            "profile_id": profile_id,
            "name": profile.name,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "配置已删除"}


# ===== 可视化登录API =====

from pydantic import Field

class OpenVisualBrowserRequest(BaseModel):
    """打开可视化浏览器请求"""
    url: str = Field(default="https://login.taobao.com", description="打开的目标URL")
    timeout_seconds: int = Field(default=300, description="浏览器保持打开的最大秒数")


class OpenVisualBrowserResponse(BaseModel):
    """打开可视化浏览器响应"""
    success: bool
    message: str
    profile_id: int
    opened_url: str


class SaveCookiesResponse(BaseModel):
    """保存Cookie响应"""
    success: bool
    message: str
    cookie_count: int
    cookie_status: str


@router.post("/{profile_id}/open-visual", response_model=OpenVisualBrowserResponse)
async def open_visual_browser(
    profile_id: int,
    request: OpenVisualBrowserRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    打开可视化浏览器供用户手动登录

    运营人员可以在可视化浏览器中：
    1. 手动登录淘宝/天猫账号
    2. 完成验证码验证
    3. 确认登录成功后调用 /save-cookies 保存登录态

    注意：此操作会打开真实的浏览器窗口，需要用户手动操作
    """
    from app.services.browser_manager import get_browser_manager
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    import asyncio

    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    browser_manager = get_browser_manager()

    try:
        # 启动浏览器（可视化模式，headless=False）
        context = await browser_manager.get_context(
            profile_id=profile_id,
            headless=False,  # 关键：可视化模式
        )

        # 创建页面（若上下文失效则自动重建）
        try:
            page = await context.new_page()
        except Exception:
            await browser_manager.close_context(profile_id)
            context = await browser_manager.get_context(
                profile_id=profile_id,
                headless=False,
            )
            page = await context.new_page()

        # 访问目标URL（默认淘宝登录页）
        await page.goto(request.url, wait_until="domcontentloaded")

        log.info(
            f"可视化浏览器已打开",
            user_id=admin.id,
            data={
                "profile_id": profile_id,
                "profile_name": profile.name,
                "url": request.url,
                "timeout_seconds": request.timeout_seconds,
                "operator": admin.username,
            }
        )

        # 保持浏览器打开一段时间（等待用户操作）
        # 实际场景中，前端应该轮询检查浏览器状态
        # 这里简单返回成功，浏览器保持打开
        return OpenVisualBrowserResponse(
            success=True,
            message=f"浏览器已打开，请在窗口中完成登录后调用 /browser/{profile_id}/save-cookies 保存登录态",
            profile_id=profile_id,
            opened_url=request.url
        )

    except Exception as e:
        log.error(f"打开可视化浏览器失败: {e}", error_stack=str(e))
        raise HTTPException(status_code=500, detail=f"打开浏览器失败: {str(e)}")


@router.post("/{profile_id}/save-cookies", response_model=SaveCookiesResponse)
async def save_browser_cookies(
    profile_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    保存当前浏览器的Cookie到配置

    在可视化浏览器中完成登录后，调用此接口保存登录态
    """
    from app.services.browser_manager import get_browser_manager
    from app.utils.encryption import encrypt_json

    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    browser_manager = get_browser_manager()

    try:
        # 获取该配置的上下文
        context = browser_manager._contexts.get(profile_id)
        if not context:
            raise HTTPException(
                status_code=400,
                detail="该配置的浏览器未打开，请先调用 /open-visual 打开浏览器"
            )

        # 获取所有Cookie
        cookies = await context.cookies()

        # 加密保存到数据库
        encrypted_cookies = encrypt_json(cookies)
        profile.cookies_data_enc = encrypted_cookies
        profile.cookie_status = "valid"
        profile.last_login_at = datetime.now()
        session.commit()

        log.info(
            f"浏览器Cookie已保存",
            user_id=admin.id,
            data={
                "profile_id": profile_id,
                "profile_name": profile.name,
                "cookie_count": len(cookies),
                "operator": admin.username,
            }
        )

        # 保存成功后自动关闭浏览器窗口
        await browser_manager.close_context(profile_id)
        log.info(f"登录完成，浏览器已自动关闭", data={"profile_id": profile_id})

        return SaveCookiesResponse(
            success=True,
            message=f"已成功保存 {len(cookies)} 个Cookie，浏览器已自动关闭",
            cookie_count=len(cookies),
            cookie_status="valid"
        )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"保存Cookie失败: {e}", error_stack=str(e))
        raise HTTPException(status_code=500, detail=f"保存Cookie失败: {str(e)}")


@router.post("/{profile_id}/close")
async def close_browser(
    profile_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    关闭指定配置的浏览器

    用于在登录完成后关闭浏览器窗口
    """
    from app.services.browser_manager import get_browser_manager

    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    browser_manager = get_browser_manager()

    try:
        await browser_manager.close_context(profile_id)

        log.info(
            f"浏览器已关闭",
            user_id=admin.id,
            data={
                "profile_id": profile_id,
                "profile_name": profile.name,
                "operator": admin.username,
            }
        )

        return {"success": True, "message": "浏览器已关闭"}

    except Exception as e:
        log.error(f"关闭浏览器失败: {e}", error_stack=str(e))
        raise HTTPException(status_code=500, detail=f"关闭浏览器失败: {str(e)}")


# ===== Cookie 导入 =====

class ImportCookiesRequest(BaseModel):
    """导入 Cookie 请求"""
    cookies: List[dict] = Field(..., description="Cookie 数组，每项含 name/value/domain 等字段")


@router.post("/{profile_id}/import-cookies", response_model=SaveCookiesResponse)
def import_cookies(
    profile_id: int,
    request: ImportCookiesRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    粘贴 Cookie JSON 导入到配置

    支持从浏览器 DevTools / 扩展导出的 cookies 数组直接粘贴。
    每条 Cookie 至少需包含 name / value / domain 三个字段。
    导入后 cookie_status 标记为 valid，last_login_at 置为当前时间。
    """
    from app.utils.encryption import encrypt_json

    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    raw_cookies = request.cookies or []
    if not raw_cookies:
        raise HTTPException(status_code=400, detail="未提供任何 Cookie")

    # 校验必要字段 + 规范化
    valid_cookies: List[dict] = []
    for i, c in enumerate(raw_cookies):
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        value = c.get("value")
        domain = c.get("domain")
        if not (name and value and domain):
            continue
        normalized = {
            "name": str(name),
            "value": str(value),
            "domain": str(domain),
            "path": str(c.get("path") or "/"),
        }
        # Playwright 可选字段
        for opt in ("expires", "httpOnly", "secure", "sameSite"):
            if opt in c and c[opt] is not None:
                normalized[opt] = c[opt]
        valid_cookies.append(normalized)

    if not valid_cookies:
        raise HTTPException(status_code=400, detail="所有 Cookie 都缺少 name/value/domain 必填字段")

    profile.cookies_data_enc = encrypt_json(valid_cookies)
    profile.cookie_status = "valid"
    profile.last_login_at = datetime.now()
    profile.last_check_at = datetime.now()
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"Cookie 已通过粘贴导入",
        user_id=admin.id,
        data={
            "profile_id": profile_id,
            "profile_name": profile.name,
            "cookie_count": len(valid_cookies),
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return SaveCookiesResponse(
        success=True,
        message=f"已成功导入 {len(valid_cookies)} 条 Cookie",
        cookie_count=len(valid_cookies),
        cookie_status="valid",
    )


# ===== 账号密码自动填充登录 =====

class AutoLoginRequest(BaseModel):
    """自动登录请求"""
    auto_submit: bool = Field(
        default=False,
        description="是否在填充后自动点击登录按钮。为 True 时可能触发滑块/短信验证，需在浏览器窗口手动完成"
    )


@router.post("/{profile_id}/auto-login", response_model=OpenVisualBrowserResponse)
async def auto_login(
    profile_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin),
    body: Optional[AutoLoginRequest] = None,
):
    """
    账号密码自动填充登录

    1. 从配置读取已加密存储的账号密码
    2. 打开可视化浏览器并导航至 tmall/taobao 登录页
    3. 用 Playwright 自动填充用户名密码
    4. 不主动点登录（淘宝滑块/短信验证需要人工处理）
    5. 用户在浏览器窗口内手动完成验证后点「保存Cookie」
    """
    from app.services.browser_manager import get_browser_manager

    profile = session.query(BrowserProfile).filter(BrowserProfile.id == profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="配置不存在")

    if not (profile.login_username_enc and profile.login_password_enc):
        raise HTTPException(status_code=400, detail="该配置未保存账号密码，请先编辑配置")

    try:
        username = decrypt_data(profile.login_username_enc)
        password = decrypt_data(profile.login_password_enc)
    except Exception as e:
        log.error(f"账号密码解密失败: {e}", error_stack=str(e))
        raise HTTPException(status_code=500, detail="账号密码解密失败，请重新保存")

    if not username or not password:
        raise HTTPException(status_code=400, detail="账号或密码为空")

    login_url = "https://login.taobao.com"
    browser_manager = get_browser_manager()

    try:
        context = await browser_manager.get_context(profile_id=profile_id, headless=False)
        try:
            page = await context.new_page()
        except Exception:
            await browser_manager.close_context(profile_id)
            context = await browser_manager.get_context(profile_id=profile_id, headless=False)
            page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=20000)

        # 尝试多个常见选择器填充账号密码（淘宝登录页结构多变）
        username_selectors = [
            "#fm-login-id",           # 淘宝账号密码登录经典 ID
            "input[name='fm-login-id']",
            "input[placeholder*='账号']",
            "input[placeholder*='会员名']",
        ]
        password_selectors = [
            "#fm-login-password",
            "input[name='fm-login-password']",
            "input[type='password']",
        ]

        filled_user = False
        for sel in username_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2500, state="visible")
                if el:
                    await el.fill(username)
                    filled_user = True
                    break
            except Exception:
                continue

        filled_pass = False
        for sel in password_selectors:
            try:
                el = await page.wait_for_selector(sel, timeout=2500, state="visible")
                if el:
                    await el.fill(password)
                    filled_pass = True
                    break
            except Exception:
                continue

        # 可选：自动点击登录按钮（滑块/短信需运营在浏览器窗口内手动完成）
        auto_submit = bool(body and body.auto_submit)
        submitted = False
        if auto_submit and filled_user and filled_pass:
            submit_selectors = [
                "button.fm-button.fm-submit",
                "button[type='submit']",
                ".fm-btn > button",
                "button:has-text('登录')",
                "button:has-text('立即登录')",
            ]
            for sel in submit_selectors:
                try:
                    btn = await page.wait_for_selector(sel, timeout=2500, state="visible")
                    if btn:
                        await btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

        log.info(
            "账号密码自动填充完成",
            user_id=admin.id,
            data={
                "profile_id": profile_id,
                "platform": profile.platform,
                "username_filled": filled_user,
                "password_filled": filled_pass,
                "auto_submit_requested": auto_submit,
                "auto_submit_clicked": submitted,
                "operator": admin.username,
            }
        )

        if not filled_user or not filled_pass:
            return OpenVisualBrowserResponse(
                success=True,
                message="浏览器已打开但部分字段未能自动填充（登录页结构可能已变），请在窗口内手动补齐后登录",
                profile_id=profile_id,
                opened_url=login_url,
            )

        if auto_submit and submitted:
            return OpenVisualBrowserResponse(
                success=True,
                message="已自动填充并点击登录。如出现滑块/短信验证，请在浏览器窗口内手动完成，登录成功后点「保存Cookie」",
                profile_id=profile_id,
                opened_url=login_url,
            )

        if auto_submit and not submitted:
            return OpenVisualBrowserResponse(
                success=True,
                message="已自动填充账号密码，但未找到登录按钮（页面结构可能已变）。请在浏览器窗口手动点「登录」",
                profile_id=profile_id,
                opened_url=login_url,
            )

        return OpenVisualBrowserResponse(
            success=True,
            message="已自动填充账号密码。请在浏览器窗口内点击「登录」并完成滑块/短信验证，完成后点「保存Cookie」",
            profile_id=profile_id,
            opened_url=login_url,
        )

    except Exception as e:
        log.error(f"自动登录失败: {e}", error_stack=str(e))
        raise HTTPException(status_code=500, detail=f"自动登录失败: {str(e)}")
