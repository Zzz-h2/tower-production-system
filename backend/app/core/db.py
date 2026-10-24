# -*- coding: utf-8 -*-
"""数据库访问层：封装原 database.py 的 pymysql 连接与节点表读写。

沿用现有表结构（process_node_plans / node_actual_progress / node_exceptions 等），不重新设计。
风险等级与整体进度均由 node_plans + node_actuals 实时计算，弃用 processes 表。
"""
import functools
import logging
import os
from typing import Any, Callable

from .cache import TTLCache
from .db_pool import get_connection as _pooled_get_connection
from .config import MYSQL_CONFIG, SCHEDULE_PROCESS_NAMES  # MYSQL_CONFIG 仍对外 re-export（脚本/排障会 `db.MYSQL_CONFIG`）
from .timeutil import business_today

logger = logging.getLogger(__name__)

# v7.2 排产工序白名单区间（与根 database.py 同源，顺序由 SCHEDULE_PROCESS_NAMES 保证）：
# 排产导入写出的行满足 process_order = index+1，即 1..len(SCHEDULE_PROCESS_NAMES)。
# ⚠️ 判定「有没有排产计划」必须用它，不能用「process_name NOT IN (90,91)」——
#    「手动完成」占位行（process_order=99, process_name='附件安装'）也满足后者，会造成假阳性。
SCHEDULE_ORDER_MIN = 1
SCHEDULE_ORDER_MAX = len(SCHEDULE_PROCESS_NAMES)

# 「手动完成」占位行的 process_order（与根 database.py 同源）：
# 提前完工但无排产计划的项目用该行补录产出（process_name 仍是「附件安装」，
# 与排产第 9 道工序同名，因此**只能靠 process_order 区分**）。
# 排产计划总览据此展示「手动完成」痕迹（原实现完全不可见）。
MANUAL_COMPLETE_ORDER = 99


def _env_float(name: str, default: float) -> float:
    """读取浮点型环境变量（非法值回退默认，避免启动即崩）。"""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        logger.warning("环境变量 %s=%r 不是数字，回退默认值 %s", name, raw, default)
        return default


# ---------- 首页 KPI 短缓存（2026-10 性能优化） ----------
# 背景：get_dashboard_stats 为算 4 个数字，要把**全部项目**的风险判定（排产/实际/异常/工期）
#       跑一遍（limit=100000），单次约 0.5s。首页每次刷新都调 → 加 30 秒 TTL 内存缓存。
# 一致性：
#   * key 必须含 month + big_area_person —— 大区行级隔离，绝不能按 month 单独建键。
#   * 写操作（排产导入/填报保存/异常提报关闭/项目增删改/调度令导入）由
#     ``_invalidates_dashboard`` 装饰器主动清空，改数据后首页立即变化（同副本内）。
#   * 多副本部署时各副本独立缓存，最坏延迟 = TTL（默认 30s）；可用环境变量
#     DASHBOARD_STATS_TTL_SECONDS 调整，设 0 则完全关闭缓存（A/B 比对用）。
DASHBOARD_STATS_TTL_SECONDS = _env_float("DASHBOARD_STATS_TTL_SECONDS", 30.0)
_dashboard_cache = TTLCache("dashboard_stats", DASHBOARD_STATS_TTL_SECONDS, max_entries=256)


def invalidate_dashboard_stats() -> int:
    """失效首页 KPI 缓存（全部月份 × 全部大区），返回清除条数。

    写操作后调用；也可供脚本/运维在数据订正后手动清空。
    """
    cleared = _dashboard_cache.invalidate()
    if cleared:
        logger.debug("已失效首页 KPI 缓存 %d 条", cleared)
    return cleared


