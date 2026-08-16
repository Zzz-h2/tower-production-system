"""
business_logic.py — 塔筒生产进度管控核心业务逻辑

包含：
- 正向/倒排计划生成
- 进度与状态计算
- 预警等级判定
- 工序状态管理

Author: Senior Developer
Date: 2026-08-03
"""

from datetime import datetime, date, timedelta
from typing import Optional

from .workday_calendar import (
    parse_date, add_workdays, subtract_workdays,
    count_workdays_between, calculate_lag_days,
    is_workday, next_workday
)


# ============================================================
# 工序标准参数（固定常量）
# ============================================================

PROCESS_NAMES: list[str] = [
    "下料", "坡口", "卷板", "纵缝", "组对", "环缝",
    "焊接小件", "门框", "黑塔报检", "打砂", "防腐", "内装"
]

PROCESS_DAYS: list[int] = [
    2, 2, 1, 2, 2, 3, 1, 4, 1, 2, 3, 2
]

TOTAL_DAYS: int = 25  # 标准总工期

assert len(PROCESS_NAMES) == len(PROCESS_DAYS) == 12, "工序参数长度不一致"
assert sum(PROCESS_DAYS) == TOTAL_DAYS, f"工序工期总和应为{TOTAL_DAYS}，实际{sum(PROCESS_DAYS)}"


# ============================================================
# 函数1：正向计划生成
# ============================================================

def generate_forward_plan(
    start_date: date,
    holidays: Optional[list[date]] = None
) -> list[dict]:
    """
    正向生成工序计划 —— 从开工日期顺排计算每道工序的计划开始与结束日期。

    计算逻辑：
    - 工序1从 start_date 当日开始
    - 每道工序按标准工期顺排，自动跳过周末与节假日
    - 前序结束后，下一道工序从次日（或下一个工作日）开始

    Args:
        start_date: 项目计划开工日期
        holidays: 自定义节假日列表，默认 None（仅排除周末）

    Returns:
        list[dict]: 每道工序的计划信息，
            格式: [{"process_order": 1, "process_name": "下料",
                    "plan_start": date, "plan_end": date, "days": 2}, ...]

    Example:
        >>> from datetime import date
        >>> plan = generate_forward_plan(date(2026, 8, 3))
        >>> plan[0]['plan_start']
        date(2026, 8, 3)  # 周一
    """
    from .workday_calendar import set_holidays

    if holidays:
        set_holidays(list(holidays))

    forward_plan = []
    current_start = start_date  # v3.0: 不再校准为工作日

    for i, (name, days) in enumerate(zip(PROCESS_NAMES, PROCESS_DAYS)):
        plan_start = current_start
        # v3.0: 自然日计算 — plan_end = plan_start + (days - 1)
        plan_end = plan_start + timedelta(days=days - 1)

        forward_plan.append({
            "process_order": i + 1,
            "process_name": name,
            "plan_start": plan_start,
            "plan_end": plan_end,
            "days": days,
            "cumulative_days": sum(PROCESS_DAYS[:i + 1])
        })

        # v3.0: 下一道工序从当前结束后第二天开始
        current_start = plan_end + timedelta(days=1)

    return forward_plan


# ============================================================
# 函数2：倒排计划生成
# ============================================================

def generate_backward_plan(
    deadline: date,
    holidays: Optional[list[date]] = None
) -> list[dict]:
    """
    倒排生成工序计划 —— 从交付截止日期倒推计算每道工序的最晚开始与结束日期。

    计算逻辑：
    - 最后一道工序(内装)的最晚结束日期 = deadline
    - 向前倒推每道工序，自动跳过周末与节假日
    - 每道工序的最晚结束 = 下一道工序的最晚开始 - 1个工作日

    Args:
        deadline: 项目最终交付截止日期
        holidays: 自定义节假日列表

    Returns:
        list[dict]: 每道工序的倒排计划（按工序顺序 1→12 排列）

    Example:
        >>> from datetime import date
        >>> plan = generate_backward_plan(date(2026, 9, 15))
        >>> plan[-1]['backward_end']  # 内装最晚完成
        date(2026, 9, 15)
    """
    from .workday_calendar import set_holidays

    if holidays:
        set_holidays(list(holidays))

    backward_plan = []
    current_end = deadline  # v3.0: 不再校准为工作日

    # 从最后一道工序开始倒排
    for i in range(11, -1, -1):
        name = PROCESS_NAMES[i]
        days = PROCESS_DAYS[i]

        backward_end = current_end
        # v3.0: 自然日倒推 — backward_start = backward_end - (days - 1)
        backward_start = backward_end - timedelta(days=days - 1)

        backward_plan.append({
            "process_order": i + 1,
            "process_name": name,
            "backward_start": backward_start,
            "backward_end": backward_end,
            "days": days
        })

        # v3.0: 上一道工序结束日 = 当前工序开始日前一天
        current_end = backward_start - timedelta(days=1)

    backward_plan.reverse()
    return backward_plan


