# -*- coding: utf-8 -*-
"""业务逻辑服务：状态机 / 前序联动 / 分组独立保存。

行为 1:1 复用原 utils/business_logic.py（同一份实现，零迁移偏差）。
"""
from datetime import date
from typing import Optional

from ..core.config import SCHEDULE_PROCESS_NAMES


# ---------- 状态机（1:1 迁移 utils/business_logic.judge_node_status） ----------

def judge_node_status(plan_date, plan_qty, actual_qty, today, completion_date=None) -> dict:
    """判定单个工序节点计划状态（五态 + 完成日期偏差）。

    关键语义（不可改）：
    - done 分支内部按日期区分：未来日期完成 → label "🟢 提前完成"；否则 "已完成"。
    - future 分支：actual_qty > 0 → "🔵 提前进行中" level=2；否则 "⚪ 未开始"。
    - overdue / warning / in_progress / pending 判定与原版一致。
    - 偏差：completion_date 非空用 plan vs completion；为空用 plan vs 今天。
    """
    from utils.business_logic import judge_node_status as _fn
    return _fn(plan_date, plan_qty, actual_qty, today, completion_date)


def judge_process_node_status(node_statuses: list[dict]) -> dict:
    """汇总工序级状态（与 utils.business_logic.judge_process_node_status 一致）。"""
    from utils.business_logic import judge_process_node_status as _fn
    return _fn(node_statuses)


def judge_warning_level(processes: list[dict]) -> tuple:
    """风险等级判定（normal/warning/delayed），与 utils 一致。"""
    from utils.business_logic import judge_warning_level as _fn
    return _fn(processes)


# ---------- 前序工序数量联动 ----------

def prev_process_total(process_name: str, plans_all: list[dict], actuals: dict) -> Optional[int]:
    """某工序之前所有工序的累计实际完成数（前序联动上限）。

    process_name 为第一道工序 → 返回 None（不限制）。
    """
    proc_idx = SCHEDULE_PROCESS_NAMES.index(process_name) if process_name in SCHEDULE_PROCESS_NAMES else -1
    if proc_idx <= 0:
        return None
    prev_procs = set(SCHEDULE_PROCESS_NAMES[:proc_idx])
    return sum(
        actuals.get(pn["id"], {}).get("actual_qty", 0)
        for pn in plans_all if pn["process_name"] in prev_procs
    )


def judge_process_card_status(proc_nodes: list[dict], actuals: dict, today=None) -> dict:
    """工序卡片状态：主状态(总进度) + 附加标签(时间维度偏差)。

    主状态（总进度）：
    - done_early 提前完成: 总实际 ≥ 总计划 且 所有 plan_date > today
    - done        已完成:   总实际 ≥ 总计划
    - overdue     已逾期:   存在 plan_date < today 且 actual < plan（严格历史逾期，不含今天）
    - in_progress 进行中:   0 < 总实际 < 总计划 且无历史逾期
    - pending     未开始:   总实际 == 0 且无历史逾期

    附加标签 tags：
    - 部分完成: 存在 plan_date ≤ today 且 0 < actual < plan（含历史逾期部分完成）
    - 已提前:   存在 plan_date > today 且 actual ≥ plan，且该工序无历史逾期
    - 当主状态为「已逾期」或 tags 含「部分完成」时，不再显示「已提前」
    """
    today = today or date.today()
    today_s = str(today)[:10]
    if not proc_nodes:
        return {"status": "pending", "label": "⚪ 未开始", "tags": []}

    total_plan = sum(int(n["plan_qty"] or 0) for n in proc_nodes)
    total_actual = sum(
        int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0) for n in proc_nodes
    )

    # 严格历史逾期：plan_date < today 且未完成（不含今天）
    overdue_nodes = [
        n for n in proc_nodes
        if str(n["plan_date"])[:10] < today_s
        and int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        < int(n["plan_qty"] or 0)
    ]
    has_overdue = bool(overdue_nodes)

    # 部分完成节点：截至今天(含)已有进度但未达到计划数量
    partial_nodes = [
        n for n in proc_nodes
        if str(n["plan_date"])[:10] <= today_s
        and 0 < int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        < int(n["plan_qty"] or 0)
    ]
    has_partial = bool(partial_nodes)

    # 提前完成节点：未来日期且已完成
    early_nodes = [
        n for n in proc_nodes
        if str(n["plan_date"])[:10] > today_s
        and int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        >= int(n["plan_qty"] or 0)
    ]
    has_early = bool(early_nodes)

    # 附加标签：有逾期时只补充"部分完成"，不显示"已提前"
    tags = []
    if has_overdue:
        if has_partial:
            tags.append("部分完成")
    else:
        if has_early:
            tags.append("已提前")

    # 主状态
    if total_actual >= total_plan:
        if min(str(n["plan_date"])[:10] for n in proc_nodes) > today_s:
            return {"status": "done_early", "label": "🟢 提前完成", "tags": tags}
        return {"status": "done", "label": "🟢 已完成", "tags": tags}
    if has_overdue:
        return {"status": "overdue", "label": "🔴 已逾期", "tags": tags}
    if total_actual > 0:
        return {"status": "in_progress", "label": "🔵 进行中", "tags": tags}
    return {"status": "pending", "label": "⚪ 未开始", "tags": tags}


def _group_nodes(proc_nodes: list[dict], actuals: dict, today) -> dict:
    """按 今日/逾期/未来/已完成 严格互斥分组（与原版口径一致）。"""
    today_nodes, overdue_nodes, future_nodes, done_nodes = [], [], [], []
    for p in proc_nodes:
        act = actuals.get(p["id"], {}).get("actual_qty", 0)
        if act >= p["plan_qty"]:
            done_nodes.append(p)
        elif str(p["plan_date"])[:10] == str(today)[:10]:
            today_nodes.append(p)
        elif str(p["plan_date"])[:10] < str(today)[:10]:
            overdue_nodes.append(p)
        else:
            future_nodes.append(p)
    return {
        "today": today_nodes,
        "overdue": overdue_nodes,
        "future": future_nodes,
        "done": done_nodes,
    }


def split_node_groups(proc_nodes: list[dict], actuals: dict, today=None) -> dict:
    """对外：按四组切分节点（前端填报弹窗四分组手风琴数据源）。"""
    today = today or date.today()
    return _group_nodes(proc_nodes, actuals, today)


def validate_today_quota(process_name: str, plans_all: list[dict], actuals: dict,
                         today_nodes: list[dict], input_values: dict) -> Optional[str]:
    """今日待填报前序联动校验。

    input_values: {node_id: qty}
    超限返回错误文案；通过返回 None。
    """
    prev_total = prev_process_total(process_name, plans_all, actuals)
    if prev_total is None:
        return None
    today_total = sum(
        int(input_values.get(p["id"], input_values.get(str(p["id"]), 0)) or 0)
        for p in today_nodes
    )
    if today_total > prev_total:
        return (
            f"保存失败：{process_name} 今日待填报累计 {today_total} 套"
            f"不能超过前序工序 {prev_total} 套。"
        )
    return None
