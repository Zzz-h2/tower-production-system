# -*- coding: utf-8 -*-
"""节点计划聚合服务：把原始行富化为前端所需的「时间轴 / 工序卡片 / 分组」数据。"""
from datetime import date, timedelta
from typing import Optional

from .business_logic import (judge_node_status, judge_process_card_status, split_node_groups,
                             compute_real_overdue, build_time_rules)
from ..core.config import SCHEDULE_PROCESS_NAMES, INDEPENDENT_PROCESS_NAMES


def enrich_rows(plans: list[dict], actuals: dict, today=None, durations: Optional[dict] = None,
                rules: Optional[dict] = None) -> list[dict]:
    """富化节点行：计划信息 + 实际完成 + 五态判定（含完成日期与偏差）。

    返回行结构与原 Streamlit 版 rows 一致（前端时间轴/卡片直接使用）。
    独立工序（累计完成总数/累计发运总数）：无日期语义，仅按 actual vs plan 输出
    done / in_progress，不走日期判定，避免被误判逾期/预警。
    工序时间规则升级（durations 非空时）：制造链工序按「实际下料闸门 + 重算日期」判定；
    durations 为 None / 缺该行时长 → 回退原规则（存量项目行为不变）。
    ⚠️ rules 可由调用方预计算传入——**闸门锚点需要全项目的计划行**（找「下料」行），
    若 plans 已被过滤成单道工序，必须传全量行算出的 rules，否则全部误判为待下料。
    """
    today = today or date.today()
    if rules is None:
        rules = build_time_rules(plans, actuals, durations)
    rows = []
    for r in plans:
        nid = r["id"]
        act = actuals.get(nid, {})
        actual_qty = act.get("actual_qty", 0)
        completion_date = act.get("report_date") if actual_qty >= r["plan_qty"] else None
        ru = rules.get(nid) or {}
        if r["process_name"] in INDEPENDENT_PROCESS_NAMES:
            done = actual_qty >= r["plan_qty"]
            st = {
                "status": "done" if done else "in_progress",
                "label": "🟢 已完成" if done else "🔵 进行中",
                "level": 0, "lag_qty": 0, "completion_date": completion_date,
                "deviation_days": 0, "deviation_label": "-", "deviation_color": "#718096",
                "count_as_overdue": False,
            }
        else:
            st = judge_node_status(
                r["plan_date"], r["plan_qty"], actual_qty, today, completion_date,
                eff_plan_date=ru.get("eff_plan_date"),
                waiting_material=bool(ru.get("waiting_material")),
                count_as_overdue=ru.get("count_as_overdue", True),
            )
        rows.append({
            "id": nid,
            "project_id": r["project_id"],
            "process_name": r["process_name"],
            # 闸门开（已实际下料）的制造链工序：对外展示/分组的计划日期 = 重算后的 effective 日期
            # （原排产计划日期保留在 plan_date_plan 供对照）
            "plan_date": (str(ru.get("eff_plan_date"))[:10] if ru.get("eff_plan_date")
                          else (str(r["plan_date"])[:10] if r.get("plan_date") is not None else "")),
            "plan_date_plan": (str(r["plan_date"])[:10] if r.get("plan_date") is not None else ""),
            "plan_qty": r["plan_qty"],
            "actual_qty": actual_qty,
            "report_date": str(act.get("report_date") or "")[:10] or None,
            **st,
        })
    return rows


def _load_node_segments(project_id: int) -> dict[int, tuple[int, int]]:
    """读取项目全部按段填报行（v7.1 行级化）→ {node_plan_id: (segment_total, segment_done)}。

    查询失败（如表未建）返回空 dict，不阻塞总览。
    """
    if project_id is None:
        return {}
    from ..core import db
    try:
        seg_map: dict[int, tuple[int, int]] = {}
        for seg in (db.get_node_segments(int(project_id)) or []):
            seg_map[int(seg.get("node_plan_id") or 0)] = (
                int(seg.get("segment_total") or 0), int(seg.get("segment_done") or 0),
            )
        return seg_map
    except Exception as e:  # noqa: BLE001 — 按段填报为增强功能，失败不阻塞主流程
        import logging
        logging.getLogger(__name__).warning("get_node_segments(%s) 失败：%s", project_id, e)
        return {}


