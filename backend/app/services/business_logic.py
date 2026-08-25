"""
business_logic.py — 塔筒生产进度管控核心业务逻辑（v4.0 节点/工序状态判定）

FastAPI 运行路径实际在用的函数（保留）：
- judge_node_status：节点五态判定（done/pending/in_progress/warning/overdue）
- judge_process_card_status：工序卡片双维度状态（总进度 + 时间维度标签）
- split_node_groups / _group_nodes：今日/逾期/未来/已完成 四组互斥切分
- validate_today_quota / prev_process_total：今日待填报前序联动校验

已清理的历史遗留死代码：Streamlit 版 正向/倒排计划（12 道制造工序）、
工序进度计算、预警判定、预计交付、里程碑对比、日计划拆解等不再被引用的函数。
"""
from datetime import date
from typing import Optional

from .workday_calendar import parse_date
from ..core.config import SCHEDULE_PROCESS_NAMES


def prev_process_total(process_name: str, plans_all: list[dict], actuals: dict,
                       before_date: Optional[str] = None) -> Optional[int]:
    """某工序之前所有工序的累计实际完成数（前序联动上限）。

    process_name 为第一道工序 → 返回 None（不限制）。
    before_date: 传入时仅累加 ``plan_date <= before_date`` 的节点——按目标节点的 plan_date
    收口，避免"很后期前序节点已有实际"令 future 组误放行；None 时保持全量（today 组兼容）。
    """
    proc_idx = SCHEDULE_PROCESS_NAMES.index(process_name) if process_name in SCHEDULE_PROCESS_NAMES else -1
    if proc_idx <= 0:
        return None
    prev_procs = set(SCHEDULE_PROCESS_NAMES[:proc_idx])
    total = 0
    for pn in plans_all:
        if pn["process_name"] not in prev_procs:
            continue
        if before_date and str(pn["plan_date"])[:10] > str(before_date)[:10]:
            continue
        total += int(actuals.get(pn["id"], {}).get("actual_qty", 0) or 0)
    return total


