# -*- coding: utf-8 -*-
"""出品排名统计：按交付负责人维度聚合当月『附件安装』出品数据并排名。

统计口径（与排产数据一致）：
- 当月范围（调度令月份，与 core/db.get_projects_filtered 一致）：
  projects.created_at 年月 = month ∪ dispatch_records.plan_month = month
  —— 跨月延续项目（上月建档、本月又进调度令）必须计入，否则与总览/项目列表打架
- 计划/完成套数：仅『附件安装』工序（整体进度口径）；完成数为该批项目的累计实际
- 完成率 = 完成/计划×100%，分母为 0 → None（前端显示 —）
- 排名：完成率降序 → 计划套数降序 → 负责人升序
- 详情：该负责人当月存在「逾期/提前」节点的项目清单（全部工序）
  - 逾期：plan_date < today 且 actual_qty < plan_qty（含部分完成）
  - 提前：plan_date > today 且 actual_qty >= plan_qty
  - 注意：明细按 plan_date 落在当月筛选，与上面的「调度令月份」是两个不同维度（页面口径如此）
"""
import calendar
import logging
from datetime import date, datetime, timedelta

from ..core import db
from ..core.timeutil import business_today
from ..services.business_logic import judge_node_status, build_time_rules, exception_is_active
from ..services.node_service import build_exception_anchors

logger = logging.getLogger(__name__)


def _month_range(month: str) -> tuple[str, str]:
    """'2026-08' → ('2026-08-01', '2026-09-01')。"""
    y, m = map(int, month.split("-"))
    if m == 12:
        return f"{y}-12-01", f"{y + 1}-01-01"
    return f"{y}-{m:02d}-01", f"{y}-{m + 1:02d}-01"


def _today_str(today: date | str | None = None) -> str:
    """把业务日统一成 'YYYY-MM-DD'（None → business_today()）。

    全项目单一时间来源：业务时区由 ``core.timeutil`` 决定，**SQL 中禁止 CURDATE()**
    （数据库服务器时区可能与业务时区 Asia/Shanghai 不一致，导致「今日」错位）。
    """
    if today is None:
        today = business_today()
    if isinstance(today, datetime):
        return today.strftime("%Y-%m-%d")
    if isinstance(today, date):
        return today.strftime("%Y-%m-%d")
    return str(today)[:10]