# ============================================================
# 函数3：进度与状态计算
# ============================================================

def calculate_process_status(
    plan_list: list[dict],
    actual_dates: dict,
    current_date: Optional[date] = None
) -> list[dict]:
    """
    计算工序进度状态 —— 综合计划与实际数据，判定每道工序的状态、完成率与滞后天数。

    状态判定规则：
    - not_started: 未填报实际开工时间
    - in_progress: 未填完成时间，今日在计划周期内
    - completed: 已填报实际完成时间（唯一依据，最高优先级）
    - delayed: 未填完成时间，今日超过计划结束

    规则：只要 actual_end 有合法值，状态强制为 completed，不受任何其他条件影响。

    Args:
        plan_list: 计划工序列表（来自 generate_forward_plan 或数据库）
        actual_dates: 实际日期字典，格式：
            {process_order: {"actual_end": date|None}}
        current_date: 当前日期（默认今天）

    Returns:
        list[dict]: 补充了状态信息的工序列表，
            每项增加: status, lag_days, completion_pct, is_overdue
    """
    today = current_date or date.today()

    result = []

    for plan in plan_list:
        order = plan["process_order"]
        name = plan.get("process_name", PROCESS_NAMES[order - 1])

        actual = actual_dates.get(order, {})
        actual_end = actual.get("actual_end")

        # 解析计划日期（兼容 date 对象与字符串）
        plan_start = plan.get("plan_start")
        if isinstance(plan_start, str):
            plan_start = parse_date(plan_start)
        plan_end = plan.get("plan_end")
        if isinstance(plan_end, str):
            plan_end = parse_date(plan_end)

        status = "not_started"
        lag_days = 0
        completion_pct = 0.0

        # === 分支1: 已完成（只要 actual_end 有值即强制完成） ===
        if actual_end is not None:
            status = "completed"
            completion_pct = 100.0
            if plan_end:
                lag_days = (actual_end - plan_end).days
            else:
                lag_days = 0

        # === 分支2: 未完成（按计划时间 vs 今日判定） ===
        elif plan_end and today > plan_end:
            status = "delayed"
            lag_days = (today - plan_end).days
            completion_pct = 0.0

        elif plan_start and today >= plan_start:
            status = "in_progress"
            lag_days = 0
            if plan_end:
                elapsed = count_workdays_between(plan_start, min(today, plan_end))
                total = plan.get("days", PROCESS_DAYS[order - 1])
                completion_pct = min(round(elapsed / total * 100, 1), 99.0) if total > 0 else 0.0

        else:
            status = "not_started"
            lag_days = 0
            completion_pct = 0.0

        plan_entry = {
            **plan,
            "status": status,
            "lag_days": lag_days,
            "completion_pct": completion_pct,
        }
        result.append(plan_entry)

    return result


# ============================================================
# 函数4：预警等级判定
# ============================================================

def judge_warning_level(
    process_status_list: list[dict]
) -> tuple[str, list[dict]]:
    """项目风险等级：基于工序状态实时判定。

    规则：
      - 任一工序 status == 'delayed'（延期）→ delayed
      - 任一工序 status == 'in_progress'（今日在进行/有计划）→ warning
      - 否则 → normal

    Args:
        process_status_list: 工序状态列表（含 process_name/status/plan_start_date/plan_end_date）

    Returns:
        tuple[str, list[dict]]: (风险等级, 预警/延期工序清单)
            - 风险等级: "normal" | "warning" | "delayed"
            - 工序清单: 仅在非 normal 时有内容
    """
    today_s = str(date.today())
    max_level = 0
    alert_processes = []
    for proc in process_status_list:
        status = proc.get("status", "not_started")
        ps = str(proc.get("plan_start_date") or "")[:10]
        pe = str(proc.get("plan_end_date") or "")[:10]
        # 延期：明确 delayed，或计划结束日已过且未完成
        is_delayed = (status == "delayed") or (pe and pe < today_s and status != "completed")
        # 预警：正在进行中（含今日有计划，但未完成）
        is_warning = (status == "in_progress") or (
            ps and pe and ps <= today_s <= pe and status != "completed"
        )
        if is_delayed:
            max_level = max(max_level, 2)
            alert_processes.append({"process_name": proc.get("process_name", ""), "status": "delayed"})
        elif is_warning:
            max_level = max(max_level, 1)
            alert_processes.append({"process_name": proc.get("process_name", ""), "status": "warning"})
    if max_level == 2:
        return "delayed", alert_processes
    elif max_level == 1:
        return "warning", alert_processes
    return "normal", []


