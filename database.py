"""
database.py — 塔筒生产进度管控系统数据库模块
MySQL (PyMySQL) 数据库初始化、连接管理、基础 CRUD 操作

Author: Senior Developer
Date: 2026-08-03
Updated: 2026-08-XX (SQLite → MySQL 迁移)
"""

import os
from datetime import datetime
from typing import Optional, Any

import pymysql
import pymysql.cursors

from backend.app.core.config import MYSQL_CONFIG

try:
    import streamlit as st  # 仅用于 @st.cache_data 只读查询缓存
except Exception:  # 后端（FastAPI）环境无 streamlit：缓存降级为空操作，保证纯后端可导入
    class _NoOpCache:
        def __call__(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    class _StStub:
        cache_data = _NoOpCache()
    st = _StStub()

# MySQL schema 文件路径（SQLite → MySQL 迁移后使用）
MYSQL_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_schema_mysql.sql')


def get_connection() -> pymysql.Connection:
    """获取 MySQL 数据库连接，自动开启外键约束"""
    conn = pymysql.connect(
        **MYSQL_CONFIG,
        cursorclass=pymysql.cursors.DictCursor,  # 返回字典式行对象
    )
    with conn.cursor() as cursor:
        cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    return conn


def _execute_script(conn: pymysql.Connection, script: str) -> None:
    """按分号拆分 SQL 脚本逐条执行（替代 SQLite 驱动的一次性整脚本执行）。

    MySQL 驱动不支持一次执行多语句脚本；此处先剔除纯注释行，
    再按分号拆分逐条执行。保留换行以便行内 `-- ` 注释正常结束。
    """
    cursor = conn.cursor()
    try:
        for statement in script.split(';'):
            lines = [ln for ln in statement.splitlines()
                     if not ln.strip().startswith('--')]
            stmt = '\n'.join(lines).strip()
            if stmt:
                cursor.execute(stmt)
    finally:
        cursor.close()


def init_database() -> None:
    """初始化数据库：读取 MySQL schema 文件建表；表已存在则跳过。"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND table_name = 'projects'"
        )
        if cursor.fetchone()['cnt'] == 0:
            if not os.path.exists(MYSQL_SCHEMA_PATH):
                raise FileNotFoundError(f"Schema file not found: {MYSQL_SCHEMA_PATH}")
            with open(MYSQL_SCHEMA_PATH, 'r', encoding='utf-8') as f:
                schema_sql = f.read()
            _execute_script(conn, schema_sql)
            conn.commit()
            print(f"[DB] Database initialized: {MYSQL_CONFIG['database']}")
        else:
            print(f"[DB] Database already exists: {MYSQL_CONFIG['database']}")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


# ============================================================
# 项目 CRUD 操作
# ============================================================

def insert_project(data: dict) -> int:
    """插入新项目，返回项目ID"""
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO projects 
                    (project_name, factory_name, last_month_output, monthly_plan, 
                     delivery_person, plan_start_date, plan_end_date,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['project_name'],
                data['factory_name'],
                data.get('last_month_output', 0),
                data['monthly_plan'],
                data['delivery_person'],
                data.get('plan_start_date'),
                data.get('plan_end_date'),
                now, now
            ))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def upsert_project(data: dict) -> tuple[int, bool]:
    """
    插入或更新项目（以 项目名称+钢塔厂家+交付负责人+机型 四字段为唯一键）。
    返回 (project_id, is_new)。
    """
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        machine_type = data.get('machine_type', '') or ''
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT id FROM projects 
                WHERE project_name = %s AND factory_name = %s
                  AND delivery_person = %s AND machine_type = %s
            """, (data['project_name'], data['factory_name'],
                  data['delivery_person'], machine_type))
            existing = cursor.fetchone()

            if existing:
                # 更新已有项目（四字段唯一键不变，机型不更新）
                cursor.execute("""
                    UPDATE projects SET
                        last_month_output = %s, monthly_plan = %s,
                        monthly_total_plan = %s,
                        plan_start_date = %s, plan_end_date = %s,
                        updated_at = %s
                    WHERE id = %s
                """, (
                    data.get('last_month_output', 0),
                    data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data.get('plan_start_date'),
                    data.get('plan_end_date'),
                    now,
                    existing['id']
                ))
                conn.commit()
                return existing['id'], False
            else:
                # 插入新项目（含机型）
                cursor.execute("""
                    INSERT INTO projects 
                        (project_name, factory_name, last_month_output, monthly_plan,
                         monthly_total_plan,
                         delivery_person, machine_type, plan_start_date, plan_end_date,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data['project_name'], data['factory_name'],
                    data.get('last_month_output', 0), data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data['delivery_person'], machine_type,
                    data.get('plan_start_date'),
                    data.get('plan_end_date'), now, now
                ))
                conn.commit()
                return cursor.lastrowid, True
    finally:
        conn.close()


# 首页项目列表不做缓存：风险等级随日期实时变化，缓存会导致首页显示过期状态。
# （数据量小（项目×12工序），实时查询毫秒级，保证日期推移后首页立即同步。）
def get_all_projects(status_filter: Optional[str] = None) -> list[dict]:
    """获取所有项目列表（基础字段；风险/进度由 backend 基于 node_plans 实时计算覆盖）。"""
    conn = get_connection()
    try:
        where_clause = "WHERE p.status = %s" if status_filter else ""
        params = (status_filter,) if status_filter else ()

        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT p.* FROM projects p
                {where_clause}
                ORDER BY p.updated_at DESC
            """, params)
            rows = []
            for row in cursor.fetchall():
                d = dict(row)
                d.setdefault('risk_level', 'normal')
                d.setdefault('progress_pct', 0)
                rows.append(d)
            return rows
    finally:
        conn.close()