def get_production_ranking(month: str, big_area_person: str | None = None,
                           today: date | str | None = None) -> list[dict]:
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
    today: 业务日（'YYYY-MM-DD' 或 date）；None → 取 business_today()。
       仅用于计算展示字段 today_increment，**不参与**任何计划/完成/完成率的计算。

    返回字段：manager / delivery_person(=manager 兼容别名) / total_plan / total_actual /
              completion_rate / project_count / rank /
              today_increment（今日新增完成套数，v7.8）/ today（业务日 'YYYY-MM-DD'）。
    """
    today_s = _today_str(today)
    manager_rows = db.get_ranking_manager_rows_by_month(month, big_area_person, today_s)

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
            "today_increment": 0,
            "project_ids": set(),
        })
        bucket["total_plan"] += int(r.get("total_plan") or 0)
        bucket["total_actual"] += int(r.get("total_actual") or 0)
        bucket["today_increment"] += int(r.get("today_actual") or 0)
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
            # v7.8：今日新增（仅展示用，>0 时前端在「累计完成套数」旁显示 ↑）
            "today_increment": b["today_increment"],
            "today": today_s,
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
    # v7.4：显式传 month，使取到的计划行与「按套时长」都与该排产归属月口径一致
    plans = db.get_all_plans_by_month_and_person(ns, ne, person, big_area_person, month)  # 1 次查询
    if not plans:
        return []
    node_ids = [p["id"] for p in plans]
    actuals = db.get_actuals_rich_by_node_ids(node_ids)           # 1 次查询（含日期，支持闸门锚点）
    pids = sorted({int(p["project_id"]) for p in plans})
    durations_map = db.get_project_process_durations_batch(pids, month)   # 1 次查询（按套时长/偏移）
    # 异常暂停（2026-10）：排名明细的「逾期/提前」必须与页面同口径 ——
    # 暂停中的后续工序不得出现在逾期明细里；已关闭异常按「解决时间」重算的新计划日判定。
    # 批量取回（1 次查询）；失败降级为"无异常"，排名口径回到改动前行为。
    try:
        exc_map = db.get_node_exceptions_batch(pids)
    except Exception as exc:                      # noqa: BLE001 — 增强判定，失败不阻塞排名
        logger.warning("get_node_exceptions_batch 失败（按无异常处理）：%s", exc)
        exc_map = {}
    today = business_today()

    # 按项目算「闸门 + effective 计划日期」（与页面口径一致，避免排名与页面打架）
    by_pid: dict[int, list] = {}
    for p in plans:
        by_pid.setdefault(int(p["project_id"]), []).append(p)
    rules_all: dict = {}
    for pid, plist in by_pid.items():
        _dur = durations_map.get(pid)
        exc_anchors = build_exception_anchors(exc_map.get(pid) or [], _dur, plist)
        rules_all.update(build_time_rules(plist, actuals, _dur, exc_anchors))

    result = []
    for p in plans:
        aq = int((actuals.get(int(p["id"])) or {}).get("actual_qty", 0) or 0)
        ru = rules_all.get(int(p["id"])) or {}
        # 待下料（闸门关的制造链工序）与法兰到货（不作主指标）不进逾期/提前明细；
        # 异常暂停（⏸ 异常暂停）同样排除——暂停期间不追责（用户 2026-10 口径）
        if ru.get("waiting_material") or ru.get("exception_paused") \
                or not ru.get("count_as_overdue", True):
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


# ============================================================
# 提报情况总览（v7.6）：当月日期 × 负责人 矩阵
# ============================================================
# 数据模型固有限制（必须对用户如实说明，前后端文案一致）：
# ① 填报：node_actual_progress 唯一键为 (project_id, node_plan_id)，每个计划节点**只有一条**
#    填报记录，report_date 是「最后一次填报日期」（覆盖式 upsert）。同一节点事后被改到另一日期时，
#    先前那天的「已提报」痕迹即消失 → 历史上个别已真实提报的日子可能被反标为 ×。
# ② 排产：排产导入是**整体覆盖式**（database.py insert_node_plans 的 del_cond 不含月份），
#    被重导项目的历史计划行已归档进 process_node_plans_history，主表只保留最新一份。
#    故历史月份矩阵可能整月空白——那是「计划已归档」，**不等于**「当月全部按时提报」。
SUBMISSION_BOARD_CAVEAT = (
    "数据说明：填报记录按节点覆盖式保存（node_actual_progress 唯一键 "
    "(project_id, node_plan_id)，report_date 为最后一次填报日期），"
    "同一节点事后改期会覆盖先前记录，历史个别已真实提报的日期可能被反标为 ×。"
    "另：排产计划为整体覆盖式导入，重新导入后历史月份的计划可能已被归档，"
    "该月矩阵可能出现空白（≠ 全部按时提报）。"
    # 2026-10：本页已改用「有效计划日」（异常/前置暂停顺延后的新计划日）判定，
    # 顺延出本月的工序不会出现在本月，也不会出现在顺延后所属月份（该月未导入它的计划），
    # 这类行属"剔除"而非"漏统计"，故在此明示，避免被反复当成漏报。
    "注：因异常或前置工序暂停而顺延到其它月份的工序，按顺延后的新计划日归属，"
    "不计入本月未提报统计（可在工序详情中查看「新计划日 / 原排产日」对照）。"
)


def _date_str(value) -> str:
    """把 date / datetime / 'YYYY-MM-DD HH:MM:SS' 统一成 'YYYY-MM-DD'。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


# ============================================================
# 提报情况总览 · 人工覆盖（v7.7 管理员编辑模式）
# ============================================================
# 语义：**覆盖记录，不是翻转**（用户 2026-10 确认）。
#   无记录                    → 自动判定
#   'missed'                  → 强制 ×（即使当天有填报/异常）
#   'on_time'                 → 强制留空（即使自动判定漏报）
#   同一格再操作回「无记录」  → action='auto' 删除覆盖行，恢复自动判定（可逆）
OVERRIDE_MISSED = "missed"
OVERRIDE_ON_TIME = "on_time"
OVERRIDE_AUTO = "auto"
OVERRIDE_ACTIONS = (OVERRIDE_MISSED, OVERRIDE_ON_TIME, OVERRIDE_AUTO)
# 单次批量提交上限（一个月最多 31 天 × 数十位负责人，2000 已远超真实需要）
OVERRIDE_MAX_ITEMS = 2000