def _invalidates_dashboard(fn: Callable) -> Callable:
    """写操作装饰器：执行后失效首页 KPI 缓存（异常也失效，宁可多算一次）。

    注意：用 functools.wraps 保留原函数签名与 ``__wrapped__``，不影响桥接层
    ``getattr(_fn, "__wrapped__", _fn)`` 的既有调用约定。
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        finally:
            invalidate_dashboard_stats()

    return wrapper


def get_connection():
    """获取池化 pymysql 连接（**每次调用不再新建 TCP 连接**，close() 即归还）。

    语义与改造前完全一致：``autocommit=True`` + ``DictCursor`` + ``utf8mb4``。
    调用方无需改动 —— ``PooledDB`` 连接的 ``close()`` 就是「归还到池」。
    """
    return _pooled_get_connection(autocommit=True)


# ---------- 节点计划 / 实际进度（v4.0 表） ----------

def get_node_plans(project_id: int, manager: str | None = None,
                   month: str | None = None) -> list[dict]:
    """查询工序节点计划（含 id/project_id/process_name/plan_date/plan_qty/process_order/manager）。

    多负责人（v6.0）：manager=None 返回该项目全部行（汇总视图）；
    manager='张三' 只返回该负责人名下行（单人视图）。
    按月隔离（v7.4）：month='YYYY-MM' 只返回「该月导入的行 ∪ 未标注月行」；None=不限定月份。
    """
    from database import get_node_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager, month)


def get_node_actuals(project_id: int) -> dict:
    """查询节点实际进度：{node_plan_id: {actual_qty, report_date, ...}}。"""
    from database import get_node_actuals as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_node_plans_batch(project_ids: list[int],
                         month: str | None = None) -> dict[int, list[dict]]:
    """批量查询多个项目的工序节点计划：{project_id: [plan, ...]}（消除列表页 N+1）。

    v7.4：month 按月隔离（该月 ∪ 未标注月）；项目列表的「整体进度/风险」由此结果聚合，
    必须传入当前列表月份，否则跨月行相加会让进度虚高。
    """
    from database import get_node_plans_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids, month)


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
                                      big_area_person: str | None = None,
                                      month: str | None = None) -> list[dict]:
    """取某负责人当月全部工序节点计划（含项目名/机号/厂家，供逾期/提前明细）。

    v7.4.x：month 传入时叠加排产归属月隔离，语义已收紧为**严格 plan_month = month**
    （``plan_month IS NULL`` 的未标注月历史残留行一律排除），避免旧导入行混入详情页。
    """
    from database import get_all_plans_by_month_and_person as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end, person,
                                            big_area_person, month)


@_invalidates_dashboard
def insert_node_plans(project_id: int, plans: list[dict], manager: str | None = None,
                      durations: list[dict] | None = None,
                      plan_month: str | None = None) -> int:
    """批量写入节点计划（**整体覆盖式**）。

    多负责人（v6.0）：manager 非 None 时只覆盖该负责人名下的排产工序行（并吸收历史 NULL 行），
    实现各负责人分别导入、互不覆盖。manager=None 时覆盖该项目全部排产工序行。
    durations：按「套」的工序计划时长/相对下料偏移，与 plan 行同范围覆盖式重建。
    plan_month：排产归属月 'YYYY-MM'，只作为**标记 + 读取口径**；导入本身不分月份，
    一律整体覆盖旧计划（旧行先归档到 process_node_plans_history 再删除，历史可回溯/恢复）。
    """
    from database import insert_node_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, plans, manager, durations, plan_month)


# ---------- 排产上传台账（schedule_imports，v7.2 新增） ----------
# ⚠️ 根 database.py 新增函数必须在此同步 re-export，否则 `db.xxx` 抛 AttributeError → FastAPI 默认 500。

@_invalidates_dashboard
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


def get_project_process_durations(project_id: int, manager: str | None = None,
                                 month: str | None = None) -> dict:
    """读取项目「按套工序时长/偏移」并按 (工序, 计划日) 归并（无数据返回 {}）。

    v7.4：month 与读到的计划行同一月份口径，避免「计划行按月过滤、时长跨月混用」。
    """
    from database import get_project_process_durations as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager, month)


def list_project_process_durations(project_id: int, manager: str | None = None,
                                  month: str | None = None) -> list[dict]:
    """读取项目「按套工序时长/偏移」的**原始行**（含 set_seq，不归并）。

    「第 N 套」展示层的唯一数据源：逐套明细，供 node_service.build_set_index 聚合。
    ⚠️ 判定层仍用 ``get_project_process_durations``（中位数归并），两者互不影响。
    """
    from database import list_project_process_durations as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager, month)


def get_project_process_durations_batch(project_ids: list[int],
                                        month: str | None = None) -> dict[int, dict]:
    """批量读取多项目「按套工序时长/偏移」并归并（消除列表页 N+1）。"""
    from database import get_project_process_durations_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids, month)


def get_actuals_rich_by_node_ids(node_ids: list[int]) -> dict:
    """批量取节点实际进度（含 report_date）：{node_plan_id: {actual_qty, report_date}}。"""
    from database import get_actuals_rich_by_node_ids as _fn
    return getattr(_fn, "__wrapped__", _fn)(node_ids)


@_invalidates_dashboard
def delete_all_node_plans(project_id: int) -> None:
    """彻底清空项目全部节点计划（含独立工序）。"""
    from database import delete_all_node_plans as _fn
    _fn(project_id)


@_invalidates_dashboard
def upsert_node_actual(project_id: int, node_plan_id: int, process_name: str,
                       actual_qty: int, report_date: str,
                       manager: str | None = None) -> None:
    """写入/更新单个节点实际进度。多负责人（v6.0）：manager 标注归属负责人。"""
    from database import upsert_node_actual as _fn
    getattr(_fn, "__wrapped__", _fn)(project_id, node_plan_id, process_name,
                                     actual_qty, report_date, manager)


@_invalidates_dashboard
def upsert_manual_complete(project_id: int, complete_qty: int, complete_date: str,
                           manager: str | None = None) -> int:
    """手动完成：按日期 upsert 一条『附件安装』节点计划 + 实际完成，返回 node_plan_id。

    manager（v6.0 多负责人）必须写入，否则出品排名按 pnp.manager IS NOT NULL
    过滤会漏掉手动完成数据。桥接根目录 database.py 的 upsert_manual_complete。
    """
    from database import upsert_manual_complete as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, complete_qty, complete_date, manager)


@_invalidates_dashboard
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


@_invalidates_dashboard
def move_independent_fill_date(project_id: int, process_name: str,
                               node_plan_id: int, new_report_date: str,
                               new_qty: int | None = None) -> int:
    """独立工序「已完成」记录改日期/数量（管理员用）：移动 plan_date + actual.report_date，
    目标日期已有记录则合并；new_qty 非 None 时同步数量。桥接根目录 database.py 的同名函数。
    """
    from database import move_independent_fill_date as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, process_name, node_plan_id, new_report_date, new_qty)


# ---------- 按段填报（v7.1 行级化，node_segment_progress） ----------

@_invalidates_dashboard
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


@_invalidates_dashboard
def delete_node_segment(project_id: int, node_plan_id: int) -> int:
    """删除某套（计划行）的按段填报记录（「取消按段提报」用）。

    桥接根目录 database.py 的 delete_node_segment：只清 node_segment_progress，
    **不改** actual_qty / report_date —— 已填完成套数是既成事实，取消后状态自然回落到
    按 actual_qty 的常规判定（取消按段不影响进度百分比与排名口径）。
    返回实际删除行数（0 = 本来没有按段记录，幂等）。
    """
    from database import delete_node_segment as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, node_plan_id)


def get_node_segments_batch(project_ids: list[int]) -> dict:
    """批量查询多项目的按段填报行 → {project_id: {node_plan_id: (total, done)}}。

    桥接根目录 database.py 的 get_node_segments_batch（项目列表一次性取回，避免 N+1）。
    """
    from database import get_node_segments_batch as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_ids)


# ---------- 多负责人管理（v6.0） ----------

def split_managers(delivery_person: str | None) -> list[str]:
    """把「交付负责人」按 '/'（含全角'／'）拆分为负责人列表（去空+去重+保序）。"""
    from database import split_managers as _fn
    return getattr(_fn, "__wrapped__", _fn)(delivery_person)


@_invalidates_dashboard
def upsert_manager_monthly_plan(project_id: int, manager: str, monthly_plan: int) -> None:
    """写入/更新「某负责人 对 某项目」的本月计划数（方案P：独立申报，不校验求和）。"""
    from database import upsert_manager_monthly_plan as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager, monthly_plan)


def get_manager_monthly_plan_map(project_id: int) -> dict[str, int]:
    """取项目各负责人本月计划数映射：{负责人: monthly_plan}（未申报者不在结果中）。"""
    from database import get_manager_monthly_plan_map as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id)


def get_schedule_month_summary(project_id: int, manager: str | None = None) -> dict:
    """项目排产的「月份分布」概览（v7.4）：{months, last_plan_month, legacy_rows}。

    只统计排产工序白名单行（process_order 1..11）；供详情页展示
    「本月是否已导入 / 数据是否为历史结转」。
    """
    from database import get_schedule_month_summary as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, manager)


def get_manual_completes(project_id: int, month: str | None = None) -> list[dict]:
    """列出手动完成记录（process_order=99）+ 实际完成量，供「手动完成」弹窗展示/修改。

    month='YYYY-MM' 时只返回「完成月」（plan_date 所在月）匹配的记录；None=全部。
    """
    from database import get_manual_completes as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, month)


@_invalidates_dashboard
def delete_manual_complete(project_id: int, node_plan_id: int) -> int:
    """删除一条手动完成记录（99 占位行）及其实际完成量（纠正/减少套数用）。

    只允许删 process_order=99 且属于该项目的行，返回实际删除行数（0=未命中）。
    """
    from database import delete_manual_complete as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, node_plan_id)


def list_project_managers(project_id: int, month: str | None = None) -> list[dict]:
    """列出项目负责人清单及概况（供「多负责人管理」弹窗使用）。

    每项：manager / monthly_plan / plan_rows / has_imported
    v7.4：传 month 时 plan_rows / has_imported 回答「该负责人**本月**是否已导入排产」。
    """
    from database import list_project_managers as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, month)


def get_ranking_manager_rows_by_month(month: str,
                                      big_area_person: str | None = None,
                                      today: str | None = None) -> list[dict]:
    """出品排名（v6.0 多负责人）：返回当月每个 (项目 × 负责人) 的计划/完成明细行。

    与 get_ranking_summary_by_month 的区别：按 '/' 拆分后，每位负责人各占一行，
    使出品排名能把多位负责人的数据分别展示、分别排名。桥接根目录 database.py 同名函数。

    v7.8：新增 ``today``（'YYYY-MM-DD'，由调用方用 business_today() 传入，禁 SQL CURDATE()）。
    传入后每行附带 ``today_actual`` = 该 (项目 × 负责人) 今日新增完成套数；不传则为 0。
    """
    from database import get_ranking_manager_rows_by_month as _fn
    return getattr(_fn, "__wrapped__", _fn)(month, big_area_person, today)


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

    性能（2026-10）：结果按 (month, big_area_person) 缓存 DASHBOARD_STATS_TTL_SECONDS 秒。
        首次/过期后仍走原实现（结果逐项相同）；写过数据后由 ``_invalidates_dashboard``
        立即失效。缓存关闭（TTL=0）时行为与改造前完全一致。
    """
    key = (month or "", big_area_person or "")
    cached = _dashboard_cache.get(key)
    if cached is not None:
        return dict(cached)          # 返回副本，避免调用方改动污染缓存

    items, _ = get_projects_filtered(
        keyword="", person="", status="", skip=0, limit=100000, month=month,
        big_area_person=big_area_person,
    )
    stats = {
        "total_projects": len(items),
        "warning_projects": sum(1 for p in items if p.get("risk_level") == "warning"),
        "delayed_projects": sum(1 for p in items if p.get("risk_level") == "delayed"),
        # 异常项目数（第 4 态，2026-11）：与列表 status=exception 的筛选结果**必然相等**
        # （同一数据源 + 同一 risk_level 单源判定）。
        # 恒等式：normal + warning + delayed + exception == total_projects（四态互斥）。
        "exception_projects": sum(1 for p in items if p.get("risk_level") == "exception"),
        "monthly_plan_total": sum(int(p.get("monthly_plan", 0) or 0) for p in items),
    }
    _dashboard_cache.set(key, dict(stats))
    return stats



