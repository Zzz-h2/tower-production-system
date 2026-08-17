# -*- coding: utf-8 -*-
"""里程碑倒排：从交付截止日倒推 9 道排产工序的最晚开始/完成时间，并对比当前状态给出偏差。

数据源：node_plans + node_actuals（经 build_overview 实时计算的工序卡片状态），
与新版进度/预警口径一致；不再使用旧 processes 表。
标准工期为可配置常量，若与实际排产不符可直接调整。
"""
from datetime import date, timedelta

from ..core import db
from ..services.node_service import build_overview

# 9 道排产工序及其标准自然日工期（与排产 Excel 顺序一致，可按实际调整）
MILESTONE_PROCESSES = [
    ("钢板到货", 1), ("法兰到货", 1), ("下料", 2), ("卷制", 3),
    ("组对", 2), ("黑塔", 2), ("防腐", 2), ("附件安装", 3), ("具备验收", 1),
]


def _effective_durations(custom_durations: dict | None) -> dict:
    """合并自定义工期：未配置的工序回退默认工期。"""
    custom = custom_durations or {}
    return {name: custom.get(name, days) for name, days in MILESTONE_PROCESSES}


def generate_backward_plan(deadline: date, custom_durations: dict | None = None) -> list[dict]:
    """从交付截止日倒推每道工序的最晚开始/完成日（自然日，不跳周末）。

    custom_durations: 按工序名覆盖标准工期（dict[str, int]）；未覆盖的用默认值。
    """
    eff = _effective_durations(custom_durations)
    plan = []
    current_end = deadline
    # 从最后一道工序倒推
    for i in range(len(MILESTONE_PROCESSES) - 1, -1, -1):
        name, _ = MILESTONE_PROCESSES[i]
        days = eff[name]
        b_end = current_end
        b_start = b_end - timedelta(days=days - 1)
        plan.append({
            "process_order": i + 1,
            "process_name": name,
            "backward_start": b_start,
            "backward_end": b_end,
            "days": days,
        })
        current_end = b_start - timedelta(days=1)
    plan.reverse()
    return plan


def estimate_delivery_date(status_list: list[str], custom_durations: dict | None = None) -> date:
    """从第一个未完成工序起顺排（自定义/默认工期），推算预计交付日。"""
    eff = _effective_durations(custom_durations)
    today = date.today()
    idx = next((i for i, s in enumerate(status_list)
               if s not in ("done", "done_early")), None)
    if idx is None:
        return today  # 全部完成 → 已交付
    current = today
    for i in range(idx, len(MILESTONE_PROCESSES)):
        current = current + timedelta(days=eff[MILESTONE_PROCESSES[i][0]])
    return current


def build_milestone_backward(pid: int, deadline: date, custom_durations: dict | None = None) -> dict:
    """组装里程碑倒排结果：倒排计划 + 偏差分析 + 预计交付。"""
    backward = generate_backward_plan(deadline, custom_durations)
    today = date.today()

    # 当前工序状态（来自 node_plans + node_actuals 实时计算）
    try:
        plans = db.get_node_plans(pid)
        actuals = db.get_node_actuals(pid)
        ov = build_overview(pid, plans, actuals)
        status_map = {p["process_name"]: p["status"] for p in ov.get("processes", [])}
    except Exception:
        status_map = {}
    has_plan = bool(status_map)

    rows = []
    for bp in backward:
        st = status_map.get(bp["process_name"], "pending")
        deviation = "正常"
        dev_level = "normal"   # normal / warning / danger，供前端配色
        if st in ("done", "done_early"):
            deviation = "已完成（超前/达标）"
            dev_level = "normal"
        elif st == "overdue":
            deviation = "已逾期，超过倒排完成日"
            dev_level = "danger"
        elif st == "in_progress":
            if today > bp["backward_end"]:
                deviation = f"已超过倒排完成日 {bp['backward_end']}"
                dev_level = "danger"
            else:
                deviation = "进行中，未超期"
                dev_level = "warning"
        else:  # pending / 未开始
            if today > bp["backward_start"]:
                deviation = f"已晚于倒排开始日 {bp['backward_start']}"
                dev_level = "warning"
            else:
                deviation = "未开始，尚在窗口内"
                dev_level = "normal"
        rows.append({**bp, "current_status": st, "deviation": deviation, "dev_level": dev_level})

    status_seq = [r["current_status"] for r in rows]
    estimated = estimate_delivery_date(status_seq, custom_durations)
    lag_days = (estimated - deadline).days

    return {
        "deadline": str(deadline),
        "rows": rows,
        "estimated_delivery": str(estimated),
        "lag_days": lag_days,
        "has_plan": has_plan,
        "summary": (
            f"按当前进度推算预计交付 {estimated}，"
            + (f"较截止日延迟 {lag_days} 天" if lag_days > 0 else "可在截止日前完成")
        ),
    }
