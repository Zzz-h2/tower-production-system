# -*- coding: utf-8 -*-
"""认证 API：登录 / 当前用户 / 登出。

- POST /api/auth/login（公开）：用户名密码登录，签发 JWT。
- GET  /api/auth/me（需登录）：返回当前登录用户信息。
- POST /api/auth/logout（需登录）：JWT 无状态，客户端丢弃 token 即完成登出。
"""
import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from ..core import config
from ..core.deps import get_current_user, require_login
from ..core.security import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    create_access_token,
    decode_access_token,
    refresh_access_token,
)
from ..schemas.auth import LoginRequest, LoginResponse, UserOut
from ..services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request):
    """用户名密码登录。

    - 用户名或密码缺失 → 400「请输入用户名和密码」
    - 用户名或密码错误 → 401「用户名或密码错误」（防枚举）
    - 连续失败 5 次（同用户名 + 同 IP）→ 429 锁定 15 分钟
    """
    username = (payload.username or "").strip()
    password = payload.password or ""
    if not username or not password:
        raise HTTPException(status_code=400, detail="请输入用户名和密码")

    user = auth_service.authenticate(username, password, request)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    token = create_access_token(user)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.from_user(user),
    )


@router.get("/me")
def me(user: dict = Depends(require_login)):
    """返回当前登录用户信息。"""
    return {"user": UserOut.from_user(user)}


@router.post("/logout")
def logout(user: dict = Depends(require_login)):
    """登出（JWT 无状态，前端丢弃 token 即完成登出）。"""
    return {"message": "已退出"}


@router.post("/touch")
def touch_session(authorization: str = Header(None), user: dict = Depends(get_current_user)):
    """会话续期：用户仍活跃时刷新 JWT 的 iat，使空闲计时重新开始。

    前端在空闲等待期间定期调用。若会话已因空闲失效，``get_current_user`` 会直接抛
    401（detail.code = IDLE_TIMEOUT），不会走到函数体。

    Returns:
        dict: ``{"access_token": 新 token, "token_type": "bearer", "expires_in": 空闲阈值秒数}``
    """
    # get_current_user 只返回 user dict（不含 payload），此处重新取 header 解出原 payload 用于重签
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    try:
        payload = decode_access_token(token.strip())
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    new_token = refresh_access_token(payload)
    # 空闲校验未启用（阈值 <= 0）时退回 token 绝对有效期，避免返回 0 导致前端误判已过期
    idle_minutes = config.IDLE_TIMEOUT_MINUTES
    expires_in = idle_minutes * 60 if idle_minutes > 0 else ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return {
        "access_token": new_token,
        "token_type": "bearer",
        "expires_in": expires_in,
    }
