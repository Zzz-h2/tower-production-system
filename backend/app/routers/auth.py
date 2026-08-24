# -*- coding: utf-8 -*-
"""认证 API：登录 / 当前用户 / 登出。

- POST /api/auth/login（公开）：用户名密码登录，签发 JWT。
- GET  /api/auth/me（需登录）：返回当前登录用户信息。
- POST /api/auth/logout（需登录）：JWT 无状态，客户端丢弃 token 即完成登出。
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from ..core.deps import require_login
from ..core.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
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