# ============================================================
# 函数5：预计交付日期推算
# ============================================================

def estimate_delivery_date(
    process_status_list: list[dict],
    current_date: Optional[date] = None
) -> date:
    """
    基于当前进度推算预计交付日期。

    计算逻辑：
    - 找到当前进行中的工序
    - 从该工序已消耗工期推算剩余工期
    - 顺排计算后续所有工序
    - 返回最后一道工序的预计完成日期

    Args:
        process_status_list: 工序状态列表
        current_date: 当前日期

    Returns:
        date: 预计交付日期
    """
    today = current_date or date.today()

    # 找到第一个未完成（未开始或进行中）的工序
    current_process_idx = None
    for i, proc in enumerate(process_status_list):
        if proc.get("status") not in ("completed",):
            current_process_idx = i
            break

    if current_process_idx is None:
        # 全部完成，返回已完成信息无意义的情况（理论上不应该）
        return today

    # 从进行中的工序开始顺排
    current = today
    for i in range(current_process_idx, len(PROCESS_NAMES)):
        days = PROCESS_DAYS[i]
        current = add_workdays(current, days)

    return current


# ============================================================
# 函数6：里程碑倒排与偏差对比
# ============================================================

def generate_milestone_comparison(
    project_id: int,
    deadline: date,
    process_status_list: list[dict],
    holidays: Optional[list[date]] = None
) -> list[dict]:
    """
    生成里程碑倒排计划并与当前进度对比。

    Args:
        project_id: 项目ID
        deadline: 交付截止日期
        process_status_list: 当前工序状态列表
        holidays: 节假日列表

    Returns:
        list[dict]: 倒排对比列表，
            每项包含: process_order, process_name, backward_start, backward_end,
                     current_status, deviation（偏差描述）
    """
    backward_plan = generate_backward_plan(deadline, holidays)
    today = date.today()

    comparison = []
    for bp, status_entry in zip(backward_plan, process_status_list):
        deviation = "正常"
        current_status = status_entry.get("status", "not_started")
        
        if current_status == "not_started":
            if today > bp["backward_start"]:
                deviation = f"已晚于倒排开始日 {bp['backward_start']}"
        elif current_status == "in_progress":
            if today > bp["backward_end"]:
                deviation = f"已超过倒排完成日 {bp['backward_end']}"

        comparison.append({
            "process_order": bp["process_order"],
            "process_name": bp["process_name"],
            "backward_start": bp["backward_start"],
            "backward_end": bp["backward_end"],
            "current_status": current_status,
            "deviation": deviation,
        })

    return comparison


# ============================================================
# 便捷函数：从数据库记录计算状态
# ============================================================

def refresh_processes_from_db(processes: list[dict]) -> list[dict]:
    """
    从数据库工序记录刷新计算状态与滞后天数。

    核心规则（优先级从高到低）：
    1. completed: actual_end_date 非空 → 强制已完成（唯一依据）
    2. delayed: actual_end 为空 且 今日 > 计划结束
    3. in_progress: actual_end 为空 且 今日 ≥ 计划开始
    4. not_started: actual_end 为空 且 今日 < 计划开始
    """
    today = date.today()
    result = []

    for proc in processes:
        # === Step 0: 统一归一化为 date 或 None ===
        actual_end = parse_date(proc.get("actual_end_date"))
        plan_start = parse_date(proc.get("plan_start_date"))
        plan_end   = parse_date(proc.get("plan_end_date"))

        status = "not_started"
        lag_days = 0

        # === 分支1: 已完成（只要 actual_end 有值即强制完成，无任何附加条件） ===
        if actual_end is not None:
            status = "completed"
            # lag_days 语义: 完成滞后为正、提前为负、准时为0
            if plan_end:
                lag_days = (actual_end - plan_end).days

        # === 分支2: 未完成（actual_end 为空，按计划时间 vs 今日判定） ===
        elif plan_end and today > plan_end:
            status = "delayed"
            lag_days = (today - plan_end).days

        elif plan_start and today >= plan_start:
            status = "in_progress"
            lag_days = 0

        else:
            status = "not_started"
            lag_days = 0

        result.append({
            **proc,
            "status": status,
            "lag_days": lag_days,
        })

    return result


