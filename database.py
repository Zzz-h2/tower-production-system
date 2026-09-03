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

from backend.app.core.config import MYSQL_CONFIG, INDEPENDENT_PROCESS_NAMES

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
                     contract_count,
                     delivery_person, plan_start_date, plan_end_date,
                     created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                data['project_name'],
                data['factory_name'],
                data.get('last_month_output', 0),
                data['monthly_plan'],
                data.get('contract_count'),
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
                        contract_count = %s,
                        plan_start_date = %s, plan_end_date = %s,
                        big_area_person = %s,
                        updated_at = %s
                    WHERE id = %s
                """, (
                    data.get('last_month_output', 0),
                    data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data.get('contract_count'),
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
                         monthly_total_plan, contract_count,
                         delivery_person, big_area_person, machine_type, plan_start_date, plan_end_date,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    data['project_name'], data['factory_name'],
                    data.get('last_month_output', 0), data['monthly_plan'],
                    data.get('monthly_total_plan', data['monthly_plan']),
                    data.get('contract_count'),
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
                     'risk_level', 'status', 'remarks', 'contract_count', 'machine_type']:
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

def insert_node_plans(project_id: int, plans: list[dict], manager: str | None = None) -> int:
    """清空该项目（指定负责人名下）的节点计划，再批量插入新计划（覆盖式导入）。

    多负责人（v6.0）：manager 非 None 时，删除与插入都**只作用于该负责人名下**，
    实现「各负责人分别导入、互不覆盖、互不影响」；
    manager 为 None 时保持历史行为——清空该项目全部排产工序行（兼容未拆分的老数据/老调用）。

    Args:
        project_id: 项目ID
        plans: list[dict]，每项含
            process_name(str) / process_order(int) / plan_date('YYYY-MM-DD') / plan_qty(int)
        manager: 归属负责人姓名；None=不区分负责人（历史行为）

    Returns:
        int: 实际插入的节点计划条数
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 删除范围：指定 manager 时只删该负责人名下的排产工序行（不含独立工序 90/91）
            del_sql = (
                "DELETE FROM process_node_plans WHERE project_id = %s "
                "AND process_name NOT IN (%s, %s)"
            )
            del_args: list = [project_id, INDEPENDENT_PROCESS_NAMES[0], INDEPENDENT_PROCESS_NAMES[1]]
            if manager is not None:
                # 指定负责人：只替换该负责人名下的排产工序行。
                # 同时吸收「历史未拆分(NULL)行」——避免同一批数据既算在 NULL 又算在新负责人名下
                # 导致汇总视图 plan_qty 翻倍。首个导入的负责人会接管这些历史行。
                del_sql += " AND (manager <=> %s OR manager IS NULL)"
                del_args.append(str(manager).strip())
            cursor.execute(del_sql, tuple(del_args))

            if plans:
                cursor.executemany("""
                    INSERT INTO process_node_plans
                        (project_id, process_name, process_order, plan_date, plan_qty, manager)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, [(
                    project_id,
                    str(p['process_name']).strip(),
                    int(p.get('process_order', 0) or 0),
                    str(p['plan_date'])[:10],          # 统一 'YYYY-MM-DD' 字符串
                    int(p.get('plan_qty', 1) or 1),
                    (str(manager).strip() if manager is not None else None),
                ) for p in plans])
            conn.commit()
            return len(plans)
    finally:
        conn.close()


def delete_all_node_plans(project_id: int) -> None:
    """彻底清空项目全部节点计划（含两条独立工序），用于重置脏数据。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM process_node_plans WHERE project_id = %s",
                (project_id,),
            )
        conn.commit()
    finally:
        conn.close()