# ---------- 手动添加 / 调度令导入 复用封装 ----------

@_invalidates_dashboard
def upsert_project(data: dict, mapped_fields=None):
    """插入或更新项目（四字段唯一键），返回 (project_id, is_new)。

    mapped_fields: 本次 Excel 已映射的系统字段集合（覆盖保护用）；None=不过滤。
    """
    from database import upsert_project as _fn
    return getattr(_fn, "__wrapped__", _fn)(data, mapped_fields)


@_invalidates_dashboard
def sync_independent_plans(project_id: int, contract_count) -> int:
    """同步项目两条独立工序节点计划（累计完成总数 / 累计发运总数）。"""
    from database import sync_independent_plans as _fn
    return getattr(_fn, "__wrapped__", _fn)(project_id, contract_count)


@_invalidates_dashboard
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

@_invalidates_dashboard
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
                          month: str | None = None, big_area_person: str | None = None,
                          today=None):
    """项目搜索/筛选 + 服务端分页。

    status 语义为「风险等级」（normal/warning/delayed/exception），由 node_plans + node_actuals
    实时计算（与详情页/节点预警口径一致），因此**不能**下推到 SQL 的 projects.status
    （生命周期字段 in_progress/completed）。
    实现：取全量项目 → keyword/person/big_area_person 内存过滤 → 计算 risk_level/progress_pct →
    风险等级内存过滤 → 切片分页。
    month: 调度令归属月份（'YYYY-MM'），口径 = projects.created_at 年月 ∪ dispatch_records.plan_month；
           命中快照的项目以该月快照口径覆盖 monthly_plan/last_month_output，三页联动共享。
    big_area_person: 大区负责人 精确相等过滤。
    today: 基准日（None → 业务时区今天）。本函数是「列表入口」，**在此取一次**后逐层透传，
           下游不再各自取业务今天（避免跨零点请求出现两个"今天"）。

    🔴 项目级风险等级四态互斥：``exception > delayed > warning > normal``，
       判定单源 = ``business_logic.judge_project_risk``（与 routers/projects.py 详情页共用）。
    """
    # status 不再作为生命周期条件下推，统一取全量项目（big_area_person 下推 SQL 做行级隔离）
    rows = get_all_projects(None, big_area_person)
    # 基准日：本入口取一次，逐层透传（禁止 SQL CURDATE / 各处 date.today()）
    today_date = business_today() if today is None else today

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
    from ..services.node_service import enrich_rows, build_exception_anchors
    from ..services.business_logic import (judge_project_risk, has_active_exception,
                                           has_warning_exception)

    # 一次性批量查询（消除 N+1：原逻辑每项目 2 次 DB 往返 → 现在全程仅 3 次）
    # v7.4：三处批量查询统一带上当前列表月份 —— 「整体进度 / 风险等级」必须与列表的
    #       月份口径一致，否则跨月共存的排产行会被相加、进度虚高。
    all_pids = [p["id"] for p in rows]
    plans_map = get_node_plans_batch(all_pids, month)             # 1 次查询
    actuals_map = get_node_actuals_batch(all_pids)               # 1 次查询
    durations_map = get_project_process_durations_batch(all_pids, month)   # 1 次查询（工序时间规则升级）
    # 按段填报（v7.1 行级化）：批量取回全部项目的段进度 → 参与节点状态判定
    # （按段提报未填满的行 → 进行中，不再判「逾期未完成」；表缺失/查询失败不阻塞列表）
    try:
        seg_map_by_pid = get_node_segments_batch(all_pids)   # 1 次查询
    except Exception as e:  # noqa: BLE001 — 按段填报为增强功能，失败不阻塞
        import logging
        logging.getLogger(__name__).warning("get_node_segments_batch 失败：%s", e)
        seg_map_by_pid = {}

    # 异常暂停（2026-10）：批量取回全部项目的异常（含已关闭），避免逐项目 N+1。
    # 与详情页同口径：**生效中**异常 → 该套后续工序暂停（不计逾期/风险）；
    # 已关闭异常 → 以解决时间重算后续工序计划日（按新计划日判逾期）；
    # 已到期失效（expired）→ 暂停失效、**不**重算计划日（expired ≠ closed），按原计划日判逾期。
    # 缺表/查询失败 → 降级为「无异常」，风险口径回到改动前行为（不阻塞列表）。
    try:
        exc_map_by_pid = get_node_exceptions_batch(all_pids)   # 1 次查询
    except Exception as e:  # noqa: BLE001 — 异常暂停为增强判定，失败回退原规则
        import logging
        logging.getLogger(__name__).warning("get_node_exceptions_batch 失败：%s", e)
        exc_map_by_pid = {}

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

            # ---- 手动完成痕迹（process_order=99 占位行）----
            # 背景：提前完工但没有排产计划的项目走「手动完成」补录，写入的是
            # process_order=99 / process_name='附件安装' 的占位行（plan_month 恒为 NULL）。
            # 该行既不进排产白名单（1..11）、也不进上传台账 → 排产总览此前**完全看不到痕迹**，
            # 管理员无法判断这些项目是「漏传」还是「已手动完成」。
            # 这里按 plan_date 的归属月聚合，供前端展示「手动完成」状态。
            cur.execute(
                "SELECT DISTINCT project_id, DATE_FORMAT(plan_date, '%%Y-%%m') AS m "
                "FROM process_node_plans WHERE process_order = %s AND plan_date IS NOT NULL",
                (MANUAL_COMPLETE_ORDER,),
            )
            manual_months: dict[int, set] = {}
            for r in cur.fetchall():
                if r["m"]:
                    manual_months.setdefault(int(r["project_id"]), set()).add(str(r["m"]))
    finally:
        conn.close()

    for p in rows:
        pid = p["id"]
        p["has_schedule_plan"] = (pid in month_schedule_ids) if month else (pid in has_schedule_ids)
        # 历史是否传过（白名单口径）+ 最近一次上传归属月，供前端区分
        # 「本月未上传 · 上次上传 9 月」与「从未上传」两种不同状态。
        p["has_schedule_plan_ever"] = pid in has_schedule_ids
        p["schedule_upload_month"] = last_schedule_months.get(pid)

        # 手动完成痕迹（v7.3）：供排产总览展示「手动完成」，避免提前完工项目被误读为漏传。
        #   has_manual_complete          —— 曾经手动完成过（任何月份）
        #   manual_complete_month        —— 最近一次手动完成的归属月（'YYYY-MM'）
        #   manual_completed_this_month  —— 该手动完成是否落在当前查询月份（无 month 时恒 False）
        _mmonths = manual_months.get(pid) or set()
        p["has_manual_complete"] = bool(_mmonths)
        p["manual_complete_month"] = max(_mmonths) if _mmonths else None
        p["manual_completed_this_month"] = bool(month and month in _mmonths)

        plans = plans_map.get(pid, [])
        actuals = actuals_map.get(pid, {})
        _dur = durations_map.get(pid)
        _exc_rows = exc_map_by_pid.get(pid) or []
        nodes = enrich_rows(plans, actuals, today_date, durations=_dur,
                            seg_map=seg_map_by_pid.get(pid) or {},
                            exceptions=build_exception_anchors(
                                _exc_rows, _dur, plans, today=today_date))

        # ---- 风险等级（四态互斥：exception > delayed > warning > normal）----
        # 🔴 单源 = business_logic.judge_project_risk（与 routers/projects.py 详情页共用同一函数）
        # 项目级「生效中异常」用 **原始异常表** 判定（不依赖 durations 能否反推所属套）：
        # 无时长数据的存量项目同样能进 exception 态（PRD 明确口径）。
        # 2026-10：预警期（计划关闭日当天）异常不再让项目进 exception 态 ——
        # 项目整体转「预警」（warning），次日超期才按 exception/delayed 判。
        _has_active_exc = has_active_exception(_exc_rows, today_date, exclude_warning=True)
        _has_warning_exc = has_warning_exception(_exc_rows, today_date)
        p["has_active_exception"] = _has_active_exc or _has_warning_exc   # 含预警期（前端标记用）
        p["has_warning_exception"] = _has_warning_exc
        p["risk_level"] = judge_project_risk(
            nodes, int(p.get("monthly_plan") or 0), today_date,
            has_active_exception=_has_active_exc,
            has_warning_exception=_has_warning_exc,
        )

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
        # v7.5（2026-11）：把「整体进度」的分母一并返回，前端进度条 hover 展示
        #   「已完成 X 套 / 本月计划 Y 套」，X/Y 与 progress_pct **同源同分母**，
        #   保证 100% ↔ X==Y、16.7% ↔ 1/6，用户不会再看到「3/25 却是满条」的口径错位。
        # 注意：此处必须用 att_plan_qty（附件安装计划合计），**不是** contract_count
        #   （合同总数）也不是 monthly_plan（本月计划出品，语义不同）——三者不可互换。
        p["att_plan_qty"] = att_plan_qty
        # 剩余口径：contract_count = 项目总数（用户口径 2026-08-31 澄清）；
        # monthly_plan 是「本月待完成套数」，语义不同，**不做回退**
        _total = int(p.get("contract_count") or 0)
        p["remaining_sets"] = max(0, _total - att_actual_qty)

    # status 按风险等级在内存过滤（all / None / 其它值 → 不过滤）
    # 🔴 2026-11：白名单必须含 exception，否则「筛选异常」恒返回空、KPI 与列表对不上。
    if status in ("normal", "warning", "delayed", "exception"):
        rows = [p for p in rows if p.get("risk_level") == status]

    total = len(rows)
    items = rows[skip: skip + limit]
    return items, total


