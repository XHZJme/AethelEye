"""
筱和灵眸(AethelEye) - 用户模型

用户表结构（users）
- 支持三种角色：admin/operator/viewer
- 密码bcrypt加密存储
- 支持账号启用/禁用
"""
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum
from sqlalchemy.sql import func
from datetime import datetime
import enum

from app.database import Base


class UserRole(enum.Enum):
    """用户角色枚举"""
    ADMIN = "admin"       # 管理员 - 全部权限
    OPERATOR = "operator" # 操作员 - 任务CRUD、数据查看导出
    VIEWER = "viewer"     # 观察者 - 仅查看数据和报表


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="operator")  # admin/operator/viewer
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=func.now())
    last_login_at = Column(DateTime, nullable=True)

    # 登录失败计数（用于锁定机制）
    login_fail_count = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}')>"

    def is_locked(self) -> bool:
        """
        检查账号是否被锁定

        Returns:
            True: 账号已被锁定
            False: 账号未锁定
        """
        if self.locked_until is None:
            return False
        return datetime.now() < self.locked_until

    def is_admin(self) -> bool:
        """检查是否为管理员"""
        return self.role == "admin"

    def can_operate(self) -> bool:
        """检查是否有操作权限（管理员或操作员）"""
        return self.role in ("admin", "operator")