def sync_independent_plans(project_id: int, contract_count) -> int:
    """同步项目两条独立工序节点计划（累计完成总数 / 累计发运总数）。

    plan_qty = 调度令「合同数量」(contract_count)；plan_date 为 NULL（无日期语义）。
    在调度令导入后调用；重新导入时先删后插，保证幂等、不堆叠。
    """
    names = INDEPENDENT_PROCESS_NAMES
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM process_node_plans WHERE project_id = %s AND process_name IN (%s, %s)",
                (project_id, names[0], names[1]),
            )
            qty = int(contract_count or 0)
            cursor.executemany(
                "INSERT INTO process_node_plans (project_id, process_name, process_order, plan_date, plan_qty) "
                "VALUES (%s, %s, %s, NULL, %s)",
                [(project_id, names[0], 90, qty), (project_id, names[1], 91, qty)],
            )
            conn.commit()
            return 2
    finally:
        conn.close()


def get_node_plans(project_id: int, manager: str | None = None) -> list[dict]:
    """获取项目的工序节点计划，按 工序顺序 + 计划日期 排序。

    多负责人（v6.0）：
      - manager=None（默认）→ 返回该项目**全部**行（汇总视图口径，含历史 NULL 行）
      - manager='张三'      → 只返回该负责人名下行（单人视图口径，历史 NULL 行不可见）

    Args:
        project_id: 项目ID
        manager: 负责人姓名；None=不区分负责人（汇总）

    Returns:
        list[dict]: 节点计划行
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = "SELECT * FROM process_node_plans WHERE project_id = %s"
            args: list = [project_id]
            if manager is not None:
                sql += " AND manager <=> %s"
                args.append(str(manager).strip())
            sql += " ORDER BY process_order, plan_date"
            cursor.execute(sql, tuple(args))
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


# ============================================================
# v6.0 多负责人管理：负责人拆分 / 月度计划 / 负责人列表
# ============================================================

def split_managers(delivery_person: str | None) -> list[str]:
    """把「交付负责人」字段按 '/'（含全角'／'）拆分为负责人列表。

    边界处理：
      - 空/None         → []（项目列表仍原样展示原始字符串，此处仅用于详情/排名拆分）
      - 单人无分隔符    → ['张三']（行为等同原版）
      - 多人 '张三/李四' → ['张三', '李四']
      - 重复 '张三/张三' → ['张三']（去重，保序）
      - 空片段 '张三/'  → 忽略空片段

    Args:
        delivery_person: projects.delivery_person 原始值

    Returns:
        list[str]: 去重保序的负责人姓名列表
    """
    raw = str(delivery_person or "").strip()
    if not raw:
        return []
    # 统一全角斜杠 → 半角
    normalized = raw.replace("／", "/")
    result: list[str] = []
    for part in normalized.split("/"):
        name = part.strip()
        if name and name not in result:      # 去空 + 去重（保序）
            result.append(name)
    return result


def upsert_manager_monthly_plan(project_id: int, manager: str, monthly_plan: int) -> None:
    """写入/更新「某负责人 对 某项目」的本月计划数（方案P：独立申报，不校验求和）。

    Args:
        project_id: 项目ID
        manager: 负责人姓名
        monthly_plan: 该负责人申报的本月计划数（非负整数）
    """
    if not str(manager or "").strip():
        raise ValueError("负责人姓名不能为空")
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO project_manager_plans (project_id, manager, monthly_plan)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE monthly_plan = VALUES(monthly_plan)
            """, (project_id, str(manager).strip(), max(0, int(monthly_plan or 0))))
            conn.commit()
    finally:
        conn.close()


