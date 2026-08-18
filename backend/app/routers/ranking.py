# -*- coding: utf-8 -*-
"""出品排名接口。"""
from datetime import date

from fastapi import APIRouter, HTTPException

from ..services.ranking_service import get_production_ranking, get_production_ranking_detail

router = APIRouter(prefix="/api", tags=["ranking"])


def _valid_month(month: str) -> str:
    """校验并规范化月份（YYYY-MM）；缺省用当前自然月。"""
    if not month:
        return date.today().strftime("%Y-%m")
    try:
        y, m = map(int, month.split("-"))
        assert 2000 <= y <= 2100 and 1 <= m <= 12
    except Exception:
        raise HTTPException(status_code=400, detail="month 格式应为 YYYY-MM")
    return f"{y:04d}-{m:02d}"


@router.get("/ranking/production")
def api_production_ranking(month: str = None):
    """出品排名：按交付负责人聚合当月『附件安装』出品并排名。"""
    return get_production_ranking(_valid_month(month))


@router.get("/ranking/production/detail")
def api_production_ranking_detail(month: str = None, person: str = None):
    """某负责人当月逾期/提前项目清单。"""
    if not person or not str(person).strip():
        raise HTTPException(status_code=400, detail="缺少 person 参数")
    return get_production_ranking_detail(_valid_month(month), str(person).strip())
