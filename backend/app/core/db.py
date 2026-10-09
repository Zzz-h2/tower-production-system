# -*- coding: utf-8 -*-
"""数据库访问层：封装原 database.py 的 pymysql 连接与节点表读写。

沿用现有表结构（process_node_plans / node_actual_progress / node_exceptions 等），不重新设计。
风险等级与整体进度均由 node_plans + node_actuals 实时计算，弃用 processes 表。
"""
from datetime import date

from .config import MYSQL_CONFIG, SCHEDULE_PROCESS_NAMES

# v7.2 排产工序白名单区间（与根 database.py 同源，顺序由 SCHEDULE_PROCESS_NAMES 保证）：
# 排产导入写出的行满足 process_order = index+1，即 1..len(SCHEDULE_PROCESS_NAMES)。
# ⚠️ 判定「有没有排产计划」必须用它，不能用「process_name NOT IN (90,91)」——
#    「手动完成」占位行（process_order=99, process_name='附件安装'）也满足后者，会造成假阳性。
SCHEDULE_ORDER_MIN = 1
SCHEDULE_ORDER_MAX = len(SCHEDULE_PROCESS_NAMES)


def get_connection():
    """获取 pymysql 连接（与原 database.py 同配置）。"""
    import pymysql
    return pymysql.connect(
        host=MYSQL_CONFIG["host"],
        port=MYSQL_CONFIG["port"],
        user=MYSQL_CONFIG["user"],
        password=MYSQL_CONFIG["password"],
        database=MYSQL_CONFIG["database"],
        charset=MYSQL_CONFIG["charset"],
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


# ---------- 节点计划 / 实际进度（v4.0 表） ----------

def get_node_plans(project_id: int, manager: str | None = None) -> list[dict]:
    """查询工序节点计划（含 id/project_id/process_name/plan_date/plan_qty/process_order/manager）。

    多负责人（v6.0）：manager=None 返回该项目全部行（汇总视图）；
    manager='张三' 只返回该负责人名下行（单人视图）。
    """
    from database import get_node_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager)


def get_node_actuals(project_id: int) -> dict:
    """查询节点实际进度：{node_plan_id: {actual_qty, report_date, ...}}。"""
    from database import get_node_actuals as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_node_plans_batch(project_ids: list[int]) -> dict[int, list[dict]]:
    """批量查询多个项目的工序节点计划：{project_id: [plan, ...]}（消除列表页 N+1）。"""
    from database import get_node_plans_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids)


def get_node_actuals_batch(project_ids: list[int]) -> dict[int, dict]:
    """批量查询多个项目节点实际进度：{project_id: {node_plan_id: {...}}}。"""
    from database import get_node_actuals_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids)


def get_attachment_plans_by_month(month_start: str, month_end: str, month: str | None = None,
                                  big_area_person: str | None = None) -> list[dict]:
    """取某月内所有『附件安装』工序节点计划（出品排名统计源；month 约束项目 created_at 月份）。"""
    from database import get_attachment_plans_by_month as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end, month, big_area_person)


def get_ranking_summary_by_month(month: str, big_area_person: str | None = None) -> list[dict]:
    """出品排名总览聚合：累计计划套数=SUM(monthly_plan)；累计完成套数=SUM(附件安装 actual)。"""
    from database import get_ranking_summary_by_month as _fn
    return getattr(_fn, "__wrapped__", _fn)(month, big_area_person)


