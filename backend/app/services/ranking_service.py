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
from ..services.business_logic import judge_node_status, build_time_rules


def _month_range(month: str) -> tuple[str, str]:
    """'2026-08' → ('2026-08-01', '2026-09-01')。"""
    y, m = map(int, month.split("-"))
    if m == 12:
        return f"{y}-12-01", f"{y + 1}-01-01"
    return f"{y}-{m:02d}-01", f"{y}-{m + 1:02d}-01"


def get_production_ranking(month: str, big_area_person: str | None = None) -> list[dict]:
    """返回按完成率降序的负责人排名列表（v6.0 多负责人：每位负责人独立一行）。

    month 形如 '2026-08'。

    口径（与「生产进度总览」页面联动一致）：
    - 数据源切换为 db.get_ranking_manager_rows_by_month：先按 (项目 × 负责人) 拆分，
      再在本函数按『负责人』聚合（同一负责人名下多个项目汇总），
      使「张三/李四」这类多负责人在出品排名中各占一行、分别排名。
    - total_plan / total_actual 已按负责人归属（见 get_ranking_manager_rows_by_month 口径）。
    - 完成率 = 累计完成套数 / 累计计划套数 × 100%；分母为 0 → None（前端显示 —）。
    - project_count = 该负责人当月涉及的项目数（去重）。
    排名：完成率降序（None 排最后）→ 计划套数降序 → 负责人升序。
    big_area_person: 大区负责人（大区行级隔离；admin 传 None 看全量）。

    返回字段：manager / delivery_person(=manager 兼容别名) / total_plan / total_actual /
              completion_rate / project_count / rank。
    """
    manager_rows = db.get_ranking_manager_rows_by_month(month, big_area_person)

    # 按负责人聚合：同一负责人名下跨多个项目汇总
    agg: dict[str, dict] = {}
    for r in manager_rows:
        mgr = str(r.get("manager") or "").strip()
        if not mgr:
            continue
        bucket = agg.setdefault(mgr, {
            "manager": mgr,
            "total_plan": 0,
            "total_actual": 0,
            "project_ids": set(),
        })
        bucket["total_plan"] += int(r.get("total_plan") or 0)
        bucket["total_actual"] += int(r.get("total_actual") or 0)
        bucket["project_ids"].add(int(r.get("project_id")))

    rows = []
    for mgr, b in agg.items():
        plan = b["total_plan"]
        actual = b["total_actual"]
        rate = round(actual / plan * 100, 1) if plan else None
        rows.append({
            "manager": mgr,
            "delivery_person": mgr,   # 兼容前端旧字段名
            "total_plan": plan,
            "total_actual": actual,
            "completion_rate": rate,   # None 表示分母为零
            "project_count": len(b["project_ids"]),
        })

    # 排序：完成率降序（None 排最后）→ 计划套数降序 → 负责人升序
    rows.sort(key=lambda r: (
        -(r["completion_rate"] if r["completion_rate"] is not None else -1),
        -r["total_plan"],
        r["manager"],
    ))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r.pop("project_ids", None)
    return rows


def get_production_ranking_detail(month: str, person: str, big_area_person: str | None = None) -> list[dict]:
    """该负责人当月名下、存在逾期或提前节点的项目清单（全部工序）。

    big_area_person: 大区负责人（大区行级隔离；admin 传 None 看全量）。
    """
    ns, ne = _month_range(month)
    plans = db.get_all_plans_by_month_and_person(ns, ne, person, big_area_person)  # 1 次查询
    if not plans:
        return []
    node_ids = [p["id"] for p in plans]
    actuals = db.get_actuals_rich_by_node_ids(node_ids)           # 1 次查询（含日期，支持闸门锚点）
    pids = sorted({int(p["project_id"]) for p in plans})
    durations_map = db.get_project_process_durations_batch(pids)   # 1 次查询（按套时长/偏移）
    today = date.today()

    # 按项目算「闸门 + effective 计划日期」（与页面口径一致，避免排名与页面打架）
    by_pid: dict[int, list] = {}
    for p in plans:
        by_pid.setdefault(int(p["project_id"]), []).append(p)
    rules_all: dict = {}
    for pid, plist in by_pid.items():
        rules_all.update(build_time_rules(plist, actuals, durations_map.get(pid)))

    result = []
    for p in plans:
        aq = int((actuals.get(int(p["id"])) or {}).get("actual_qty", 0) or 0)
        ru = rules_all.get(int(p["id"])) or {}
        # 待下料（闸门关的制造链工序）与法兰到货（不作主指标）不进逾期/提前明细
        if ru.get("waiting_material") or not ru.get("count_as_overdue", True):
            continue
        eff = ru.get("eff_plan_date")
        plan_date = eff if eff else p["plan_date"]        # 闸门开 → 用重算后的计划日期
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
