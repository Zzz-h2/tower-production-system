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
from ..core.config import SCHEDULE_PROCESS_NAMES, INDEPENDENT_PROCESS_NAMES


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


def compute_real_overdue(rows: list[dict], monthly_plan: int) -> list[dict]:
    """计算「真逾期」节点列表（逾期判定规则变更后口径）。

    真逾期 = 节点状态为 overdue **且** 该节点所属工序的累计完成套数 < 调度令本月计划数。
    即：某工序已完成/到达套数已达调度令计划时，其后续超产套数的逾期不再算作「延期」。

    ⚠️ 边界（用户 2026-09-01 选定方案 B）：
    monthly_plan <= 0（项目无调度令计划数据）时**回退原有逻辑**——所有 overdue 节点都算真逾期。
    原因：没有月计划阈值就无法判断什么是"超产"，若返回空集会漏报真实延期。
    此处与 judge_process_card_status 的 monthly_plan<=0 分支保持一致（卡片仍显示"已逾期"），
    保证项目级风险等级与工序卡片状态不打架。

    Args:
        rows: enrich_rows() 产出的节点行列表（每行含 process_name / actual_qty / status）
        monthly_plan: 调度令本月计划数（projects.monthly_plan）；
                      <=0 表示无调度令计划 → 回退原有逻辑，返回全部 overdue 节点

    Returns:
        list[dict]: 真逾期节点行（可能为空列表）
    """
    all_overdue = [r for r in rows if r["status"] == "overdue"]
    if monthly_plan <= 0:
        # 无调度令计划 → 无法判定"超产"，回退原有逻辑（避免漏报延期）
        return all_overdue
    proc_actual: dict[str, int] = {}
    for r in rows:
        proc_actual[r["process_name"]] = proc_actual.get(r["process_name"], 0) + int(r["actual_qty"] or 0)
    return [
        r for r in all_overdue
        if proc_actual.get(r["process_name"], 0) < monthly_plan
    ]