def get_actuals_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度：{node_plan_id: actual_qty}（消除 N+1）。"""
    from database import get_actuals_by_node_ids as _fn
    return getattr(_fn, "__wrapped__", _fn)(node_ids)


def get_delivery_persons_by_projects(project_ids: list[int]) -> dict[int, str]:
    """批量取项目交付负责人：{project_id: delivery_person}。"""
    from database import get_delivery_persons_by_projects as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids)


def get_all_plans_by_month_and_person(month_start: str, month_end: str, person: str,
                                      big_area_person: str | None = None) -> list[dict]:
    """取某负责人当月全部工序节点计划（含项目名/机号/厂家，供逾期/提前明细）。"""
    from database import get_all_plans_by_month_and_person as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end, person, big_area_person)


def insert_node_plans(project_id: int, plans: list[dict], manager: str | None = None,
                      durations: list[dict] | None = None,
                      plan_month: str | None = None) -> int:
    """批量写入节点计划（覆盖式）。

    多负责人（v6.0）：manager 非 None 时只覆盖该负责人名下的排产工序行（并吸收历史 NULL 行），
    实现各负责人分别导入、互不覆盖。manager=None 保持历史行为（清空该项目全部排产工序行）。
    durations：按「套」的工序计划时长/相对下料偏移（工序时间规则升级用），与 plan 行同范围覆盖式重建。
    plan_month（v7.2）：排产归属月 'YYYY-MM'，记到每个排产工序行上；被替换掉的行先归档到
    process_node_plans_history 再删除（替换而非销毁，历史月份可回溯）。
    """
    from database import insert_node_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plans, manager, durations, plan_month)


# ---------- 排产上传台账（schedule_imports，v7.2 新增） ----------
# ⚠️ 根 database.py 新增函数必须在此同步 re-export，否则 `db.xxx` 抛 AttributeError → FastAPI 默认 500。

def upsert_schedule_import(project_id: int, plan_month: str, manager: str = "",
                           row_count: int = 0, source_file: str = "") -> None:
    """写入「项目 × 排产归属月 × 负责人」上传台账（重复导入幂等覆盖）。"""
    from database import upsert_schedule_import as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plan_month, manager, row_count, source_file)


def get_schedule_imports(plan_month: str) -> dict[int, dict]:
    """按归属月取上传台账 → {project_id: {'managers': [...], 'row_count': int}}。"""
    from database import get_schedule_imports as _fn
    return getattr(_fn, "__wrapped__", _fn)(plan_month)


def get_last_schedule_months() -> dict[int, str]:
    """取每个项目最近一次排产上传的归属月 → {project_id: 'YYYY-MM'}。"""
    from database import get_last_schedule_months as _fn
    return getattr(_fn, "__wrapped__", _fn)()


def get_schedule_import_months() -> list[dict]:
    """返回已留档的排产归属月列表（倒序）。"""
    from database import get_schedule_import_months as _fn
    return getattr(_fn, "__wrapped__", _fn)()


def get_node_plans_history(project_id: int, plan_month: str | None = None,
                           manager: str | None = None, limit: int = 5000) -> list[dict]:
    """读取已归档的排产明细（历史月份回溯）。"""
    from database import get_node_plans_history as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plan_month, manager, limit)


def get_project_process_durations(project_id: int, manager: str | None = None) -> dict:
    """读取项目「按套工序时长/偏移」并按 (工序, 计划日) 归并（无数据返回 {}）。"""
    from database import get_project_process_durations as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager)


def get_project_process_durations_batch(project_ids: list[int]) -> dict[int, dict]:
    """批量读取多项目「按套工序时长/偏移」并归并（消除列表页 N+1）。"""
    from database import get_project_process_durations_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids)


def get_actuals_rich_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度（含 report_date）：{node_plan_id: {actual_qty, report_date}}。"""
    from database import get_actuals_rich_by_node_ids as _fn
    return getattr(_fn, "__wrapped__", _fn)(node_ids)


def delete_all_node_plans(project_id: int) -> None:
    """彻底清空项目全部节点计划（含独立工序）。"""
    from database import delete_all_node_plans as _fn
    _fn(project_id)


def upsert_node_actual(project_id: int, node_plan_id: int, process_name: str,
                       actual_qty: int, report_date: str,
                       manager: str | None = None) -> None:
    """写入/更新单个节点实际进度。多负责人（v6.0）：manager 标注归属负责人。"""
    from database import upsert_node_actual as _fn
    getattr(_fn, "__wrapped__", _fn)(project_id, node_plan_id, process_name,
                                     actual_qty, report_date, manager)


def upsert_manual_complete(project_id: int, complete_qty: int, complete_date: str,
                           manager: str | None = None) -> int:
    """手动完成：按日期 upsert 一条『附件安装』节点计划 + 实际完成，返回 node_plan_id。

    manager（v6.0 多负责人）必须写入，否则出品排名按 pnp.manager IS NOT NULL
    过滤会漏掉手动完成数据。桥接根目录 database.py 的 upsert_manual_complete。
    """
    from database import upsert_manual_complete as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, complete_qty, complete_date, manager)


