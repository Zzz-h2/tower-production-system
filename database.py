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

from config import MYSQL_CONFIG

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
    """获取所有项目列表（含进度统计；风险等级实时计算，不缓存）"""
    conn = get_connection()
    try:
        where_clause = "WHERE p.status = %s" if status_filter else ""
        params = (status_filter,) if status_filter else ()

        with conn.cursor() as cursor:
            cursor.execute(f"""
                SELECT 
                    p.*,
                    COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) AS completed_count,
                    ROUND(
                        COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) * 100.0 / 12, 1
                    ) AS progress_pct,
                    -- 实时风险等级：取所有工序中最大滞后天数判断（每日实时计算，不再依赖静态字段）
                    CASE 
                        WHEN MAX(
                            CASE 
                                WHEN pr.actual_end_date IS NOT NULL THEN 
                                    -- 已完成：按实际完成 vs 计划结束算滞后
                                    COALESCE(DATEDIFF(pr.actual_end_date, pr.plan_end_date), 0)
                                WHEN pr.plan_end_date IS NOT NULL AND CURDATE() > pr.plan_end_date THEN 
                                    -- 未完成且已超计划结束：按今天 vs 计划结束算滞后
                                    DATEDIFF(CURDATE(), pr.plan_end_date)
                                ELSE 0
                            END
                        ) >= 2 THEN 'delayed'
                        WHEN MAX(
                            CASE 
                                WHEN pr.actual_end_date IS NOT NULL THEN 
                                    COALESCE(DATEDIFF(pr.actual_end_date, pr.plan_end_date), 0)
                                WHEN pr.plan_end_date IS NOT NULL AND CURDATE() > pr.plan_end_date THEN 
                                    DATEDIFF(CURDATE(), pr.plan_end_date)
                                ELSE 0
                            END
                        ) >= 1 THEN 'warning'
                        ELSE 'normal'
                    END AS risk_level_live
                FROM projects p
                LEFT JOIN processes pr ON p.id = pr.project_id
                {where_clause}
                GROUP BY p.id
                ORDER BY 
                    CASE risk_level_live
                        WHEN 'delayed' THEN 1 
                        WHEN 'warning' THEN 2 
                        WHEN 'normal' THEN 3 
                    END,
                    p.updated_at DESC
            """, params)

            rows = []
            for row in cursor.fetchall():
                d = dict(row)
                # p.* 展开含静态 risk_level 列，实时计算列用独立别名避免冲突，此处统一映射回 risk_level
                d['risk_level'] = d.pop('risk_level_live')
                rows.append(d)
            return rows
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_project_by_id(project_id: int) -> Optional[dict]:
    """根据ID获取单个项目"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    p.*,
                    COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) AS completed_count,
                    ROUND(
                        COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) * 100.0 / 12, 1
                    ) AS progress_pct,
                    -- 实时风险等级（与 get_all_projects 口径一致：取所有工序最大滞后天数）
                    CASE 
                        WHEN MAX(
                            CASE 
                                WHEN pr.actual_end_date IS NOT NULL THEN 
                                    COALESCE(DATEDIFF(pr.actual_end_date, pr.plan_end_date), 0)
                                WHEN pr.plan_end_date IS NOT NULL AND CURDATE() > pr.plan_end_date THEN 
                                    DATEDIFF(CURDATE(), pr.plan_end_date)
                                ELSE 0
                            END
                        ) >= 2 THEN 'delayed'
                        WHEN MAX(
                            CASE 
                                WHEN pr.actual_end_date IS NOT NULL THEN 
                                    COALESCE(DATEDIFF(pr.actual_end_date, pr.plan_end_date), 0)
                                WHEN pr.plan_end_date IS NOT NULL AND CURDATE() > pr.plan_end_date THEN 
                                    DATEDIFF(CURDATE(), pr.plan_end_date)
                                ELSE 0
                            END
                        ) >= 1 THEN 'warning'
                        ELSE 'normal'
                    END AS risk_level_live
                FROM projects p
                LEFT JOIN processes pr ON p.id = pr.project_id
                WHERE p.id = %s
                GROUP BY p.id
            """, (project_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                # 同 get_all_projects：实时列独立别名避免与 p.* 静态 risk_level 冲突
                d['risk_level'] = d.pop('risk_level_live')
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


# ============================================================
# 工序操作
# ============================================================

def init_project_processes(project_id: int, plan_start_date: str) -> None:
    """
    为项目初始化12道标准工序。
    若工序已存在则跳过（避免重复初始化）。
    """
    from utils.business_logic import PROCESS_NAMES, PROCESS_DAYS  # 延迟导入避免循环

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM processes WHERE project_id = %s",
                (project_id,)
            )
            if cursor.fetchone()['cnt'] > 0:
                return  # 已初始化，跳过

            # 使用正向计划生成函数计算计划日期
            from utils.business_logic import generate_forward_plan
            from utils.workday_calendar import parse_date

            start_date = parse_date(plan_start_date)
            forward_plan = generate_forward_plan(start_date)

            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            for i, (name, days, plan) in enumerate(
                zip(PROCESS_NAMES, PROCESS_DAYS, forward_plan), 1
            ):
                cursor.execute("""
                    INSERT INTO processes 
                        (project_id, process_order, process_name, standard_days,
                         plan_start_date, plan_end_date, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    project_id, i, name, days,
                    plan['plan_start'].strftime('%Y-%m-%d'),
                    plan['plan_end'].strftime('%Y-%m-%d'),
                    now, now
                ))
            conn.commit()
    finally:
        conn.close()


def regenerate_process_plan(project_id: int, plan_start_date: str) -> int:
    """
    修改项目计划开工日期后，重算12道工序的计划开始/结束日期。
    若工序不存在则初始化。返回更新的工序数。

    Args:
        project_id: 项目ID
        plan_start_date: 新计划开工日期

    Returns:
        int: 更新/创建的工序数量
    """
    from utils.business_logic import PROCESS_NAMES, PROCESS_DAYS, generate_forward_plan
    from utils.workday_calendar import parse_date

    conn = get_connection()
    try:
        start_date = parse_date(plan_start_date)
        if start_date is None:
            return 0
        forward_plan = generate_forward_plan(start_date)
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        count = 0

        with conn.cursor() as cursor:
            # 工序已存在 → 更新计划日期；不存在 → 插入
            for i, (name, days, plan) in enumerate(
                zip(PROCESS_NAMES, PROCESS_DAYS, forward_plan), 1
            ):
                ps = plan['plan_start'].strftime('%Y-%m-%d')
                pe = plan['plan_end'].strftime('%Y-%m-%d')
                cursor.execute(
                    "SELECT id FROM processes WHERE project_id = %s AND process_order = %s",
                    (project_id, i)
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute("""
                        UPDATE processes SET
                            process_name = %s, standard_days = %s,
                            plan_start_date = %s, plan_end_date = %s, updated_at = %s
                        WHERE id = %s
                    """, (name, days, ps, pe, now, row['id']))
                else:
                    cursor.execute("""
                        INSERT INTO processes
                            (project_id, process_order, process_name, standard_days,
                             plan_start_date, plan_end_date, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (project_id, i, name, days, ps, pe, now, now))
                count += 1

            conn.commit()
            return count
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_project_processes(project_id: int) -> list[dict]:
    """获取项目的所有工序列表"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM processes 
                WHERE project_id = %s 
                ORDER BY process_order
            """, (project_id,))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_process(process_id: int, data: dict) -> None:
    """更新工序进度（含 status 写入前校验，防止 CHECK 约束冲突）"""
    # status 字段合法枚举值（需与 db_schema_mysql.sql 中 CHECK 约束严格一致）
    VALID_STATUSES = {'not_started', 'in_progress', 'completed', 'delayed'}

    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        fields = []
        values = []
        for key in ['actual_start_date', 'actual_end_date', 'status', 
                     'lag_days', 'completion_pct', 'updated_by',
                     'plan_start_date', 'plan_end_date']:
            if key in data:
                val = data[key]
                # status 字段写入前校验：strip 首尾空格 + 检查是否合法
                if key == 'status':
                    val = str(val).strip() if val else 'not_started'
                    if val not in VALID_STATUSES:
                        val = 'not_started'  # 非法值兜底
                fields.append(f"{key} = %s")
                values.append(val)
        fields.append("updated_at = %s")
        values.append(now)
        values.append(process_id)

        with conn.cursor() as cursor:
            cursor.execute(f"UPDATE processes SET {', '.join(fields)} WHERE id = %s", values)
            conn.commit()
    finally:
        conn.close()