# ---------- 项目编辑 / 删除 / 计划重排 ----------

@_invalidates_dashboard
def update_project(project_id: int, data: dict) -> None:
    """更新项目信息（仅更新 data 中出现的字段）。"""
    from database import update_project as _fn
    _fn(project_id, data)


@_invalidates_dashboard
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


@_invalidates_dashboard
def create_node_exception(exc: dict) -> int:
    """新增异常记录，返回 id。

    「异常精确到套」（2026-10）：可选写入 ``set_seq`` / ``set_d0``（该异常指向第几套 +
    该套下料计划日快照），均为 **NULL 可空**——老调用方不传即写 NULL，历史行为不变
    （判定层对 set_seq IS NULL 的异常仍走中位数反推，逐条结果与改造前一致）。
    """
    params = dict(exc)
    # 老调用方（不传套号）→ 显式补 None，保证命名参数齐全、INSERT 不 KeyError
    params.setdefault("set_seq", None)
    params.setdefault("set_d0", None)
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO node_exceptions
                  (project_id, node_id, process_name, plan_date, responsibility_category,
                   reason_detail, handler, planned_close_date, measures, status,
                   set_seq, set_d0)
                VALUES
                  (%(project_id)s, %(node_id)s, %(process_name)s, %(plan_date)s,
                   %(responsibility_category)s, %(reason_detail)s, %(handler)s,
                   %(planned_close_date)s, %(measures)s, %(status)s,
                   %(set_seq)s, %(set_d0)s)
                """,
                params,
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


def get_open_exception_processes(project_id: int, today=None) -> dict[str, int]:
    """查询项目下**生效中**异常按工序聚合的数量：{process_name: 数量}。

    用于工序卡片显示「存在异常」标签并把该工序置为预警态。
    - 生效中 = status 不为 'closed'（pending / processing 都算；NULL 视为未关闭，防御历史脏数据）
      **且** (planned_close_date IS NULL OR planned_close_date >= today)
      —— 已过计划关闭日（expired）的异常暂停失效，不再计入「存在异常」。
      🔴 today 由 Python 传入，**禁止**在 SQL 里用 CURDATE()（时区/业务日历双口径会漂）。
    - 直接用 node_exceptions.process_name（该列 NOT NULL，提报时写入），
      **不 JOIN process_node_plans**：排产重导会删旧节点，JOIN 会让历史异常查不到
    - 独立工序（累计完成/发运）若有异常也会返回，由调用方决定是否展示

    Args:
        project_id: 项目 ID
        today: 基准日（None → 业务时区今天）

    Returns:
        dict[str, int]: {process_name: 生效中异常数量}
    """
    today_s = str(today if today is not None else business_today())[:10]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT process_name, COUNT(*) AS cnt
                FROM node_exceptions
                WHERE project_id = %s
                  AND (status IS NULL OR status <> 'closed')
                  AND (planned_close_date IS NULL OR planned_close_date >= %s)
                GROUP BY process_name
                """,
                (project_id, today_s),
            )
            return {row["process_name"]: int(row["cnt"]) for row in cur.fetchall()}
    finally:
        conn.close()


