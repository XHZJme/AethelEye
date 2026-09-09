"""
筱和灵眸(AethelEye) - 认证API路由

登录、登出、获取当前用户信息、首次初始化管理员账号
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session, check_admin_exists
from app.models.user import User
from app.services.auth_service import AuthService
from app.middleware.auth import get_current_user, require_login
from app.middleware.permission import require_admin
from app.utils.security import create_jwt_token
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/auth", tags=["认证"])


# ===== Pydantic模型 =====

class LoginRequest(BaseModel):
    """登录请求"""
    username: str
    password: str
    remember_me: bool = False


class LoginResponse(BaseModel):
    """登录响应"""
    token: str
    user_id: int
    username: str
    role: str


class UserInfoResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: Optional[datetime]


class InitAdminRequest(BaseModel):
    """首次初始化管理员请求"""
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    old_password: str
    new_password: str


class InitStatusResponse(BaseModel):
    """初始化状态响应"""
    need_init: bool
    message: str


# ===== API端点 =====

@router.get("/init-status", response_model=InitStatusResponse)
def get_init_status():
    """
    获取系统初始化状态

    检查是否存在管理员账号，用于首次使用时的初始化流程
    """
    admin_exists = check_admin_exists()
    if admin_exists:
        return InitStatusResponse(
            need_init=False,
            message="系统已初始化，请使用账号登录"
        )
    else:
        return InitStatusResponse(
            need_init=True,
            message="系统未初始化，请先创建管理员账号"
        )


@router.post("/init-admin", response_model=LoginResponse)
def init_admin(
    request: InitAdminRequest,
    http_request: Request,
    session: Session = Depends(get_db_session)
):
    """
    首次初始化管理员账号

    仅在系统未初始化时可用
    """
    # 检查是否已初始化
    if check_admin_exists():
        raise HTTPException(
            status_code=400,
            detail="系统已初始化，无法重复创建管理员"
        )

    # 获取客户端IP
    ip_address = http_request.client.host if http_request.client else "unknown"

    # 验证用户名长度
    if len(request.username) < 3 or len(request.username) > 50:
        raise HTTPException(
            status_code=400,
            detail="用户名长度需在3-50字符之间"
        )

    # 验证密码长度
    if len(request.password) < 6:
        raise HTTPException(
            status_code=400,
            detail="密码长度需至少6字符"
        )

    # 创建管理员
    auth_service = AuthService(session)
    user = auth_service.create_admin_user(
        username=request.username,
        password=request.password,
        created_by_ip=ip_address
    )

    # 自动登录
    token = create_jwt_token(user.id, user.username, user.role, False)

    return LoginResponse(
        token=token,
        user_id=user.id,
        username=user.username,
        role=user.role
    )


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    http_request: Request,
    session: Session = Depends(get_db_session)
):
    """
    用户登录

    验证账号密码，返回JWT Token
    """
    # 获取客户端IP
    ip_address = http_request.client.host if http_request.client else "unknown"

    # 登录验证
    auth_service = AuthService(session)
    token, error = auth_service.login(
        username=request.username,
        password=request.password,
        ip_address=ip_address,
        remember_me=request.remember_me
    )

    if error:
        raise HTTPException(
            status_code=401,
            detail=error
        )

    # 获取用户信息
    user = auth_service.get_user_by_id(
        auth_service.get_user_by_username(request.username).id
        if auth_service.get_user_by_username(request.username) else 0
    )

    # 重新查询获取最新状态
    user = session.query(User).filter(User.username == request.username).first()

    return LoginResponse(
        token=token,
        user_id=user.id,
        username=user.username,
        role=user.role
    )


@router.get("/me", response_model=UserInfoResponse)
def get_current_user_info(
    user: User = Depends(require_login)
):
    """
    获取当前登录用户信息
    """
    return UserInfoResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        last_login_at=user.last_login_at
    )


@router.post("/logout")
def logout(
    user: User = Depends(require_login),
    http_request: Request = None
):
    """
    用户登出

    记录登出日志（JWT Token由前端清除）
    """
    ip_address = http_request.client.host if http_request and http_request.client else "unknown"

    log.info(
        f"用户登出",
        user_id=user.id,
        data={
            "operator": user.username,
            "ip": ip_address,
        }
    )

    return {"message": "登出成功"}


@router.post("/change-password")
def change_password(
    request: ChangePasswordRequest,
    user: User = Depends(require_login),
    session: Session = Depends(get_db_session)
):
    """
    修改密码
    """
    auth_service = AuthService(session)
    success, error = auth_service.change_password(
        user_id=user.id,
        old_password=request.old_password,
        new_password=request.new_password
    )

    if error:
        raise HTTPException(
            status_code=400,
            detail=error
        )

    return {"message": "密码修改成功"}