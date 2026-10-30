# -*- coding: utf-8 -*-
"""出品排名接口。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import db
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


# ============================================================
# 计划外完成（v7.9）：非本月调度令、人工录入的额外完成套数
# ------------------------------------------------------------
# 口径（用户确认）：month 只影响该月排名/KPI；行的 total_actual = 原实绩 + 该月该负责人 SUM(qty)；
# completion_rate 只加分子不动分母（可 >100%）；排名按含额外后重排。
# 权限：**仅 admin**（大区账号 403）——这是人工兜底录入，不给大区自助改数。
# ============================================================
class ExtraCompletionRequest(BaseModel):
    """新增计划外完成的请求体。

    qty 必须为正整数（``gt=0``）；month 由 ``_valid_month`` 规范化；
    manager / project_name 必填（自由文本，允许不在 projects 表里）。
    """
    month: str = Field(..., description="归属月 YYYY-MM（只影响该月排名/KPI）")
    manager: str = Field(..., min_length=1, max_length=64, description="负责人")
    project_name: str = Field(..., min_length=1, max_length=255, description="项目名称")
    machine_type: str | None = Field(None, max_length=128, description="机型（选填）")
    qty: int = Field(..., gt=0, le=100000, description="额外完成套数（必须 > 0）")


@router.post("/ranking/extra")
def api_add_extra_completion(payload: ExtraCompletionRequest,
                             user: dict = Depends(require_admin)):
    """录入一条「计划外完成」（**仅管理员**，非 admin → 403）。

    - ``qty`` 由 schema 校验（``gt=0``，0/负数 → 422；非整数 → 422）；
    - ``created_by`` 取当前登录用户名；
    - 返回 ``{id, extra_total}``：``extra_total`` = 该月**最新**合计，前端可直接用于 KPI。

    影响面：只叠加到 ``get_production_ranking`` 的该负责人 ``total_actual`` 与 KPI，
    **不改**任何计划行、不改完成率分母、不影响「排产计划总览 / 提报情况总览」。
    """
    month = _valid_month(payload.month)
    mgr = payload.manager.strip()
    # 🔴 数据一致性校验（2026-10）：负责人必须存在于**当月排名行**内。
    #    原因：KPI 的 extra_total = SUM(qty WHERE month=查询月)，若录入的负责人不在排名里，
    #    这笔量会进 KPI 却不会加到任何一行 → 顶部「计划外完成套数」> 各行「+N」之和，看起来像算错。
    #    前端下拉本就只提供排名内负责人，此校验只拦「绕过页面直连 API」的情形。
    #    查询失败时跳过校验（宁可漏校验，也不让录入被误拒）。
    try:
        _ranking = get_production_ranking(month, big_area_person=get_scope_big_area(user),
                                          today=business_today())
        _valid = {str(r.get("manager") or "").strip() for r in (_ranking.get("rows") or [])}
    except Exception:  # noqa: BLE001
        _valid = set()
    if _valid and mgr not in _valid:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "MANAGER_NOT_IN_RANKING",
                "message": f"负责人「{mgr}」在 {month} 没有排名记录，"
                           f"请确认该月是否有该负责人的完成数据，或检查月份是否选错",
            },
        )
    try:
        new_id = db.add_extra_completion(
            month,
            mgr,
            payload.project_name.strip(),
            (payload.machine_type.strip() if payload.machine_type else None),
            int(payload.qty),
            created_by=str(user.get("username") or ""),
        )
    except Exception as exc:  # noqa: BLE001 — 表缺失等部署问题给出明确 503（而非 500）
        raise HTTPException(status_code=503, detail=f"计划外完成写入失败：{exc}")

    return {"id": new_id, "extra_total": db.get_extra_qty_total(month)}


@router.get("/ranking/extra/list")
def api_list_extra_completions(month: str = None, manager: str = None,
                              user: dict = Depends(get_current_user)):
    """当月「计划外完成」明细（详情弹窗用），按录入时间倒序。

    权限：管理员可查任意负责人；大区账号只能查**本大区可见的负责人**
    （口径与排名列表一致：先用 ``get_ranking_manager_rows_by_month`` 取该大区当月负责人集合，
    manager 不在其中 → 403，避免越权读取其它大区的登记数据）。
    ``manager`` 为空时：管理员返回当月全部；大区账号返回其可见负责人的全部。

    Returns:
        dict: ``{items: [{id, manager, project_name, machine_type, qty, created_at}]}``
    """
    month_v = _valid_month(month)
    scope = get_scope_big_area(user)          # admin / 全区哨兵 → None
    mgr = (manager or "").strip() or None

    if scope:
        # 大区可见负责人集合（1 条查询；与排名同一数据源，不会放宽口径）
        visible = {str(r.get("manager") or "").strip()
                   for r in (db.get_ranking_manager_rows_by_month(
                       month_v, scope, business_today().strftime("%Y-%m-%d")) or [])}
        visible.discard("")
        if mgr and mgr not in visible:
            raise HTTPException(status_code=403, detail="无权查看该负责人的计划外完成登记")

    try:
        rows = db.list_extra_completions(month_v, mgr)
    except Exception as exc:  # noqa: BLE001 — 表缺失等部署问题给 503（而非 500）
        raise HTTPException(status_code=503, detail=f"读取计划外完成失败：{exc}")

    if scope and not mgr:
        # 未指定负责人：大区账号只看可见负责人的记录（演示/兜底，正常流程都会带 manager）
        rows = [r for r in rows if str(r.get("manager") or "").strip() in visible]

    items = [{
        "id": r.get("id"),
        "manager": r.get("manager"),
        "project_name": r.get("project_name"),
        "machine_type": r.get("machine_type"),
        "qty": int(r.get("qty") or 0),
        "created_at": (r.get("created_at").strftime("%Y-%m-%d %H:%M")
                       if hasattr(r.get("created_at"), "strftime")
                       else str(r.get("created_at") or "")[:16]),
    } for r in rows]
    return {"items": items}
