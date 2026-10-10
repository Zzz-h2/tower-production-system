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

from backend.app.core.config import MYSQL_CONFIG, INDEPENDENT_PROCESS_NAMES, SCHEDULE_PROCESS_NAMES

logger = logging.getLogger(__name__)

# MySQL schema 文件路径（SQLite → MySQL 迁移后使用）
MYSQL_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db_schema_mysql.sql')

# v7.2 排产工序白名单区间：排产导入写入的行满足 process_order = SCHEDULE_PROCESS_NAMES.index(name)+1，
# 即 1..len(SCHEDULE_PROCESS_NAMES)（当前 11）。
# ⚠️ 判定「有没有排产计划」必须用这个区间，**不能**用「非独立工序（NOT IN 90,91）」：
#    「手动完成」占位行（process_order=99, process_name='附件安装'）也满足「非独立工序」，
#    会把只做过手动完成、从未导过排产的项目误判为「已上传排产」（假阳性）。
SCHEDULE_ORDER_MIN = 1
SCHEDULE_ORDER_MAX = len(SCHEDULE_PROCESS_NAMES)

# 「手动完成」占位行的 process_order（与 backend/app/core/db.py 同源）：
# 提前完工但无排产计划的项目用该行补录产出，process_name 仍是「附件安装」，
# 必须靠 process_order 与排产工序（1..11）、独立工序（90/91）区分。
MANUAL_COMPLETE_ORDER = 99


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


def upsert_project(data: dict, mapped_fields: Optional[set] = None) -> tuple[int, bool]:
    """
    插入或更新项目（以 项目名称+钢塔厂家+交付负责人+机型 四字段为唯一键）。
    返回 (project_id, is_new)。

    Args:
        data: 解析后的项目行数据
        mapped_fields: 本次 Excel **已映射**到系统的字段名集合（调度令导入传入）。
                       仅用于 UPDATE 分支的覆盖保护：未映射的列不参与 UPDATE，
                       避免跨月重复导入时把历史月份口径冲掉。
                       传 None 时退化为「值为非 None 才算提供」。
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
                #
                # ★ 覆盖保护（跨月重复导入）：只更新本次 Excel **真正提供**（已映射到）的字段，
                #   未提供的列保持原值。否则「8 月导入过的项目在 10 月再次导入」时，
                #   会把 projects.monthly_plan / last_month_output 直接冲掉，历史月份口径不可回溯。
                #   mapped_fields 由调用方（调度令导入）传入 = 本次 Excel 实际映射到的字段集合；
                #   未传时退化为「值为非 None 才算提供」。
                mapped = mapped_fields if mapped_fields is not None else data.get('_mapped_fields')

                def _provided(field: str) -> bool:
                    if mapped is not None:
                        return field in mapped
                    return data.get(field) is not None

                sets, vals = [], []

                if _provided('last_month_output'):
                    sets.append("last_month_output = %s")
                    vals.append(int(data.get('last_month_output') or 0))
                if _provided('monthly_plan'):
                    mp = int(data.get('monthly_plan') or 0)
                    sets.append("monthly_plan = %s")
                    vals.append(mp)
                    # monthly_total_plan 无独立 Excel 列（历史遗留字段），与 monthly_plan 同步
                    sets.append("monthly_total_plan = %s")
                    vals.append(data.get('monthly_total_plan', mp))
                if _provided('contract_count'):
                    sets.append("contract_count = %s")
                    vals.append(data.get('contract_count'))
                if _provided('plan_start_date'):
                    sets.append("plan_start_date = %s")
                    vals.append(data.get('plan_start_date'))
                if _provided('plan_end_date'):
                    sets.append("plan_end_date = %s")
                    vals.append(data.get('plan_end_date'))
                if _provided('big_area_person'):
                    sets.append("big_area_person = %s")
                    vals.append(str(data.get('big_area_person') or '').strip())

                sets.append("updated_at = %s")
                vals.append(now)
                vals.append(existing['id'])

                cursor.execute(
                    f"UPDATE projects SET {', '.join(sets)} WHERE id = %s", tuple(vals)
                )
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
    """删除项目（应用层级联：工序计划/实际进度/异常/月度调度令快照先删，再删项目主表；里程碑由外键 cascade 自动清理）。

    说明：三张无外键子表（node_actual_progress / node_exceptions / process_node_plans）在
    db_schema_mysql.sql 中已补充 projects(id) 的 ON DELETE CASCADE 外键；
    dispatch_records / schedule_imports 同样带 FK CASCADE（新建库）；
    此处的逐表删除是兼容「建库时尚未带外键的存量库」的兜底，两路叠加互不影响。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 先清子表，避免孤儿行（顺序：子→父）
            cursor.execute("DELETE FROM node_actual_progress WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM node_exceptions WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM process_node_plans WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM dispatch_records WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM schedule_imports WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM process_node_plans_history WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM project_process_durations WHERE project_id = %s", (project_id,))
            cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))
            conn.commit()
    finally:
        conn.close()


