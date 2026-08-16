# -*- coding: utf-8 -*-
"""数据库访问层：封装原 database.py 的 pymysql 连接与节点表读写。

沿用现有表结构（process_node_plans / node_actual_progress / node_exceptions 等），不重新设计。
风险等级与整体进度均由 node_plans + node_actuals 实时计算，弃用 processes 表。
"""
from datetime import date

from .config import MYSQL_CONFIG


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

def get_node_plans(project_id: int) -> list[dict]:
    """查询工序节点计划（含 id/project_id/process_name/plan_date/plan_qty/process_order）。"""
    from database import get_node_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_node_actuals(project_id: int) -> dict:
    """查询节点实际进度：{node_plan_id: {actual_qty, report_date, ...}}。"""
    from database import get_node_actuals as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def insert_node_plans(project_id: int, plans: list[dict]) -> int:
    """批量写入节点计划（先清空该项目旧计划再写入，与原版一致）。"""
    from database import insert_node_plans as _fn
    return _fn(project_id, plans)


def upsert_node_actual(project_id: int, node_plan_id: int, process_name: str,
                       actual_qty: int, report_date: str) -> None:
    """写入/更新单个节点实际进度。"""
    from database import upsert_node_actual as _fn
    _fn(project_id, node_plan_id, process_name, actual_qty, report_date)


# ---------- 项目（复用于项目列表/详情） ----------

def get_all_projects(status_filter=None) -> list[dict]:
    from database import get_all_projects as _fn
    return getattr(_fn, "__wrapped__", _fn)(status_filter)


def get_project_by_id(project_id: int) -> dict | None:
    from database import get_project_by_id as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_project_processes(project_id: int) -> list[dict]:
    from database import get_project_processes as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_project_anomalies(project_id: int) -> list[dict]:
    from database import get_project_anomalies as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_dashboard_stats() -> dict:
    """首页总览统计：与项目列表风险口径完全一致（复用 get_projects_filtered 实时计算）。

    不再基于 processes 表旧 risk_level 统计——直接复用项目列表的
    node_plans + node_actuals 实时风险判定结果，保证两者 100% 一致。
    """
    items, _ = get_projects_filtered(keyword="", person="", status="", skip=0, limit=100000)
    return {
        "total_projects": len(items),
        "warning_projects": sum(1 for p in items if p.get("risk_level") == "warning"),
        "delayed_projects": sum(1 for p in items if p.get("risk_level") == "delayed"),
        "monthly_plan_total": sum(int(p.get("monthly_plan", 0) or 0) for p in items),
    }


# ---------- 手动添加 / 调度令导入 复用封装 ----------

def upsert_project(data: dict):
    """插入或更新项目（四字段唯一键），返回 (project_id, is_new)。"""
    from database import upsert_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(data)


def get_duplicate_project(project_name: str, factory_name: str,
                          delivery_person: str, machine_type: str):
    """四字段组合查重：名称+厂家+负责人+机型 全部一致才算重复。"""
    from database import get_duplicate_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_name, factory_name, delivery_person, machine_type)


def init_project_processes(project_id: int, plan_start_date: str):
    """为项目初始化 12 道标准工序。"""
    from database import init_project_processes as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plan_start_date)


def update_project_risk_level(project_id: int):
    """根据工序状态重新计算并更新项目风险等级，返回新等级。"""
    from database import update_project_risk_level as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def insert_import_log(file_name: str, total: int, success: int, error: int, error_details: str = ""):
    """记录导入日志。"""
    from database import insert_import_log as _fn
    return getattr(_fn, "__wrapped__", _fn)(file_name, total, success, error, error_details)


# ---------- 项目列表：搜索/筛选 + 服务端分页 ----------

def get_projects_filtered(keyword: str | None = None, person: str | None = None,
                          status: str | None = None, skip: int = 0, limit: int = 10):
    """项目搜索/筛选 + 服务端分页。

    status 语义为「风险等级」（normal/warning/delayed），由 node_plans + node_actuals
    实时计算（与详情页/节点预警口径一致），因此**不能**下推到 SQL 的 projects.status
    （生命周期字段 in_progress/completed）。
    实现：取全量项目 → keyword/person 内存过滤 → 计算 risk_level/progress_pct →
    风险等级内存过滤 → 切片分页。
    """
    # status 不再作为生命周期条件下推，统一取全量项目
    rows = get_all_projects(None)

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

    # 风险等级 + 整体进度：基于 node_plans + node_actuals 实时计算（弃用 processes 表）
    from ..services.node_service import enrich_rows
    today_s = str(date.today())
    for p in rows:
        pid = p["id"]
        plans = get_node_plans(pid)
        actuals = get_node_actuals(pid)
        nodes = enrich_rows(plans, actuals)

        # 风险等级：历史逾期 > 今日未完成 > 正常
        # （未来日期的 in_progress「提前进行中」不算预警；今日 in_progress 须 actual < plan 才算）
        has_overdue = any(r["status"] == "overdue" for r in nodes)
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


def regenerate_process_plan(project_id: int, plan_start_date: str) -> int:
    """按新开工日期重新生成 12 道工序计划，返回生成的工序数。"""
    from database import regenerate_process_plan as _fn
    return _fn(project_id, plan_start_date)


# ---------- 节点异常提报（node_exceptions） ----------

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
