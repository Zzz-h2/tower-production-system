# -*- coding: utf-8 -*-
"""认证服务：登录校验 + 内存登录限流。

- 认证：get_user_by_username → verify_password（密码 pbkdf2，标准库实现）
- 限流：内存 dict[(username, client_ip)] -> {fails, lock_until}
  同用户名 + 同 IP 连续失败 5 次锁定 15 分钟；登录成功清零。
"""
import threading
import time
from typing import Optional

from fastapi import HTTPException, Request

from ..core import db
from ..core.security import verify_password

# 大区账号初始密码（导出供 T05 导入联动使用）
DEFAULT_BIG_AREA_PWD = "dq@123456"

# 登录限流参数
MAX_LOGIN_FAILS = 5
LOCK_SECONDS = 15 * 60

# 内存限流表：{(username, client_ip): {"fails": int, "lock_until": float}}
_login_attempts: dict[tuple[str, str], dict] = {}
_login_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    """取客户端 IP（兼容反向代理 X-Forwarded-For）。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_locked(key: tuple[str, str]) -> bool:
    """判断 (username, ip) 是否处于锁定状态；锁已过期则清除记录。"""
    with _login_lock:
        record = _login_attempts.get(key)
        if not record:
            return False
        if record.get("lock_until", 0.0) > time.time():
            return True
        # 仅清理「已过期锁定」记录；未锁定的计数记录（lock_until=0）保留以继续累计
        if record.get("lock_until", 0.0) > 0:
            _login_attempts.pop(key, None)
        return False


def _register_failure(key: tuple[str, str]) -> None:
    """记录一次失败；达到上限则进入锁定（锁定期满后重新计数）。"""
    with _login_lock:
        record = _login_attempts.setdefault(key, {"fails": 0, "lock_until": 0.0})
        record["fails"] += 1
        if record["fails"] >= MAX_LOGIN_FAILS:
            record["lock_until"] = time.time() + LOCK_SECONDS
            record["fails"] = 0


def _reset_success(key: tuple[str, str]) -> None:
    """登录成功后清零失败计数。"""
    with _login_lock:
        _login_attempts.pop(key, None)


def authenticate(username: str, password: str, request: Request) -> Optional[dict]:
    """校验用户名/密码；成功返回 user dict，失败返回 None（统一由路由转 401 防枚举）。

    - 处于锁定期 → 429「尝试次数过多，请 15 分钟后再试」
    - 用户名不存在 / 密码错误 / 账号已停用 → 记失败并返回 None
      （账号停用也返回 None，避免泄露账号状态，与防枚举口径一致）

    Args:
        username: 用户名（大区名或 admin）。
        password: 明文密码。
        request: FastAPI Request（用于取客户端 IP 做限流）。

    Returns:
        Optional[dict]: 认证成功返回 users 表记录，否则 None。
    """
    key = (username, _client_ip(request))
    if _is_locked(key):
        raise HTTPException(status_code=429, detail="尝试次数过多，请 15 分钟后再试")

    user = db.get_user_by_username(username)
    if not user or not verify_password(password, user.get("password_hash") or ""):
        _register_failure(key)
        return None
    if user.get("status") != "active":
        _register_failure(key)
        return None

    _reset_success(key)
    return user