def save_independent_fill(project_id: int, process_name: str,
                          fill_qty: int, report_date: str,
                          manager: str | None = None) -> int:
    """独立工序（累计完成总数/累计发运总数）逐日填报：按日期 find-or-create node_plan + upsert actual。

    桥接根目录 database.py 的 save_independent_fill（路由层通过本桥接调用）。
    多负责人（v6.0）：manager 非 None 时限定在该负责人名下 find-or-create，互不覆盖。
    """
    from database import save_independent_fill as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, process_name, fill_qty,
                                            report_date, manager)


def move_independent_fill_date(project_id: int, process_name: str,
                               node_plan_id: int, new_report_date: str,
                               new_qty: int | None = None) -> int:
    """独立工序「已完成」记录改日期/数量（管理员用）：移动 plan_date + actual.report_date，
    目标日期已有记录则合并；new_qty 非 None 时同步数量。桥接根目录 database.py 的同名函数。
    """
    from database import move_independent_fill_date as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, process_name, node_plan_id, new_report_date, new_qty)


# ---------- 按段填报（v7.1 行级化，node_segment_progress） ----------

def upsert_node_segment(project_id: int, node_plan_id: int,
                        segment_total: int, segment_done: int) -> None:
    """写入/更新某套（计划行）的分段进度（总段数/已完成段数）。

    桥接根目录 database.py 的 upsert_node_segment（路由层通过本桥接调用）。
    段数唯一挂在 node_plan_id 上（uk_node_seg）；独立记录不折算、不写 actual_qty。
    """
    from database import upsert_node_segment as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, node_plan_id,
                                            segment_total, segment_done)


def get_node_segments(project_id: int) -> list[dict]:
    """查询项目全部按段填报行（行级化）：node_plan_id/segment_total/segment_done。

    桥接根目录 database.py 的 get_node_segments（总览/详情组装段进度用）。
    """
    from database import get_node_segments as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


# ---------- 多负责人管理（v6.0） ----------

def split_managers(delivery_person: str | None) -> list[str]:
    """把「交付负责人」按 '/'（含全角'／'）拆分为负责人列表（去空+去重+保序）。"""
    from database import split_managers as _fn
    return getattr(_fn, "__wrapped__", _fn)(delivery_person)


def upsert_manager_monthly_plan(project_id: int, manager: str, monthly_plan: int) -> None:
    """写入/更新「某负责人 对 某项目」的本月计划数（方案P：独立申报，不校验求和）。"""
    from database import upsert_manager_monthly_plan as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager, monthly_plan)


def get_manager_monthly_plan_map(project_id: int) -> dict[str, int]:
    """取项目各负责人本月计划数映射：{负责人: monthly_plan}（未申报者不在结果中）。"""
    from database import get_manager_monthly_plan_map as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def list_project_managers(project_id: int) -> list[dict]:
    """列出项目负责人清单及概况（供「多负责人管理」弹窗使用）。

    每项：manager / monthly_plan / plan_rows / has_imported
    """
    from database import list_project_managers as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_ranking_manager_rows_by_month(month: str,
                                      big_area_person: str | None = None) -> list[dict]:
    """出品排名（v6.0 多负责人）：返回当月每个 (项目 × 负责人) 的计划/完成明细行。

    与 get_ranking_summary_by_month 的区别：按 '/' 拆分后，每位负责人各占一行，
    使出品排名能把多位负责人的数据分别展示、分别排名。桥接根目录 database.py 同名函数。
    """
    from database import get_ranking_manager_rows_by_month as _fn
    return getattr(_fn, "__wrapped__", _fn)(month, big_area_person)


# ---------- 项目（复用于项目列表/详情） ----------

def get_all_projects(status_filter=None, big_area_person: str | None = None) -> list[dict]:
    from database import get_all_projects as _fn
    return getattr(_fn, "__wrapped__", _fn)(status_filter, big_area_person)


def get_project_by_id(project_id: int) -> dict | None:
    from database import get_project_by_id as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)