@st.cache_data(ttl=300, show_spinner=False)
def get_project_by_id(project_id: int) -> Optional[dict]:
    """根据ID获取单个项目（基础字段；风险/进度由路由基于 node_plans 实时计算覆盖）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT p.* FROM projects p WHERE p.id = %s", (project_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d.setdefault('risk_level', 'normal')
                d.setdefault('progress_pct', 0)
                return d
            return None
    finally:
        conn.close()

def get_project_by_name(project_name: str) -> Optional[dict]:
    """根据项目名称查询项目（用于手动添加的重复校验）。

    Args:
        project_name: 项目名称

    Returns:
        项目记录 dict（含 id 等字段），不存在返回 None
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, project_name, factory_name FROM projects WHERE project_name = %s LIMIT 1",
                (project_name,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_duplicate_project(project_name: str, factory_name: str,
                          delivery_person: str, machine_type: str) -> Optional[dict]:
    """四字段组合查重：项目名称+钢塔厂家+交付负责人+机型 全部一致才算重复。

    Args:
        project_name: 项目名称
        factory_name: 钢塔厂家
        delivery_person: 交付负责人
        machine_type: 机型

    Returns:
        完全重复的项目记录 dict，不存在返回 None
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """SELECT id, project_name, factory_name, delivery_person, machine_type
                   FROM projects
                   WHERE project_name = %s AND factory_name = %s
                     AND delivery_person = %s AND machine_type = %s
                   LIMIT 1""",
                (project_name, factory_name, delivery_person, machine_type or ''),
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def update_project(project_id: int, data: dict) -> None:
    """更新项目信息"""
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fields = []
        values = []
        for key in ['project_name', 'factory_name', 'last_month_output', 'monthly_plan',
                     'delivery_person', 'plan_start_date', 'plan_end_date', 
                     'risk_level', 'status', 'remarks']:
            if key in data:
                fields.append(f"{key} = %s")
                values.append(data[key])
        fields.append("updated_at = %s")
        values.append(now)
        values.append(project_id)

        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def delete_project(project_id: int) -> None:
    """删除项目（级联删除工序、异常、里程碑）"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()
    finally:
        conn.close()
@st.cache_data(ttl=300, show_spinner=False)
def insert_import_log(file_name: str, total: int, success: int, 
                       error: int, error_details: str = '') -> None:
    """记录导入日志"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO import_logs (file_name, total_rows, success_rows, 
                                          error_rows, error_details)
                VALUES (%s, %s, %s, %s, %s)
            """, (file_name, total, success, error, error_details))
            conn.commit()
    finally:
        conn.close()


# ============================================================
# 配置管理
# ============================================================

def get_config(key: str) -> Optional[str]:
    """获取系统配置值"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT config_value FROM system_config WHERE config_key = %s", (key,)
            )
            row = cursor.fetchone()
            return row['config_value'] if row else None
    finally:
        conn.close()
# ============================================================
# v4.0: 工序节点计划管控（排产矩阵 → process_node_plans / node_actual_progress）
# 排产工序独立于 processes 表 12 道制造工序，process_name 独立存储。
# 全部走 MySQL，pymysql 风格：%s 占位、显式 cursor。
# ============================================================

def insert_node_plans(project_id: int, plans: list[dict]) -> int:
    """先清空该项目全部节点计划，再批量插入新计划（覆盖式导入）。

    Args:
        project_id: 项目ID
        plans: list[dict]，每项含
            process_name(str) / process_order(int) / plan_date('YYYY-MM-DD') / plan_qty(int)

    Returns:
        int: 实际插入的节点计划条数
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM process_node_plans WHERE project_id = %s",
                (project_id,)
            )
            if plans:
                cursor.executemany("""
                    INSERT INTO process_node_plans
                        (project_id, process_name, process_order, plan_date, plan_qty)
                    VALUES (%s, %s, %s, %s, %s)
                """, [(
                    project_id,
                    str(p['process_name']).strip(),
                    int(p.get('process_order', 0) or 0),
                    str(p['plan_date'])[:10],          # 统一 'YYYY-MM-DD' 字符串
                    int(p.get('plan_qty', 1) or 1),
                ) for p in plans])
            conn.commit()
            return len(plans)
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_node_plans(project_id: int) -> list[dict]:
    """获取项目的全部工序节点计划，按 工序顺序 + 计划日期 排序。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM process_node_plans
                WHERE project_id = %s
                ORDER BY process_order, plan_date
            """, (project_id,))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def upsert_node_actual(project_id: int, node_plan_id: int, process_name: str,
                       actual_qty: int, report_date: str) -> None:
    """插入或更新节点实际完成套数（唯一键 uk_proj_node，同节点可重复修改）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO node_actual_progress
                    (project_id, node_plan_id, process_name, actual_qty, report_date)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    actual_qty = VALUES(actual_qty),
                    report_date = VALUES(report_date)
            """, (project_id, node_plan_id, str(process_name).strip(),
                  int(actual_qty or 0), str(report_date)[:10]))
            conn.commit()
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_node_actuals(project_id: int) -> dict:
    """获取项目全部节点实际进度，返回 {node_plan_id: {"actual_qty": int, "report_date": date}}。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT node_plan_id, actual_qty, report_date FROM node_actual_progress
                WHERE project_id = %s
            """, (project_id,))
            return {
                int(row['node_plan_id']): {
                    "actual_qty": int(row['actual_qty'] or 0),
                    "report_date": row['report_date'],  # 保持原类型（date 或 str）
                }
                for row in cursor.fetchall()
            }
    finally:
        conn.close()