def get_manager_monthly_plan_map(project_id: int) -> dict[str, int]:
    """取项目各负责人的本月计划数映射：{负责人: monthly_plan}。

    未申报的负责人不会出现在结果里（调用方用 .get(m, 0) 取默认值 0）。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT manager, monthly_plan FROM project_manager_plans WHERE project_id = %s",
                (project_id,),
            )
            return {row["manager"]: int(row["monthly_plan"] or 0) for row in cursor.fetchall()}
    finally:
        conn.close()


def list_project_managers(project_id: int) -> list[dict]:
    """列出项目的负责人清单及其导入/计划概况（供「多负责人管理」弹窗使用）。

    负责人来源（取并集，保序：先 delivery_person 拆分结果，再补 DB 中已存在但未在
    delivery_person 里的负责人，避免调度令改名后旧数据负责人「消失」）：
      1. projects.delivery_person 按 '/' 拆分
      2. process_node_plans 中该项目已出现的 manager 值（非空）

    Returns:
        list[dict]，每项：
          manager(str)       负责人姓名
          monthly_plan(int)  该负责人申报的本月计划数（未申报=0）
          plan_rows(int)     该负责人名下已导入的排产工序节点行数（不含独立工序 90/91）
          has_imported(bool) 是否已导入过排产计划
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 1) projects.delivery_person
            cursor.execute(
                "SELECT delivery_person FROM projects WHERE id = %s", (project_id,)
            )
            proj = cursor.fetchone()
            names = split_managers(proj["delivery_person"] if proj else "")

            # 2) 已入库的 manager（排除独立工序行，只看排产工序）
            cursor.execute("""
                SELECT DISTINCT manager FROM process_node_plans
                WHERE project_id = %s
                  AND manager IS NOT NULL AND manager <> ''
                  AND process_name NOT IN (%s, %s)
                ORDER BY manager
            """, (project_id, INDEPENDENT_PROCESS_NAMES[0], INDEPENDENT_PROCESS_NAMES[1]))
            for r in cursor.fetchall():
                nm = str(r["manager"]).strip()
                if nm and nm not in names:
                    names.append(nm)

            # 3) 各负责人已导入行数
            row_counts: dict[str, int] = {}
            if names:
                cursor.execute("""
                    SELECT manager, COUNT(*) AS c FROM process_node_plans
                    WHERE project_id = %s
                      AND process_name NOT IN (%s, %s)
                      AND manager IS NOT NULL
                    GROUP BY manager
                """, (project_id, INDEPENDENT_PROCESS_NAMES[0], INDEPENDENT_PROCESS_NAMES[1]))
                row_counts = {str(r["manager"]).strip(): int(r["c"]) for r in cursor.fetchall()}

            plan_map = get_manager_monthly_plan_map(project_id)
            return [
                {
                    "manager": nm,
                    "monthly_plan": int(plan_map.get(nm, 0)),
                    "plan_rows": int(row_counts.get(nm, 0)),
                    "has_imported": int(row_counts.get(nm, 0)) > 0,
                }
                for nm in names
            ]
    finally:
        conn.close()


def upsert_node_actual(project_id: int, node_plan_id: int, process_name: str,
                       actual_qty: int, report_date: str,
                       manager: str | None = None) -> None:
    """插入或更新节点实际完成套数（唯一键 uk_proj_node，同节点可重复修改）。

    多负责人（v6.0）：manager 记录该条实际完成归属的负责人，与对应 node_plan 行一致。
    uk_proj_node (project_id, node_plan_id) 已天然按负责人隔离（不同负责人有不同的 node_plan_id），
    故 manager 列在此作为冗余标注，便于单人视图直接过滤、无需回查 plan 表。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO node_actual_progress
                    (project_id, node_plan_id, process_name, actual_qty, report_date, manager)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    actual_qty = VALUES(actual_qty),
                    report_date = VALUES(report_date),
                    manager = VALUES(manager)
            """, (project_id, node_plan_id, str(process_name).strip(),
                  int(actual_qty or 0), str(report_date)[:10],
                  (str(manager).strip() if manager is not None else None)))
            conn.commit()
    finally:
        conn.close()