def judge_process_card_status(proc_nodes: list[dict], actuals: dict, today=None, monthly_plan: int = 0) -> dict:
    """工序卡片状态：主状态(总进度) + 附加标签(时间维度偏差)。

    主状态（总进度）：
    - done_early 提前完成: 总实际 ≥ 总计划 且 所有 plan_date > today
    - done        已完成:   总实际 ≥ 总计划
    - matches_dispatch 符合调度令进度: 存在历史逾期但总实际 >= 调度令本月计划（monthly_plan>0）
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

    # 逾期判定规则：本月计划达成后，超产套数的逾期不再显示「延期」
    if has_overdue and monthly_plan > 0 and total_actual >= monthly_plan:
        return {"status": "matches_dispatch", "label": "✅ 符合调度令进度", "tags": []}

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
    """按 今日/逾期/未来/已完成 严格互斥分组（与原版口径一致）。

    独立工序（累计完成/累计发运）特殊口径：
      - plan_date IS NULL → today（合同占位行，可继续填）
      - plan_date IS NOT NULL → done（每次填报生成的"本次记录"行，date 即填报日期）
      - 不再走 act >= plan_qty 判定（独立工序每行 plan_qty = 本次填报量，actual = plan，已自洽）
    """
    today_nodes, overdue_nodes, future_nodes, done_nodes = [], [], [], []
    for p in proc_nodes:
        act = actuals.get(p["id"], {}).get("actual_qty", 0)
        is_independent = p.get("process_name") in INDEPENDENT_PROCESS_NAMES
        if p.get("plan_date") is None and is_independent:
            # 独立工序的合同占位行：始终留在「今日待填报」供继续填报
            today_nodes.append(p)
        elif p.get("plan_date") is not None and is_independent:
            # 独立工序的填报记录行：按日期归档到「已完成」
            done_nodes.append(p)
        elif act >= p["plan_qty"]:
            done_nodes.append(p)
        elif p.get("plan_date") is None:
            # 非独立工序且 plan_date 为 NULL（理论上不应出现，兜底）
            today_nodes.append(p)
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


def validate_today_quota_nodes(process_name: str, plans_all: list[dict], actuals: dict,
                               target_nodes: list[dict], input_values: dict) -> dict:
    """节点级前序联动校验（部分成功模式核心）：返回 ``{node_id: 错误文案}``，全部合规返回 ``{}``。

    规则与 validate_today_quota 完全一致（见其 docstring），区别仅在于：
    逐节点独立判定、失败不中断，供一键提报「部分成功」使用。
    """
    errors: dict = {}
    proc_idx = SCHEDULE_PROCESS_NAMES.index(process_name) if process_name in SCHEDULE_PROCESS_NAMES else -1
    # 独立工序（累计完成总数/累计发运总数）：不参与 11 道前序联动校验，直接放行
    if process_name in INDEPENDENT_PROCESS_NAMES:
        return errors
    if proc_idx < 0:
        msg = (
            f"【配置缺失】工序「{process_name}」未在排产顺序配置（SCHEDULE_PROCESS_NAMES）中，"
            f"无法执行前序联动校验。请联系管理员在 backend/app/core/config.py 中补齐该工序名后重新部署。"
        )
        return {p["id"]: msg for p in target_nodes}
    # 钢板到货(0)、法兰到货(1)：原材料到货，无数量限制
    if proc_idx <= 1:
        return errors

    steel_name = SCHEDULE_PROCESS_NAMES[0]  # 钢板到货（下料的数量主约束）
    is_cutting = (process_name == "下料")   # 下料前置硬编码为钢板到货

    def _total_after(upto_pd: str) -> int:
        """本工序截至 upto_pd 的累计实际（口径：本批提交值覆盖同节点既有值，非叠加）。

        本批已被拒（errors）的节点不会写入，不计入累计——按 plan_date 升序逐条判定时，
        当前条只承受「存量 + 先行通过条目」的额度占用。
        """
        t = 0
        for pl in plans_all:
            if pl["process_name"] != process_name:
                continue
            if str(pl["plan_date"])[:10] > upto_pd:
                continue
            nid = pl["id"]
            if nid in errors:   # 已拒条目不会落库
                continue
            if nid in input_values:
                t += int(input_values.get(nid, input_values.get(str(nid), 0)) or 0)
            else:
                t += int(actuals.get(nid, {}).get("actual_qty", 0) or 0)
        return t

    for p in sorted(target_nodes, key=lambda x: str(x["plan_date"])[:10]):
        target_pd = str(p["plan_date"])[:10]
        qty = int(input_values.get(p["id"], input_values.get(str(p["id"]), 0)) or 0)
        if qty <= 0:
            continue

        # === 硬卡 1：下料→钢板到货；其他→紧邻前序 ===
        prev_proc_name = steel_name if is_cutting else SCHEDULE_PROCESS_NAMES[proc_idx - 1]
        prev_started = any(
            int(actuals.get(pl["id"], {}).get("actual_qty", 0) or 0) > 0
            and pl["process_name"] == prev_proc_name
            and str(pl["plan_date"])[:10] <= target_pd
            for pl in plans_all
        )
        if not prev_started:
            errors[p["id"]] = (
                f"【前一工序未开始】{process_name} 节点 {target_pd} 拟填报 {qty} 套，"
                f"但前置工序「{prev_proc_name}」截至 {target_pd} 尚未开始实际进度，"
                f"前序累计实际仅 0 套。请先完成「{prev_proc_name}」的进度填报后再来提交。"
            )
            continue

        # === 硬卡 2（累计口径）：填报后「本工序截至 target_pd 的累计」不得超过「前序截至 target_pd 的累计实际」。
        # 旧口径只比单条 qty ≤ 前序累计，一批多条逐条判 1≤1 全过、合计却超额（pid=60 防腐 3>黑塔 1 即此漏洞）。
        if is_cutting:
            # 下料专属：钢板到货「全部完成」则放行多填（满足提前到货实际）
            steel_total = sum(
                int(actuals.get(pl["id"], {}).get("actual_qty", 0) or 0)
                for pl in plans_all
                if pl["process_name"] == steel_name
                and str(pl["plan_date"])[:10] <= target_pd
            )
            steel_plan_total = sum(
                int(pl.get("plan_qty", 0) or 0)
                for pl in plans_all
                if pl["process_name"] == steel_name
                and str(pl["plan_date"])[:10] <= target_pd
            )
            total_after = _total_after(target_pd)
            if steel_total < steel_plan_total and total_after > steel_total:
                errors[p["id"]] = (
                    f"【数量校验未通过】{process_name} 节点 {target_pd} 拟填报 {qty} 套，"
                    f"填报后本工序截至 {target_pd} 累计将达 {total_after} 套，"
                    f"但截至 {target_pd} 钢板到货累计实际仅 {steel_total} 套"
                    f"（计划 {steel_plan_total} 套尚未全部到货）。"
                    f"请先完成钢板到货的进度填报后再来提交。"
                )
            # 钢板到货全部完成 → 放行多填
        else:
            # 卷制及之后：仅卡「紧邻前一工序」实际累计
            prev_total = sum(
                int(actuals.get(pl["id"], {}).get("actual_qty", 0) or 0)
                for pl in plans_all
                if pl["process_name"] == prev_proc_name
                and str(pl["plan_date"])[:10] <= target_pd
            )
            total_after = _total_after(target_pd)
            if total_after > prev_total:
                errors[p["id"]] = (
                    f"【数量校验未通过】{process_name} 节点 {target_pd} 拟填报 {qty} 套，"
                    f"填报后本工序截至 {target_pd} 累计将达 {total_after} 套，"
                    f"但截至 {target_pd} 前一工序「{prev_proc_name}」累计实际仅 {prev_total} 套。"
                    f"请先完成「{prev_proc_name}」的进度填报后再来提交。"
                )
    return errors


def validate_today_quota(process_name: str, plans_all: list[dict], actuals: dict,
                         target_nodes: list[dict], input_values: dict) -> Optional[str]:
    """填报前序联动校验（手动逐条保存路径：整批硬卡，任一节点失败即整批拒绝）。

    部分成功模式（一键提报）请改用 validate_today_quota_nodes。
    """
    errors = validate_today_quota_nodes(
        process_name, plans_all, actuals, target_nodes, input_values,
    )
    if errors:
        return next(iter(errors.values()))
    return None