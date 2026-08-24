# -*- coding: utf-8 -*-
"""FastAPI 依赖：登录校验、角色校验、大区数据范围推导。

T01 只做认证基础；行级隔离注入（业务路由内调用 require_project_access /
get_scope_big_area 做 scope 过滤）由 T02 完成。
"""
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException

from ..core import db
from ..core.security import decode_access_token


def _unauthorized() -> HTTPException:
    """统一 401：无 header / token 无效 / 过期 / 用户不存在。"""
    return HTTPException(status_code=401, detail="登录已过期，请重新登录")


def get_current_user(authorization: str = Header(None)) -> dict:
    """从 ``Authorization: Bearer <token>`` 解析当前登录用户。

    - 无 header / scheme 非 Bearer / token 无效 / 已过期 → 401
    - 用户不存在 → 401
    - 用户存在但 status != active → 403「账号已停用，请联系管理员」

    Returns:
        dict: users 表记录（含 id/username/role/big_area_name/status）。
    """
    if not authorization:
        raise _unauthorized()
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    try:
        payload = decode_access_token(token.strip())
    except jwt.PyJWTError:
        raise _unauthorized()

    uid = payload.get("sub")
    if not uid:
        raise _unauthorized()
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        raise _unauthorized()

    user = db.get_user_by_id(uid)
    if not user:
        raise _unauthorized()
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="账号已停用，请联系管理员")
    return user


def require_login(user: dict = Depends(get_current_user)) -> dict:
    """登录即可访问（透传用户信息）。"""
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """仅管理员可访问。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权限执行该操作")
    return user


def get_scope_big_area(user: dict = Depends(get_current_user)) -> Optional[str]:
    """推导数据隔离范围：admin → None（全量）；big_area → 大区名。"""
    if user.get("role") == "admin":
        return None
    return user.get("big_area_name")


def require_project_access(project: Optional[dict], user: dict) -> None:
    """校验当前用户对项目的访问权（防探测：无权一律返回 404「项目不存在」）。

    - project 不存在 → 404「项目不存在」
    - admin → 通过
    - big_area 且 project.big_area_person != user.big_area_name → 404「项目不存在」
    - 匹配 → 通过
    """
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if user.get("role") == "admin":
        return
    if str(project.get("big_area_person") or "") != str(user.get("big_area_name") or ""):
        raise HTTPException(status_code=404, detail="项目不存在")