def _load_submission_overrides(ns: str, ne: str) -> tuple[dict, dict]:
    """读取某自然月的人工覆盖 → ``(映射, 元信息)``。

    - 映射：``{(manager, 'YYYY-MM-DD'): 'missed'|'on_time'}``（合并矩阵时 O(1) 查表）
    - 元信息：``{(manager, 'YYYY-MM-DD'): {'updated_by','updated_at'}}``（tooltip 用）

    ⚠️ 容错：若目标库尚未执行 v7.7 DDL（表不存在），**只读接口不得因此 500**——
    这里降级为「无任何人工覆盖」，页面行为与改动前完全一致，仅缺少人工调整能力。
    写接口（保存）不做降级，缺表必须显式报错（提示先执行迁移脚本）。
    """
    try:
        records = db.get_submission_override_records(ns, ne)
    except Exception as exc:                      # noqa: BLE001 — 缺表/权限问题降级为无覆盖
        logger.warning("读取 submission_board_overrides 失败（按无覆盖处理）：%s", exc)
        return {}, {}

    mapping: dict[tuple[str, str], str] = {}
    meta: dict[tuple[str, str], dict] = {}
    for r in records or []:
        mgr = str(r.get("manager") or "").strip()
        ds = str(r.get("date") or "")[:10]
        ov = str(r.get("override_type") or "").strip()
        if not mgr or not ds or ov not in (OVERRIDE_MISSED, OVERRIDE_ON_TIME):
            continue
        key = (mgr, ds)
        mapping[key] = ov
        meta[key] = {
            "updated_by": str(r.get("updated_by") or "").strip(),
            "updated_at": str(r.get("updated_at") or "").strip(),
        }
    return mapping, meta


