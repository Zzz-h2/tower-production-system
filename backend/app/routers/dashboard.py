# -*- coding: utf-8 -*-
"""看板统计 API（项目总览页指标卡数据来源）。"""
from fastapi import APIRouter

from ..core import db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def dashboard_stats(month: str = None):
    """看板指标：在产总数 / 预警数 / 延期数 / 本月计划总量 / 正常数。

    薄封装 db.get_dashboard_stats()，直接返回其 dict。month 为调度令月份（created_at 年月）。
    """
    return db.get_dashboard_stats(month=month)
