# -*- coding: utf-8 -*-
"""出品排名接口。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.deps import get_current_user, get_scope_big_area, require_admin
from ..core.timeutil import business_today
from ..services.ranking_service import (
    OVERRIDE_ACTIONS,
    get_production_ranking,
    get_production_ranking_detail,
    get_submission_board,
    save_submission_board_overrides,
)

router = APIRouter(prefix="/api", tags=["ranking"])


def _valid_month(month: str) -> str:
    """校验并规范化月份（YYYY-MM）；缺省用当前自然月。"""
    if not month:
        return business_today().strftime("%Y-%m")
    try:
        y, m = map(int, month.split("-"))
        assert 2000 <= y <= 2100 and 1 <= m <= 12
    except Exception:
        raise HTTPException(status_code=400, detail="month 格式应为 YYYY-MM")
    return f"{y:04d}-{m:02d}"


@router.get("/ranking/production")
def api_production_ranking(month: str = None, user: dict = Depends(get_current_user)):
    """出品排名：按交付负责人聚合当月『附件安装』出品并排名。

    行级隔离：big_area 用户仅统计本大区项目；admin 全量。

    v7.8：每行附加 ``today_increment``（今日新增完成套数，仅供前端「累计完成套数 ↑」
    提示）+ ``today``（业务日）。业务日由 Python 侧 ``business_today()`` 显式传入，
    走 SQL 参数绑定而**不用 CURDATE()**，避免数据库时区与业务时区不一致。
    完成率等既有口径（累计完成 ÷ 累计计划）一律不变。
    """
    return get_production_ranking(
        _valid_month(month),
        big_area_person=get_scope_big_area(user),
        today=business_today(),
    )


@router.get("/ranking/production/detail")
def api_production_ranking_detail(month: str = None, person: str = None,
                                  user: dict = Depends(get_current_user)):
    """某负责人当月逾期/提前项目清单。行级隔离：big_area 用户仅本大区；admin 全量。"""
    if not person or not str(person).strip():
        raise HTTPException(status_code=400, detail="缺少 person 参数")
    return get_production_ranking_detail(
        _valid_month(month), str(person).strip(), big_area_person=get_scope_big_area(user)
    )


@router.get("/ranking/submission-board")
def api_submission_board(month: str = None, user: dict = Depends(get_current_user)):
    """提报情况总览：当月自然日 × 负责人矩阵，标记「当天有计划但完全未提报」（×）。

    只读接口，不写任何表。

    口径：
    - 日期 = 筛选月份的自然月 1 日～月末（真实天数）
    - 负责人 = 该月存在排产计划行的负责人，按拼音升序
    - × = 当天有计划（plan_date=当天 且 plan_qty>0）且当天既无填报也无异常，且该日 ≤ 昨天
    - 今天与未来一律留空
    - v7.7：管理员可人工覆盖个别日期（见 POST …/overrides）；cell.override 为生效的人工覆盖，
      cell.auto_missed 为原始自动判定，cell.missed 为**最终值**（人工覆盖优先）。

    行级隔离：big_area 用户仅统计本大区项目；admin 全量。
    """
    return get_submission_board(_valid_month(month), big_area_person=get_scope_big_area(user))


# ============================================================
# 提报情况总览 · 人工覆盖（v7.7，仅管理员）
# ============================================================

class SubmissionOverrideItem(BaseModel):
    """单格改动。"""

    manager: str = Field(default="", description="负责人（与排产 manager 同口径）")
    date: str = Field(default="", description="被改动的日期 YYYY-MM-DD（须落在 month 内）")
    action: str = Field(default="", description="missed=强制未按时 / on_time=强制准时 / auto=恢复自动判定")


class SubmissionOverridesRequest(BaseModel):
    """批量保存请求体。"""

    month: str = Field(default="", description="月份 YYYY-MM；空 = 当前自然月")
    items: list[SubmissionOverrideItem] = Field(default_factory=list, description="改动清单")


@router.post("/ranking/submission-board/overrides")
def api_save_submission_overrides(payload: SubmissionOverridesRequest,
                                  user: dict = Depends(require_admin)):
    """批量保存「提报情况总览」的人工覆盖标记（**仅管理员**，非 admin → 403）。

    语义（覆盖记录，**不是翻转**）：
      - ``action='missed'``  → 该格强制 ×（即使当天有填报/异常）
      - ``action='on_time'`` → 该格强制留空（即使自动判定漏报）
      - ``action='auto'``    → 删除覆盖行，恢复自动判定（可逆）
    同一 (manager, date) 唯一（``uk_mgr_date``），重复提交只更新不新增行（幂等）。

    校验：date 格式 / 是否落在该月 / manager 非空 / action 合法 → 400；
    以及可编辑范围（当天有计划 且 已过判定截止日）→ 400，整批不落库。

    返回：``{'saved': N, 'upserted': N, 'deleted': N, 'board': <最新矩阵>}``
    board 与 GET 完全同构，前端保存后可直接用它刷新（省一次往返）。
    """
    month = _valid_month(payload.month)
    items = [
        {"manager": it.manager, "date": it.date, "action": it.action}
        for it in (payload.items or [])
    ]
    for it in items:
        # 提前给出更精确的 action 提示（服务层同样会校验，这里只为文案更早命中）
        if it["action"].strip() not in OVERRIDE_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"action 只能为 missed / on_time / auto（收到 {it['action']!r}）",
            )
    try:
        result = save_submission_board_overrides(
            month, items, updated_by=str(user.get("username") or "")
        )
    except ValueError as exc:
        # 参数非法 / 超出可编辑范围 → 400（不是 500，也不是 403）
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        # 目标库未执行 v7.7 DDL（表不存在）→ 503，并给出明确的部署指引
        raise HTTPException(status_code=503, detail=str(exc))

    board = get_submission_board(month, big_area_person=get_scope_big_area(user))
    return {
        "saved": result["saved"],
        "upserted": result["upserted"],
        "deleted": result["deleted"],
        "board": board,
    }
