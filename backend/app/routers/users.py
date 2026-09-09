"""
筱和灵眸(AethelEye) - 用户管理API路由

用户CRUD操作（仅管理员）
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models.user import User
from app.services.auth_service import AuthService
from app.middleware.permission import require_admin, can_manage_users
from app.utils.security import hash_password
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

# 路由
router = APIRouter(prefix="/api/users", tags=["用户管理"])


# ===== Pydantic模型 =====

class UserCreateRequest(BaseModel):
    """创建用户请求"""
    username: str
    password: str
    role: str  # admin/operator/viewer


class UserUpdateRequest(BaseModel):
    """更新用户请求"""
    username: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """用户响应"""
    id: int
    username: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]

    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """用户列表响应"""
    total: int
    users: List[UserResponse]


class ResetPasswordRequest(BaseModel):
    """重置密码请求"""
    new_password: str


# ===== API端点 =====

@router.get("", response_model=UserListResponse)
def list_users(
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    获取用户列表（仅管理员）
    """
    users = session.query(User).order_by(User.id).all()
    return UserListResponse(
        total=len(users),
        users=[UserResponse.model_validate(u) for u in users]
    )


@router.post("", response_model=UserResponse)
def create_user(
    request: UserCreateRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    创建用户（仅管理员）
    """
    # 检查用户名是否已存在
    existing = session.query(User).filter(User.username == request.username).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="用户名已存在"
        )

    # 验证角色
    if request.role not in ("admin", "operator", "viewer"):
        raise HTTPException(
            status_code=400,
            detail="角色必须是 admin/operator/viewer"
        )

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

    # 创建用户
    ip_address = http_request.client.host if http_request.client else "unknown"
    hashed_password = hash_password(request.password)
    user = User(
        username=request.username,
        password_hash=hashed_password,
        role=request.role,
        is_active=True,
    )
    session.add(user)
    session.commit()

    log.info(
        f"用户已创建",
        user_id=admin.id,
        data={
            "target_user_id": user.id,
            "username": user.username,
            "role": user.role,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    获取单个用户详情（仅管理员）
    """
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )
    return UserResponse.model_validate(user)


@router.put("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    request: UserUpdateRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    更新用户信息（仅管理员）
    """
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    # 更新字段
    old_values = {}
    if request.username and request.username != user.username:
        # 检查新用户名是否已存在
        existing = session.query(User).filter(User.username == request.username).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="用户名已存在"
            )
        old_values["username"] = user.username
        user.username = request.username

    if request.role and request.role != user.role:
        if request.role not in ("admin", "operator", "viewer"):
            raise HTTPException(
                status_code=400,
                detail="角色必须是 admin/operator/viewer"
            )
        old_values["role"] = user.role
        user.role = request.role

    if request.is_active is not None and request.is_active != user.is_active:
        old_values["is_active"] = user.is_active
        user.is_active = request.is_active

    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"用户信息已更新",
        user_id=admin.id,
        data={
            "target_user_id": user_id,
            "changes": old_values,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return UserResponse.model_validate(user)


@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    删除用户（仅管理员）

    不允许删除自己
    """
    # 不允许删除自己
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="不能删除自己的账号"
        )

    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    session.delete(user)
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"用户已删除",
        user_id=admin.id,
        data={
            "target_user_id": user_id,
            "username": user.username,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "用户已删除"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    request: ResetPasswordRequest,
    http_request: Request,
    session: Session = Depends(get_db_session),
    admin: User = Depends(require_admin)
):
    """
    重置用户密码（仅管理员）
    """
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail="用户不存在"
        )

    # 验证密码长度
    if len(request.new_password) < 6:
        raise HTTPException(
            status_code=400,
            detail="密码长度需至少6字符"
        )

    # 更新密码
    user.password_hash = hash_password(request.new_password)
    user.login_fail_count = 0
    user.locked_until = None
    session.commit()

    ip_address = http_request.client.host if http_request.client else "unknown"
    log.info(
        f"用户密码已重置",
        user_id=admin.id,
        data={
            "target_user_id": user_id,
            "username": user.username,
            "operator": admin.username,
            "ip": ip_address,
        }
    )

    return {"message": "密码已重置"}