"""
认证工具模块 - 密码哈希和 JWT Token 处理
纯 Python 实现，不依赖 PyJWT 库
- 密码哈希: SHA-256 + 随机盐（格式: salt:hash）
- JWT Token: HS256 签名，标准三段式 header.payload.signature
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

# ==================== JWT 配置 ====================
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")  # 签名密钥（生产环境必须更换）
JWT_ALGORITHM = "HS256"  # 签名算法
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", "3600"))  # Token 有效期，默认 1 小时


# ==================== 密码哈希 ====================

def hash_password(password: str) -> str:
    """
    密码哈希（SHA-256 + 随机盐）
    1. 生成 16 字节随机盐（hex 编码，32 字符）
    2. 拼接盐和密码，计算 SHA-256
    3. 返回格式: {salt}:{hash}
    """
    salt = secrets.token_hex(16)
    hash_obj = hashlib.sha256(f"{salt}{password}".encode())
    password_hash = hash_obj.hexdigest()
    return f"{salt}:{password_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    """
    验证密码是否匹配
    1. 从存储的哈希中提取盐
    2. 用相同盐 + 输入密码计算 SHA-256
    3. 使用 hmac.compare_digest 防止时序攻击
    """
    try:
        salt, stored_hash = password_hash.split(":")
        hash_obj = hashlib.sha256(f"{salt}{password}".encode())
        return hmac.compare_digest(hash_obj.hexdigest(), stored_hash)
    except (ValueError, AttributeError):
        return False


# ==================== Base64 URL 编解码 ====================

def _base64url_encode(data: bytes) -> str:
    """Base64 URL 安全编码（去除填充 = 号）"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _base64url_decode(s: str) -> bytes:
    """Base64 URL 安全解码（补齐填充 = 号）"""
    padding = 4 - len(s) % 4
    s += "=" * padding
    return base64.urlsafe_b64decode(s)


# ==================== JWT Token ====================

def create_access_token(user_id: str, username: str) -> str:
    """
    创建 JWT Token（纯 Python 实现）
    1. 构造 Header（算法 + 类型）
    2. 构造 Payload（用户ID + 用户名 + 签发时间 + 过期时间）
    3. 使用 HMAC-SHA256 对 header.payload 签名
    4. 返回 base64url(header).base64url(payload).base64url(signature)
    """
    # 1. Header
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = _base64url_encode(json.dumps(header).encode())

    # 2. Payload
    now = int(time.time())
    payload = {
        "sub": user_id,        # 用户 ID（subject）
        "username": username,  # 用户名
        "iat": now,            # 签发时间（issued at）
        "exp": now + JWT_EXPIRE_SECONDS,  # 过期时间（expiration）
    }
    payload_b64 = _base64url_encode(json.dumps(payload).encode())

    # 3. Signature（HMAC-SHA256 签名）
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
    1. 拆分三段式 Token
    2. 重新计算签名并与传入签名比对（防篡改）
    3. 解码 Payload 并验证过期时间
    :return: payload 字典，验证失败返回 None
    """
    try:
        # 1. 拆分 Token
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        # 2. 验证签名（重新计算并与传入签名比对）
        message = f"{header_b64}.{payload_b64}"
        expected_sig = hmac.new(
            JWT_SECRET.encode(),
            message.encode(),
            hashlib.sha256
        ).digest()
        actual_sig = _base64url_decode(signature_b64)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # 3. 解码 Payload
        payload = json.loads(_base64url_decode(payload_b64))

        # 4. 验证过期时间
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload
    except Exception:
        return None


def get_token_expire_time() -> int:
    """获取 Token 过期时间（秒），供响应体返回 expires_in 字段使用"""
    return JWT_EXPIRE_SECONDS
