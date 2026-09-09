"""
筱和灵眸(AethelEye) - 安全工具

密码加密和JWT Token管理
- bcrypt密码哈希
- JWT生成/验证
- Token过期管理
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import bcrypt
import jwt

from app.config import settings
from app.utils.logger import get_logger

# 日志
log = get_logger("audit")

def hash_password(password: str) -> str:
    """
    使用bcrypt加密密码

    Args:
        password: 明文密码

    Returns:
        加密后的密码哈希
    """
    # bcrypt限制密码长度为72字节，需要截断
    password_bytes = password.encode('utf-8')[:72]
    hashed = bcrypt.hashpw(
        password_bytes,
        bcrypt.gensalt(rounds=settings.bcrypt_rounds),
    )
    return hashed.decode("ascii")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码

    Args:
        plain_password: 明文密码
        hashed_password: 密码哈希

    Returns:
        True: 密码正确
        False: 密码错误
    """
    password_bytes = plain_password.encode("utf-8")[:72]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("ascii"))
    except (TypeError, ValueError, UnicodeError):
        return False


def create_jwt_token(
    user_id: int,
    username: str,
    role: str,
    remember_me: bool = False
) -> str:
    """
    创建JWT Token

    Args:
        user_id: 用户ID
        username: 用户名
        role: 用户角色
        remember_me: 是否启用"记住我"（延长有效期）

    Returns:
        JWT Token字符串
    """
    # 计算过期时间
    if remember_me:
        expire_days = settings.jwt_remember_me_days
    else:
        expire_minutes = settings.jwt_expire_minutes
        expire_days = expire_minutes / (60 * 24)

    expire = datetime.utcnow() + timedelta(days=expire_days)

    # Token内容
    payload = {
        "sub": str(user_id),  # subject - 用户ID
        "username": username,
        "role": role,
        "exp": expire,  # expiration time
        "iat": datetime.utcnow(),  # issued at
    }

    token = jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm
    )

    log.info(
        "JWT Token已创建",
        data={
            "user_id": user_id,
            "username": username,
            "remember_me": remember_me,
            "expire_days": expire_days,
        }
    )

    return token


def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """
    解析JWT Token

    Args:
        token: JWT Token字符串

    Returns:
        Token内容字典，解析失败返回None
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.PyJWTError as e:
        log.warning(f"JWT Token解析失败: {e}", error_stack=str(e))
        return None


def get_user_id_from_token(token: str) -> Optional[int]:
    """
    从Token中获取用户ID

    Args:
        token: JWT Token字符串

    Returns:
        用户ID，解析失败返回None
    """
    payload = decode_jwt_token(token)
    if payload:
        try:
            return int(payload.get("sub"))
        except (TypeError, ValueError):
            return None
    return None


def check_token_expired(token: str) -> bool:
    """
    检查Token是否已过期

    Args:
        token: JWT Token字符串

    Returns:
        True: Token已过期
        False: Token有效
    """
    payload = decode_jwt_token(token)
    if not payload:
        return True

    exp = payload.get("exp")
    if not exp:
        return True

    return datetime.utcnow() > datetime.utcfromtimestamp(exp)
