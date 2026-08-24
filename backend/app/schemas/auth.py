# -*- coding: utf-8 -*-
"""认证相关 Pydantic 模型。"""
from pydantic import BaseModel


class LoginRequest(BaseModel):
    """登录请求体。"""
    username: str
    password: str


class UserOut(BaseModel):
    """用户信息（脱敏，不含密码哈希）。

    label 为前端展示名：大区账号显示大区名，admin 显示用户名。
    """
    id: int
    username: str
    role: str
    big_area_name: str = ""
    label: str = ""

    @classmethod
    def from_user(cls, user: dict) -> "UserOut":
        """由 users 表记录构造输出模型（容忍缺失字段）。"""
        big_area_name = str(user.get("big_area_name") or "")
        username = str(user.get("username") or "")
        label = big_area_name or username
        return cls(
            id=int(user.get("id") or user.get("user_id") or 0),
            username=username,
            role=str(user.get("role") or "big_area"),
            big_area_name=big_area_name,
            label=label,
        )


class LoginResponse(BaseModel):
    """登录成功响应。"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut
