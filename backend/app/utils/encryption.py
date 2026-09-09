"""
筱和灵眸(AethelEye) - 加密工具

用于加密存储敏感信息（平台账号密码、代理密码、Cookie数据、LLM API Key）。
底层使用 Fernet 认证加密；密钥由首次启动生成的本地 JWT 密钥派生。
"""
import os
import json
from typing import Optional, Any
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

SECRET_PREFIX = "enc:v1:"

from app.config import settings
from app.utils.logger import get_logger

# 日志
log = get_logger("system")


class EncryptionManager:
    """
    加密管理器

    使用AES-256加密敏感数据
    密钥基于应用配置中的secret_key生成
    """

    def __init__(self):
        """
        初始化加密器

        从应用配置的secret_key生成加密密钥
        """
        # 使用PBKDF2从secret_key派生密钥
        password = settings.jwt_secret_key.encode()
        salt = b"aetheleye_encryption_salt"  # 固定盐值

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )

        key = base64.urlsafe_b64encode(kdf.derive(password))
        self.fernet = Fernet(key)

    def encrypt(self, data: str) -> str:
        """
        加密字符串数据

        Args:
            data: 待加密的字符串

        Returns:
            加密后的字符串（Base64编码）
        """
        if not data:
            return ""
        encrypted = self.fernet.encrypt(data.encode())
        return encrypted.decode()

    def decrypt(self, encrypted_data: str) -> str:
        """
        解密字符串数据

        Args:
            encrypted_data: 加密的字符串（Base64编码）

        Returns:
            解密后的原始字符串
        """
        if not encrypted_data:
            return ""
        try:
            decrypted = self.fernet.decrypt(encrypted_data.encode())
            return decrypted.decode()
        except Exception as e:
            log.error(f"解密失败: {e}", error_stack=str(e))
            return ""

    def encrypt_json(self, data: Any) -> str:
        """
        加密JSON数据

        Args:
            data: 待加密的数据（会转为JSON）

        Returns:
            加密后的字符串
        """
        json_str = json.dumps(data, ensure_ascii=False)
        return self.encrypt(json_str)

    def decrypt_json(self, encrypted_data: str) -> Any:
        """
        解密JSON数据

        Args:
            encrypted_data: 加密的字符串

        Returns:
            解密后的Python对象
        """
        json_str = self.decrypt(encrypted_data)
        if not json_str:
            return {}
        try:
            return json.loads(json_str)
        except Exception as e:
            log.error(f"JSON解析失败: {e}", error_stack=str(e))
            return {}


# 全局加密管理器实例
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """
    获取加密管理器实例

    Returns:
        EncryptionManager实例
    """
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


# 便捷函数
def encrypt_data(data: str) -> str:
    """加密数据"""
    return get_encryption_manager().encrypt(data)


def decrypt_data(encrypted_data: str) -> str:
    """解密数据"""
    return get_encryption_manager().decrypt(encrypted_data)


def encrypt_secret(data: str) -> str:
    """加密秘密值，并添加可识别的版本前缀。"""
    if not data:
        return ""
    return SECRET_PREFIX + encrypt_data(data)


def decrypt_secret(stored_data: str) -> str:
    """解密带版本前缀的秘密值；无前缀值按旧版明文兼容读取。"""
    if not stored_data:
        return ""
    if stored_data.startswith(SECRET_PREFIX):
        return decrypt_data(stored_data[len(SECRET_PREFIX):])
    return stored_data


def is_encrypted_secret(stored_data: str) -> bool:
    """判断数据库值是否使用当前秘密值格式。"""
    return bool(stored_data and stored_data.startswith(SECRET_PREFIX))


def encrypt_json(data: Any) -> str:
    """加密JSON"""
    return get_encryption_manager().encrypt_json(data)


def decrypt_json(encrypted_data: str) -> Any:
    """解密JSON"""
    return get_encryption_manager().decrypt_json(encrypted_data)