def get_all_persons(big_area_person: str | None = None) -> list[str]:
    """获取所有项目的交付负责人（去重、非空、排序）。

    big_area_person 非 None 时仅返回该大区下的负责人（大区行级隔离）。
    """
    conn = get_connection()
    try:
        sql = (
            "SELECT DISTINCT delivery_person FROM projects "
            "WHERE delivery_person IS NOT NULL AND delivery_person != ''"
        )
        params = []
        if big_area_person:
            sql += " AND big_area_person = %s"
            params.append(big_area_person)
        sql += " ORDER BY delivery_person"
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [row["delivery_person"] for row in cur.fetchall()]
    finally:
        conn.close()


def get_all_big_area_persons() -> list[str]:
    """获取所有项目的大区负责人（去重、非空、排序）。"""
    from database import get_all_big_area_persons as _fn
    return getattr(_fn, "__wrapped__", _fn)()


def get_dashboard_stats(month: str | None = None, big_area_person: str | None = None) -> dict:
    """首页总览统计：与项目列表风险口径完全一致（复用 get_projects_filtered 实时计算）。

    不再基于 processes 表旧 risk_level 统计——直接复用项目列表的
    node_plans + node_actuals 实时风险判定结果，保证两者 100% 一致。
    month: 调度令月份（created_at 年月），透传给列表过滤。
    big_area_person: 大区负责人（大区行级隔离；admin 传 None 看全量）。
    """
    items, _ = get_projects_filtered(
        keyword="", person="", status="", skip=0, limit=100000, month=month,
        big_area_person=big_area_person,
    )
    return {
        "total_projects": len(items),
        "warning_projects": sum(1 for p in items if p.get("risk_level") == "warning"),
        "delayed_projects": sum(1 for p in items if p.get("risk_level") == "delayed"),
        "monthly_plan_total": sum(int(p.get("monthly_plan", 0) or 0) for p in items),
    }


# ---------- 手动添加 / 调度令导入 复用封装 ----------

def upsert_project(data: dict, mapped_fields=None):
    """插入或更新项目（四字段唯一键），返回 (project_id, is_new)。

    mapped_fields: 本次 Excel 已映射的系统字段集合（覆盖保护用）；None=不过滤。
    """
    from database import upsert_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(data, mapped_fields)


def sync_independent_plans(project_id: int, contract_count) -> int:
    """同步项目两条独立工序节点计划（累计完成总数 / 累计发运总数）。"""
    from database import sync_independent_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, contract_count)


def update_independent_contract_qty(project_id: int, contract_count) -> int:
    """非破坏性同步独立工序「合同占位行」的 plan_qty（只改 plan_date IS NULL 的占位行）。"""
    from database import update_independent_contract_qty as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, contract_count)


def get_duplicate_project(project_name: str, factory_name: str,
                          delivery_person: str, machine_type: str):
    """四字段组合查重：名称+厂家+负责人+机型 全部一致才算重复。"""
    from database import get_duplicate_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_name, factory_name, delivery_person, machine_type)
def insert_import_log(file_name: str, total: int, success: int, error: int, error_details: str = ""):
    """记录导入日志。"""
    from database import insert_import_log as _fn
    return getattr(_fn, "__wrapped__", _fn)(file_name, total, success, error, error_details)


# ---------- 月度调度令快照（dispatch_records）桥接 ----------
# ⚠️ 根 database.py 新增函数必须在此同步 re-export，否则调用方报
#    AttributeError: module 'app.core.db' has no attribute 'xxx' → FastAPI 500。

def upsert_dispatch_record(project_id: int, plan_month: str, data: dict,
                           source_file: str = "", is_approx: int = 0) -> None:
    """写入/更新「项目 × 调度令归属月」快照。"""
    from database import upsert_dispatch_record as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plan_month, data, source_file, is_approx)


def get_dispatch_records(plan_month: str) -> dict:
    """按归属月取全部快照 → {project_id: 快照行}。"""
    from database import get_dispatch_records as _fn
    return getattr(_fn, "__wrapped__", _fn)(plan_month)


def get_dispatch_months() -> list:
    """已留档的调度令月份列表（倒序）。"""
    from database import get_dispatch_months as _fn
    return getattr(_fn, "__wrapped__", _fn)()


# ---------- 项目列表：搜索/筛选 + 服务端分页 ----------

