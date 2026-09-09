"""
筱和灵眸(AethelEye) - 认证服务

用户登录、登出、Token管理
- 登录验证
- 登录失败锁定机制
- Token刷新
"""
from datetime import datetime, timedelta
from typing import Optional, Tuple
from sqlalchemy.orm import Session

from app.models.user import User
from app.utils.security import hash_password, verify_password, create_jwt_token
from app.utils.logger import get_logger
from app.config import settings

# 日志
log = get_logger("audit")


class AuthService:
    """认证服务类"""

    # 登录失败锁定配置
    MAX_LOGIN_FAIL_COUNT = 5  # 最大失败次数
    LOCK_DURATION_MINUTES = 15  # 锁定时长（分钟）

    def __init__(self, session: Session):
        """
        初始化认证服务

        Args:
            session: 数据库Session
        """
        self.session = session

    def login(
        self,
        username: str,
        password: str,
        ip_address: str,
        remember_me: bool = False
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        用户登录

        Args:
            username: 用户名
            password: 密码
            ip_address: 客户端IP地址
            remember_me: 是否启用"记住我"

        Returns:
            (token, error_message)
            - 成功: (token, None)
            - 失败: (None, error_message)
        """
        # 查找用户
        user = self.session.query(User).filter(User.username == username).first()

        # 用户不存在
        if not user:
            log.warning(
                f"登录失败：用户不存在",
                data={"username": username, "ip": ip_address}
            )
            return None, "用户名或密码错误"

        # 用户已禁用
        if not user.is_active:
            log.warning(
                f"登录失败：账号已禁用",
                data={"username": username, "ip": ip_address}
            )
            return None, "账号已被禁用，请联系管理员"

        # 账号被锁定
        if user.is_locked():
            remaining = (user.locked_until - datetime.now()).seconds // 60
            log.warning(
                f"登录失败：账号已锁定",
                data={"username": username, "ip": ip_address, "remaining_minutes": remaining}
            )
            return None, f"账号已被锁定，请{remaining}分钟后重试"

        # 验证密码
        if not verify_password(password, user.password_hash):
            # 记录失败次数
            user.login_fail_count += 1
            log.warning(
                f"登录失败：密码错误",
                data={"username": username, "ip": ip_address, "fail_count": user.login_fail_count}
            )

            # 达到锁定阈值
            if user.login_fail_count >= self.MAX_LOGIN_FAIL_COUNT:
                user.locked_until = datetime.now() + timedelta(minutes=self.LOCK_DURATION_MINUTES)
                self.session.commit()
                log.warning(
                    f"账号已锁定",
                    data={"username": username, "ip": ip_address, "lock_minutes": self.LOCK_DURATION_MINUTES}
                )
                return None, f"密码错误次数过多，账号已被锁定{self.LOCK_DURATION_MINUTES}分钟"

            self.session.commit()
            return None, f"用户名或密码错误，剩余尝试次数：{self.MAX_LOGIN_FAIL_COUNT - user.login_fail_count}"

        # 登录成功
        # 清除失败计数，更新最后登录时间
        user.login_fail_count = 0
        user.locked_until = None
        user.last_login_at = datetime.now()
        self.session.commit()

        # 创建Token
        token = create_jwt_token(user.id, user.username, user.role, remember_me)

        log.info(
            f"用户登录成功",
            data={
                "user_id": user.id,
                "username": user.username,
                "role": user.role,
                "ip": ip_address,
                "remember_me": remember_me,
            }
        )

        return token, None

    def get_user_by_id(self, user_id: int) -> Optional[User]:
        """
        根据ID获取用户

        Args:
            user_id: 用户ID

        Returns:
            User对象，不存在返回None
        """
        return self.session.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        """
        根据用户名获取用户

        Args:
            username: 用户名

        Returns:
            User对象，不存在返回None
        """
        return self.session.query(User).filter(User.username == username).first()

    def create_admin_user(
        self,
        username: str,
        password: str,
        created_by_ip: str
    ) -> User:
        """
        创建管理员账号（首次初始化）

        Args:
            username: 用户名
            password: 明文密码
            created_by_ip: 创建者IP

        Returns:
            新创建的User对象
        """
        hashed_password = hash_password(password)
        user = User(
            username=username,
            password_hash=hashed_password,
            role="admin",
            is_active=True,
        )
        self.session.add(user)
        self.session.commit()

        log.info(
            f"管理员账号已创建",
            data={
                "user_id": user.id,
                "username": user.username,
                "ip": created_by_ip,
            }
        )

        return user

    def change_password(
        self,
        user_id: int,
        old_password: str,
        new_password: str
    ) -> Tuple[bool, Optional[str]]:
        """
        修改密码

        Args:
            user_id: 用户ID
            old_password: 原密码
            new_password: 新密码

        Returns:
            (success, error_message)
        """
        user = self.get_user_by_id(user_id)
        if not user:
            return False, "用户不存在"

        # 验证原密码
        if not verify_password(old_password, user.password_hash):
            return False, "原密码错误"

        # 更新密码
        user.password_hash = hash_password(new_password)
        self.session.commit()

        log.info(
            f"密码已修改",
            data={"user_id": user_id, "username": user.username}
        )

        return True, None