"""
认证工具模块 - 密码哈希和 JWT Token 处理
"""
import os
import hashlib
import hmac
import secrets
import time
import json
import base64
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# JWT 配置
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))  # 默认1小时


def hash_password(password: str) -> str:
    """
    使用 SHA-256 对密码进行哈希
    生产环境建议使用 bcrypt 或 argon2
    """
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256(f"{salt}{password}".encode())
    password_hash = hash_obj.hexdigest()
    return f"{salt}:{password_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    """验证密码是否匹配"""
    try:
        salt, stored_hash = password_hash.split(":")
        hash_obj = hashlib.sha256(f"{salt}{password}".encode())
        return hmac.compare_digest(hash_obj.hexdigest(), stored_hash)
    except (ValueError, AttributeError):
        return False


def _base64url_encode(data: bytes) -> str:
    """Base64 URL 安全编码"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64url_decode(s: str) -> bytes:
    """Base64 URL 安全解码"""
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_access_token(user_id: str, username: str) -> str:
    """
    创建 JWT Token（纯 Python 实现，不依赖 PyJWT）
    """
    # Header
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = _base64url_encode(json.dumps(header).encode())

    # Payload
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS,
    }
    payload_b64 = _base64url_encode(json.dumps(payload).encode())

    # Signature
    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        JWT_SECRET.encode(),
        message.encode(),
        hashlib.sha256
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_access_token(token: str) -> Optional[dict]:
    """
    解码并验证 JWT Token
    :return: payload 字典，验证失败返回 None
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # 验证签名
        message = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            JWT_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        actual_sig = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # 解码 payload
        payload = json.loads(_base64url_decode(payload_b64))

        # 验证过期时间
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload
    except Exception:
        return None


def get_token_expire_time() -> int:
    """获取 Token 过期时间（秒）"""
    return JWT_EXPIRE_SECONDS