def get_projects_filtered(keyword: str | None = None, person: str | None = None,
                          status: str | None = None, skip: int = 0, limit: int = 10,
                          month: str | None = None, big_area_person: str | None = None):
    """项目搜索/筛选 + 服务端分页。

    status 语义为「风险等级」（normal/warning/delayed），由 node_plans + node_actuals
    实时计算（与详情页/节点预警口径一致），因此**不能**下推到 SQL 的 projects.status
    （生命周期字段 in_progress/completed）。
    实现：取全量项目 → keyword/person/big_area_person 内存过滤 → 计算 risk_level/progress_pct →
    风险等级内存过滤 → 切片分页。
    month: 调度令归属月份（'YYYY-MM'），口径 = projects.created_at 年月 ∪ dispatch_records.plan_month；
           命中快照的项目以该月快照口径覆盖 monthly_plan/last_month_output，三页联动共享。
    big_area_person: 大区负责人 精确相等过滤。
    """
    # status 不再作为生命周期条件下推，统一取全量项目（big_area_person 下推 SQL 做行级隔离）
    rows = get_all_projects(None, big_area_person)

    # ★ 按调度令月份过滤：口径 = 「创建月」∪「月度调度令快照（dispatch_records）」
    #   历史实现只看 created_at，导致「8/9 月建过的项目在 10 月调度令中再次出现」时
    #   走 upsert 的 UPDATE 分支、created_at 保持不变 → 被当月筛选吞掉
    #   （实测：10 月调度令 51 条只显示 38 条）。快照表按月留档后，命中快照的项目
    #   同样计入当月，并用**该月口径**覆盖计划数列（各月计划数互不覆盖）。
    if month:
        rec_map = get_dispatch_records(month)
        created_ids = {p["id"] for p in rows if str(p.get("created_at", ""))[:7] == month}
        keep_ids = created_ids | set(rec_map.keys())
        rows = [p for p in rows if p["id"] in keep_ids]

        # 月度口径覆盖：必须在下方 compute_real_overdue / KPI 汇总之前生效
        for p in rows:
            rec = rec_map.get(p["id"])
            if not rec:
                continue
            p["monthly_plan"] = int(rec.get("monthly_plan") or 0)
            p["last_month_output"] = int(rec.get("last_month_output") or 0)
            if rec.get("contract_count") is not None:
                p["contract_count"] = rec["contract_count"]
            p["dispatch_month"] = month
            p["is_approx"] = bool(rec.get("is_approx"))

    # keyword：项目名称 或 机型 模糊包含（忽略大小写）
    if keyword:
        kw = str(keyword).strip().lower()
        rows = [
            p for p in rows
            if kw in str(p.get("project_name", "")).lower()
            or kw in str(p.get("machine_type", "")).lower()
        ]

    # person：交付负责人 精确相等
    if person:
        pname = str(person).strip()
        rows = [p for p in rows if str(p.get("delivery_person", "")) == pname]

    # big_area_person：大区负责人 精确相等
    if big_area_person:
        bname = str(big_area_person).strip()
        rows = [p for p in rows if str(p.get("big_area_person", "")) == bname]

    # 风险等级 + 整体进度：基于 node_plans + node_actuals 实时计算（弃用 processes 表）
    from ..services.node_service import enrich_rows
    from ..services.business_logic import compute_real_overdue
    today_s = str(date.today())

    # 一次性批量查询（消除 N+1：原逻辑每项目 2 次 DB 往返 → 现在全程仅 3 次）
    all_pids = [p["id"] for p in rows]
    plans_map = get_node_plans_batch(all_pids)      # 1 次查询
    actuals_map = get_node_actuals_batch(all_pids)  # 1 次查询
    durations_map = get_project_process_durations_batch(all_pids)   # 1 次查询（工序时间规则升级）

    # ---- 排产上传状态（v7.2：台账 + 归属月双口径，替代原「有非独立工序行」的臆测）----
    # ① 口径修正：判定「有排产计划」必须用排产工序白名单（process_order 1..11）。
    #    原口径 process_name NOT IN (90,91) 会被「手动完成」占位行（process_order=99,
    #    process_name='附件安装'）命中 → 只做过手动完成、从未导过排产的项目显示「已上传排产」。
    # ② 月份维度：即使口径修对，白名单也只能回答「曾经传过没有」；列表是按月看的，
    #    必须回答「本月传了没有」→ 以 schedule_imports 台账（排产导入成功即落一条）为准，
    #    叠加 process_node_plans.plan_month 命中作兜底。
    #    未传 month 时（跨月视图）退回「曾经传过」口径，保持历史行为。
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT project_id FROM process_node_plans "
                "WHERE process_order BETWEEN %s AND %s",
                (SCHEDULE_ORDER_MIN, SCHEDULE_ORDER_MAX),
            )
            has_schedule_ids = {int(r["project_id"]) for r in cur.fetchall()}

            month_schedule_ids: set[int] = set()
            if month:
                cur.execute(
                    "SELECT DISTINCT project_id FROM process_node_plans "
                    "WHERE plan_month = %s AND process_order BETWEEN %s AND %s",
                    (month, SCHEDULE_ORDER_MIN, SCHEDULE_ORDER_MAX),
                )
                month_schedule_ids |= {int(r["project_id"]) for r in cur.fetchall()}
                cur.execute(
                    "SELECT DISTINCT project_id FROM schedule_imports WHERE plan_month = %s",
                    (month,),
                )
                month_schedule_ids |= {int(r["project_id"]) for r in cur.fetchall()}

            # 「上次上传：X月」提示源（同一连接内取，不额外开连接）
            cur.execute(
                "SELECT project_id, MAX(plan_month) AS m FROM schedule_imports GROUP BY project_id"
            )
            last_schedule_months = {
                int(r["project_id"]): str(r["m"]) for r in cur.fetchall() if r["m"]
            }
    finally:
        conn.close()

    for p in rows:
        pid = p["id"]
        p["has_schedule_plan"] = (pid in month_schedule_ids) if month else (pid in has_schedule_ids)
        # 历史是否传过（白名单口径）+ 最近一次上传归属月，供前端区分
        # 「本月未上传 · 上次上传 9 月」与「从未上传」两种不同状态。
        p["has_schedule_plan_ever"] = pid in has_schedule_ids
        p["schedule_upload_month"] = last_schedule_months.get(pid)
        plans = plans_map.get(pid, [])
        actuals = actuals_map.get(pid, {})
        nodes = enrich_rows(plans, actuals, durations=durations_map.get(pid))

        # 风险等级：历史逾期 > 今日未完成 > 正常
        # （未来日期的 in_progress「提前进行中」不算预警；今日 in_progress 须 actual < plan 才算）
        # 逾期判定规则：只统计「真逾期」（工序累计完成 < 调度令本月计划 的逾期节点）
        has_overdue = bool(compute_real_overdue(nodes, int(p.get("monthly_plan") or 0)))
        has_today_unfinished = any(
            r["status"] == "in_progress"
            and str(r["plan_date"])[:10] == today_s
            and r["actual_qty"] < r["plan_qty"]
            for r in nodes
        )

        if has_overdue:
            p["risk_level"] = "delayed"
        elif has_today_unfinished:
            p["risk_level"] = "warning"
        else:
            p["risk_level"] = "normal"

        # 整体进度：取「附件安装」工序进度
        att_plans = [n for n in plans if n["process_name"] == "附件安装"]
        att_plan_qty = sum(int(n["plan_qty"] or 0) for n in att_plans)
        att_actual_qty = sum(
            int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
            for n in att_plans
        )
        p["progress_pct"] = float(round(att_actual_qty / att_plan_qty * 100, 1)) if att_plan_qty else 0.0

        # 已完成 / 剩余套数：复用上面已算好的 att_actual_qty，不新增查询
        p["completed_sets"] = att_actual_qty
        # 剩余口径：contract_count = 项目总数（用户口径 2026-08-31 澄清）；
        # monthly_plan 是「本月待完成套数」，语义不同，**不做回退**
        _total = int(p.get("contract_count") or 0)
        p["remaining_sets"] = max(0, _total - att_actual_qty)

    # status 按风险等级在内存过滤（all / None / 其它值 → 不过滤）
    if status in ("normal", "warning", "delayed"):
        rows = [p for p in rows if p.get("risk_level") == status]

    total = len(rows)
    items = rows[skip: skip + limit]
    return items, total


