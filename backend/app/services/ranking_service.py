# -*- coding: utf-8 -*-
"""出品排名统计：按交付负责人维度聚合当月『附件安装』出品数据并排名。

统计口径（与排产数据一致）：
- 当月范围：process_node_plans.plan_date 落在所选月份
- 计划/完成套数：仅『附件安装』工序（整体进度口径）
- 完成率 = 完成/计划×100%，分母为 0 → None（前端显示 —）
- 排名：完成率降序 → 计划套数降序 → 负责人升序
- 详情：该负责人当月存在「逾期/提前」节点的项目清单（全部工序）
  - 逾期：plan_date < today 且 actual_qty < plan_qty（含部分完成）
  - 提前：plan_date > today 且 actual_qty >= plan_qty
"""
from datetime import date

from ..core import db
from ..services.business_logic import judge_node_status


def _month_range(month: str) -> tuple[str, str]:
    """'2026-08' → ('2026-08-01', '2026-09-01')。"""
    y, m = map(int, month.split("-"))
    if m == 12:
        return f"{y}-12-01", f"{y + 1}-01-01"
    return f"{y}-{m:02d}-01", f"{y}-{m + 1:02d}-01"


def get_production_ranking(month: str, big_area_person: str | None = None) -> list[dict]:
    """返回按完成率降序的负责人排名列表。month 形如 '2026-08'。

    口径（与「生产进度总览」页面联动一致，2026-08-31 修正）：
    - 累计计划套数 total_plan = 名下所有项目「本月计划出品」(projects.monthly_plan) 之和；
      月份 = 调度令月份（projects.created_at 年月），与项目列表/看板同口径。
    - 累计完成套数 total_actual = 名下所有项目「附件安装」工序实际完成量
      (node_actual_progress.actual_qty) 之和。
    - 完成率 = 累计完成套数 / 累计计划套数 × 100%；分母为 0 → None（前端显示 —）。
    - project_count = 当月项目数。
    排名：完成率降序（None 排最后）→ 计划套数降序 → 负责人升序。
    big_area_person: 大区负责人（大区行级隔离；admin 传 None 看全量）。
    """
    summary = db.get_ranking_summary_by_month(month, big_area_person)   # 1 次查询（已按人聚合）

    rows = []
    for r in summary:
        person = str(r.get("delivery_person") or "").strip()
        if not person:
            continue
        plan = int(r.get("total_plan") or 0)
        actual = int(r.get("total_actual") or 0)
        rate = round(actual / plan * 100, 1) if plan else None
        rows.append({
            "delivery_person": person,
            "total_plan": plan,
            "total_actual": actual,
            "completion_rate": rate,   # None 表示分母为零
            "project_count": int(r.get("project_count") or 0),
        })

    # 排序：完成率降序（None 排最后）→ 计划套数降序 → 负责人升序
    rows.sort(key=lambda r: (
        -(r["completion_rate"] if r["completion_rate"] is not None else -1),
        -r["total_plan"],
        r["delivery_person"],
    ))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def get_production_ranking_detail(month: str, person: str, big_area_person: str | None = None) -> list[dict]:
    """该负责人当月名下、存在逾期或提前节点的项目清单（全部工序）。

    big_area_person: 大区负责人（大区行级隔离；admin 传 None 看全量）。
    """
    ns, ne = _month_range(month)
    plans = db.get_all_plans_by_month_and_person(ns, ne, person, big_area_person)  # 1 次查询
    node_ids = [p["id"] for p in plans]
    actuals = db.get_actuals_by_node_ids(node_ids)                # 1 次查询
    today = date.today()

    result = []
    for p in plans:
        aq = actuals.get(int(p["id"]), 0)
        plan_date = p["plan_date"]
        info = judge_node_status(str(plan_date), int(p["plan_qty"] or 0), aq, today)
        pd = str(plan_date)[:10]
        ts = str(today)
        if pd < ts and aq < int(p["plan_qty"] or 0):
            # 逾期（含部分完成；judge_node_status 的 overdue 仅 actual==0，此处按用户口径覆盖）
            exception_type = "逾期"
        elif pd > ts and aq >= int(p["plan_qty"] or 0):
            # 提前
            exception_type = "提前"
        else:
            continue
        result.append({
            "project_id": p["project_id"],
            "project_name": p["project_name"],
            "machine_no": p["machine_type"],
            "factory": p["factory_name"],
            "process_name": p["process_name"],
            "plan_date": pd,
            "plan_qty": int(p["plan_qty"] or 0),
            "actual_qty": aq,
            "deviation_days": info.get("deviation_days", 0),
            "exception_type": exception_type,
        })
    return result