# ---------- 月度调度令快照（dispatch_records） ----------
# 语义：项目主表 projects 与月份无关（四字段唯一键跨月复用同一行），
# 「该项目在某月调度令中的计划口径」由本表按月留档，使同一项目可同时出现在多个月份列表，
# 且各月 monthly_plan / last_month_output 互不覆盖（历史月份可回溯）。

# 会写入快照的业务字段（与 dispatch_records 列一一对应）
_DISPATCH_RECORD_FIELDS = (
    "monthly_plan", "last_month_output", "monthly_total_plan", "contract_count",
    "delivery_person", "big_area_person", "factory_name", "machine_type",
)


def upsert_dispatch_record(project_id: int, plan_month: str, data: dict,
                           source_file: str = "", is_approx: int = 0) -> None:
    """写入/更新「项目 × 调度令归属月」快照（唯一键 uk_pid_month，重复导入幂等覆盖）。

    Args:
        project_id: 项目ID
        plan_month: 调度令归属月，格式 'YYYY-MM'
        data: 解析后的项目行数据（缺失字段按 None 存快照列）
        source_file: 来源调度令文件名
        is_approx: 1=历史回填近似值（原值已被后续导入覆盖）
    """
    conn = get_connection()
    try:
        cols = ["project_id", "plan_month"] + list(_DISPATCH_RECORD_FIELDS) + \
               ["source_file", "is_approx"]

        def _val(field: str):
            """取快照列值。monthly_plan / last_month_output 在表上是 NOT NULL，
            缺键或 None 时兜底为 0，避免 IntegrityError(1048) 直接 500。"""
            v = data.get(field)
            if field in ("monthly_plan", "last_month_output"):
                return int(v or 0)
            return v

        vals = [int(project_id), plan_month] + [_val(f) for f in _DISPATCH_RECORD_FIELDS] + \
               [source_file or "", int(is_approx or 0)]
        placeholders = ", ".join(["%s"] * len(cols))
        updates = ", ".join(f"{c} = VALUES({c})" for c in _DISPATCH_RECORD_FIELDS) + \
                  ", source_file = VALUES(source_file), is_approx = VALUES(is_approx), " \
                  "updated_at = NOW()"
        with conn.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO dispatch_records ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}",
                tuple(vals),
            )
            conn.commit()
    finally:
        conn.close()


def get_dispatch_records(plan_month: str) -> dict[int, dict]:
    """按归属月取全部快照 → {project_id: 快照行}（列表/KPI 的月度口径覆盖源）。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM dispatch_records WHERE plan_month = %s", (plan_month,)
            )
            return {int(r["project_id"]): dict(r) for r in cursor.fetchall()}
    finally:
        conn.close()


def get_dispatch_months() -> list[dict]:
    """返回已留档的调度令月份列表（倒序），供前端月份下拉/校验使用。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT plan_month, COUNT(*) AS cnt FROM dispatch_records "
                "GROUP BY plan_month ORDER BY plan_month DESC"
            )
            return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


# ---------- 排产上传台账（schedule_imports） ----------
# 语义：一次排产 Excel 导入成功 = 一条「项目 × 归属月 × 负责人」台账。
# 存在的理由：排产导入是覆盖式重排，process_node_plans 只保留最后一次上传的行，
# 系统原本无处记录「哪个月传过排产」。仅凭「有没有工序行」推测会假阳性——
# 「手动完成」占位行（process_order=99）与调度令自动创建的独立工序（90/91）都不是排产上传证据。