# ---------- 项目编辑 / 删除 / 计划重排 ----------

def update_project(project_id: int, data: dict) -> None:
    """更新项目信息（仅更新 data 中出现的字段）。"""
    from database import update_project as _fn
    _fn(project_id, data)


def delete_project(project_id: int) -> None:
    """删除项目（级联删除工序/异常/里程碑等关联数据，行为与原版一致）。"""
    from database import delete_project as _fn
    _fn(project_id)
def get_node_plan_by_id(node_id: int) -> dict | None:
    """按 id 查询单个节点计划。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM process_node_plans WHERE id = %s", (node_id,))
            return cur.fetchone()
    finally:
        conn.close()


def create_node_exception(exc: dict) -> int:
    """新增异常记录，返回 id。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO node_exceptions
                  (project_id, node_id, process_name, plan_date, responsibility_category,
                   reason_detail, handler, planned_close_date, measures, status)
                VALUES
                  (%(project_id)s, %(node_id)s, %(process_name)s, %(plan_date)s,
                   %(responsibility_category)s, %(reason_detail)s, %(handler)s,
                   %(planned_close_date)s, %(measures)s, %(status)s)
                """,
                exc,
            )
            return cur.lastrowid
    finally:
        conn.close()


def get_node_exceptions_by_project(project_id: int) -> list[dict]:
    """查询项目下所有异常（按创建时间倒序）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM node_exceptions WHERE project_id = %s ORDER BY created_at DESC",
                (project_id,),
            )
            return [row for row in cur.fetchall()]
    finally:
        conn.close()