def upsert_manual_complete(project_id: int, complete_qty: int, complete_date: str,
                           manager: str | None = None) -> int:
    """手动完成：为项目写入/更新一条『附件安装』节点计划 + 实际完成。

    用于「提前完工但没有排产计划」的项目补录产出。语义：
    - process_name='附件安装'，process_order=99（区别于排产工序 1-11 与独立工序 90/91）
    - plan_qty 与 actual_qty **都写 complete_qty**：项目整体进度 progress_pct 的口径是
      附件安装 SUM(actual)/SUM(plan)（见 backend/app/core/db.py:296-303），只写 actual
      会让分母为 0、进度恒为 0。
    - 唯一键 uk_proj_proc_date (project_id, process_name, plan_date)：
      同一天重复提交 = **覆盖**（plan_qty 更新为本次值），不同日期 = 新增一行（累加）。
    - ⚠️ manager（v6.0 多负责人）：**必须写入**。出品排名的完成侧统计按
      ``pnp.manager IS NOT NULL`` 过滤并按 manager 归属（get_ranking_manager_rows_by_month），
      manager=NULL 的行会被排名整体漏掉（2026-09-03 修复的根因）。
      同日覆盖时同步更新 manager（管理员可改归属）。

    Args:
        project_id: 项目ID
        complete_qty: 完成套数（正整数，上限由路由层校验）
        complete_date: 完成日期 'YYYY-MM-DD'
        manager: 归属负责人（路由层推导：单负责人项目自动取 delivery_person；
                 多负责人项目必须显式指定）

    Returns:
        int: 写入/更新的 node_plan_id
    """
    complete_date = str(complete_date)[:10]
    mgr = (str(manager).strip() if manager else None) or None
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO process_node_plans "
                    "(project_id, process_name, process_order, plan_date, plan_qty, manager) "
                "VALUES (%s, %s, 99, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE plan_qty = VALUES(plan_qty), manager = VALUES(manager)",
                (project_id, "附件安装", complete_date, int(complete_qty or 0), mgr),
            )
            node_plan_id = cursor.lastrowid
            if not node_plan_id:
                # ON DUPLICATE 走 UPDATE 分支时 lastrowid 可能为 0，回查取回 id
                cursor.execute(
                    "SELECT id FROM process_node_plans "
                    "WHERE project_id=%s AND process_name=%s AND plan_date=%s LIMIT 1",
                    (project_id, "附件安装", complete_date),
                )
                row = cursor.fetchone()
                node_plan_id = row['id'] if row else 0
            conn.commit()
    finally:
        conn.close()

    upsert_node_actual(project_id, node_plan_id, "附件安装",
                       int(complete_qty or 0), complete_date)
    return node_plan_id


def save_independent_fill(project_id: int, process_name: str,
                          fill_qty: int, report_date: str,
                          manager: str | None = None) -> int:
    """独立工序（累计完成/累计发运）每次填报：按日期 find-or-create node_plan + upsert actual。

    - 同一天再次填报：更新该日那条 actual（不会产生新行）
    - 不同天填报：INSERT 新 node_plan（plan_date=report_date, plan_qty=fill_qty）+ 新 actual
    - 原 NULL-date 占位行（由 sync_independent_plans 创建）始终保留，作为「合同总数」分母

    多负责人（v6.0）：manager 非 None 时，find-or-create 与 upsert 都限定在该负责人名下，
    保证不同负责人同一天的填报各自独立、互不覆盖。

    Args:
        project_id: 项目ID
        process_name: 工序名（必须是 INDEPENDENT_PROCESS_NAMES 之一）
        fill_qty: 本次填报数量（delta，不是累计）
        report_date: 'YYYY-MM-DD' 字符串
        manager: 归属负责人姓名；None=不区分负责人

    Returns:
        int: 受影响的 node_plan_id
    """
    if process_name not in INDEPENDENT_PROCESS_NAMES:
        raise ValueError(f"非独立工序不支持逐日报表：{process_name}")
    mgr_val = str(manager).strip() if manager is not None else None
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            find_sql = (
                "SELECT id FROM process_node_plans "
                "WHERE project_id=%s AND process_name=%s AND plan_date=%s"
            )
            find_args: list = [project_id, process_name, report_date]
            if manager is not None:
                find_sql += " AND manager <=> %s"
                find_args.append(mgr_val)
            find_sql += " LIMIT 1"
            cursor.execute(find_sql, tuple(find_args))
            row = cursor.fetchone()
            if row:
                node_plan_id = row['id']
            else:
                process_order = 90 if process_name == INDEPENDENT_PROCESS_NAMES[0] else 91
                cursor.execute(
                    "INSERT INTO process_node_plans "
                        "(project_id, process_name, process_order, plan_date, plan_qty, manager) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (project_id, process_name, process_order, report_date, int(fill_qty), mgr_val),
                )
                node_plan_id = cursor.lastrowid
            cursor.execute("""
                INSERT INTO node_actual_progress
                    (project_id, node_plan_id, process_name, actual_qty, report_date, manager)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    actual_qty = VALUES(actual_qty),
                    report_date = VALUES(report_date),
                    manager = VALUES(manager)
            """, (project_id, node_plan_id, process_name, int(fill_qty), report_date, mgr_val))
            conn.commit()
            return node_plan_id
    finally:
        conn.close()