def judge_node_status(plan_date, plan_qty, actual_qty, today, completion_date=None):
    """
    判定单个工序节点计划状态（五态 + 完成日期偏差）。

    规则（按此顺序）：
    - done:        actual_qty >= plan_qty              → 🟢 已完成
    - pending:     plan_date > today                   → ⚪ 未开始
    - in_progress: plan_date == today                  → 🔵 进行中（当日不再显示逾期）
    - warning:     plan_date < today 且 actual_qty > 0 → 🟡 部分完成
    - overdue:     plan_date < today 且 actual_qty == 0 → 🔴 逾期未完成

    Args:
        plan_date: 计划完成日期（str 'YYYY-MM-DD' 或 date 对象，内部统一 parse_date）
        plan_qty:  应完成套数（整数）
        actual_qty: 实际完成套数（整数）
        today:     当前日期（date 对象或 str，内部统一 parse_date）
        completion_date: 实际完成日期（date/str/None；有值时用于计算偏差）

    Returns:
        dict: {"status", "label", "level", "lag_qty",
               "completion_date", "deviation_days", "deviation_label", "deviation_color"}
            - status: done | pending | in_progress | warning | overdue
            - level:  overdue=4 > warning=3 > in_progress=2 > pending=0 = done=0
            - lag_qty: 部分完成=plan-actual；逾期=plan；其余 0
            - deviation_label: 提前X天 / 准时 / 延期X天 / 还有X天 / 进行中 / 逾期X天
            - deviation_color: 提前/准时/进行中 #38a169；未到 #718096；warning #d69e2e；overdue #e53e3e
    """
    # 统一解析日期（str / date / datetime / Timestamp 均兼容）
    parsed_plan = parse_date(plan_date)
    if parsed_plan is None and plan_date is not None:
        parsed_plan = plan_date

    if today is None:
        today = date.today()
    parsed_today = parse_date(today) or today

    plan_qty = int(plan_qty or 0)
    actual_qty = int(actual_qty or 0)
    parsed_comp = parse_date(completion_date) if completion_date is not None else None

    # ---- 状态判定（按用户指定顺序）----
    if actual_qty >= plan_qty:
        # done 保持最高优先级；未来日期完成 → 「提前完成」语义
        if parsed_plan is not None and parsed_today < parsed_plan:
            status, label, level, lag = "done", "🟢 提前完成", 0, 0
        else:
            status, label, level, lag = "done", "🟢 已完成", 0, 0
    elif parsed_plan is not None and parsed_today < parsed_plan:
        # 未来计划节点：支持提前进行中语义
        if actual_qty > 0:
            status, label, level, lag = "in_progress", "🔵 提前进行中", 2, 0
        else:
            status, label, level, lag = "pending", "⚪ 未开始", 0, 0
    elif parsed_plan is not None and parsed_today == parsed_plan:
        status, label, level, lag = "in_progress", "🔵 进行中", 2, 0
    elif actual_qty > 0:
        status, label, level, lag = "warning", "🟡 部分完成", 3, plan_qty - actual_qty
    else:
        status, label, level, lag = "overdue", "🔴 逾期未完成", 4, plan_qty

    # ---- 偏差计算 ----
    if parsed_comp is not None and parsed_plan is not None:
        delta = (parsed_comp - parsed_plan).days
        if delta < 0:
            dev_days, dev_label, dev_color = -delta, f"提前{-delta}天", "#38a169"
        elif delta > 0:
            dev_days, dev_label, dev_color = delta, f"延期{delta}天", "#e53e3e"
        else:
            dev_days, dev_label, dev_color = 0, "准时", "#38a169"
    elif parsed_plan is not None:
        if parsed_today < parsed_plan:
            d = (parsed_plan - parsed_today).days
            dev_days, dev_label, dev_color = d, f"还有{d}天", "#718096"
        elif parsed_today == parsed_plan:
            dev_days, dev_label, dev_color = 0, "进行中", "#38a169"
        else:
            d = (parsed_today - parsed_plan).days
            dev_days, dev_label, dev_color = d, f"逾期{d}天", "#e53e3e"
    else:
        dev_days, dev_label, dev_color = 0, "-", "#718096"

    return {
        "status": status, "label": label, "level": level, "lag_qty": lag,
        "completion_date": parsed_comp if status == "done" else None,
        "deviation_days": dev_days,
        "deviation_label": dev_label,
        "deviation_color": dev_color,
    }


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
                         target_nodes: list[dict], input_values: dict) -> Optional[str]:
    """填报前序联动校验（适用于 today/overdue/future 三组，节点级硬卡）。

    规则：
      - 钢板到货(0)、法兰到货(1)：原材料到货工序，不设任何数量/前序限制。
      - 下料(2) 及之后：紧邻前序必须已开工（硬卡 1）；可填报量 ≤ 钢板到货 实际累计（硬卡 2）。

    节点级逐一校验（per-node）。错误文案统一保留「累计实际仅 M 套」句式，
    供前端 parseQuotaMsg 解析成「拟报 N 套 / 前序仅 M 套」的旧版量化格式。
    """
    proc_idx = SCHEDULE_PROCESS_NAMES.index(process_name) if process_name in SCHEDULE_PROCESS_NAMES else -1
    if proc_idx < 0:
        return (
            f"【配置缺失】工序「{process_name}」未在排产顺序配置（SCHEDULE_PROCESS_NAMES）中，"
            f"无法执行前序联动校验。请联系管理员在 backend/app/core/config.py 中补齐该工序名后重新部署。"
        )
    # 钢板到货(0)、法兰到货(1)：原材料到货，无数量限制
    if proc_idx <= 1:
        return None

    prev_proc_name = SCHEDULE_PROCESS_NAMES[proc_idx - 1]  # 紧邻的前一工序
    steel_name = SCHEDULE_PROCESS_NAMES[0]                 # 钢板到货（下游数量主约束）

    for p in target_nodes:
        target_pd = str(p["plan_date"])[:10]
        qty = int(input_values.get(p["id"], input_values.get(str(p["id"]), 0)) or 0)
        if qty <= 0:
            continue

        # 硬卡 1：紧邻的前一工序必须已「开始」（截至 target_pd 至少一个节点 actual_qty>0）
        prev_started = any(
            int(actuals.get(pl["id"], {}).get("actual_qty", 0) or 0) > 0
            and pl["process_name"] == prev_proc_name
            and str(pl["plan_date"])[:10] <= target_pd
            for pl in plans_all
        )
        if not prev_started:
            return (
                f"【前一工序未开始】{process_name} 节点 {target_pd} 拟填报 {qty} 套，"
                f"但紧邻的前一工序「{prev_proc_name}」截至 {target_pd} 尚未开始实际进度，"
                f"前序累计实际仅 0 套。请先完成「{prev_proc_name}」的进度填报后再来提交。"
            )

        # 硬卡 2：可填报量 ≤ 钢板到货 实际累计（截至 target_pd）
        steel_total = sum(
            int(actuals.get(pl["id"], {}).get("actual_qty", 0) or 0)
            for pl in plans_all
            if pl["process_name"] == steel_name
            and str(pl["plan_date"])[:10] <= target_pd
        )
        if qty > steel_total:
            return (
                f"【数量校验未通过】{process_name} 节点 {target_pd} 拟填报 {qty} 套，"
                f"但截至 {target_pd} 钢板到货累计实际仅 {steel_total} 套。"
                f"请先完成钢板到货的进度填报后再来提交。"
            )
    return None