def get_node_exceptions_batch(project_ids: list[int]) -> dict[int, list[dict]]:
    """批量查询多项目的异常记录（**含已关闭**）→ {project_id: [异常行, ...]}。

    用途：项目列表的「风险等级 / 逾期」需要按异常的暂停与重算口径计算，逐项目查询会
    造成 N+1；此处按 900 分片一次取回。

    ⚠️ 与 ``get_open_exception_processes`` 同口径：**不 JOIN process_node_plans**
    （排产重导会删旧节点，JOIN 会让历史异常查不到），只按 project_id 过滤。
    缺表/查询失败时抛异常，由调用方决定是否降级（列表页降级为"无异常"）。

    🔴 必须取回 ``planned_close_date``（2026-11）：调用方据此判 active/expired。
       漏掉该列会让 active 判定在**列表/KPI/排名全域**退化成「永不到期」（到期不失效）。
    """
    if not project_ids:
        return {}
    by_pid: dict[int, list[dict]] = {}
    ids = [int(pid) for pid in project_ids]
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                fmt = ",".join(["%s"] * len(chunk))
                cur.execute(
                    f"SELECT id, project_id, node_id, process_name, plan_date, status, "
                    f"created_at, updated_at, closed_at, planned_close_date FROM node_exceptions "
                    f"WHERE project_id IN ({fmt})",
                    tuple(chunk),
                )
                for row in cur.fetchall():
                    by_pid.setdefault(int(row["project_id"]), []).append(dict(row))
    finally:
        conn.close()
    return by_pid