def upsert_schedule_import(project_id: int, plan_month: str, manager: str = "",
                           row_count: int = 0, source_file: str = "") -> None:
    """写入/更新「项目 × 排产归属月 × 负责人」上传台账（唯一键 uk_pid_month_mgr，重复导入幂等覆盖）。

    Args:
        project_id: 项目ID
        plan_month: 排产归属月，格式 'YYYY-MM'
        manager: 本次导入归属负责人；空串=未区分负责人（表列为 NOT NULL DEFAULT ''，
                 用空串而非 NULL 才能让唯一键对「无负责人」项目真正生效）
        row_count: 本次导入实际写入的计划行数
        source_file: 来源排产文件名
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO schedule_imports (project_id, plan_month, manager, row_count, source_file) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE row_count = VALUES(row_count), "
                "source_file = VALUES(source_file), imported_at = NOW(), updated_at = NOW()",
                (int(project_id), plan_month, str(manager or "").strip(),
                 int(row_count or 0), source_file or ""),
            )
            conn.commit()
    finally:
        conn.close()


def get_schedule_imports(plan_month: str) -> dict[int, dict]:
    """按归属月取上传台账 → {project_id: {'managers': [...], 'row_count': int}}。

    同一项目同月可能有多位负责人各上传一次，这里按项目聚合（managers 去重保序、row_count 求和）。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT project_id, manager, row_count FROM schedule_imports "
                "WHERE plan_month = %s ORDER BY project_id, manager",
                (plan_month,),
            )
            out: dict[int, dict] = {}
            for r in cursor.fetchall():
                pid = int(r["project_id"])
                slot = out.setdefault(pid, {"managers": [], "row_count": 0})
                mgr = str(r["manager"] or "").strip()
                if mgr and mgr not in slot["managers"]:
                    slot["managers"].append(mgr)
                slot["row_count"] += int(r["row_count"] or 0)
            return out
    finally:
        conn.close()


def get_last_schedule_months() -> dict[int, str]:
    """取每个项目**最近一次**排产上传的归属月 → {project_id: 'YYYY-MM'}。

    供列表页展示「本月未上传 · 上次上传：X月」，让用户一眼看出该补哪个项目。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT project_id, MAX(plan_month) AS m FROM schedule_imports GROUP BY project_id"
            )
            return {int(r["project_id"]): str(r["m"]) for r in cursor.fetchall() if r["m"]}
    finally:
        conn.close()


def get_schedule_import_months() -> list[dict]:
    """返回已留档的排产归属月列表（倒序），供前端月份下拉/校验使用。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT plan_month, COUNT(*) AS cnt FROM schedule_imports "
                "GROUP BY plan_month ORDER BY plan_month DESC"
            )
            return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


# ---------- 排产明细归档（process_node_plans_history） ----------
# 语义：覆盖式重排前把即将 DELETE 的排产工序行原样归档，做到「替换而非销毁」。
# 主表 process_node_plans 保持「每个项目只有一份最新排产」的单月语义——读路径零改动，
# 规避跨月行共存导致的 plan_qty 翻倍风险；历史月份明细在本表可按月回溯与恢复。

def archive_node_plans_in_scope(cursor, where_sql: str, where_args: tuple,
                                reason: str = "schedule_reimport") -> int:
    """把 WHERE 命中的 process_node_plans 行归档一份（不删除）。

    由 insert_node_plans 在 DELETE 之前调用，传入与之**完全相同的 WHERE 子句**，
    保证「归档集合 == 删除集合」，不重不漏。返回归档行数。

    注意：cursor 由调用方传入（要求与随后的 DELETE 处于同一事务），本函数不 commit。
    """
    cursor.execute(
        "INSERT INTO process_node_plans_history "
        "(id, project_id, process_name, process_order, plan_date, plan_qty, manager, plan_month, archived_reason) "
        f"SELECT id, project_id, process_name, process_order, plan_date, plan_qty, manager, plan_month, %s "
        f"FROM process_node_plans WHERE {where_sql}",
        (reason, *where_args),
    )
    return int(cursor.rowcount or 0)