def move_independent_fill_date(project_id: int, process_name: str,
                               node_plan_id: int, new_report_date: str,
                               new_qty: int | None = None) -> int:
    """独立工序（累计完成/累计发运）「已完成」记录改日期/数量（管理员用，后端兜底移动）。

    - 语义是**移动**该条记录的日期（改 node_plan.plan_date + actual.report_date），
      不是 find-or-create——避免复制出一条新记录导致累计翻倍。
    - 目标日期已有另一条记录 → **合并**：把源记录 actual_qty 累加到目标行，删除源行。
    - 目标日期无记录 → 直接改源行 plan_date + report_date。
    - new_qty 非 None：管理员同时修改了数量 → 用新数量替代源行 DB 值（合并累加/移动更新都用它），
      并同步 plan_qty 与 actual_qty 保持一致（独立工序记录行 plan_qty = 当次填报量）。

    Args:
        project_id: 项目ID
        process_name: 工序名（必须是 INDEPENDENT_PROCESS_NAMES 之一）
        node_plan_id: 要移动的「已完成」记录行 id
        new_report_date: 目标日期 'YYYY-MM-DD'
        new_qty: 新数量（管理员改了数量时传入；只改日期时传 None）

    Returns:
        int: 移动/合并后存活的 node_plan_id
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 1) 源行必须存在且属于该项目+工序
            cursor.execute(
                "SELECT id, plan_qty FROM process_node_plans "
                "WHERE id=%s AND project_id=%s AND process_name=%s",
                (node_plan_id, project_id, process_name),
            )
            src = cursor.fetchone()
            if not src:
                raise ValueError(f"独立工序记录 {node_plan_id} 不存在（project={project_id}, process={process_name}）")
            # 2) 源记录的实际数量：管理员传了新数量则优先用新值，否则用 DB 源行 actual（兜底 plan_qty）
            if new_qty is not None:
                src_qty = int(new_qty)
            else:
                cursor.execute(
                    "SELECT actual_qty FROM node_actual_progress "
                    "WHERE node_plan_id=%s AND project_id=%s",
                    (node_plan_id, project_id),
                )
                src_act = cursor.fetchone()
                src_qty = int(src_act["actual_qty"] if src_act else src["plan_qty"] or 0)
            # 3) 目标日期是否已有另一条记录
            cursor.execute(
                "SELECT id FROM process_node_plans "
                "WHERE project_id=%s AND process_name=%s AND plan_date=%s AND id != %s LIMIT 1",
                (project_id, process_name, new_report_date, node_plan_id),
            )
            tgt = cursor.fetchone()
            if tgt:
                # 合并：qty 累加到目标行（actual + plan 同步），删除源行（actual + plan）
                cursor.execute(
                    "UPDATE node_actual_progress SET actual_qty=actual_qty+%s, report_date=%s "
                    "WHERE node_plan_id=%s AND project_id=%s",
                    (src_qty, new_report_date, tgt["id"], project_id),
                )
                cursor.execute(
                    "UPDATE process_node_plans SET plan_qty=plan_qty+%s WHERE id=%s",
                    (src_qty, tgt["id"]),
                )
                cursor.execute("DELETE FROM node_actual_progress WHERE node_plan_id=%s", (node_plan_id,))
                cursor.execute("DELETE FROM process_node_plans WHERE id=%s", (node_plan_id,))
                conn.commit()
                return tgt["id"]
            # 4) 无冲突：移动（改 plan_date；数量有变则同步 plan_qty + actual_qty）
            if new_qty is not None:
                cursor.execute(
                    "UPDATE process_node_plans SET plan_date=%s, plan_qty=%s WHERE id=%s",
                    (new_report_date, src_qty, node_plan_id),
                )
                cursor.execute(
                    "UPDATE node_actual_progress SET report_date=%s, actual_qty=%s "
                    "WHERE node_plan_id=%s AND project_id=%s",
                    (new_report_date, src_qty, node_plan_id, project_id),
                )
            else:
                cursor.execute(
                    "UPDATE process_node_plans SET plan_date=%s WHERE id=%s",
                    (new_report_date, node_plan_id),
                )
                cursor.execute(
                    "UPDATE node_actual_progress SET report_date=%s "
                    "WHERE node_plan_id=%s AND project_id=%s",
                    (new_report_date, node_plan_id, project_id),
                )
            conn.commit()
            return node_plan_id
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
            # 多负责人（v6.0）：person 现按「单个负责人姓名」解释。
            # 匹配：该负责人名下行（n.manager = person），或旧数据未拆分时
            # 整项目归属（n.manager IS NULL 且 p.delivery_person = person）。
            sql = """
                SELECT n.id, n.project_id, n.process_name, n.plan_date, n.plan_qty,
                       p.project_name, p.machine_type, p.factory_name
                FROM process_node_plans n
                JOIN projects p ON p.id = n.project_id
                WHERE (n.manager = %s OR (n.manager IS NULL AND p.delivery_person = %s))
                  AND n.plan_date >= %s AND n.plan_date < %s
            """
            params = [person, person, month_start, month_end]
            if big_area_person:
                sql += " AND p.big_area_person = %s"
                params.append(big_area_person)
            sql += " ORDER BY p.id, n.process_order, n.plan_date"
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def get_ranking_manager_rows_by_month(month: str,
                                      big_area_person: str | None = None) -> list[dict]:
    """出品排名（v6.0 多负责人）：返回当月每个 (项目 × 负责人) 的计划/完成明细行。

    与 get_ranking_summary_by_month 的区别：后者按 delivery_person 原样聚合成一行
    （如「张三/李四」算一个人）；本函数按 '/' 拆分后，每位负责人各占一行，
    使出品排名能把多位负责人的数据分别展示、分别排名。

    口径：
      - manager：delivery_person 按 '/' 拆分后的单个姓名（去重保序）；
        若 delivery_person 为空/脏数据，则回退为原样单人（保持旧行为，不丢数据）。
      - total_plan：该负责人申报的本月计划数（project_manager_plans.monthly_plan）；
        单人项目且未申报时，回退用 projects.monthly_plan（向后兼容旧数据）。
      - total_actual：该负责人名下『附件安装』工序实际完成量之和（按 pnp.manager 归属）。
      - project_id / delivery_person / project_monthly_plan：便于上层追溯与前端展示。

    big_area_person 非 None 时追加大区行级隔离。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ba_sql = " AND p.big_area_person = %s" if big_area_person else ""
            params: list = [month]
            if big_area_person:
                params.append(big_area_person)

            # 1) 当月项目（调度令月份 = created_at 年月）
            cur.execute(f"""
                SELECT p.id AS project_id,
                       p.delivery_person,
                       p.monthly_plan AS project_monthly_plan
                FROM projects p
                WHERE DATE_FORMAT(p.created_at, '%%Y-%%m') = %s
                  AND p.delivery_person IS NOT NULL AND TRIM(p.delivery_person) <> ''
                  AND p.delivery_person NOT REGEXP '^[0-9]+$'
                  {ba_sql}
                ORDER BY p.id
            """, params)
            projects = [dict(r) for r in cur.fetchall()]
            if not projects:
                return []

            pids = [int(p["project_id"]) for p in projects]
            ph = ", ".join(["%s"] * len(pids))

            # 2) 各负责人申报的本月计划数
            cur.execute(f"""
                SELECT project_id, manager, monthly_plan
                FROM project_manager_plans
                WHERE project_id IN ({ph})
            """, pids)
            declared: dict[tuple[int, str], int] = {}
            for r in cur.fetchall():
                declared[(int(r["project_id"]), str(r["manager"]).strip())] = int(r["monthly_plan"] or 0)

            # 3) 各负责人名下『附件安装』实际完成量
            cur.execute(f"""
                SELECT pnp.project_id, pnp.manager, SUM(nap.actual_qty) AS total_actual
                FROM process_node_plans pnp
                JOIN node_actual_progress nap ON nap.node_plan_id = pnp.id
                WHERE pnp.project_id IN ({ph})
                  AND pnp.process_name = '附件安装'
                  AND pnp.manager IS NOT NULL
                GROUP BY pnp.project_id, pnp.manager
            """, pids)
            actuals: dict[tuple[int, str], int] = {}
            for r in cur.fetchall():
                actuals[(int(r["project_id"]), str(r["manager"]).strip())] = int(r["total_actual"] or 0)

            # 4) 拆分并组装 (项目 × 负责人) 行
            rows: list[dict] = []
            for p in projects:
                pid = int(p["project_id"])
                raw_person = str(p["delivery_person"] or "").strip()
                names = split_managers(raw_person) or ([raw_person] if raw_person else [])
                proj_plan = int(p["project_monthly_plan"] or 0)
                for nm in names:
                    key = (pid, nm)
                    if key in declared:
                        plan = declared[key]
                    elif len(names) == 1:
                        # 单人项目且未单独申报 → 回退用项目整体计划数（向后兼容）
                        plan = proj_plan
                    else:
                        plan = 0
                    rows.append({
                        "project_id": pid,
                        "delivery_person": raw_person,
                        "project_monthly_plan": proj_plan,
                        "manager": nm,
                        "total_plan": plan,
                        "total_actual": int(actuals.get(key, 0)),
                    })
            return rows
    finally:
        conn.close()


