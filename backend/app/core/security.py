# -*- coding: utf-8 -*-
"""认证与安全工具：密码哈希（pbkdf2_hmac） + JWT 签发/校验。

- 密码存储格式：``pbkdf2$100000$<salt>$<hex(dk)>``（标准库实现，零第三方依赖）
- JWT：HS256，默认 12 小时有效期（用户已确认）；SECRET_KEY 经 ``JWT_SECRET`` 环境变量覆盖。
"""
import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

logger = logging.getLogger(__name__)

# ---------- 密码哈希参数（与存储串内嵌版本保持一致） ----------
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 100_000

# ---------- JWT 配置 ----------
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 720  # 12 小时（用户已确认）
_DEV_SECRET = "dev-insecure-tower-jwt-secret-change-me"

SECRET_KEY: str = os.environ.get("JWT_SECRET", _DEV_SECRET)
if os.environ.get("JWT_SECRET") is None:
    logger.warning("JWT_SECRET 未设置，使用开发默认密钥（生产环境请通过环境变量配置）")


def hash_password(plain: str) -> str:
    """使用随机 salt + pbkdf2_hmac('sha256', 100_000) 生成密码哈希串。

    Args:
        plain: 明文密码。

    Returns:
        存储格式字符串 ``pbkdf2$100000$<salt>$<hex(dk)>``。
    """
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        str(plain).encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(plain: str, stored: str) -> bool:
    """校验明文密码是否匹配存储串；存储串格式非法时返回 False。

    Args:
        plain: 待校验明文密码。
        stored: 存储串（``pbkdf2$<iterations>$<salt>$<hex(dk)>``）。

    Returns:
        bool: 匹配返回 True，否则 False。
    """
    if not stored or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2":
        return False
    try:
        iterations = int(parts[1])
        salt = parts[2]
        expected_hex = parts[3]
    except (ValueError, IndexError):
        return False
    dk = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        str(plain).encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return hmac.compare_digest(dk.hex(), expected_hex)


def create_access_token(user: dict) -> str:
    """为已认证用户签发 JWT。

    Args:
        user: 用户 dict（须含 id/username/role/big_area_name）。

    Returns:
        str: JWT 字符串。
    """
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user.get("id") or user.get("user_id") or ""),
        "username": user.get("username", ""),
        "role": user.get("role", "big_area"),
        "big_area_name": user.get("big_area_name", "") or "",
        "iat": now,
        "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解码并校验 JWT。

    Args:
        token: JWT 字符串。

    Returns:
        dict: payload。

    Raises:
        jwt.PyJWTError: 签名无效 / 已过期 / 格式非法（由调用方转 401）。
    """
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