def _parse_iso_date(value) -> date | None:
    """'YYYY-MM-DD' → date；格式非法 / 非日期返回 None。"""
    text = str(value or "").strip()
    if len(text) != 10:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def save_submission_board_overrides(month: str, items: list[dict],
                                     updated_by: str = "") -> dict:
    """保存「提报情况总览」人工覆盖（批量、单事务、可逆）。

    逐条校验（任一不合法 → 抛 ``ValueError``，整批不落库）：
      1. ``manager`` 去空格后非空；
      2. ``date`` 为合法 ``YYYY-MM-DD`` 且落在 ``month`` 所在自然月；
      3. ``action`` ∈ {'missed','on_time','auto'}；
      4. **可编辑范围**：``action`` 为 'missed'/'on_time' 时，该 (负责人, 日期) 必须
         「当天有计划且已过判定截止日（judged）」——与只读矩阵同一口径
         （直接复用 ``get_submission_board`` 的 cell，避免两处口径漂移）。
         ``action='auto'``（恢复自动判定）**不做可编辑校验**：它只是删除一条覆盖记录，
         不改变矩阵语义，且便于清理历史遗留的无效覆盖。
      5. 同一批内重复的 (manager, date) 以**最后一条**为准（去重，避免重复计数）。

    Args:
        month: 'YYYY-MM'（调用方已规范化；本函数仍做一次解析兜底）
        items: [{'manager': str, 'date': 'YYYY-MM-DD', 'action': 'missed'|'on_time'|'auto'}]
        updated_by: 操作人用户名（写入 updated_by）

    Returns:
        dict: {'upserted': int, 'deleted': int, 'saved': int}；saved = upserted + deleted

    Raises:
        ValueError: 参数非法 / 超出可编辑范围（路由层转 400）
    """
    try:
        y, m = map(int, str(month).split("-"))
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("month 格式应为 YYYY-MM")

    if not isinstance(items, list) or not items:
        raise ValueError("items 不能为空")
    if len(items) > OVERRIDE_MAX_ITEMS:
        raise ValueError(f"单次最多提交 {OVERRIDE_MAX_ITEMS} 条")

    ns, ne = _month_range(f"{y:04d}-{m:02d}")
    cleaned: dict[tuple[str, str], str] = {}   # (manager, date) → action（后写覆盖前写）
    for idx, raw in enumerate(items, 1):
        row = raw or {}
        mgr = str(row.get("manager") or "").strip()
        if not mgr:
            raise ValueError(f"第 {idx} 条：manager 不能为空")
        ds = str(row.get("date") or "").strip()
        parsed = _parse_iso_date(ds)
        if not parsed:
            raise ValueError(f"第 {idx} 条：date 格式应为 YYYY-MM-DD（收到 {ds!r}）")
        if not (ns <= parsed.strftime("%Y-%m-%d") < ne):
            raise ValueError(f"第 {idx} 条：date {ds} 不在 {y:04d}-{m:02d} 内")
        action = str(row.get("action") or "").strip()
        if action not in OVERRIDE_ACTIONS:
            raise ValueError(
                f"第 {idx} 条：action 只能为 missed / on_time / auto（收到 {action!r}）")
        cleaned[(mgr, parsed.strftime("%Y-%m-%d"))] = action

    # ---- 可编辑范围校验（与只读矩阵同一口径）----
    # 只有「强制标记」需要校验：无计划谈不上未按时，今天/未来尚未判定。
    forced = {k: a for k, a in cleaned.items() if a != OVERRIDE_AUTO}
    if forced:
        board = get_submission_board(f"{y:04d}-{m:02d}", big_area_person=None)
        cells: dict[tuple[str, str], dict] = {}
        for r in board.get("rows") or []:
            mgr = str(r.get("manager") or "").strip()
            for c in r.get("cells") or []:
                cells[(mgr, str(c.get("date") or "")[:10])] = c
        for (mgr, ds), _action in forced.items():
            cell = cells.get((mgr, ds))
            if cell is None:
                raise ValueError(f"{mgr} · {ds}：该负责人当日无排产计划，不可编辑")
            if not cell.get("has_plan"):
                raise ValueError(f"{mgr} · {ds}：当天无计划，不可编辑")
            if not cell.get("judged"):
                raise ValueError(f"{mgr} · {ds}：今天/未来日期尚未判定，不可编辑")

    payload = [{"manager": mgr, "date": ds, "action": action}
               for (mgr, ds), action in cleaned.items()]
    res = db.save_submission_overrides(payload, updated_by)
    result = {
        "upserted": int(res.get("upserted") or 0),
        "deleted": int(res.get("deleted") or 0),
    }
    result["saved"] = result["upserted"] + result["deleted"]
    return result


