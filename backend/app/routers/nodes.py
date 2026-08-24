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
from ..core.config import GROUP_LABELS

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
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)

    if req.group not in GROUP_LABELS:
        raise HTTPException(status_code=400, detail={"code": "UNKNOWN_GROUP", "message": f"未知分组：{req.group}"})
    if req.group == "done" and user.get("role") != "admin":
        # done 分组对普通用户为「无法编辑」只读模式（前端禁用输入）；admin 可编辑补录
        raise HTTPException(status_code=400, detail={"code": "DONE_READONLY", "message": "已完成分组不可编辑（无法填报）"})

    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    proc_nodes = [p for p in plans if p["process_name"] == process_name]
    if not proc_nodes:
        raise HTTPException(status_code=404, detail=f"工序「{process_name}」无节点")

    plan_qty_by_id = {p["id"]: int(p["plan_qty"] or 0) for p in proc_nodes}

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
        if v.qty > limit:
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

    # 写入（只写当前分组，每行独立填报日期；大区账号锁定今日）
    saved = 0
    lock_date = user.get("role") == "big_area"
    for v in req.values:
        if lock_date:
            rd = today.strftime("%Y-%m-%d")
        else:
            rd = v.report_date or req.report_date or today.strftime("%Y-%m-%d")
            try:
                datetime.strptime(rd, "%Y-%m-%d")
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
        db.upsert_node_actual(pid, v.node_id, process_name, int(v.qty), rd)
        saved += 1

    return {
        "message": f"✅ 已保存 {saved} 个节点进度（工序：{process_name}，{GROUP_LABELS[req.group]}）",
        "saved": saved,
        "group": req.group,
    }