# ============================================================
# v2.0: 日计划拆解 + 双重判定
# ============================================================

def decompose_daily_plan(monthly_total: int, plan_start: date,
                          plan_end: date, standard_days: int,
                          process_total_days: int,
                          process_name: str = '') -> list[dict]:
    """
    将月度总计划按工序工期占比拆解为每日计划基线。
    特殊规则：内装工序总计划量 = monthly_total（最终成品），其余工序按工期占比。
    """
    from .workday_calendar import add_workdays
    import math
    
    # 内装：总计划 = 月度总指标（成品口径）
    if process_name == '内装':
        process_total_qty = max(monthly_total, 0)
    else:
        ratio = standard_days / process_total_days if process_total_days > 0 else 0
        process_total_qty = max(1, round(monthly_total * ratio))

    daily_plan = []
    cumulative = 0
    current = plan_start
    remaining_qty = process_total_qty
    remaining_days = standard_days

    # 向上取整公平分摊：前期多分、末期收尾，避免大面积首日0计划
    for d in range(standard_days):
        day_qty = math.ceil(remaining_qty / remaining_days) if remaining_days > 0 else 0
        remaining_qty -= day_qty
        remaining_days -= 1
        cumulative += day_qty
        daily_plan.append({
            'date': current,
            'plan_qty': day_qty,
            'cumulative_plan': cumulative,
        })
        current = add_workdays(current, 1)
    
    return daily_plan


def calc_cumulative_stats(process_id: int, daily_records: list[dict]) -> dict:
    """
    从日进度记录计算某工序的累计统计。
    
    Returns:
        {total_plan, total_actual, latest_cumulative_plan, latest_cumulative_actual}
    """
    if not daily_records:
        return {'total_plan': 0, 'total_actual': 0,
                'latest_cumulative_plan': 0, 'latest_cumulative_actual': 0}
    
    total_plan = sum(r.get('plan_qty', 0) for r in daily_records)
    total_actual = sum(r.get('actual_qty', 0) for r in daily_records)
    latest = daily_records[-1]
    
    return {
        'total_plan': total_plan,
        'total_actual': total_actual,
        'latest_cumulative_plan': latest.get('cumulative_plan', 0),
        'latest_cumulative_actual': latest.get('cumulative_actual', 0),
    }


def compute_qty_deviation(cumulative_actual: float, cumulative_plan: float) -> tuple[str, str]:
    """计算数量偏差"""
    diff = cumulative_actual - cumulative_plan
    if diff > 0:
        return (f"提前{abs(int(diff))}段", "#38a169")
    elif diff < 0:
        return (f"滞后{abs(int(diff))}段", "#e53e3e")
    return ("持平", "#718096")


# ============================================================
# v4.0: 工序节点计划状态判定（排产矩阵 → 节点管控/预警）
# 排产工序独立于 processes 表 12 道制造工序（见 config.SCHEDULE_PROCESS_NAMES）
# ============================================================

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


def judge_process_node_status(node_statuses: list[dict]) -> dict:
    """
    由一组节点状态聚合出工序级状态：取该工序全部节点 level 最大值对应状态。

    规则：
    - level 最大值对应状态（level 相同时按优先级 overdue > warning > in_progress > done > pending）
    - 空列表 → pending（⚪ 未开始）

    Args:
        node_statuses: judge_node_status 返回值列表

    Returns:
        dict: 所选节点的完整判定结果（含 status/label/level/lag_qty/deviation_*）
    """
    if not node_statuses:
        return {"status": "pending", "label": "⚪ 未开始", "level": 0, "lag_qty": 0,
                "completion_date": None, "deviation_days": 0,
                "deviation_label": "-", "deviation_color": "#718096"}

    max_level = max(s.get("level", 0) for s in node_statuses)
    candidates = [s for s in node_statuses if s.get("level") == max_level]
    if not candidates:
        return {"status": "pending", "label": "⚪ 未开始", "level": 0, "lag_qty": 0,
                "completion_date": None, "deviation_days": 0,
                "deviation_label": "-", "deviation_color": "#718096"}

    # level 相同时按优先级取：overdue > warning > in_progress > done > pending
    for prio in ("overdue", "warning", "in_progress", "done", "pending"):
        for s in candidates:
            if s.get("status") == prio:
                return dict(s)
    return dict(candidates[0])


