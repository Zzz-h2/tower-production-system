"""
database.py — 塔筒生产进度管控系统数据库模块
MySQL (PyMySQL) 数据库初始化、连接管理、基础 CRUD 操作

Author: Senior Developer
Date: 2026-08-03
Updated: 2026-08-XX (SQLite → MySQL 迁移)
"""

import logging
import os
from datetime import datetime
from typing import Optional, Any

import pymysql
import pymysql.cursors

from backend.app.core.config import MYSQL_CONFIG

logger = logging.getLogger(__name__)

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
            logger.info("[DB] Database initialized: %s", MYSQL_CONFIG['database'])
        else:
            logger.info("[DB] Database already exists: %s", MYSQL_CONFIG['database'])
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
                        big_area_person = %s,
                        updated_at = %s
                    WHERE id = %s
                """, (
                    data.get('last_month_output', 0),
                    data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data.get('plan_start_date'),
                    data.get('plan_end_date'),
                    data.get('big_area_person', '') or '',
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
                         delivery_person, big_area_person, machine_type, plan_start_date, plan_end_date,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data['project_name'], data['factory_name'],
                    data.get('last_month_output', 0), data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data['delivery_person'], data.get('big_area_person', '') or '',
                    machine_type,
                    data.get('plan_start_date'),
                    data.get('plan_end_date'), now, now
                ))
                conn.commit()
                return cursor.lastrowid, True
    finally:
        conn.close()


# 首页项目列表不做缓存：风险等级随日期实时变化，缓存会导致首页显示过期状态。
# （数据量小（项目×12工序），实时查询毫秒级，保证日期推移后首页立即同步。）
def get_all_projects(status_filter: Optional[str] = None,
                     big_area_person: Optional[str] = None) -> list[dict]:
    """获取所有项目列表（基础字段；风险/进度由 backend 基于 node_plans 实时计算覆盖）。

    big_area_person 非 None 时追加 ``AND p.big_area_person = %s``（大区行级隔离）。
    """
    conn = get_connection()
    try:
        clauses = []
        params = []
        if status_filter:
            clauses.append("p.status = %s")
            params.append(status_filter)
        if big_area_person:
            clauses.append("p.big_area_person = %s")
            params.append(big_area_person)
        where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT p.* FROM projects p
                {where_clause}
                ORDER BY p.updated_at DESC
            """, tuple(params))
            rows = []
            for row in cursor.fetchall():
                d = dict(row)
                d.setdefault('risk_level', 'normal')
                d.setdefault('progress_pct', 0)
                rows.append(d)
            return rows
    finally:
        conn.close()

