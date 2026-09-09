"""
筱和灵眸(AethelEye) - 权限检查中间件

基于角色的权限控制
- admin: 全部权限
- operator: 任务CRUD、数据查看导出
- viewer: 仅查看数据和报表
"""
from typing import List, Optional
from fastapi import Depends, HTTPException

from app.models.user import User
from app.middleware.auth import require_login


def require_role(allowed_roles: List[str]):
    """
    创建角色检查依赖

    Args:
        allowed_roles: 允许的角色列表

    Returns:
        权限检查函数
    """
    def role_checker(user: User = Depends(require_login)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，需要以下角色之一：{', '.join(allowed_roles)}"
            )
        return user

    return role_checker


# 常用权限检查依赖
require_admin = require_role(["admin"])
require_operator = require_role(["admin", "operator"])
require_viewer = require_role(["admin", "operator", "viewer"])


def can_manage_users(user: User) -> bool:
    """检查是否有用户管理权限（仅管理员）"""
    return user.role == "admin"


def can_create_task(user: User) -> bool:
    """检查是否有创建监控任务权限"""
    return user.role in ("admin", "operator")


def can_delete_task(user: User) -> bool:
    """检查是否有删除监控任务权限"""
    return user.role == "admin"


def can_export_data(user: User) -> bool:
    """检查是否有数据导出权限"""
    return user.role in ("admin", "operator")


def can_view_logs(user: User) -> bool:
    """检查是否有日志查看权限（仅管理员）"""
    return user.role == "admin"


def can_modify_settings(user: User) -> bool:
    """检查是否有修改系统设置权限（仅管理员）"""
    return user.role == "admin"