def update_project_risk_level(project_id: int) -> str:
    """
    根据工序状态重新计算并更新项目风险等级。
    返回新的风险等级。
    """
    from utils.business_logic import judge_warning_level  # 延迟导入

    processes = get_project_processes(project_id)
    risk_level, _ = judge_warning_level(processes)

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE projects SET risk_level = %s, updated_at = %s WHERE id = %s",
                (risk_level, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), project_id)
            )
            conn.commit()
    finally:
        conn.close()

    return risk_level


# ============================================================
# 异常管理操作
# ============================================================

def insert_anomaly(data: dict) -> int:
    """新增异常记录"""
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO anomalies 
                    (project_id, process_id, process_name, anomaly_reason,
                     responsibility, estimated_resolve_date, measures, handler,
                     status, created_at, updated_at, created_by, updated_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['project_id'], data['process_id'], data['process_name'],
                data['anomaly_reason'], data['responsibility'],
                data.get('estimated_resolve_date'), data.get('measures'),
                data.get('handler', 'system'), 'open',
                now, now, data.get('created_by', 'system'), data.get('updated_by', 'system')
            ))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_project_anomalies(project_id: int) -> list[dict]:
    """获取项目的所有异常记录"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM anomalies 
                WHERE project_id = %s 
                ORDER BY created_at DESC
            """, (project_id,))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def update_anomaly_status(anomaly_id: int, status: str, 
                           actual_resolve_date: Optional[str] = None,
                           handler: Optional[str] = None) -> None:
    """更新异常处理状态（闭环）"""
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cursor:
            if actual_resolve_date:
                cursor.execute("""
                    UPDATE anomalies SET 
                        status = %s, actual_resolve_date = %s, updated_at = %s
                    WHERE id = %s
                """, (status, actual_resolve_date, now, anomaly_id))
            else:
                cursor.execute("""
                    UPDATE anomalies SET status = %s, updated_at = %s WHERE id = %s
                """, (status, now, anomaly_id))
            conn.commit()
    finally:
        conn.close()