def get_node_exception_by_id(exc_id: int) -> dict | None:
    """按 id 查询单条异常。"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM node_exceptions WHERE id = %s", (exc_id,))
            return cur.fetchone()
    finally:
        conn.close()


@_invalidates_dashboard
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


@_invalidates_dashboard
def delete_exception_by_id(exception_id: int) -> int:
    """删除单条异常记录（**仅** node_exceptions 该行，不动实际进度/计划行）。

    桥接根目录 ``database.py`` 的同名函数。
    ⚠️ 根 database.py 新增函数必须在此同步 re-export，否则 ``db.delete_exception_by_id``
    抛 AttributeError → FastAPI 默认 500（本项目最高频踩坑点）。

    语义（与业务口径一致）：
      - 删除异常 = 该异常的「暂停 / 已关闭后重算计划日」影响**同时解除**；
        判定逻辑（services/business_logic.py）一行不改，下次读取自然回到无异常口径。
      - 幂等：记录不存在 / 已被删除 → 返回 0（由路由层决定 404）。

    Args:
        exception_id: 异常记录主键（node_exceptions.id）

    Returns:
        int: 实际删除行数（1 = 成功，0 = 不存在或已被删除）
    """
    from database import delete_exception_by_id as _fn
    return getattr(_fn, "__wrapped__", _fn)(int(exception_id))


# ---------- 用户（认证：大区行级隔离 v5.0） ----------

# 用户查询短缓存（2026-10 性能优化）：
# 每个需认证的请求都会经 deps.get_current_user → get_user_by_id 查一次 users 表
# （一次建连 + 一次查询）。用户信息读多写极少 → 30 秒 TTL 内存缓存。
# 失效：upsert_user（新建/改角色/改大区/改状态）同步清空；TTL ≤ 60s 兜底，
#       保证「用户被删除/停用/改角色/改密码」最迟 30 秒内对所有新请求生效。
USER_CACHE_TTL_SECONDS = _env_float("USER_CACHE_TTL_SECONDS", 30.0)
_user_cache = TTLCache("user_by_id", USER_CACHE_TTL_SECONDS, max_entries=2048)


def invalidate_user_cache(uid: int | None = None) -> int:
    """失效用户缓存：``uid`` 给定则只清该用户，否则清空全部。"""
    if uid is None:
        return _user_cache.invalidate()
    return _user_cache.invalidate(int(uid))


@_invalidates_dashboard
def upsert_user(username: str, password_hash: str, role: str,
                big_area_name: str = '', status: str = 'active') -> int:
    """插入或更新用户（唯一键 username；已存在保留原密码哈希），返回用户 id。

    写后清空用户缓存：角色 / 大区 / 状态变更必须立刻对新请求生效。
    """
    from database import upsert_user as _fn
    try:
        return getattr(_fn, "__wrapped__", _fn)(username, password_hash, role,
                                                big_area_name, status)
    finally:
        invalidate_user_cache()


def get_user_by_username(username: str) -> dict | None:
    """按用户名查询用户（不存在返回 None）。"""
    from database import get_user_by_username as _fn
    return getattr(_fn, "__wrapped__", _fn)(username)


def get_user_by_id(uid: int) -> dict | None:
    """按 id 查询用户（不存在返回 None）。

    性能（2026-10）：USER_CACHE_TTL_SECONDS（默认 30s）进程内缓存，命中 0 次查库；
    返回**副本**，调用方改动不会污染缓存。写用户（upsert_user）后立即失效。
    """
    try:
        key = int(uid)
    except (TypeError, ValueError):
        from database import get_user_by_id as _fn_raw
        return getattr(_fn_raw, "__wrapped__", _fn_raw)(uid)

    cached = _user_cache.get(key)
    if cached is not None:
        return dict(cached)

    from database import get_user_by_id as _fn
    user = getattr(_fn, "__wrapped__", _fn)(key)
    if user:
        _user_cache.set(key, dict(user))
    return user



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


# ---------- 提报情况总览（v7.6） ----------

def get_submission_board_aggregates(month_start: str, month_end: str,
                                    big_area_person: str | None = None) -> dict:
    """「提报情况总览」矩阵的 3 组聚合事实（计划 / 填报 / 异常，按 负责人×日期）。

    实现与口径见根 ``database.py`` 同名函数（仅 3 条 GROUP BY 查询，无 N+1）。
    """
    from database import get_submission_board_aggregates as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end, big_area_person)


# ---------- 提报情况总览 · 人工覆盖（v7.7） ----------
# ⚠️ 根 database.py 新增函数必须在此同步 re-export，否则 `db.xxx`
#    抛 AttributeError → FastAPI 默认 500（本项目最高频的坑）。

def get_submission_overrides(month_start: str, month_end: str) -> dict:
    """某自然月的人工覆盖映射 → {(manager, 'YYYY-MM-DD'): 'missed' | 'on_time'}。"""
    from database import get_submission_overrides as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end)


def get_submission_override_records(month_start: str, month_end: str) -> list[dict]:
    """某自然月的人工覆盖明细行（含 updated_by/updated_at，供前端 tooltip）。"""
    from database import get_submission_override_records as _fn
    return getattr(_fn, "__wrapped__", _fn)(month_start, month_end)


@_invalidates_dashboard
def save_submission_overrides(items: list[dict], updated_by: str = "") -> dict:
    """批量保存人工覆盖（'missed'/'on_time' → UPSERT，'auto' → DELETE），单事务。

    Returns:
        dict: {'upserted': int, 'deleted': int}
    """
    from database import save_submission_overrides as _fn
    return getattr(_fn, "__wrapped__", _fn)(items, updated_by)