def _segment_delay_tags(tags: list, grp: list[dict],
                        seg_map: dict[int, tuple[int, int]], today: date) -> list:
    """按段填报标签（v7.1 行级化 + 未来计划预警门槛）：
    该工序任一节点有段记录且未填满 → 追加「部分完成」；预警/延期按计划日门槛分级：
      1) 已开始（plan_date ≤ today，无日期保守视为已开始）节点中存在 plan_date + 7 天
         仍早于今天 → 「部分完成」+「延期」；
      2) 否则已开始节点中存在未填满 → 「部分完成」+「预警」；
      3) 仅未来计划（plan_date > today）未填满 → 只给「部分完成」，**不给预警/延期**
         （用户口径：预警仅在该套计划已开始后才触发，未来计划不触发任何预警）；
      4) 填满（done>=total）或无段记录 → 不加任何标签。
    ⚠️ 卡片主状态/status/label 一律不改（tags 仅追加，其余字段不动）。
    ⚠️ 逐词判重（P2-1）：业务层可能已产出「部分完成」（0<actual<plan 且 plan<today），
       追加段标签前对三个词逐一判重，已在 tags 里的不再重复 append；
       「延期」替换「预警」的现有逻辑保持不变。
    """
    # 活跃节点：该工序的行中，有段记录且 done < total 的节点
    active = [
        (r, seg_map[r["id"]]) for r in grp
        if r.get("id") in seg_map and 0 <= seg_map[r["id"]][1] < seg_map[r["id"]][0]
    ]
    if not active:
        return tags
    # 按 plan_date 分两组：started = plan_date ≤ today（无日期保守视为已开始）；future = > today
    started, future = [], []
    for r, seg in active:
        pd_str = str(r.get("plan_date") or "")[:10]
        if pd_str and date.fromisoformat(pd_str) > today:
            future.append((r, seg))
        else:
            started.append((r, seg))

    def _over7(row):
        d = str(row.get("plan_date") or "")[:10]
        return bool(d) and (date.fromisoformat(d) + timedelta(days=7)) < today

    if any(_over7(r) for r, (_t, _d) in started):
        seg_tags = ["部分完成", "延期"]
    elif started:
        seg_tags = ["部分完成", "预警"]
    else:
        # 仅未来计划未填满：不触发预警/延期
        seg_tags = ["部分完成"]
    # 逐词判重追加（保序）：「预警」已被业务层加入时不重复；「延期」始终以替换语义处理
    out = list(tags)
    for t in seg_tags:
        if t == "延期":
            if "延期" in out:
                continue
            if "预警" in out:
                out = [x for x in out if x != "预警"]  # 「预警」换「延期」
            out.append("延期")
        elif t not in out:
            out.append(t)
    return out


def build_overview(project_id: int, plans: list[dict], actuals: dict, today=None, monthly_plan: int = 0,
                   contract_count=None, durations: Optional[dict] = None) -> dict:
    """节点计划总览：指标 + 工序卡片 + 时间轴 + 分组数据。

    - kpis: 总套数/工序数/节点总数/达标节点/逾期节点
    - processes: 按 SCHEDULE_PROCESS_NAMES 顺序的工序卡片（名称/状态/进度/分组）
    - timeline: 时间轴所需行
    - contract_count: 项目主表合同总数（独立工序卡片的「合同总数」单一数据源；None 时回退占位行）
    """
    today = today or date.today()
    rows = enrich_rows(plans, actuals, today, durations)

    # 按段填报（v7.1 行级化）：{node_plan_id: (segment_total, segment_done)}
    seg_map = _load_node_segments(project_id)

    proc_groups: dict[str, list[dict]] = {}
    for r in rows:
        proc_groups.setdefault(r["process_name"], []).append(r)

    per_proc_sets = {pn: sum(r["plan_qty"] for r in grp) for pn, grp in proc_groups.items()}
    total_sets = max(per_proc_sets.values()) if per_proc_sets else 0
    done_count = sum(1 for r in rows if r["status"] == "done")
    overdue_count = len(compute_real_overdue(rows, monthly_plan))

    processes = []
    for pn in SCHEDULE_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = proc_groups[pn]
        # 工序卡片状态：双维度判定（总套数完成度 + 当日计划完成度），
        # 替代原节点级 level 汇总——只有全部套数完成才显示"已完成"
        proc_status = judge_process_card_status(grp, actuals, today, monthly_plan)
        total_plan = sum(r["plan_qty"] for r in grp)
        total_actual = sum(r["actual_qty"] for r in grp)
        current_plan = sum(
            r["plan_qty"] for r in grp
            if str(r["plan_date"])[:10] == str(today)[:10]
        )
        # 今日有计划：存在 plan_date 为今天的节点 且 实际 < 计划（今天仍有未完成节点）
        has_today_plan = any(
            str(r["plan_date"])[:10] == str(today)[:10]
            and actuals.get(r["id"], {}).get("actual_qty", 0) < r["plan_qty"]
            for r in grp
        )
        progress = (total_actual / total_plan * 100) if total_plan else 0
        proc_tags = _segment_delay_tags(
            list(proc_status.get("tags", [])), grp, seg_map, today,
        )
        processes.append({
            "process_name": pn,
            "status": proc_status["status"],
            "label": proc_status["label"],
            "tags": proc_tags,
            "has_today_plan": has_today_plan,
            "total_plan": total_plan,
            "total_plan_qty": total_plan,      # 总计划套数（前端进度条分母）
            "total_actual": total_actual,
            "current_plan_qty": current_plan,  # 当日计划累计（前端/诊断用）
            "progress_pct": round(min(progress, 100), 1),
            "node_count": len(grp),
            "independent": False,
        })

    # 独立工序卡片（累计完成总数/累计发运总数）：追加在 11 道工序之后。
    # 合同总数（total_plan）**单一数据源 = projects.contract_count**；为空时回退占位行 plan_qty（兼容旧数据）。
    # total_actual = 所有行 actual_qty 之和（每次填报一条；总和 = 累计填报）
    for pn in INDEPENDENT_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = proc_groups[pn]
        # 合同占位行：plan_date 为 NULL，plan_qty = contract_count
        placeholder = [r for r in grp if not str(r.get("plan_date") or "")]
        if contract_count is not None:
            total_plan = int(contract_count or 0)
        else:
            total_plan = sum(r["plan_qty"] for r in placeholder) if placeholder else sum(r["plan_qty"] for r in grp)
        total_actual = sum(r["actual_qty"] for r in grp)
        done = total_actual >= total_plan and total_plan > 0
        status = "done" if done else "in_progress"
        progress = (total_actual / total_plan * 100) if total_plan else 0
        processes.append({
            "process_name": pn,
            "status": status,
            "label": "🟢 已完成" if done else "🔵 进行中",
            "tags": [],
            "has_today_plan": False,
            "total_plan": total_plan,
            "total_plan_qty": total_plan,
            "total_actual": total_actual,
            "current_plan_qty": 0,
            "progress_pct": round(min(progress, 100), 1),
            "node_count": len(grp),
            "independent": True,
        })

    return {
        "kpis": {
            "total_sets": total_sets,
            "process_count": len(proc_groups),
            "node_count": len(rows),
            "done_count": done_count,
            "overdue_count": overdue_count,
        },
        "processes": processes,
        "timeline": rows,
        "visible_processes": [pn for pn in SCHEDULE_PROCESS_NAMES if pn in proc_groups],
    }