# ============================================================
# 统计查询操作
# ============================================================

@st.cache_data(ttl=300, show_spinner=False)
def get_dashboard_stats() -> dict:
    """获取看板统计数据（风险计数基于实时工序状态，与项目列表口径一致）"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT 
                    COUNT(*) AS total_projects,
                    COUNT(CASE WHEN COALESCE(risk_calc.risk_level, 'normal') = 'normal' THEN 1 END) AS normal_count,
                    COUNT(CASE WHEN COALESCE(risk_calc.risk_level, 'normal') = 'warning' THEN 1 END) AS warning_count,
                    COUNT(CASE WHEN COALESCE(risk_calc.risk_level, 'normal') = 'delayed' THEN 1 END) AS delayed_count,
                    COALESCE(SUM(p.monthly_plan), 0) AS total_monthly_plan
                FROM projects p
                LEFT JOIN (
                    SELECT 
                        project_id,
                        CASE 
                            WHEN MAX(
                                CASE 
                                    WHEN actual_end_date IS NOT NULL AND plan_end_date IS NOT NULL THEN
                                        CAST(DATEDIFF(actual_end_date, plan_end_date) AS SIGNED)
                                    WHEN actual_end_date IS NULL AND plan_end_date IS NOT NULL AND CURDATE() > plan_end_date THEN
                                        CAST(DATEDIFF(CURDATE(), plan_end_date) AS SIGNED)
                                    ELSE 0
                                END
                            ) >= 2 THEN 'delayed'
                            WHEN MAX(
                                CASE 
                                    WHEN actual_end_date IS NOT NULL AND plan_end_date IS NOT NULL THEN
                                        CAST(DATEDIFF(actual_end_date, plan_end_date) AS SIGNED)
                                    WHEN actual_end_date IS NULL AND plan_end_date IS NOT NULL AND CURDATE() > plan_end_date THEN
                                        CAST(DATEDIFF(CURDATE(), plan_end_date) AS SIGNED)
                                    ELSE 0
                                END
                            ) >= 1 THEN 'warning'
                            ELSE 'normal'
                        END AS risk_level
                    FROM processes
                    GROUP BY project_id
                ) risk_calc ON risk_calc.project_id = p.id
                WHERE p.status = 'in_progress'
            """)
            return dict(cursor.fetchone())
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
# v2.0: 每日进度填报
# ============================================================