def _load_effective_plan_dates(plan_rows: list[dict], exception_rows: list[dict],
                               today: date) -> tuple[dict, set, dict]:
    """算出每行「有效计划日 eff_plan_date」与「行级异常暂停」标记（2026-11 新增）。

    背景（用户 2026-11）：提报总览必须按**异常重算后的有效计划日**判定，与工序详情
    （``node_service.enrich_rows`` 用 ``eff_plan_date``、原值留在 ``plan_date_plan``）一致；
    此前总览直接用排产原始 ``plan_date``，导致「已因异常顺延到下月的工序」在原计划日被判未提报。

    实现：**完全复用** ``build_time_rules``（闸门 + 异常锚点），不重写任何判定：
      - 按 project_id 分组，每组一次 ``build_time_rules(该项目的全部计划行, actuals, durations,
        build_exception_anchors(该项目异常), today)``；
      - 取 ``eff_plan_date``（None → 不写 map，调用方回退原始 plan_date）；
      - 顺带取 ``exception_paused``（供覆盖口径的条件②，避免再跑一遍规则）。

    Args:
        plan_rows: ``db.get_submission_board_aggregates`` 的 ``plan_rows``（本批项目 × 本月）
        exception_rows: 同次返回的 ``exception_rows``（**本批项目的全部异常**，含已关闭）
        today: 业务今天（active 判定与判定层同源）

    Returns:
        (eff_map, paused_nodes, plans_by_id)
          - eff_map: ``{(project_id, node_id): 'YYYY-MM-DD'}``
          - paused_nodes: ``set[(project_id, node_id)]``（行级 exception_paused）
          - plans_by_id: ``{node_id: 计划行}``（供异常计数反查 manager/归属，INNER 语义）
    """
    plans_by_id: dict[int, dict] = {}
    project_ids: set[int] = set()
    for r in plan_rows:
        try:
            pid = int(r.get("project_id"))
            nid = int(r.get("node_id"))
        except (TypeError, ValueError):
            continue
        project_ids.add(pid)
        plans_by_id[nid] = r

    if not project_ids:
        return {}, set(), plans_by_id

    # 异常按项目分组（本批项目的全部异常，一次查询已由 db 层取回，不再重复查库）
    exc_by_pid: dict[int, list[dict]] = {}
    for e in exception_rows:
        try:
            exc_by_pid.setdefault(int(e.get("project_id")), []).append(e)
        except (TypeError, ValueError):
            continue

    try:
        plans_map = db.get_node_plans_batch(sorted(project_ids))
        actuals_map = db.get_node_actuals_batch(sorted(project_ids))
        dur_map = db.get_project_process_durations_batch(sorted(project_ids), None)
    except Exception as e:  # noqa: BLE001 — 有效计划日为增强口径，失败则回退原始 plan_date
        logger.warning("提报情况：批量加载 plans/actuals/durations 失败，回退原始计划日：%s", e)
        return {}, set(), plans_by_id

    eff_map: dict[tuple[int, int], str] = {}
    paused_nodes: set[tuple[int, int]] = set()
    for pid in sorted(project_ids):
        plans = plans_map.get(pid) or []
        durations = dur_map.get(pid) or {}
        if not plans:
            continue
        if durations:
            anchors = build_exception_anchors(exc_by_pid.get(pid) or [], durations, plans,
                                              today=today)
            rules = build_time_rules(plans, actuals_map.get(pid) or {}, durations,
                                     anchors, today=today)
        else:
            # 无时长数据（存量项目/未重导）→ 规则回退：不做闸门抑制、不重算日期
            # （与 build_time_rules 的 fallback 分支等价，此处直接跳过以免空跑）
            rules = {}
        for nid, rule in rules.items():
            eff = rule.get("eff_plan_date")
            if eff:
                eff_map[(pid, int(nid))] = str(eff)[:10]
            if rule.get("exception_paused"):
                paused_nodes.add((pid, int(nid)))
    return eff_map, paused_nodes, plans_by_id


def _build_plan_facts(plan_rows: list[dict], eff_map: dict,
                      month_start: str, month_end: str) -> tuple[list, dict, dict, list]:
    """把计划行按**有效计划日**聚合成矩阵所需的 (负责人, 日期) 事实（2026-11 改用 eff）。

    - 格子日期 = ``eff_map[(project_id, node_id)]``，缺失则回退原始 ``plan_date``；
    - **eff 落在查询月之外的行直接丢弃**（用户口径：延期到下月的工序不计入本月）；
    - ``plan_count`` / ``processes`` 的统计口径与旧 SQL 完全一致：
      ``COUNT(DISTINCT 项目|工序)`` 且仅 ``plan_qty > 0`` 才计入；
    - 负责人顺序沿用 SQL 的 gbk 拼音序（plan_rows 已按该顺序返回，去重保序）。

    Returns:
        (managers, plan_count, plan_procs, units)
          - units: [{'manager','d','project_id','process_name','node_id','has_actual'}]
            仅含 ``plan_qty > 0`` 的行（覆盖判定与 plan_count 同空间）
    """
    managers: list[str] = []
    seen: set[str] = set()
    plan_count: dict[tuple[str, str], int] = {}
    plan_procs: dict[tuple[str, str], set] = {}
    units: list[dict] = []
    unit_seen: dict[tuple[str, str], set] = {}

    for r in plan_rows:
        mgr = str(r.get("manager") or "").strip()
        if not mgr:
            continue
        try:
            pid = int(r.get("project_id"))
            nid = int(r.get("node_id"))
        except (TypeError, ValueError):
            continue
        ds = eff_map.get((pid, nid)) or _date_str(r.get("plan_date"))
        if not ds or ds < month_start or ds >= month_end:
            # eff 跑到月外（如 10-20 → 11-07）→ 本月不显示（用户明确要求）
            continue
        if mgr not in seen:
            seen.add(mgr)
            managers.append(mgr)
        key = (mgr, ds)
        qty = int(r.get("plan_qty") or 0)
        if qty > 0:
            unit = (pid, str(r.get("process_name") or ""))
            bucket = unit_seen.setdefault(key, set())
            if unit not in bucket:
                bucket.add(unit)
                plan_count[key] = plan_count.get(key, 0) + 1
            plan_procs.setdefault(key, set()).add(unit[1])
            units.append({
                "manager": mgr, "d": ds, "project_id": pid,
                "process_name": unit[1], "node_id": nid,
                "has_actual": r.get("has_actual"),
            })
        else:
            # plan_qty<=0：只用于「该负责人本月有排产行」（与旧口径一致，不计入格子）
            plan_count.setdefault(key, 0)

    procs = {k: sorted(v) for k, v in plan_procs.items()}
    return managers, plan_count, procs, units