def get_node_plans_history(project_id: int, plan_month: str | None = None,
                           manager: str | None = None, limit: int = 5000) -> list[dict]:
    """读取已归档的排产明细（历史回溯）。

    Args:
        project_id: 项目ID
        plan_month: 归属月过滤；None=全部月份
        manager: 负责人过滤；None=不区分
        limit: 单次返回上限（防大项目全量拉爆内存）
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = ("SELECT * FROM process_node_plans_history "
                   "WHERE project_id = %s")
            args: list = [project_id]
            if plan_month is not None:
                sql += " AND plan_month <=> %s"
                args.append(str(plan_month).strip())
            if manager is not None:
                sql += " AND manager <=> %s"
                args.append(str(manager).strip())
            sql += " ORDER BY plan_month DESC, process_order, plan_date LIMIT %s"
            args.append(int(limit))
            cursor.execute(sql, tuple(args))
            return [dict(r) for r in cursor.fetchall()]
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

def insert_node_plans(project_id: int, plans: list[dict], manager: str | None = None,
                      durations: list[dict] | None = None,
                      plan_month: str | None = None) -> int:
    """清空该项目（指定负责人名下）的节点计划，再批量插入新计划（覆盖式导入）。

    多负责人（v6.0）：manager 非 None 时，删除与插入都**只作用于该负责人名下**，
    实现「各负责人分别导入、互不覆盖、互不影响」；
    manager 为 None 时保持历史行为——清空该项目全部排产工序行（兼容未拆分的老数据/老调用）。

    v7.2 归属月 + 归档：
      - plan_month 记到每个排产工序行上（独立工序 90/91、手动完成占位行 99 恒为 NULL），
        使「本月是否上传过排产」可判定，不再靠「有没有工序行」推测；
      - 被本次替换掉的行先原样存入 process_node_plans_history 再删除（替换而非销毁），
        历史月份明细可回溯、可恢复（backend/scripts/restore_schedule_month.py）。

    Args:
        project_id: 项目ID
        plans: list[dict]，每项含
            process_name(str) / process_order(int) / plan_date('YYYY-MM-DD') / plan_qty(int)
            可选 actual_qty(int)：仅由排产导入的「已完成」文本识别产出（此时 plan_qty 与
            actual_qty 均=完成套数），存在时会同步写入 node_actual_progress。
            不带 actual_qty 的普通导入**行为完全不变**（不产生任何额外 SQL）。
        manager: 归属负责人姓名；None=不区分负责人（历史行为）
        plan_month: 排产归属月 'YYYY-MM'；None=不标记（调用方负责解析，路由层默认取当前自然月）

    Returns:
        int: 实际插入的节点计划条数
    """
    mgr_val = str(manager).strip() if manager is not None else None
    month_val = str(plan_month).strip() if plan_month else None
    # 「已完成」识别项：仅由排产导入的「已完成」文本识别产出，带 actual_qty 的计划行
    actual_items = [p for p in plans if int(p.get('actual_qty') or 0) > 0]
    # 回填完成量队列：(node_plan_id, process_name, actual_qty, report_date)
    pending_actuals: list[tuple[int, str, int, str]] = []
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 删除范围：指定 manager 时只删该负责人名下的排产工序行（不含独立工序 90/91）
            del_cond = (
                "project_id = %s "
                "AND process_name NOT IN (%s, %s)"
            )
            del_args: list = [project_id, INDEPENDENT_PROCESS_NAMES[0], INDEPENDENT_PROCESS_NAMES[1]]
            if manager is not None:
                # 指定负责人：只替换该负责人名下的排产工序行。
                # 同时吸收「历史未拆分(NULL)行」——避免同一批数据既算在 NULL 又算在新负责人名下
                # 导致汇总视图 plan_qty 翻倍。首个导入的负责人会接管这些历史行。
                del_cond += " AND (manager <=> %s OR manager IS NULL)"
                del_args.append(str(manager).strip())

            # v7.2：删除前先按**完全相同的 WHERE**归档一份（归档集合 == 删除集合，不重不漏）。
            # 主表因此永远只保留该（负责人名下的）最新一份排产，读路径无需感知月份，
            # 规避跨月行共存导致的 plan_qty 翻倍；历史明细在归档表按月可回溯。
            cursor.execute(f"SELECT COUNT(*) AS c FROM process_node_plans WHERE {del_cond}",
                           tuple(del_args))
            _will_delete = int(cursor.fetchone()['c'] or 0)
            if _will_delete:
                archived = archive_node_plans_in_scope(cursor, del_cond, tuple(del_args))
                if archived != _will_delete:
                    # 归档与删除集合必须一致；不一致直接回滚，绝不静默丢数据
                    conn.rollback()
                    raise RuntimeError(
                        f"排产明细归档异常：待删除 {_will_delete} 行、实际归档 {archived} 行，已回滚")

            # 覆盖式重导入会重建 plan 行（新 id）。为**不丢失已填报进度**：
            # ① 删除前按 (process_name, plan_date, manager) 快照既有实际进度；
            # ② 重建后按同键把进度回挂到新行（行未被改动的进度不丢）；
            # ③ 清理旧 plan 行（含历史遗留孤儿）的 actual。
            snap_cond = "pnp.project_id = %s AND pnp.process_name NOT IN (%s, %s)"
            snap_args: list = [project_id, INDEPENDENT_PROCESS_NAMES[0], INDEPENDENT_PROCESS_NAMES[1]]
            if manager is not None:
                snap_cond += " AND (pnp.manager <=> %s OR pnp.manager IS NULL)"
                snap_args.append(str(manager).strip())
            cursor.execute(
                "SELECT pnp.process_name, pnp.plan_date, pnp.manager, nap.actual_qty, nap.report_date "
                "FROM process_node_plans pnp JOIN node_actual_progress nap ON nap.node_plan_id = pnp.id "
                f"WHERE {snap_cond}", tuple(snap_args))
            progress_snapshot: dict = {}
            for r in cursor.fetchall():
                if not r.get('plan_date'):
                    continue
                # 键只用 (process_name, plan_date)：删除范围内同一键可能同时存在
                # 「本负责人行」与被吸收的「历史 NULL 行」，优先保留本负责人的进度
                key = (str(r['process_name']).strip(), str(r['plan_date'])[:10])
                prev = progress_snapshot.get(key)
                if prev is None or r['manager'] == mgr_val:
                    progress_snapshot[key] = (
                        int(r['actual_qty'] or 0),
                        (str(r['report_date'])[:10] if r['report_date'] else None),
                    )

            # 待删旧 plan 行 id（用于删除后清理其 actual，避免孤儿行堆积）
            cursor.execute(f"SELECT id FROM process_node_plans WHERE {del_cond}", tuple(del_args))
            stale_plan_ids: list[int] = [int(r['id']) for r in cursor.fetchall()]

            cursor.execute(f"DELETE FROM process_node_plans WHERE {del_cond}", tuple(del_args))

            # 工序时长表（按套）与 plan 行同范围覆盖式重建，避免重导残留孤儿行
            dur_cond = "project_id = %s"
            dur_args: list = [project_id]
            if manager is not None:
                dur_cond += " AND (manager <=> %s OR manager IS NULL)"
                dur_args.append(str(manager).strip())
            cursor.execute(f"DELETE FROM project_process_durations WHERE {dur_cond}", tuple(dur_args))

            if stale_plan_ids:
                # 只删「本次刚被覆盖掉的 plan 行」挂着的完成量，不动其他任何实际进度
                ids_ph = ",".join(["%s"] * len(stale_plan_ids))
                cursor.execute(
                    f"DELETE FROM node_actual_progress "
                    f"WHERE project_id = %s AND node_plan_id IN ({ids_ph})",
                    (project_id, *stale_plan_ids),
                )

            if plans:
                cursor.executemany("""
                    INSERT INTO process_node_plans
                        (project_id, process_name, process_order, plan_date, plan_qty, manager, plan_month)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [(
                    project_id,
                    str(p['process_name']).strip(),
                    int(p.get('process_order', 0) or 0),
                    str(p['plan_date'])[:10],          # 统一 'YYYY-MM-DD' 字符串
                    int(p.get('plan_qty', 1) or 1),
                    mgr_val,
                    month_val,                          # v7.2 排产归属月（None=不标记）
                ) for p in plans])

            # 按「套」写入工序计划时长/相对下料偏移（无 durations → 零额外 SQL）
            if durations:
                cursor.executemany("""
                    INSERT INTO project_process_durations
                        (project_id, manager, set_seq, process_name, plan_date, duration_days, offset_days)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, [(
                    project_id,
                    mgr_val,
                    int(d.get('set_seq') or 0),
                    str(d.get('process_name') or '').strip(),
                    (str(d['plan_date'])[:10] if d.get('plan_date') else None),
                    (int(d['duration_days']) if d.get('duration_days') is not None else None),
                    (int(d['offset_days']) if d.get('offset_days') is not None else None),
                ) for d in durations])
            conn.commit()

            # 「已完成」文本识别回填：只有带 actual_qty 的项才走这段，
            # 普通导入（无 actual_qty）零额外 SQL、零行为变化。
            # 先 commit 再回查 id（upsert_node_actual 走独立连接，未提交的行看不见）。
            for p in plans:
                qty = int(p.get('actual_qty') or 0)
                if qty <= 0:
                    continue
                proc_name = str(p['process_name']).strip()
                plan_date = str(p['plan_date'])[:10]
                cursor.execute(
                    "SELECT id FROM process_node_plans "
                    "WHERE project_id = %s AND process_name = %s AND plan_date = %s "
                    "  AND manager <=> %s LIMIT 1",   # <=> : NULL 安全等值（manager IS NULL 也能匹配）
                    (project_id, proc_name, plan_date, mgr_val),
                )
                row = cursor.fetchone()
                if not row:
                    continue
                pending_actuals.append((int(row['id']), proc_name, qty, plan_date))

            # 进度回挂：把快照按 (process_name, plan_date, manager) 挂到新建的 plan 行上，
            # 使「重新导入排产计划」不再清空已填报进度。显式 actual_qty 项已在上方处理，此处跳过。
            for p in plans:
                if int(p.get('actual_qty') or 0) > 0:
                    continue
                pn = str(p['process_name']).strip()
                pd = str(p['plan_date'])[:10]
                snap = progress_snapshot.get((pn, pd))
                if not snap or snap[0] <= 0:
                    continue
                cursor.execute(
                    "SELECT id FROM process_node_plans WHERE project_id = %s AND process_name = %s "
                    "AND plan_date = %s AND manager <=> %s LIMIT 1",
                    (project_id, pn, pd, mgr_val),
                )
                row = cursor.fetchone()
                if row:
                    pending_actuals.append((int(row['id']), pn, snap[0], snap[1] or pd))
    finally:
        conn.close()

    for node_plan_id, proc_name, qty, report_date in pending_actuals:
        upsert_node_actual(project_id, node_plan_id, proc_name, qty, report_date, mgr_val)
    return len(plans)


def get_project_process_durations(project_id: int, manager: str | None = None) -> dict:
    """读取项目的「按套工序时长/偏移」，按 (process_name, plan_date) 归并后返回。

    同一 (工序, 计划日) 若来自多套（排产按 plan_date 聚合行的情形，实测约 4% 行），
    取各套的**中位数**作为该行代表值——95%+ 的行本就与「套」1:1，中位数对合并行稳健。

    Returns:
        {(process_name, 'YYYY-MM-DD'): {"duration_days": int|None, "offset_days": int|None}}
        无数据（存量项目未重新导入）→ 返回 {}，调用方回退原判定规则。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = ("SELECT process_name, plan_date, duration_days, offset_days "
                   "FROM project_process_durations WHERE project_id = %s")
            args: list = [project_id]
            if manager is not None:
                sql += " AND manager <=> %s"
                args.append(str(manager).strip())
            cursor.execute(sql, tuple(args))
            raw = [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
    return _merge_duration_rows(raw)


def _merge_duration_rows(rows: list[dict]) -> dict:
    """把 durations 原始行按 (process_name, plan_date) 归并为
    {key: {"duration_days", "offset_days"}}；同一行来自多套时取中位数（稳健代表值）。"""
    groups: dict = {}
    for row in rows:
        if not row.get('plan_date'):
            continue
        key = (str(row['process_name']).strip(), str(row['plan_date'])[:10])
        groups.setdefault(key, []).append((row.get('duration_days'), row.get('offset_days')))

    def _median(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals:
            return None
        n = len(vals)
        return vals[n // 2] if n % 2 else int(round((vals[n // 2 - 1] + vals[n // 2]) / 2))

    return {
        key: {"duration_days": _median([p[0] for p in pairs]),
              "offset_days": _median([p[1] for p in pairs])}
        for key, pairs in groups.items()
    }


def get_project_process_durations_batch(project_ids: list[int]) -> dict[int, dict]:
    """批量读取多项目「按套工序时长/偏移」并归并：{project_id: {(pn,date): {...}}}。

    用于项目列表风险等级计算，避免逐项目查询造成 N+1（按 900 分片）。
    """
    if not project_ids:
        return {}
    by_pid: dict[int, list] = {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for chunk in _chunked(project_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT project_id, process_name, plan_date, duration_days, offset_days "
                    f"FROM project_process_durations WHERE project_id IN ({fmt})", chunk)
                for row in cur.fetchall():
                    by_pid.setdefault(int(row['project_id']), []).append(dict(row))
    finally:
        conn.close()
    return {pid: _merge_duration_rows(rws) for pid, rws in by_pid.items()}


def get_actuals_rich_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度（含日期）：{node_plan_id: {"actual_qty": int, "report_date": str|None}}。

    排名明细需要 report_date 以支持「实际下料日」锚点；按 900 分片规避占位符上限。
    """
    if not node_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            result: dict = {}
            for chunk in _chunked(node_ids):
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT node_plan_id, actual_qty, report_date FROM node_actual_progress "
                    f"WHERE node_plan_id IN ({fmt})", chunk)
                for r in cur.fetchall():
                    result[int(r["node_plan_id"])] = {
                        "actual_qty": int(r["actual_qty"] or 0),
                        "report_date": str(r["report_date"])[:10] if r.get("report_date") else None,
                    }
            return result
    finally:
        conn.close()


def delete_all_node_plans(project_id: int) -> None:
    """彻底清空项目全部节点计划（含两条独立工序），用于重置脏数据。

    v7.3 修正：同一事务内先清「挂在计划行上的派生数据」，再删计划行。
      - `node_actual_progress` **没有指向 process_node_plans 的外键**（只有 project 外键），
        只删计划行会让实际进度变成孤儿行：既不参与任何 JOIN/展示，又永久堆积。
      - `project_process_durations`（按套时长/偏移）同理，随计划行覆盖式重建。
      - `node_segment_progress` 有 ON DELETE CASCADE 外键，随计划行自动清理，无需显式删除。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM node_actual_progress WHERE project_id = %s",
                (project_id,),
            )
            cursor.execute(
                "DELETE FROM project_process_durations WHERE project_id = %s",
                (project_id,),
            )
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


def update_independent_contract_qty(project_id: int, contract_count) -> int:
    """同步独立工序「合同占位行」的 plan_qty = contract_count（**非破坏性**）。

    与 sync_independent_plans 的区别（关键）：
      - sync_independent_plans 会 DELETE 该工序**全部行**再重建，用于调度令导入的全量同步；
      - 本函数只 UPDATE `plan_date IS NULL` 的**占位行**，**不删除、不重建**，
        因此不会误删用户已填报的日期行，也不会留下孤儿 node_actual_progress。

    用于「编辑项目·合同总数」后的占位行同步，保证任何读取占位行的路径与 projects.contract_count 一致。
    返回受影响行数（项目从未导入调度令 → 0，不新增行）。
    """
    names = INDEPENDENT_PROCESS_NAMES
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE process_node_plans SET plan_qty = %s "
                "WHERE project_id = %s AND process_name IN (%s, %s) AND plan_date IS NULL",
                (int(contract_count or 0), project_id, names[0], names[1]),
            )
            affected = cursor.rowcount
            conn.commit()
            return int(affected or 0)
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

            # 2) 已入库的 manager（排除独立工序行；此处只作**姓名来源**，不参与「是否已导入」判定，
            #    故保留宽松范围——名字被漏掉比多出一个名字更糟）
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

            # 3) 各负责人已导入的排产工序行数
            #    ⚠️ v7.2 判定口径必须是排产工序白名单（process_order 1..11），不能用
            #    「process_name NOT IN (90,91)」——「手动完成」占位行（process_order=99,
            #    process_name='附件安装'）也满足后者，会把只做过手动完成的项目误判为「已导入排产」。
            row_counts: dict[str, int] = {}
            if names:
                cursor.execute("""
                    SELECT manager, COUNT(*) AS c FROM process_node_plans
                    WHERE project_id = %s
                      AND process_order BETWEEN %s AND %s
                      AND manager IS NOT NULL
                    GROUP BY manager
                """, (project_id, SCHEDULE_ORDER_MIN, SCHEDULE_ORDER_MAX))
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
                f"VALUES (%s, %s, {MANUAL_COMPLETE_ORDER}, %s, %s, %s) "
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


# ---------- 按段填报（v7.1 行级化，node_segment_progress） ----------

def upsert_node_segment(project_id: int, node_plan_id: int,
                        segment_total: int, segment_done: int) -> None:
    """按段填报（行级化）：写入/更新某套（计划行）的分段进度（总段数/已完成段数）。

    - 段数唯一挂在计划行 node_plan_id 上（唯一键 uk_node_seg），同套重复提交 = **覆盖**；
    - 负责人维度不单独存——计划行 process_node_plans 自带 manager；
    - 排产重导删除计划行时段数随 FK 级联清理（重导=重排）；
    - 独立记录，不折算、不写 actual_qty，联动校验/出品排名/进度百分比零影响。

    Args:
        project_id: 项目ID（冗余标注，供行级隔离/级联删除）
        node_plan_id: 计划行ID（路由层已校验存在且属于该项目+该工序）
        segment_total: 总段数（正整数，路由层已校验 1..99）
        segment_done: 已完成段数（路由层已校验 0 <= done <= total）
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO node_segment_progress "
                    "(project_id, node_plan_id, segment_total, segment_done) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                    "segment_total = VALUES(segment_total), "
                    "segment_done = VALUES(segment_done)",
                (int(project_id), int(node_plan_id),
                 int(segment_total or 0), int(segment_done or 0)),
            )
            conn.commit()
    finally:
        conn.close()


def get_node_segments(project_id: int) -> list[dict]:
    """查询项目全部按段填报行（行级化）：返回 node_plan_id/segment_total/segment_done。"""
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, project_id, node_plan_id, segment_total, segment_done, updated_at "
                "FROM node_segment_progress WHERE project_id = %s",
                (int(project_id),),
            )
            return list(cursor.fetchall())
    finally:
        conn.close()


def get_node_segments_batch(project_ids: list[int]) -> dict[int, dict[int, tuple[int, int]]]:
    """批量查询多个项目的按段填报行（避免项目列表 N+1 查询）。

    Returns:
        {project_id: {node_plan_id: (segment_total, segment_done)}}
        空入参 → {}
    """
    ids = [int(x) for x in (project_ids or []) if x is not None]
    if not ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            placeholders = ",".join(["%s"] * len(ids))
            cursor.execute(
                f"SELECT project_id, node_plan_id, segment_total, segment_done "
                f"FROM node_segment_progress WHERE project_id IN ({placeholders})",
                tuple(ids),
            )
            out: dict[int, dict[int, tuple[int, int]]] = {}
            for row in cursor.fetchall():
                pid = int(row["project_id"])
                out.setdefault(pid, {})[int(row["node_plan_id"])] = (
                    int(row["segment_total"] or 0), int(row["segment_done"] or 0),
                )
            return out
    finally:
        conn.close()


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
        单人项目且未申报时，回退用项目本月计划数（向后兼容旧数据）。
      - total_actual：该负责人名下『附件安装』工序实际完成量之和（按 pnp.manager 归属）。
      - project_id / delivery_person / project_monthly_plan：便于上层追溯与前端展示。

    🔴 **当月项目口径（与 core/db.get_projects_filtered 严格一致）**：
    `projects.created_at 年月 = month` **∪** `dispatch_records.plan_month = month`。
    仅用 created_at 会让「跨月延续项目」（8/9 月已建档、本月又进调度令 → 走 upsert 的
    UPDATE 分支、created_at 不变）整批漏掉，导致排名与「生产进度总览 / 项目列表」数字打架
    （实测生产 2026-10：仅 created_at → 39 项目 / 13 负责人 / 计划 109 / 完成 0；
    正确应为 51 项目 / 14 负责人 / 计划 169 / 完成 14）。
    命中快照的项目用**该月快照**的 monthly_plan 作为计划数（同一项目跨月各月互不覆盖，
    历史月份也才能显示当月口径，而不是被最新一次导入覆盖后的值）。

    big_area_person 非 None 时追加大区行级隔离。
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            ba_sql = " AND p.big_area_person = %s" if big_area_person else ""
            # 前两个占位符依次是：LEFT JOIN 的快照月份、WHERE 的 created_at 月份
            params: list = [month, month]
            if big_area_person:
                params.append(big_area_person)

            # 1) 当月项目：created_at 年月 ∪ dispatch_records.plan_month（命中快照者用该月口径）
            cur.execute(f"""
                SELECT p.id AS project_id,
                       p.delivery_person,
                       COALESCE(d.monthly_plan, p.monthly_plan) AS project_monthly_plan
                FROM projects p
                LEFT JOIN dispatch_records d
                       ON d.project_id = p.id
                      AND d.plan_month = %s
                WHERE (DATE_FORMAT(p.created_at, '%%Y-%%m') = %s OR d.id IS NOT NULL)
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
