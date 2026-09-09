"""
筱和灵眸(AethelEye) - JWT认证中间件

验证请求中的JWT Token，获取当前用户信息
"""
from typing import Optional, Callable
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.user import User
from app.utils.security import decode_jwt_token, check_token_expired
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# HTTP Bearer认证
security = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    session: Session = Depends(get_db_session)
) -> Optional[User]:
    """
    获取当前登录用户

    从请求头Authorization中提取JWT Token，验证并返回用户对象

    Args:
        request: FastAPI请求对象
        credentials: Bearer认证凭据
        session: 数据库Session

    Returns:
        User对象，未登录返回None

    Raises:
        HTTPException: Token无效或过期
    """
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # 用于 video/img 等资源预览场景（浏览器标签无法自动附带 Authorization header）
        query_token = request.query_params.get("token")
        if query_token:
            token = query_token

    # 未提供Token
    if not token:
        return None

    # Token已过期
    if check_token_expired(token):
        log.warning(f"JWT Token已过期")
        raise HTTPException(
            status_code=401,
            detail="登录已过期，请重新登录"
        )

    # 解析Token
    payload = decode_jwt_token(token)
    if not payload:
        log.warning(f"JWT Token无效")
        raise HTTPException(
            status_code=401,
            detail="登录状态无效，请重新登录"
        )

    # 获取用户ID
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="登录状态无效"
        )

    # 查询用户
    user = session.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=401,
            detail="用户不存在"
        )

    # 用户已禁用
    if not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="账号已被禁用"
        )

    return user


def require_login(
    user: Optional[User] = Depends(get_current_user)
) -> User:
    """
    要求用户已登录

    用于保护需要登录的API路由

    Args:
        user: 当前用户

    Returns:
        User对象

    Raises:
        HTTPException: 用户未登录
    """
    if not user:
        raise HTTPException(
            status_code=401,
            detail="请先登录"
        )
    return user