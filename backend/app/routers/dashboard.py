# -*- coding: utf-8 -*-
"""看板统计 API（项目总览页指标卡数据来源）。"""
from fastapi import APIRouter, Depends

from ..core import db
from ..core.deps import get_current_user, get_scope_big_area

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def dashboard_stats(month: str = None, user: dict = Depends(get_current_user)):
    """看板指标：在产总数 / 预警数 / 延期数 / 本月计划总量 / 正常数。

    薄封装 db.get_dashboard_stats()，直接返回其 dict。month 为调度令月份（created_at 年月）。
    行级隔离：big_area 用户 KPI 收敛本大区；admin 全量。
    """
    return db.get_dashboard_stats(month=month, big_area_person=get_scope_big_area(user))