# ============================================================
# 单元测试
# ============================================================
if __name__ == '__main__':
    from .workday_calendar import set_holidays

    # 清除节假日
    set_holidays([])

    # 测试1: 正向计划生成
    plan = generate_forward_plan(date(2026, 8, 3))  # 周一
    assert len(plan) == 12, f"期望12道工序，实际{len(plan)}"
    assert plan[0]["process_name"] == "下料"
    assert plan[0]["plan_start"] == date(2026, 8, 3), f"下料开始日期望08-03，实际{plan[0]['plan_start']}"
    assert plan[1]["process_name"] == "坡口"
    print("✅ 测试1 通过：正向计划生成")

    # 测试2: 倒排计划生成
    deadline = date(2026, 9, 15)
    bplan = generate_backward_plan(deadline)
    assert len(bplan) == 12
    assert bplan[-1]["backward_end"] == deadline, f"内装最晚完成日应为{deadline}，实际{bplan[-1]['backward_end']}"
    print("✅ 测试2 通过：倒排计划生成")

    # 测试3: 进度状态计算（未到计划开始 → 全部未开始）
    actual_dates = {}
    status_list = calculate_process_status(plan, actual_dates, date(2026, 8, 2))
    assert status_list[0]["status"] == "not_started", f"未到开工日应为未开始，实际{status_list[0]['status']}"
    print("✅ 测试3 通过：全部未开始状态计算")

    # 测试4: 进度状态计算（部分完成）
    actual_dates = {
        1: {"actual_start": date(2026, 8, 3), "actual_end": date(2026, 8, 4)},
        2: {"actual_start": date(2026, 8, 5), "actual_end": None},
    }
    status_list = calculate_process_status(plan, actual_dates, date(2026, 8, 6))
    assert status_list[0]["status"] == "completed", f"下料应已完成，实际{status_list[0]['status']}"
    assert status_list[1]["status"] == "in_progress", f"坡口应进行中，实际{status_list[1]['status']}"
    assert status_list[2]["status"] == "not_started", f"卷板应未开始，实际{status_list[2]['status']}"
    print("✅ 测试4 通过：部分完成状态计算")

    # 测试5: 预警判定（工序进行中 → warning）
    today_s = str(date.today())
    warning_test = [
        {"process_name": "下料", "status": "completed",
         "plan_start_date": str(date.today() - timedelta(days=5)), "plan_end_date": str(date.today() - timedelta(days=1))},
        {"process_name": "坡口", "status": "in_progress",
         "plan_start_date": str(date.today() - timedelta(days=2)), "plan_end_date": str(date.today() + timedelta(days=3))},
    ]
    level, alerts = judge_warning_level(warning_test)
    assert level == "warning", f"应为warning，实际{level}"
    assert len(alerts) == 1
    print("✅ 测试5 通过：预警判定(warning)")

    # 测试6: 延期判定（工序 delayed / 计划结束日已过未完成）
    delay_test = [
        {"process_name": "下料", "status": "delayed",
         "plan_start_date": str(date.today() - timedelta(days=10)), "plan_end_date": str(date.today() - timedelta(days=1))},
    ]
    level, alerts = judge_warning_level(delay_test)
    assert level == "delayed", f"应为delayed，实际{level}"
    print("✅ 测试6 通过：延期判定(delayed)")

    # 测试7: 正常判定（全部 completed）
    normal_test = [
        {"process_name": "下料", "status": "completed",
         "plan_start_date": str(date.today() - timedelta(days=5)), "plan_end_date": str(date.today() - timedelta(days=1))},
        {"process_name": "坡口", "status": "completed",
         "plan_start_date": str(date.today() - timedelta(days=2)), "plan_end_date": str(date.today() + timedelta(days=3))},
    ]
    level, alerts = judge_warning_level(normal_test)
    assert level == "normal"
    assert len(alerts) == 0
    print("✅ 测试7 通过：正常判定(normal)")

    print("\n🎉 全部核心业务逻辑测试通过！")