def _load_submission_covered(units: list[dict], paused_nodes: set) -> tuple[dict, dict, dict]:
    """计算「当天视为已提报」的两类覆盖（2026-11 口径）。

    覆盖来源（任一成立即算该「单元 = 项目|工序」当天已提报）：
      ① **已提前完成**：该计划行已有 ``actual_qty > 0`` 的填报记录
         （report_date 可早于计划日 —— 计划日之前就填完了，当天没再填不算漏报）；
      ② **前置工序异常暂停**：该行**行级** ``exception_paused`` 为真
         （同套存在生效中异常且位于其上游工序）。

    Args:
        units: ``_build_plan_facts`` 的 units（日期已是 eff_plan_date）
        paused_nodes: ``_load_effective_plan_dates`` 的 ``paused_nodes``

    Returns:
        (covered_all, covered_early, covered_paused)，均为
        ``{(manager, 'YYYY-MM-DD'): set[(project_id, process_name)]}``；
        covered_early / covered_paused 为**互斥**拆分，便于 tooltip 分别说明。
    """
    early: dict[tuple[str, str], set] = {}
    paused_raw: dict[tuple[str, str], set] = {}
    for r in units:
        mgr = str(r.get("manager") or "").strip()
        if not mgr:
            continue
        try:
            pid = int(r.get("project_id"))
            nid = int(r.get("node_id"))
        except (TypeError, ValueError):
            continue
        key = (mgr, _date_str(r.get("d")))
        unit = (pid, str(r.get("process_name") or ""))
        if int(r.get("has_actual") or 0) > 0:
            early.setdefault(key, set()).add(unit)
        if (pid, nid) in paused_nodes:
            paused_raw.setdefault(key, set()).add(unit)

    covered_all: dict[tuple[str, str], set] = {}
    covered_paused: dict[tuple[str, str], set] = {}
    for key in set(early) | set(paused_raw):
        e_set = early.get(key, set())
        p_set = paused_raw.get(key, set())
        covered_all[key] = e_set | p_set
        if p_set - e_set:
            covered_paused[key] = p_set - e_set
    return covered_all, early, covered_paused