def get_node_plans_batch(project_ids: list[int]) -> dict[int, list[dict]]:
    """批量查询多个项目的工序节点计划，返回 {project_id: [plan, ...]}（消除列表页 N+1）。"""
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(project_ids))
            cur.execute(f"""
                SELECT * FROM process_node_plans
                WHERE project_id IN ({fmt})
                ORDER BY project_id, process_order, plan_date
            """, project_ids)
            rows = cur.fetchall()
        result: dict[int, list[dict]] = {}
        for row in rows:
            d = dict(row)
            result.setdefault(int(d["project_id"]), []).append(d)
        return result
    finally:
        conn.close()


def get_node_actuals_batch(project_ids: list[int]) -> dict[int, dict]:
    """批量查询多个项目节点实际进度，返回 {project_id: {node_plan_id: {actual_qty, report_date}}}。"""
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(project_ids))
            cur.execute(f"""
                SELECT project_id, node_plan_id, actual_qty, report_date
                FROM node_actual_progress
                WHERE project_id IN ({fmt})
            """, project_ids)
            rows = cur.fetchall()
        result: dict[int, dict] = {}
        for row in rows:
            pid = int(row["project_id"])
            result.setdefault(pid, {})[int(row["node_plan_id"])] = {
                "actual_qty": int(row["actual_qty"] or 0),
                "report_date": row["report_date"],
            }
        return result
    finally:
        conn.close()


def get_attachment_plans_by_month(month_start: str, month_end: str) -> list[dict]:
    """取某月内所有『附件安装』工序节点计划（出品排名统计源）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, project_id, process_name, plan_date, plan_qty
                FROM process_node_plans
                WHERE process_name = '附件安装'
                  AND plan_date >= %s AND plan_date < %s
            """, (month_start, month_end))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_actuals_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度，返回 {node_plan_id: actual_qty}（消除 N+1）。"""
    if not node_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(node_ids))
            cur.execute(f"""
                SELECT node_plan_id, actual_qty
                FROM node_actual_progress
                WHERE node_plan_id IN ({fmt})
            """, node_ids)
            return {int(r["node_plan_id"]): int(r["actual_qty"] or 0) for r in cur.fetchall()}
    finally:
        conn.close()


def get_delivery_persons_by_projects(project_ids: list[int]) -> dict[int, str]:
    """批量取项目交付负责人：{project_id: delivery_person}（跳过空负责人）。"""
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            fmt = ",".join(["%s"] * len(project_ids))
            cur.execute(f"""
                SELECT id, delivery_person FROM projects
                WHERE id IN ({fmt})
            """, project_ids)
            return {
                int(r["id"]): str(r["delivery_person"]).strip()
                for r in cur.fetchall() if r["delivery_person"]
            }
    finally:
        conn.close()


def get_all_plans_by_month_and_person(month_start: str, month_end: str, person: str) -> list[dict]:
    """取某负责人当月全部工序节点计划（含项目名/机号/厂家，供逾期/提前明细）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT n.id, n.project_id, n.process_name, n.plan_date, n.plan_qty,
                       p.project_name, p.machine_type, p.factory_name
                FROM process_node_plans n
                JOIN projects p ON p.id = n.project_id
                WHERE p.delivery_person = %s
                  AND n.plan_date >= %s AND n.plan_date < %s
                ORDER BY p.id, n.process_order, n.plan_date
            """, (person, month_start, month_end))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


if __name__ == '__main__':
    init_database()
    print("Database initialization test passed.")
