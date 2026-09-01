# -*- coding: utf-8 -*-
"""节点计划聚合服务：把原始行富化为前端所需的「时间轴 / 工序卡片 / 分组」数据。"""
from datetime import date

from .business_logic import (judge_node_status, judge_process_card_status, split_node_groups,
                             compute_real_overdue)
from ..core.config import SCHEDULE_PROCESS_NAMES, INDEPENDENT_PROCESS_NAMES


def enrich_rows(plans: list[dict], actuals: dict, today=None) -> list[dict]:
    """富化节点行：计划信息 + 实际完成 + 五态判定（含完成日期与偏差）。

    返回行结构与原 Streamlit 版 rows 一致（前端时间轴/卡片直接使用）。
    独立工序（累计完成总数/累计发运总数）：无日期语义，仅按 actual vs plan 输出
    done / in_progress，不走日期判定，避免被误判逾期/预警。
    """
    today = today or date.today()
    rows = []
    for r in plans:
        nid = r["id"]
        act = actuals.get(nid, {})
        actual_qty = act.get("actual_qty", 0)
        completion_date = act.get("report_date") if actual_qty >= r["plan_qty"] else None
        if r["process_name"] in INDEPENDENT_PROCESS_NAMES:
            done = actual_qty >= r["plan_qty"]
            st = {
                "status": "done" if done else "in_progress",
                "label": "🟢 已完成" if done else "🔵 进行中",
                "level": 0, "lag_qty": 0, "completion_date": completion_date,
                "deviation_days": 0, "deviation_label": "-", "deviation_color": "#718096",
            }
        else:
            st = judge_node_status(r["plan_date"], r["plan_qty"], actual_qty, today, completion_date)
        rows.append({
            "id": nid,
            "project_id": r["project_id"],
            "process_name": r["process_name"],
            "plan_date": (str(r["plan_date"])[:10] if r.get("plan_date") is not None else ""),
            "plan_qty": r["plan_qty"],
            "actual_qty": actual_qty,
            "report_date": str(act.get("report_date") or "")[:10] or None,
            **st,
        })
    return rows


def build_overview(project_id: int, plans: list[dict], actuals: dict, today=None, monthly_plan: int = 0) -> dict:
    """节点计划总览：指标 + 工序卡片 + 时间轴 + 分组数据。

    - kpis: 总套数/工序数/节点总数/达标节点/逾期节点
    - processes: 按 SCHEDULE_PROCESS_NAMES 顺序的工序卡片（名称/状态/进度/分组）
    - timeline: 时间轴所需行
    """
    today = today or date.today()
    rows = enrich_rows(plans, actuals, today)

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
        processes.append({
            "process_name": pn,
            "status": proc_status["status"],
            "label": proc_status["label"],
            "tags": proc_status.get("tags", []),
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
    # total_plan = 合同占位行（plan_date IS NULL）的 plan_qty = contract_count（进度条分母不变）
    # total_actual = 所有行 actual_qty 之和（每次填报一条；总和 = 累计填报）
    for pn in INDEPENDENT_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = proc_groups[pn]
        # 合同占位行：plan_date 为 NULL，plan_qty = contract_count
        placeholder = [r for r in grp if not str(r.get("plan_date") or "")]
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


def build_process_detail(process_name: str, plans: list[dict], actuals: dict, today=None) -> dict:
    """某工序节点列表：按 今日/逾期/未来/已完成 四组返回（填报弹窗数据源）。

    独立工序特殊处理：
      - groups.done 按 plan_date 降序（最新填报在上）
      - 卡片（build_overview）total_plan = 合同占位行（plan_date IS NULL）的 plan_qty = contract_count
      - 卡片 total_actual = 所有行 actual_qty 之和（每次填报一条）
    """
    today = today or date.today()
    proc_nodes = sorted(
        (r for r in plans if r["process_name"] == process_name),
        key=lambda r: str(r["plan_date"]),
    )
    groups = split_node_groups(proc_nodes, actuals, today)
    rows = enrich_rows(proc_nodes, actuals, today)

    # 独立工序的 done 组按日期降序展示（最新填报在上）
    if process_name in INDEPENDENT_PROCESS_NAMES:
        groups['done'] = sorted(
            groups['done'],
            key=lambda p: str(p.get('plan_date') or ''),
            reverse=True,
        )

    return {
        "process_name": process_name,
        "is_independent": process_name in INDEPENDENT_PROCESS_NAMES,
        "nodes": rows,
        "groups": {
            g: [{"id": p["id"],
                 "plan_date": (str(p["plan_date"])[:10] if p.get("plan_date") is not None else ""),
                 "plan_qty": p["plan_qty"],
                 "actual_qty": actuals.get(p["id"], {}).get("actual_qty", 0)}
                for p in nodes]
            for g, nodes in groups.items()
        },
    }