def build_process_detail(process_name: str, plans: list[dict], actuals: dict, today=None,
                         contract_count=None, durations: Optional[dict] = None,
                         project_id: int | None = None) -> dict:
    """某工序节点列表：按 今日/逾期/未来/已完成 四组返回（填报弹窗数据源）。

    独立工序特殊处理：
      - groups.done 按 plan_date 降序（最新填报在上）
      - 卡片（build_overview）total_plan **单一数据源 = projects.contract_count**
      - 卡片 total_actual = 所有行 actual_qty 之和（每次填报一条）
      - 返回值额外带 contract_count，供前端「合同总数」直接读取（避免依赖占位行 plan_qty）
    v7.1 按段填报（行级化）：project_id 非空时每个节点行（nodes/groups 行）带
      segment_total/segment_done（该套的分段进度；无记录为 None），供填报 tab 回显 +
      节点详情 tab 展示；旧调用（不传参）行为不变。
    """
    today = today or date.today()
    # ⚠️ 闸门锚点必须基于【全项目】计划行（找「下料」行），不能只用本工序的行
    rules = build_time_rules(plans, actuals, durations)
    proc_nodes = sorted(
        (r for r in plans if r["process_name"] == process_name),
        key=lambda r: str(r["plan_date"]),
    )
    # 分组/展示统一使用「重算后的计划日期」（闸门开时）——与节点详情、时间轴口径一致
    proc_nodes = [
        ({**p, "plan_date": rules[p["id"]]["eff_plan_date"]}
         if rules.get(p["id"], {}).get("eff_plan_date") else p)
        for p in proc_nodes
    ]
    groups = split_node_groups(proc_nodes, actuals, today)
    rows = enrich_rows(proc_nodes, actuals, today, durations, rules)

    # 独立工序的 done 组按日期降序展示（最新填报在上）
    if process_name in INDEPENDENT_PROCESS_NAMES:
        groups['done'] = sorted(
            groups['done'],
            key=lambda p: str(p.get('plan_date') or ''),
            reverse=True,
        )

    # 按段填报（v7.1 行级化）：每套（计划行）各自的段进度——无记录为 None
    seg_map = _load_node_segments(project_id) if project_id is not None else {}
    for r in rows:
        seg = seg_map.get(int(r["id"]))
        r["segment_total"] = seg[0] if seg else None
        r["segment_done"] = seg[1] if seg else None

    return {
        "process_name": process_name,
        "is_independent": process_name in INDEPENDENT_PROCESS_NAMES,
        "contract_count": contract_count,   # 项目主表合同总数（独立工序「合同总数」单一数据源；可为 None）
        "nodes": rows,
        "groups": {
            g: [{"id": p["id"],
                 "plan_date": (str(p["plan_date"])[:10] if p.get("plan_date") is not None else ""),
                 "plan_qty": p["plan_qty"],
                 "actual_qty": actuals.get(p["id"], {}).get("actual_qty", 0),
                 # 按段填报回显（v7.1 行级化；无记录为 None）
                 "segment_total": seg_map.get(int(p["id"]), (None, None))[0],
                 "segment_done": seg_map.get(int(p["id"]), (None, None))[1]}
                for p in nodes]
            for g, nodes in groups.items()
        },
    }