def get_submission_board(month: str, big_area_person: str | None = None) -> dict:
    """「提报情况总览」矩阵：当月自然日 × 负责人，标记「当天有计划但完全未提报」。

    判定口径（用户 2026-10 确认，不得自由发挥）：
      - 日期范围：筛选月份的自然月 1 日～月末（按真实天数，含闰年）
      - 负责人范围：该月存在排产计划行（``process_order`` 1..11）的负责人，
        由 SQL ``ORDER BY CONVERT(manager USING gbk)`` 给出拼音升序
      - 「当天有计划」：该负责人该日存在 ``process_node_plans`` 行，
        ``plan_date = 当天`` 且 ``plan_qty > 0``，且属排产工序白名单
        （``process_order`` 1..11）；独立工序（90/91，含每日填报产生的
        plan_date=填报日 的行）与手动完成占位行（99）一律不参与判定
      - 「未做任何操作」：当天既无填报（``node_actual_progress.report_date = 当天``）
        也无异常（``node_exceptions.created_at`` 的日期 = 当天，**不是** plan_date）
      - 🔴 2026-11 新口径（用户原话，**任一成立即视为当天已提报**）：
        ① 该工序**已提前完成** —— 该计划行已有 actual_qty>0 的填报记录（report_date 可早于
           计划日；计划日之前就填完了，当天没再填不算漏报）；
        ② 该工序该套的**前置工序存在异常且行级 exception_paused**（同套上游有生效中异常）；
        ③ 当天提报了异常（既有 exceptions 事实）；
        ④ 当天有填报（既有 reports 事实）。
        覆盖按「单元 = 项目|工序」计数（与 plan_count 同空间）：**全部单元被覆盖才留空**，
        部分覆盖仍判未按时，但 cell 会带 ``covered_count/covered_early/covered_paused``
        供 tooltip 说明「已覆盖 N/M」。
        ①② 的实现见 ``_load_submission_covered``：① 由 SQL 的 EXISTS 事实给出，
        ② 直接复用 ``build_time_rules`` 的 ``exception_paused``，**不重写判定**。
      - 标记 ×：有计划 且 无任何操作 且 无全部覆盖 且 该日 ≤ 昨天
      - 今天与未来：一律留空（判定截止到最后一天已结束的日期）
      - 🔴 月份归属（2026-11 用户改口径）：**当月排产计划不隔月** —— 一行属于查询月 M 当且仅当
        ``plan_month = M``（严格相等，NULL 不匹配）**且** ``plan_date`` 落在 M 的自然月区间。
        因此「上月导入本月日期的工序」「本月导入但延期到下月/留在往月的工序」都不会跨月出现。
        这与「排产计划总览」「出品排名总览」的 ``plan_month`` 口径**现在一致**（此前本页是纯
        日历口径，会出现隔月行，已被用户否决）。实现位置是数据源
        （``database.get_submission_board_aggregates`` 四组聚合的 WHERE），本层不重复过滤。

    v7.7 人工覆盖（管理员编辑模式）：
      ``submission_board_overrides`` 记录「负责人 × 日期」的人工判断，**覆盖**自动判定
      （不是翻转）：``'missed'`` → 强制 ×；``'on_time'`` → 强制留空。
      故每个 cell 同时暴露：
        - ``auto_missed``：原始自动判定值（保留，便于前端说明「自动判定 vs 人工调整」）
        - ``override``   ：``None | 'missed' | 'on_time'``（本格生效的人工覆盖）
        - ``missed``     ：**最终值**（人工覆盖优先，否则 = auto_missed）
        - ``editable``   ：``has_plan and judged``（前端编辑态据此置灰）
        - ``override_by`` / ``override_at``：操作人 / 操作时间（tooltip 用，未覆盖为 None）
      ``summary.missed_total`` 与 ``rows[].missed_total`` 均按**最终值**重算。

    Args:
        month: 'YYYY-MM'
        big_area_person: 大区负责人（行级隔离）；None = 全量

    Returns:
        dict: month / today / cutoff / dates / rows[{manager, cells[], missed_total}] /
              summary{manager_count, missed_total, day_count, override_count} / caveat
    """
    y, m = map(int, month.split("-"))
    days_in_month = calendar.monthrange(y, m)[1]          # 2 月自动 28/29
    month_dates = [date(y, m, d) for d in range(1, days_in_month + 1)]
    date_strs = [d.strftime("%Y-%m-%d") for d in month_dates]
    ns, ne = _month_range(month)

    today = business_today()
    cutoff = today - timedelta(days=1)

    agg = db.get_submission_board_aggregates(ns, ne, big_area_person)
    override_map, override_meta = _load_submission_overrides(ns, ne)

    # ---- 有效计划日（2026-11）：用异常重算后的 eff_plan_date 决定格子归属 ----
    # 与工序详情（node_service.enrich_rows）同源：build_time_rules + build_exception_anchors
    plan_rows = agg.get("plan_rows") or []
    exception_rows = agg.get("exception_rows") or []
    eff_map, paused_nodes, plans_by_id = _load_effective_plan_dates(plan_rows, exception_rows, today)

    # ---- 计划事实（按 eff 日期聚合；eff 落到月外的行不进入本月任何格子）----
    managers, plan_count, plan_procs, units = _build_plan_facts(plan_rows, eff_map, ns, ne)

    # ---- 填报事实（report_date = 操作日，不随 eff 改动）----
    reported: set[tuple[str, str]] = set()
    for r in agg.get("reports", []):
        mgr = str(r.get("manager") or "").strip()
        if mgr:
            reported.add((mgr, _date_str(r.get("d"))))

    # ---- 异常事实（created_at = 提报日；归属沿用「本月排产行」口径）----
    # exception_rows 是本批项目的**全部**异常（含历史），这里按旧口径过滤：
    #   · 该异常的计划行必须属于本月排产集合（plans_by_id 已按 plan_month/日期/白名单/负责人过滤）
    #   · created_at 的日期落在查询月
    exceptioned: set[tuple[str, str]] = set()
    for e in exception_rows:
        try:
            nid = int(e.get("node_id"))
        except (TypeError, ValueError):
            continue
        plan = plans_by_id.get(nid)
        if not plan:
            continue                     # 计划行不在本月集合 → 不计入（等价旧 INNER JOIN）
        mgr = str(plan.get("manager") or "").strip()
        if not mgr:
            continue
        ds = _date_str(e.get("created_at"))
        if ds and ns <= ds < ne:
            exceptioned.add((mgr, ds))

    # ---- 覆盖事实（2026-11 新口径）：已提前完成 / 前置工序异常暂停 → 当天视为已提报 ----
    covered_all, covered_early_map, covered_paused_map = _load_submission_covered(units, paused_nodes)

    # ---- 组装矩阵 ----
    rows: list[dict] = []
    missed_total = 0
    override_count = 0
    for mgr in managers:
        cells: list[dict] = []
        row_missed = 0
        for d, ds in zip(month_dates, date_strs):
            key = (mgr, ds)
            cnt = plan_count.get(key, 0)
            has_plan = cnt > 0
            has_report = key in reported
            has_exc = key in exceptioned
            # 覆盖：当天计划单元中「已提前完成」或「前置工序异常暂停」的个数
            # （单元 = 项目|工序，与 plan_count 同一空间；见 _load_submission_covered）
            cov_all = covered_all.get(key) or set()
            cov_early = covered_early_map.get(key) or set()
            cov_paused_only = covered_paused_map.get(key) or set()
            covered_count = len(cov_all) if has_plan else 0
            # 全部单元都被覆盖 → 当天视为已提报（不判未按时）
            all_covered = bool(cnt > 0 and covered_count >= cnt)
            # 仅判定「已经完整结束的日期」：今天与未来一律留空
            judged = d <= cutoff
            editable = bool(has_plan and judged)
            auto_missed = bool(has_plan and judged and not has_report and not has_exc
                               and not all_covered)
            # 人工覆盖只在「可编辑格」上生效（防御层）：即便库中存在陈旧记录
            # （排产重导后该日已无计划 / 该日已变为未来），也不得改变矩阵显示。
            override = override_map.get(key) if editable else None
            if override == OVERRIDE_MISSED:
                missed = True
            elif override == OVERRIDE_ON_TIME:
                missed = False
            else:
                missed = auto_missed
            meta = override_meta.get(key) or {}
            if override:
                override_count += 1
            if missed:
                row_missed += 1
            cells.append({
                "date": ds,
                "has_plan": has_plan,
                "plan_count": cnt,
                "processes": plan_procs.get(key, []),
                "reported": has_report,
                "exception": has_exc,
                # 2026-11 覆盖口径（前端 tooltip 用；判定已在 auto_missed 里生效）
                "covered_count": covered_count,
                "covered_early": len(cov_early),
                "covered_paused": len(cov_paused_only),
                "judged": judged,
                "editable": editable,
                "auto_missed": auto_missed,
                "override": override,
                "override_by": meta.get("updated_by") if override else None,
                "override_at": meta.get("updated_at") if override else None,
                "missed": missed,
            })
        missed_total += row_missed
        rows.append({"manager": mgr, "cells": cells, "missed_total": row_missed})

    return {
        "month": month,
        "today": today.strftime("%Y-%m-%d"),
        "cutoff": cutoff.strftime("%Y-%m-%d"),
        "dates": date_strs,
        "rows": rows,
        "summary": {
            "manager_count": len(rows),
            "missed_total": missed_total,
            "day_count": days_in_month,
            "override_count": override_count,
        },
        "caveat": SUBMISSION_BOARD_CAVEAT,
    }