def get_ranking_summary_by_month(month: str, big_area_person: str | None = None) -> list[dict]:
    """出品排名总览：按交付负责人汇总「当月(调度令月份=projects.created_at 年月)」项目。

    口径（与「生产进度总览」页面联动一致）：
    - 累计计划套数 total_plan = SUM(projects.monthly_plan)（项目级「本月计划出品」之和，
      对应生产进度总览页面各项目「本月计划」列的总和）
    - 累计完成套数 total_actual = SUM(附件安装工序节点 actual_qty)（名下项目附件安装实际完成量）
    - project_count = 当月项目数

    big_area_person 非 None 时追加 ``AND p.big_area_person = %s``（大区行级隔离）。
    排除 delivery_person 为空 / 纯数字（脏数据），避免汇总失真。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ba_sql = " AND p.big_area_person = %s" if big_area_person else ""
            sql = f"""
                SELECT plan.delivery_person,
                       plan.total_plan,
                       plan.project_count,
                       COALESCE(act.total_actual, 0) AS total_actual
                FROM (
                    SELECT p.delivery_person,
                           SUM(p.monthly_plan) AS total_plan,
                           COUNT(*) AS project_count
                    FROM projects p
                    WHERE DATE_FORMAT(p.created_at, '%%Y-%%m') = %s
                      AND p.delivery_person IS NOT NULL AND TRIM(p.delivery_person) <> ''
                      AND p.delivery_person NOT REGEXP '^[0-9]+$'
                      {ba_sql}
                    GROUP BY p.delivery_person
                ) plan
                LEFT JOIN (
                    SELECT p.delivery_person, SUM(nap.actual_qty) AS total_actual
                    FROM projects p
                    JOIN process_node_plans pnp ON pnp.project_id = p.id
                         AND pnp.process_name = '附件安装'
                    JOIN node_actual_progress nap ON nap.node_plan_id = pnp.id
                    WHERE DATE_FORMAT(p.created_at, '%%Y-%%m') = %s
                      AND p.delivery_person IS NOT NULL AND TRIM(p.delivery_person) <> ''
                      AND p.delivery_person NOT REGEXP '^[0-9]+$'
                      {ba_sql}
                    GROUP BY p.delivery_person
                ) act ON act.delivery_person = plan.delivery_person
                ORDER BY plan.total_plan DESC
            """
            params = [month]
            if big_area_person:
                params.append(big_area_person)
            params.append(month)
            if big_area_person:
                params.append(big_area_person)
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
