# -*- coding: utf-8 -*-
"""节点实际进度保存 API：按分组独立保存（互不覆盖）。"""
from fastapi import APIRouter, HTTPException
from datetime import date, datetime

from ..core import db
from ..schemas import SaveNodeProgressRequest
from ..services.business_logic import (
    validate_today_quota, split_node_groups,
)
from ..core.config import GROUP_LABELS

router = APIRouter(prefix="/api/projects", tags=["nodes"])


@router.post("/{pid}/nodes/{process_name}/save")
def save_node_progress(pid: int, process_name: str, req: SaveNodeProgressRequest):
    """按分组保存节点实际进度。

    - 只写当前分组节点（其他分组数据不被触碰）；
    - group=today：前序工序数量联动校验（累计 ≤ 前序累计实际）；
    - group=overdue/future：自由填报（qty ≤ plan_qty，前端已限 max）；
    - group=done：已完成只能减少（qty ≤ 当前保存值，前端已限 max）。
    """
    if req.group not in GROUP_LABELS:
        raise HTTPException(status_code=400, detail=f"未知分组：{req.group}")

    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    proc_nodes = [p for p in plans if p["process_name"] == process_name]
    if not proc_nodes:
        raise HTTPException(status_code=404, detail=f"工序「{process_name}」无节点")

    today = date.today()
    groups = split_node_groups(proc_nodes, actuals, today)
    target_ids = {p["id"] for p in groups[req.group]}
    if not target_ids:
        raise HTTPException(status_code=400, detail=f"当前分组「{GROUP_LABELS[req.group]}」没有可保存的节点。")

    # 校验：提交的节点必须属于当前分组；数量非负
    input_values = {}
    for v in req.values:
        if v.node_id not in target_ids:
            raise HTTPException(status_code=400, detail=f"节点 {v.node_id} 不属于当前分组 {req.group}")
        input_values[v.node_id] = v.qty

    # 今日待填报：前序联动校验
    if req.group == "today":
        err = validate_today_quota(process_name, plans, actuals, groups["today"], input_values)
        if err:
            raise HTTPException(status_code=422, detail=err)

    # 填报日期：前端传入则使用，否则回退当天；校验格式
    report_date = req.report_date or today.strftime("%Y-%m-%d")
    if req.report_date:
        try:
            datetime.strptime(req.report_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="report_date 格式必须为 YYYY-MM-DD")

    # 写入（只写当前分组）
    saved = 0
    for p in groups[req.group]:
        qty = int(input_values.get(p["id"], actuals.get(p["id"], {}).get("actual_qty", 0)))
        db.upsert_node_actual(pid, p["id"], process_name, qty, report_date)
        saved += 1

    return {
        "message": f"✅ 已保存 {saved} 个节点进度（工序：{process_name}，{GROUP_LABELS[req.group]}）",
        "saved": saved,
        "group": req.group,
    }