def get_all_big_area_persons() -> list[str]:
    """获取所有项目的大区负责人（去重、非空、排序），供主页面下拉框使用。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT big_area_person FROM projects
                WHERE big_area_person IS NOT NULL AND big_area_person != ''
                ORDER BY big_area_person
            """)
            return [row['big_area_person'] for row in cursor.fetchall()]
    finally:
        conn.close()


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
                     'delivery_person', 'big_area_person', 'plan_start_date', 'plan_end_date', 
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
    """删除项目（应用层级联：工序计划/实际进度/异常先删，再删项目主表；里程碑由外键 cascade 自动清理）。

    说明：三张无外键子表（node_actual_progress / node_exceptions / process_node_plans）在
    db_schema_mysql.sql 中已补充 projects(id) 的 ON DELETE CASCADE 外键；
    此处的逐表删除是兼容「建库时尚未带外键的存量库」的兜底，两路叠加互不影响。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 先清三张无外键的子表，避免孤儿行（顺序：子→父）
            cursor.execute("DELETE FROM node_actual_progress WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM node_exceptions WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM process_node_plans WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()
    finally:
        conn.close()

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


def _chunked(seq: list[int], size: int = 900) -> list[list[int]]:
    """把 id 列表切成固定大小的分片，规避 MySQL 单语句 IN 占位符上限（65535）。"""
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def get_node_plans_batch(project_ids: list[int]) -> dict[int, list[dict]]:
    """批量查询多个项目的工序节点计划，返回 {project_id: [plan, ...]}（消除列表页 N+1）。

    按 900 分片执行 IN 查询，规避 MySQL 单语句占位符上限。
    """
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            result: dict[int, list[dict]] = {}
            for chunk in _chunked(project_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(f"""
                    SELECT * FROM process_node_plans
                    WHERE project_id IN ({fmt})
                    ORDER BY project_id, process_order, plan_date
                """, chunk)
                for row in cur.fetchall():
                    d = dict(row)
                    result.setdefault(int(d["project_id"]), []).append(d)
        return result
    finally:
        conn.close()


def get_node_actuals_batch(project_ids: list[int]) -> dict[int, dict]:
    """批量查询多个项目节点实际进度，返回 {project_id: {node_plan_id: {actual_qty, report_date}}}。

    按 900 分片执行 IN 查询，规避 MySQL 单语句占位符上限。
    """
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            result: dict[int, dict] = {}
            for chunk in _chunked(project_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(f"""
                    SELECT project_id, node_plan_id, actual_qty, report_date
                    FROM node_actual_progress
                    WHERE project_id IN ({fmt})
                """, chunk)
                for row in cur.fetchall():
                    pid = int(row["project_id"])
                    result.setdefault(pid, {})[int(row["node_plan_id"])] = {
                        "actual_qty": int(row["actual_qty"] or 0),
                        "report_date": row["report_date"],
                    }
        return result
    finally:
        conn.close()


def get_attachment_plans_by_month(month_start: str, month_end: str, month: str | None = None,
                                  big_area_person: str | None = None) -> list[dict]:
    """取某月内所有『附件安装』工序节点计划（出品排名统计源）。

    month 传入时约束项目 created_at 月份（调度令月份口径，三页联动一致），并带回 delivery_person。
    big_area_person 非 None 时追加 ``AND p.big_area_person = %s``（大区行级隔离）。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if month:
                sql = """
                    SELECT pnp.id, pnp.project_id, pnp.process_name, pnp.plan_date, pnp.plan_qty,
                           p.delivery_person
                    FROM process_node_plans pnp
                    JOIN projects p ON pnp.project_id = p.id
                    WHERE pnp.process_name = '附件安装'
                      AND DATE_FORMAT(p.created_at, '%%Y-%%m') = %s
                      AND pnp.plan_date >= %s AND pnp.plan_date < %s
                """
                params = [month, month_start, month_end]
                if big_area_person:
                    sql += " AND p.big_area_person = %s"
                    params.append(big_area_person)
                cur.execute(sql, params)
            else:
                sql = """
                    SELECT pnp.id, pnp.project_id, pnp.process_name, pnp.plan_date, pnp.plan_qty,
                           p.delivery_person
                    FROM process_node_plans pnp
                    JOIN projects p ON pnp.project_id = p.id
                    WHERE pnp.process_name = '附件安装'
                      AND pnp.plan_date >= %s AND pnp.plan_date < %s
                """
                params = [month_start, month_end]
                if big_area_person:
                    sql += " AND p.big_area_person = %s"
                    params.append(big_area_person)
                cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_actuals_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度，返回 {node_plan_id: actual_qty}（消除 N+1）。

    按 900 分片执行 IN 查询，规避 MySQL 单语句占位符上限。
    """
    if not node_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            result: dict[int, int] = {}
            for chunk in _chunked(node_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(f"""
                    SELECT node_plan_id, actual_qty
                    FROM node_actual_progress
                    WHERE node_plan_id IN ({fmt})
                """, chunk)
                for r in cur.fetchall():
                    result[int(r["node_plan_id"])] = int(r["actual_qty"] or 0)
            return result
    finally:
        conn.close()


def get_delivery_persons_by_projects(project_ids: list[int]) -> dict[int, str]:
    """批量取项目交付负责人：{project_id: delivery_person}（跳过空负责人）。

    按 900 分片执行 IN 查询，规避 MySQL 单语句占位符上限。
    """
    if not project_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            result: dict[int, str] = {}
            for chunk in _chunked(project_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(f"""
                    SELECT id, delivery_person FROM projects
                    WHERE id IN ({fmt})
                """, chunk)
                for r in cur.fetchall():
                    if r["delivery_person"]:
                        result[int(r["id"])] = str(r["delivery_person"]).strip()
            return result
    finally:
        conn.close()


def get_all_plans_by_month_and_person(month_start: str, month_end: str, person: str,
                                      big_area_person: str | None = None) -> list[dict]:
    """取某负责人当月全部工序节点计划（含项目名/机号/厂家，供逾期/提前明细）。

    big_area_person 非 None 时追加 ``AND p.big_area_person = %s``（大区行级隔离）。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT n.id, n.project_id, n.process_name, n.plan_date, n.plan_qty,
                       p.project_name, p.machine_type, p.factory_name
                FROM process_node_plans n
                JOIN projects p ON p.id = n.project_id
                WHERE p.delivery_person = %s
                  AND n.plan_date >= %s AND n.plan_date < %s
            """
            params = [person, month_start, month_end]
            if big_area_person:
                sql += " AND p.big_area_person = %s"
                params.append(big_area_person)
            sql += " ORDER BY p.id, n.process_order, n.plan_date"
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ============================================================
# 用户表（v5.0：大区行级数据隔离）
# users.username = 大区名（与 Excel 严格一致）；admin 的 big_area_name 为空
# ============================================================

def upsert_user(username: str, password_hash: str, role: str,
                big_area_name: str = '', status: str = 'active') -> int:
    """插入或更新用户（唯一键 username）。

    已存在时仅更新 big_area_name 与 status='active'（保留原密码哈希，不重置）。
    返回用户 id。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO users (username, password_hash, role, big_area_name, status)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    big_area_name = VALUES(big_area_name),
                    status = 'active'
            """, (username, password_hash, role, big_area_name, status))
            conn.commit()
            cursor.execute("SELECT id FROM users WHERE username = %s", (username,))
            row = cursor.fetchone()
            return int(row['id']) if row else 0
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[dict]:
    """按用户名查询用户（不存在返回 None）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(uid: int) -> Optional[dict]:
    """按 id 查询用户（不存在返回 None）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM users WHERE id = %s", (uid,))
            row = cursor.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


if __name__ == '__main__':
    init_database()
    print("Database initialization test passed.")