def get_node_exception_by_id(exc_id: int) -> dict | None:
    """按 id 查询单条异常。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM node_exceptions WHERE id = %s", (exc_id,))
            return cur.fetchone()
    finally:
        conn.close()


def update_node_exception(exc_id: int, fields: dict) -> bool:
    """更新异常（仅允许白名单字段；status=closed 时自动写 closed_at）。"""
    allowed = {"responsibility_category", "reason_detail", "handler",
               "planned_close_date", "measures", "status"}
    sets = [f"{k}=%({k})s" for k in fields if k in allowed]
    if not sets:
        return False
    fields["id"] = exc_id
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = f"UPDATE node_exceptions SET {', '.join(sets)}, updated_at=NOW() WHERE id = %(id)s"
            if fields.get("status") == "closed" and "closed_at" not in fields:
                sql = sql.replace("updated_at=NOW()", "updated_at=NOW(), closed_at=NOW()")
            cur.execute(sql, fields)
            return cur.rowcount > 0
    finally:
        conn.close()


def get_node_exceptions_by_node(node_id: int) -> list[dict]:
    """按 node_id 查询异常（供弹窗展示，按创建时间倒序）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM node_exceptions WHERE node_id = %s ORDER BY created_at DESC",
                (node_id,),
            )
            return [row for row in cur.fetchall()]
    finally:
        conn.close()


# ---------- 用户（认证：大区行级隔离 v5.0） ----------

def upsert_user(username: str, password_hash: str, role: str,
                big_area_name: str = '', status: str = 'active') -> int:
    """插入或更新用户（唯一键 username；已存在保留原密码哈希），返回用户 id。"""
    from database import upsert_user as _fn
    return getattr(_fn, "__wrapped__", _fn)(username, password_hash, role, big_area_name, status)


def get_user_by_username(username: str) -> dict | None:
    """按用户名查询用户（不存在返回 None）。"""
    from database import get_user_by_username as _fn
    return getattr(_fn, "__wrapped__", _fn)(username)


def get_user_by_id(uid: int) -> dict | None:
    """按 id 查询用户（不存在返回 None）。"""
    from database import get_user_by_id as _fn
    return getattr(_fn, "__wrapped__", _fn)(uid)


def get_closed_exceptions_by_project(project_id: int) -> list[dict]:
    """查询项目下所有已关闭的历史异常记录（按关闭时间倒序）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, project_id, node_id, process_name, plan_date,
                       responsibility_category, reason_detail, handler,
                       planned_close_date, measures, status, created_at, updated_at, closed_at
                FROM node_exceptions
                WHERE project_id = %s AND status = 'closed'
                ORDER BY closed_at DESC, updated_at DESC
                """,
                (project_id,),
            )
            return [row for row in cur.fetchall()]
    finally:
        conn.close()
