# -*- coding: utf-8 -*-
"""节点实际进度保存 API：按分组独立保存（互不覆盖）。"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import date, datetime

from ..core import db
from ..core.deps import get_current_user, require_project_access
from ..schemas import SaveNodeProgressRequest
from ..services.business_logic import (
    validate_today_quota, split_node_groups,
)
from ..core.config import GROUP_LABELS, INDEPENDENT_PROCESS_NAMES

router = APIRouter(prefix="/api/projects", tags=["nodes"])


@router.post("/{pid}/nodes/{process_name}/save")
def save_node_progress(pid: int, process_name: str, req: SaveNodeProgressRequest,
                       user: dict = Depends(get_current_user)):
    """按分组保存节点实际进度。

    - 行级隔离：big_area 用户仅可填报本大区项目（非本区返回 404 防探测）；admin 全量；
    - 只写当前分组节点（其他分组数据不被触碰）；
    - group=today/overdue/future：前序工序数量联动校验（累计 ≤ 前序累计实际，防越序），各节点 ≤ 计划数；
    - group=done：已完成分组为「无法编辑」只读模式，后端直接拒绝写操作（不接受减少/修改）；
    - 填报日期：大区账号强制锁定为今日（防历史回填），管理员可按节点指定历史日期。
    - 业务校验一律返回 400 + {code,message} 结构，前端可读友好文案。
    - v6.0 多负责人：req.manager 非空时，只加载/校验/写入该负责人名下的节点，
      各负责人提报相互独立、互不影响；实际写入的 manager 以节点计划行自身的值为准（防跨负责人误写）。
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)

    mgr = (req.manager or "").strip() or None   # 本次填报归属负责人（空=汇总/不区分）

    if req.group not in GROUP_LABELS:
        raise HTTPException(status_code=400, detail={"code": "UNKNOWN_GROUP", "message": f"未知分组：{req.group}"})
    if req.group == "done" and user.get("role") != "admin" and process_name not in INDEPENDENT_PROCESS_NAMES:
        # done 分组对普通用户为「无法编辑」只读模式（前端禁用输入）；admin 可编辑补录。
        # 独立工序（累计完成/累计发运）例外：每次填报都是新增一条「本次记录」而非修改已有"已完成"记录，
        # 所以大区账号也允许在 done 分组写入（前端在「已填报」行允许再填一次）。
        raise HTTPException(status_code=400, detail={"code": "DONE_READONLY", "message": "已完成分组不可编辑（无法填报）"})

    # 多负责人：只取该负责人名下的节点计划（前序联动校验也随之限定在其内部，互不干扰）
    plans = db.get_node_plans(pid, mgr)
    actuals = db.get_node_actuals(pid)
    proc_nodes = [p for p in plans if p["process_name"] == process_name]
    if not proc_nodes:
        tip = f"（负责人：{mgr}）" if mgr else ""
        raise HTTPException(status_code=404, detail=f"工序「{process_name}」无节点{tip}")

    plan_qty_by_id = {p["id"]: int(p["plan_qty"] or 0) for p in proc_nodes}
    # 写入时的负责人以节点计划行自身的值为准（权威来源），避免前端传错导致串档
    plan_manager_by_id = {p["id"]: p.get("manager") for p in proc_nodes}

    is_independent = process_name in INDEPENDENT_PROCESS_NAMES  # 独立工序：不设日期、不限 qty 上限

    today = date.today()
    groups = split_node_groups(proc_nodes, actuals, today)
    target_ids = {p["id"] for p in groups[req.group]}
    if not target_ids:
        raise HTTPException(status_code=400, detail=f"当前分组「{GROUP_LABELS[req.group]}」没有可保存的节点。")

    # 校验：提交的节点必须属于当前分组；数量非负（schema ge=0）且不超过计划数
    input_values = {}
    for v in req.values:
        if v.node_id not in target_ids:
            raise HTTPException(
                status_code=400,
                detail={"code": "NODE_NOT_IN_GROUP", "message": f"节点 {v.node_id} 不属于当前分组 {req.group}"},
            )
        limit = plan_qty_by_id.get(v.node_id, 0)
        if not is_independent and v.qty > limit:
            raise HTTPException(
                status_code=400,
                detail={"code": "QTY_EXCEED_PLAN", "message": f"节点 {v.node_id} 数量不能超过计划数 {limit}"},
            )
        input_values[v.node_id] = v.qty

    # 业务前序联动校验：today / overdue / future 三组都跑（done 仍只读、不可改）
    if req.group in ("today", "overdue", "future"):
        err = validate_today_quota(process_name, plans, actuals, groups[req.group], input_values)
        if err:
            raise HTTPException(
                status_code=400,
                detail={"code": "PREV_PROC_QUOTA_EXCEEDED", "message": err},
            )

    # 写入（只写当前分组，每行独立填报日期；大区账号锁定今日；独立工序按日期 find-or-create）
    saved = 0
    lock_date = user.get("role") == "big_area"
    for v in req.values:
        if is_independent:
            rd = v.report_date or today.strftime("%Y-%m-%d")
            try:
                datetime.strptime(rd, "%Y-%m-%d")
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
            # 「已完成」记录改日期（管理员）：移动该条记录到新日期（后端合并冲突）；
            # 占位行（plan_date IS NULL）或未改日期：按日期 find-or-create（每日一条新行，同日累加到同条）
            plan = next((p for p in proc_nodes if p["id"] == v.node_id), None)
            is_move = (
                plan is not None
                and plan.get("plan_date") is not None
                and rd != str(plan["plan_date"])[:10]
            )
            if is_move:
                if user.get("role") != "admin":
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "DONE_READONLY", "message": "已完成记录的填报日期仅管理员可调整"},
                    )
                # 管理员可能同时改了数量和日期 → 移动时同步新数量（后端合并/移动用新 qty）
                db.move_independent_fill_date(pid, process_name, v.node_id, rd, int(v.qty))
            else:
                db.save_independent_fill(pid, process_name, int(v.qty), rd,
                                         plan_manager_by_id.get(v.node_id))
            saved += 1
        elif lock_date:
            rd = today.strftime("%Y-%m-%d")
            db.upsert_node_actual(pid, v.node_id, process_name, int(v.qty), rd,
                                  plan_manager_by_id.get(v.node_id))
            saved += 1
        else:
            rd = v.report_date or req.report_date or today.strftime("%Y-%m-%d")
            try:
                datetime.strptime(rd, "%Y-%m-%d")
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
            db.upsert_node_actual(pid, v.node_id, process_name, int(v.qty), rd,
                                  plan_manager_by_id.get(v.node_id))
            saved += 1

    return {
        "message": f"✅ 已保存 {saved} 个节点进度（工序：{process_name}，{GROUP_LABELS[req.group]}）",
        "saved": saved,
        "group": req.group,
    }