def upsert_daily_progress(process_id: int, project_id: int,
                           process_name: str, report_date: str,
                           plan_qty: float, actual_qty: float,
                           cumulative_plan: float = 0,
                           cumulative_actual: float = 0,
                           daily_status: str = 'in_progress',
                           remarks: str = '') -> int:
    """插入或更新日进度记录（同工序同日不可重复，依赖 UNIQUE(process_id, report_date)）"""
    conn = get_connection()
    try:
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO daily_progress 
                    (project_id, process_id, process_name, report_date,
                     plan_qty, actual_qty, cumulative_plan, cumulative_actual,
                     daily_status, remarks, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    actual_qty = VALUES(actual_qty),
                    cumulative_plan = VALUES(cumulative_plan),
                    cumulative_actual = VALUES(cumulative_actual),
                    daily_status = VALUES(daily_status),
                    remarks = VALUES(remarks),
                    updated_at = VALUES(updated_at)
            """, (project_id, process_id, process_name, report_date,
                   plan_qty, actual_qty, cumulative_plan, cumulative_actual,
                   daily_status, remarks, now))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_daily_progress_by_project(project_id: int,
                                  report_date: Optional[str] = None
                                  ) -> list[dict]:
    """获取项目的日进度记录，可按日期筛选"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if report_date:
                cursor.execute("""
                    SELECT * FROM daily_progress 
                    WHERE project_id = %s AND report_date = %s
                    ORDER BY process_id
                """, (project_id, report_date))
            else:
                cursor.execute("""
                    SELECT * FROM daily_progress 
                    WHERE project_id = %s
                    ORDER BY report_date DESC, process_id
                """, (project_id,))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


@st.cache_data(ttl=300, show_spinner=False)
def get_daily_progress_summary(project_id: int) -> dict:
    """
    获取项目的日进度汇总。
    业务规则：月度总指标 = 内装工序总计划（最终成品数）。
    累计完成 = 仅内装工序的累计实际，中间工序不计入成品完成量。
    全空值安全兜底：无任何日进度数据时返回全0汇总。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 月度总指标
            cursor.execute(
                "SELECT monthly_total_plan, monthly_plan, plan_end_date FROM projects WHERE id = %s",
                (project_id,))
            row = cursor.fetchone()
            proj = dict(row) if row else {}
            total = proj.get('monthly_total_plan', 0) or proj.get('monthly_plan', 0) or 0

            # === 累计完成：仅内装工序的累计实际（成品口径） ===
            cursor.execute("""
                SELECT COALESCE(MAX(dp.cumulative_actual), 0) AS cumulative
                FROM daily_progress dp
                WHERE dp.project_id = %s AND dp.process_name = '内装'
            """, (project_id,))
            row = cursor.fetchone()
            cumulative = row['cumulative'] if row and row['cumulative'] is not None else 0

            # === 今日产量：仅内装工序当日实际（成品口径） ===
            today = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("""
                SELECT COALESCE(dp.actual_qty, 0) AS today_done
                FROM daily_progress dp
                WHERE dp.project_id = %s AND dp.process_name = '内装'
                  AND dp.report_date = %s
            """, (project_id, today))
            row = cursor.fetchone()
            today_done = row['today_done'] if row and row['today_done'] is not None else 0

            # === 今日内装是否完成当日计划 ===
            cursor.execute("""
                SELECT dp.daily_status
                FROM daily_progress dp
                WHERE dp.project_id = %s AND dp.process_name = '内装'
                  AND dp.report_date = %s
            """, (project_id, today))
            row = cursor.fetchone()  # 只取一次，避免二次 fetchone 恒为 None
            neizhuang_done = row['daily_status'] == 'completed' if row else False

            return {
                'monthly_total': total or 0,
                'cumulative_actual': cumulative or 0,
                'completion_pct': round(cumulative / total * 100, 1) if total > 0 else 0,
                'today_done': today_done or 0,
                'neizhuang_done_today': neizhuang_done,
                'plan_end_date': proj.get('plan_end_date'),
            }
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


if __name__ == '__main__':
    init_database()
    print("Database initialization test passed.")
