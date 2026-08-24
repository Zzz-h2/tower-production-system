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

def upsert_project(data: dict):
    """插入或更新项目（四字段唯一键），返回 (project_id, is_new)。"""
    from database import upsert_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(data)


def get_duplicate_project(project_name: str, factory_name: str,
                          delivery_person: str, machine_type: str):
    """四字段组合查重：名称+厂家+负责人+机型 全部一致才算重复。"""
    from database import get_duplicate_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_name, factory_name, delivery_person, machine_type)
def insert_import_log(file_name: str, total: int, success: int, error: int, error_details: str = ""):
    """记录导入日志。"""
    from database import insert_import_log as _fn
    return getattr(_fn, "__wrapped__", _fn)(file_name, total, success, error, error_details)


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
    month: 调度令月份（projects.created_at 年月，如 '2026-08'），三页联动共享口径。
    big_area_person: 大区负责人 精确相等过滤。
    """
    # status 不再作为生命周期条件下推，统一取全量项目（big_area_person 下推 SQL 做行级隔离）
    rows = get_all_projects(None, big_area_person)

    # ★ 按调度令月份（created_at 年月）过滤
    if month:
        rows = [p for p in rows if str(p.get("created_at", ""))[:7] == month]

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
    today_s = str(date.today())

    # 一次性批量查询（消除 N+1：原逻辑每项目 2 次 DB 往返 → 现在全程仅 3 次）
    all_pids = [p["id"] for p in rows]
    plans_map = get_node_plans_batch(all_pids)      # 1 次查询
    actuals_map = get_node_actuals_batch(all_pids)  # 1 次查询

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT project_id FROM process_node_plans")
            has_schedule_ids = {r["project_id"] for r in cur.fetchall()}
    finally:
        conn.close()

    for p in rows:
        pid = p["id"]
        p["has_schedule_plan"] = pid in has_schedule_ids
        plans = plans_map.get(pid, [])
        actuals = actuals_map.get(pid, {})
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
