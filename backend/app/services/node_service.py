# -*- coding: utf-8 -*-
"""节点计划聚合服务：把原始行富化为前端所需的「时间轴 / 工序卡片 / 分组」数据。"""
from datetime import date, timedelta
from typing import Optional

from .business_logic import (judge_node_status, judge_process_card_status, split_node_groups,
                             compute_real_overdue, build_time_rules, cutting_anchor_map)
from .workday_calendar import parse_date
from ..core.config import SCHEDULE_PROCESS_NAMES, INDEPENDENT_PROCESS_NAMES
from ..core.timeutil import business_today


def _date10(value) -> str:
    """把任意日期值统一收口成 ``'YYYY-MM-DD'``（None / 空 / 字符串 'None' → ``''``）。

    统一出口用于 ``plan_date`` / ``plan_date_plan`` 两列，避免 ``str(None)[:10] == 'None'``
    这类脏值进入响应体（前端据此判断是否显示「原 X」对照）。
    """
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text == "None":
        return ""
    return text[:10]


def enrich_rows(plans: list[dict], actuals: dict, today=None, durations: Optional[dict] = None,
                rules: Optional[dict] = None, seg_map: Optional[dict] = None,
                exceptions: Optional[dict] = None,
                node_exceptions: Optional[dict] = None) -> list[dict]:
    """富化节点行：计划信息 + 实际完成 + 五态判定（含完成日期与偏差）。

    返回行结构与原 Streamlit 版 rows 一致（前端时间轴/卡片直接使用）。
    独立工序（累计完成总数/累计发运总数）：无日期语义，仅按 actual vs plan 输出
    done / in_progress，不走日期判定，避免被误判逾期/预警。
    工序时间规则升级（durations 非空时）：制造链工序按「实际下料闸门 + 重算日期」判定；
    durations 为 None / 缺该行时长 → 回退原规则（存量项目行为不变）。
    ⚠️ rules 可由调用方预计算传入——**闸门锚点需要全项目的计划行**（找「下料」行），
    若 plans 已被过滤成单道工序，必须传全量行算出的 rules，否则全部误判为待下料。
    v7.1 按段填报（行级化，seg_map 非空时）：
      - 每行输出 segment_total / segment_done（无记录为 None，前端据此显示「已完成 n/m 段」）；
      - **已按段提报且 segment_done > 0 的行 → 判定为「进行中」，不再判「逾期未完成」**
        （用户 2026-10-09 口径）。口径说明：只看「是否有已完成段」，不看是否填满——
        「已完成 5/5 段」同样属于已开工，否则会出现「已完成 5/5 段 + 逾期未完成」的矛盾；
        段记录 done=0（只填了总段数）不算开工，仍按原规则判逾期。
    异常暂停（2026-10，exceptions 非空时）：
      - 每行输出 exception_paused / has_open_exception / has_closed_exception /
        exception_processes / exception_count / set_date；
      - 该套有未关闭异常 → 其后续工序 status='exception_paused'（⏸ 异常暂停，灰），
        不计入逾期/风险/排名；该套有已关闭异常 → 以解决时间重算后续工序计划日；
      - **exceptions 为 None 时行为与改动前逐项一致**（向后兼容红线）。

    Args:
        plans: 待富化的计划行（可只含单工序，但此时建议由调用方传入 rules）
        actuals: {node_plan_id: {actual_qty, report_date}}
        today: 判定基准日（None → 业务时区当天）
        durations: {(process_name, 'YYYY-MM-DD'): {"offset_days": int}}
        rules: build_time_rules() 的产物（None 时内部按 plans 现算）
        seg_map: {node_plan_id: (segment_total, segment_done)}
        exceptions: {该套下料计划日 d0: [{process_name, offset_days, status, closed_at}]}
        node_exceptions: {node_plan_id: [{process_name, status, closed_at}]}（纯展示兜底：
            所属套无法反推时，仍能在异常自身的行上打「⚠️ 异常」标识）

    Returns:
        list[dict]: 富化后的节点行（每行含 status/label/level/... 及上述新增字段）
    """
    today = today or business_today()
    exc_map = exceptions or {}
    node_exc_map = node_exceptions or {}
    if rules is None:
        rules = build_time_rules(plans, actuals, durations, exc_map)
    seg_map = seg_map or {}
    rows = []
    for r in plans:
        nid = r["id"]
        act = actuals.get(nid, {})
        actual_qty = act.get("actual_qty", 0)
        completion_date = act.get("report_date") if actual_qty >= r["plan_qty"] else None
        ru = rules.get(nid) or {}
        seg = seg_map.get(int(nid))
        seg_total = int(seg[0]) if seg else None
        seg_done = int(seg[1]) if seg else None
        # 按段提报已开工（有已完成段）→ 「进行中」语义
        segment_active = seg_total is not None and int(seg_done or 0) > 0
        # 异常上下文（所属套 = 同一「下料计划日」）：用于状态判定 + 前端「哪一套有异常」标识
        # 合并两个来源并按 exception_id 去重：「按套聚合」+「按节点兜底」同一异常只算一次
        set_date = ru.get("set_date")
        merged: list[dict] = []
        seen_exc: set = set()
        for e in (exc_map.get(set_date) or []) if set_date else []:
            key = e.get("exception_id")
            if key is not None:
                seen_exc.add(key)
            merged.append(e)
        for e in (node_exc_map.get(int(nid)) or []):
            key = e.get("exception_id")
            if key is not None and key in seen_exc:
                continue
            merged.append(e)
        open_excs = [e for e in merged if str(e.get("status") or "pending") != "closed"]
        exception_paused = bool(ru.get("exception_paused"))
        if r["process_name"] in INDEPENDENT_PROCESS_NAMES:
            done = actual_qty >= r["plan_qty"]
            st = {
                "status": "done" if done else "in_progress",
                "label": "🟢 已完成" if done else "🔵 进行中",
                "level": 0, "lag_qty": 0, "completion_date": completion_date,
                "deviation_days": 0, "deviation_label": "-", "deviation_color": "#718096",
                "count_as_overdue": False,
            }
        else:
            st = judge_node_status(
                r["plan_date"], r["plan_qty"], actual_qty, today, completion_date,
                eff_plan_date=ru.get("eff_plan_date"),
                waiting_material=bool(ru.get("waiting_material")),
                count_as_overdue=ru.get("count_as_overdue", True),
                segment_active=segment_active,
                exception_paused=exception_paused,
            )
        rows.append({
            "id": nid,
            "project_id": r["project_id"],
            "process_name": r["process_name"],
            # 闸门开（已实际下料）的制造链工序：对外展示/分组的计划日期 = 重算后的 effective 日期
            # （原排产计划日期保留在 plan_date_plan 供对照）
            "plan_date": (str(ru.get("eff_plan_date"))[:10] if ru.get("eff_plan_date")
                          else (str(r["plan_date"])[:10] if r.get("plan_date") is not None else "")),
            # 原排产计划日：优先取上游（build_process_detail 覆盖 plan_date 前已收好的原值），
            # 否则回退 r["plan_date"]（未重算的行两者相等 → 前端不显示「原 X」删除线）
            "plan_date_plan": (_date10(r.get("plan_date_plan")) or _date10(r.get("plan_date"))),
            "plan_qty": r["plan_qty"],
            "actual_qty": actual_qty,
            "report_date": str(act.get("report_date") or "")[:10] or None,
            # 按段填报回显（v7.1 行级化；无记录为 None）
            "segment_total": seg_total,
            "segment_done": seg_done,
            # 异常上下文（2026-10）：所属套标识 + 计入口径
            # set_date = 该行所属套的「下料计划日」（同一套的关联键，非套号）
            "set_date": set_date,
            "exception_paused": st["status"] == "exception_paused",
            "has_open_exception": bool(open_excs),
            "has_closed_exception": any(
                str(e.get("status") or "") == "closed" for e in merged
            ),
            # 未关闭异常涉及的工序名（前端据此提示「卷制有异常」而非只有一句"存在异常"）
            "exception_processes": sorted({
                str(e.get("process_name") or "") for e in open_excs if e.get("process_name")
            }),
            "exception_count": len(open_excs),
            **st,
        })
    return rows


def _load_node_segments(project_id: int) -> dict[int, tuple[int, int]]:
    """读取项目全部按段填报行（v7.1 行级化）→ {node_plan_id: (segment_total, segment_done)}。

    查询失败（如表未建）返回空 dict，不阻塞总览。
    """
    if project_id is None:
        return {}
    from ..core import db
    try:
        seg_map: dict[int, tuple[int, int]] = {}
        for seg in (db.get_node_segments(int(project_id)) or []):
            seg_map[int(seg.get("node_plan_id") or 0)] = (
                int(seg.get("segment_total") or 0), int(seg.get("segment_done") or 0),
            )
        return seg_map
    except Exception as e:  # noqa: BLE001 — 按段填报为增强功能，失败不阻塞主流程
        import logging
        logging.getLogger(__name__).warning("get_node_segments(%s) 失败：%s", project_id, e)
        return {}


# 对外公开别名：路由层（项目详情风险 / 预警列表）复用同一带兜底的读取逻辑
load_node_segments = _load_node_segments


def _load_open_exceptions(project_id: int) -> dict[str, int]:
    """读取项目「未关闭」异常按工序聚合 → {process_name: 异常数量}。

    用于工序卡片打「存在异常」标签并置为预警态。
    与 _load_node_segments 同口径：查询失败（如表未建）返回空 dict，不阻塞总览。
    """
    if project_id is None:
        return {}
    from ..core import db
    try:
        return dict(db.get_open_exception_processes(int(project_id)) or {})
    except Exception as e:  # noqa: BLE001 — 异常标签为增强展示，失败不阻塞主流程
        import logging
        logging.getLogger(__name__).warning("get_open_exception_processes(%s) 失败：%s", project_id, e)
        return {}


def build_exception_anchors(exc_rows: Optional[list[dict]], durations: Optional[dict] = None,
                            plans: Optional[list[dict]] = None,
                            set_index: Optional[dict] = None) -> dict[str, list[dict]]:
    """把异常记录**反推**到「所属套」并聚合（纯函数，无 IO，便于单测/回归）。

    「同一套」的关联键 = 该行的 **下料计划日 d0**（= 该行 plan_date − 该行 offset_days），
    与 ``build_time_rules`` 的 ``cutting_anchor`` 完全同源——这是现有机制，不另造关联键。

    反推步骤（每条异常）：
      1. 定位该异常所在计划行的 (process_name, plan_date)：
         · 优先用当前计划行（node_id → plans 的 process_name/plan_date）——排产重导后
           只要有同样的节点仍能对上；
         · 计划行已不存在时回退用 ``node_exceptions.plan_date`` 快照（提报时写入）。
      2. 查 ``durations[(process_name, plan_date)].offset_days``；
         查不到（非制造链工序 / 该月未导入 / 存量项目无时长数据）→ **跳过**该异常
         （无法定位所属套，保守起见不参与排产重算，行为等同改动前）。
      3. d0 = plan_date − offset_days，按 d0 聚合成
         ``{d0: [{"process_name", "offset_days", "status", "closed_at", "exception_id",
                  "set_seq", "set_d0", "bucket_d0"}]}``。

    ===== 套号元数据（2026-10，「异常精确到套」）=====
    本函数**签名向后兼容**（新增的 ``set_index`` 为可选关键字参数，既有 3 参调用不变），
    内部按三档补充「这条异常指向第几套」的**元数据**（``set_seq`` / ``set_d0``），
    供展示层把 ⚠️ 异常标到具体的「第 N 套」子行上：
      ① 异常自带 ``set_seq``，且该 (工序, 计划日) 的套成员里存在同 seq 的成员 → 记录该成员套号
         与该成员自己的 d0（``每套各自算``，绝不跨套合并）；
      ② 无 set_seq 但自带 ``set_d0``，且成员里存在同 d0 的成员 → 记录该成员套号与该 d0；
      ③ 两者都没有（**历史 NULL 异常全部走这一档**）→ 不记录套号元数据，
         反推结果（d0 / offset_days / status / closed_at）与改造前**逐条逐字段一致**。

    🔴 判定口径零改动的关键约束：``d0`` 与条目里的 ``offset_days`` **仍取 durations 的
       中位数代表值**（与 ``build_time_rules`` 同源），**不因套号而改用某个成员的 offset**。
       原因：排产计划行按 (工序, 计划日) 聚合（1 行 = N 套），判定层只能按「中位代表值算出的
       d0」匹配行；若改成某套自己的 offset，聚合行的 d0 将对不上任何行 → 该套异常会
       **静默地不再暂停任何工序**，违反「暂停保持整行」的用户口径（第 3 套异常 → 整行后续
       工序全暂停），也让逾期数/KPI 发生漂移。逐套的精确日期只用在展示层
       （``judge_set_display_status``）里按**该套自己的 offset** 重算，不影响判定。

    Args:
        exc_rows: node_exceptions 原始行（含 project_id/node_id/process_name/plan_date/
                  status/closed_at/id，可选 set_seq/set_d0）；None/空 → 返回 {}
        durations: {(process_name, 'YYYY-MM-DD'): {"offset_days": int}}
        plans: 项目当前计划行（可选，用于把 node_id 映射到最新 plan_date）
        set_index: 可选，``build_set_index`` 的产物（套成员明细）；None → 只走第 ③ 档

    Returns:
        dict[str, list[dict]]: 按「下料计划日」聚合的异常列表
    """
    if not exc_rows or not durations:
        return {}
    # node_id → (process_name, plan_date)：仅在工序名一致时用于覆盖快照日期
    node_meta: dict[int, tuple[str, str]] = {}
    for p in plans or []:
        try:
            node_meta[int(p.get("id"))] = (
                str(p.get("process_name") or ""),
                str(p.get("plan_date") or "")[:10],
            )
        except (TypeError, ValueError):
            continue

    anchors: dict[str, list[dict]] = {}
    for e in exc_rows:
        pn = str(e.get("process_name") or "").strip()
        if not pn:
            continue
        pd = ""
        try:
            meta = node_meta.get(int(e.get("node_id") or 0))
        except (TypeError, ValueError):
            meta = None
        if meta and meta[0] == pn and meta[1]:
            pd = meta[1]                       # 优先用当前计划行的日期
        if not pd:
            pd = str(e.get("plan_date") or "")[:10]   # 回退：异常快照日期
        info = durations.get((pn, pd))
        if not info:
            continue
        offset_raw = info.get("offset_days")
        if offset_raw is None:
            continue
        base = parse_date(pd)
        if base is None:
            continue
        offset = int(offset_raw)
        d0 = (base - timedelta(days=offset)).strftime("%Y-%m-%d")
        status = str(e.get("status") or "pending").strip() or "pending"
        closed_at = str(e.get("closed_at") or "")[:10] or None
        # 套号元数据（三档；仅展示用，不改变上面的 d0 / offset）
        set_seq, set_d0 = _resolve_exception_set(e, pn, pd, set_index)
        anchors.setdefault(d0, []).append({
            "process_name": pn,
            "offset_days": offset,
            "status": status,
            "closed_at": closed_at,
            "exception_id": e.get("id"),
            "set_seq": set_seq,
            "set_d0": set_d0,
            "bucket_d0": d0,
        })
    return anchors


def _resolve_exception_set(exc: dict, process_name: str, plan_date: str,
                           set_index: Optional[dict]) -> tuple[Optional[int], Optional[str]]:
    """把一条异常解析到「具体第几套」→ ``(set_seq, set_d0)``；无法解析 → ``(None, None)``。

    三档（详见 ``build_exception_anchors`` 文档）：
      ① 异常自带 ``set_seq`` 且 (工序, 计划日) 的套成员里有同 seq → (seq, 该成员 d0)
      ② 异常自带 ``set_d0`` 且成员里有同 d0 → (该成员 seq, d0)
      ③ 否则 → (None, None)（历史 NULL 异常；行为等同改造前）

    纯函数，无 IO。set_index 为 None / 该键无成员（存量项目、非制造链工序）→ 第 ③ 档。
    """
    members = (set_index or {}).get((process_name, plan_date)) or []
    if not members:
        return None, None
    # ---- 档①：按套号精确匹配 ----
    raw_seq = exc.get("set_seq")
    if raw_seq is not None:
        try:
            want_seq = int(raw_seq)
        except (TypeError, ValueError):
            want_seq = None
        if want_seq is not None:
            for m in members:
                if int(m.get("set_seq") or 0) == want_seq:
                    return want_seq, (m.get("d0") or None)
    # ---- 档②：按该套下料计划日快照匹配 ----
    want_d0 = _date10(exc.get("set_d0"))
    if want_d0:
        for m in members:
            if (m.get("d0") or "") == want_d0:
                return int(m.get("set_seq") or 0) or None, want_d0
    # ---- 档③：无套号信息 → 保持改造前行为（不指定套）----
    return None, None


def build_node_exception_index(exc_rows: Optional[list[dict]]) -> dict[int, list[dict]]:
    """把异常记录按 **node_id** 建索引 → ``{node_plan_id: [{process_name, status, closed_at, ...}]}``。

    用途（纯展示，不参与任何判定）：
      - 所属套无法反推时（存量项目无 ``project_process_durations``，见
        ``build_exception_anchors``），仍能在这条异常**自身的计划行**上打「⚠️ 异常」标识，
        让用户至少能一眼看到「哪一套的哪道工序有异常」；
      - 所属套可反推时，与「按套聚合」的数据按 exception_id 去重合并，避免重复计数。
    """
    index: dict[int, list[dict]] = {}
    for e in exc_rows or []:
        try:
            nid = int(e.get("node_id") or 0)
        except (TypeError, ValueError):
            continue
        if nid <= 0:
            continue
        index.setdefault(nid, []).append({
            "process_name": str(e.get("process_name") or "").strip(),
            "status": str(e.get("status") or "pending").strip() or "pending",
            "closed_at": str(e.get("closed_at") or "")[:10] or None,
            "exception_id": e.get("id"),
        })
    return index


def _load_exception_context(project_id: int, durations: Optional[dict] = None,
                            plans: Optional[list[dict]] = None,
                            set_index: Optional[dict] = None) -> tuple[dict, dict]:
    """一次查询同时返回「按套聚合的异常锚点」与「按节点建索引的异常」（避免两次 IO）。

    Args:
        project_id: 项目 ID；None → ({}, {})
        durations: durations 中位数归并表（None/空 → 无法反推所属套 → anchors 为 {}）
        plans: 项目当前计划行（用于 node_id → plan_date 覆盖）
        set_index: 可选，``build_set_index`` 产物；传入时异常锚点会附带「指向第几套」的
            元数据（set_seq/set_d0），供展示层把异常标到具体套上。不传 → 与改造前一致。

    Returns:
        (anchors, node_index)：
          - anchors: {该套下料计划日 d0: [{process_name, offset_days, status, closed_at,
            set_seq, set_d0, bucket_d0}]}
          - node_index: {node_plan_id: [{process_name, status, closed_at}]}
        查询失败 / 缺表 → ({}, {})，绝不阻塞总览（与 _load_node_segments 同口径）。
    """
    if project_id is None:
        return {}, {}
    from ..core import db
    try:
        rows = db.get_node_exceptions_by_project(int(project_id)) or []
    except Exception as e:  # noqa: BLE001 — 异常暂停为增强判定，失败回退原规则
        import logging
        logging.getLogger(__name__).warning("get_node_exceptions_by_project(%s) 失败：%s",
                                            project_id, e)
        return {}, {}
    node_index = build_node_exception_index(rows)
    anchors = (build_exception_anchors(rows, durations, plans, set_index) if durations else {})
    return anchors, node_index


def _load_exception_anchors(project_id: int, durations: Optional[dict] = None,
                            plans: Optional[list[dict]] = None,
                            set_index: Optional[dict] = None) -> dict[str, list[dict]]:
    """读取项目全部异常（含已关闭）并反推为「按套聚合」结构，供 build_time_rules 使用。

    返回 ``{该套下料计划日 d0: [{process_name, offset_days, status, closed_at, ...}, ...]}``。

    ⚠️ 容错口径与 ``_load_node_segments`` 完全一致：**查询失败返回 {}**，绝不阻塞总览；
       无 durations（存量项目未导入时长）时同样返回 {}——无法反推「哪一套」，保守不动排产。
    """
    return _load_exception_context(project_id, durations, plans, set_index)[0]


# 对外公开别名：路由层（项目详情风险 / 预警列表）复用同一带兜底的读取逻辑
load_exception_anchors = _load_exception_anchors
load_exception_context = _load_exception_context


# ============================================================
# 「第 N 套」展示层（2026-10）：只读，绝不参与任何判定
# ------------------------------------------------------------
# 数据源 = project_process_durations 的**逐套原始行**（含 set_seq，每套每工序一行）；
# 判定层仍用「按 (工序, 计划日) 中位数归并」的 durations，两条线互不影响：
#   · 本层只产出 sets[]/has_set_detail/set_count/set_detail_state 等**新增只读字段**；
#   · 不改 status/label/level/count_as_overdue/deviation_*/plan_date 任一既有字段。
# ============================================================
def build_set_index(duration_rows: Optional[list[dict]]) -> dict[tuple[str, str], list[dict]]:
    """把 durations 原始行聚成「套明细索引」→ ``{(工序, 计划日): [成员, ...]}``（按 set_seq 升序）。

    纯函数（无 IO）。键用 ``(process_name, 'YYYY-MM-DD')``，与 durations 中位数表的键同构——
    这样才能用**同一把钥匙**把「聚合计划行」和「该行包含的 N 套」对上。

    每个成员字段：
      - ``set_seq``: 套序号（1-based，来自 durations 原始行，**不是**本函数重排的序号）
      - ``offset_days`` / ``duration_days``: 该套该工序的偏移/时长（可为 None）
      - ``plan_date``: 该套该工序的计划日（'YYYY-MM-DD'）
      - ``d0``: 该套的下料计划日 = ``plan_date − offset_days``（**每套各自算，绝不跨套合并**）；
        offset 缺失时为 ``''``
      - ``source``: ``'import'`` = 有 plan_month（本月/历史正式导入）；``'backfill'`` = 无 plan_month
        （补录/历史未标注月行 → 套号属推定，UI 标「（推定套号）」）

    ⚠️ 同一 ``(工序, 计划日, set_seq)`` 出现多行（多负责人/跨月重复导入）时**保留首行**，
       保证 ``len(成员) == 该行 plan_qty`` 的门禁不被重复行撑破。

    Args:
        duration_rows: ``db.list_project_process_durations`` 的原始行；None/空 → ``{}``

    Returns:
        dict[(process_name, 'YYYY-MM-DD'), list[dict]]: 套成员明细，成员按 set_seq 升序
    """
    index: dict[tuple[str, str], list[dict]] = {}
    for row in duration_rows or []:
        process_name = str(row.get("process_name") or "").strip()
        if not process_name:
            continue
        plan_date = _date10(row.get("plan_date"))
        if not plan_date:
            continue
        try:
            set_seq = int(row.get("set_seq"))
        except (TypeError, ValueError):
            continue
        offset_days = _int_or_none(row.get("offset_days"))
        base = parse_date(plan_date)
        d0 = ""
        if base is not None and offset_days is not None:
            d0 = (base - timedelta(days=offset_days)).strftime("%Y-%m-%d")
        members = index.setdefault((process_name, plan_date), [])
        if any(m.get("set_seq") == set_seq for m in members):
            continue        # 重复行（多负责人/跨月重复导入）只保留首行
        members.append({
            "set_seq": set_seq,
            "offset_days": offset_days,
            "duration_days": _int_or_none(row.get("duration_days")),
            "plan_date": plan_date,
            "d0": d0,
            "source": "import" if row.get("plan_month") else "backfill",
        })
    for members in index.values():
        members.sort(key=lambda m: int(m.get("set_seq") or 0))
    return index


def _int_or_none(value) -> Optional[int]:
    """把任意值安全转成 int；None / 空串 / 非法值 → None（纯工具，无副作用）。"""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_set_index(project_id: Optional[int], manager: Optional[str] = None,
                    month: Optional[str] = None) -> dict[tuple[str, str], list[dict]]:
    """读取项目「套明细索引」（容错；失败返回 ``{}``，绝不阻塞详情页）。

    与 ``_load_node_segments`` 同口径：查询异常（缺表/权限）只记 warning 并降级为「无套明细」，
    前端据此回退到今天完全一致的整行渲染（``has_set_detail=false``）。
    """
    if project_id is None:
        return {}
    from ..core import db
    try:
        rows = db.list_project_process_durations(int(project_id), manager, month) or []
    except Exception as e:  # noqa: BLE001 — 套明细为增强展示，失败回退原渲染
        import logging
        logging.getLogger(__name__).warning(
            "list_project_process_durations(%s) 失败：%s", project_id, e)
        return {}
    return build_set_index(rows)


def _flatten_exception_entries(exc_entries: Optional[dict]) -> list[dict]:
    """把「按 d0 聚合」的异常锚点摊平成一维列表，并为每条补上 ``bucket_d0``（所属套桶）。

    展示层按「套」匹配异常时需要逐条扫描（一条异常可能命中某个成员的 set_seq 或 d0），
    因此先摊平。``bucket_d0`` 保留判定层使用的聚合桶（中位代表值算出来的 d0），
    用于「无套号元数据的历史异常」按桶兜底匹配。
    """
    flat: list[dict] = []
    for bucket_d0, entries in (exc_entries or {}).items():
        for entry in entries or []:
            item = dict(entry)
            item.setdefault("bucket_d0", str(bucket_d0 or "")[:10])
            flat.append(item)
    return flat


def _match_set_exceptions(member: dict, exc_flat: Optional[list[dict]]) -> list[dict]:
    """挑出属于某个套成员的异常条目（纯函数）。

    匹配优先级（任一命中即算该套的异常）：
      1. 条目带 ``set_seq`` 且与本成员 ``set_seq`` 相同 → 命中（套号是跨工序稳定的，
         ``project_process_durations.set_seq`` = 导入时的数据行序，同一套在各工序同号）；
      2. 条目带 ``set_d0``（该套下料计划日快照）且与本成员 ``d0`` 相同 → 命中；
      3. 条目无任何套号元数据（历史 NULL 异常）→ 用 ``bucket_d0`` 与本成员 ``d0`` 比对，
         命中说明「这条历史异常正好落在该套的桶」，与判定层的暂停口径一致。
    """
    if not exc_flat:
        return []
    member_seq = _int_or_none(member.get("set_seq"))
    member_d0 = str(member.get("d0") or "")[:10]
    hits: list[dict] = []
    for entry in exc_flat:
        seq = _int_or_none(entry.get("set_seq"))
        if seq is not None and member_seq is not None and seq == member_seq:
            hits.append(entry)
            continue
        entry_d0 = _date10(entry.get("set_d0"))
        if entry_d0 and member_d0 and entry_d0 == member_d0:
            hits.append(entry)
            continue
        if seq is None and not entry_d0:
            bucket = _date10(entry.get("bucket_d0"))
            if bucket and member_d0 and bucket == member_d0:
                hits.append(entry)
    return hits


def judge_set_display_status(member: dict, *, position: int, plan_qty: int, actual_qty: int,
                             today=None, cutting_anchor: Optional[dict] = None,
                             exc_entries: Optional[list[dict]] = None) -> dict:
    """判定**单个套**的展示态（纯展示，绝不写回判定层字段）。

    逐套信息只来自 durations 原始行（该套自己的 offset），因此「计划日期」按该套自己的
    offset 重算：``生效日 = 该套实际下料日 + 该套 offset``；若该套有已关闭异常，再按
    ``max(实际下料日, 已关闭异常 closed_at − 异常工序 offset) + 该套 offset`` 后推，
    与 ``build_time_rules`` 的算法**同构**——但只用于「第 N 套」子行展示，
    整行 status/逾期/KPI 仍由 ``build_time_rules`` 的聚合口径决定（一个数字都不变）。

    实际完成推定（用户 2026-10 确认口径 D）：填报仍是「计划 3 套 / 实际 2 套」合并填写，
    故按 ``set_seq 升序`` 推定前 ``actual_qty`` 套已完成（前 N 套完成），UI 标「（推定）」。

    Args:
        member: ``build_set_index`` 的单个成员（含 set_seq/offset_days/plan_date/d0/source）
        position: 该成员在成员列表中的 0-based 位次（升序 → 前 actual_qty 个视为已完成）
        plan_qty: 该计划行的计划套数
        actual_qty: 该计划行的实际完成套数（合并填报值）
        today: 判定基准日（None → 业务时区当天）
        cutting_anchor: ``cutting_anchor_map`` 产物 {下料计划日: 实际下料日}
        exc_entries: 摊平后的异常条目（``_flatten_exception_entries`` 产物）

    Returns:
        dict: ``set_seq/plan_date/plan_date_plan/d0/offset_days/duration_days/actual_qty_est/
        status_display/label_display/derived/source/exception_paused/has_open_exception/
        exception_processes``
    """
    today_date = parse_date(today) or business_today()
    plan_date = _date10(member.get("plan_date"))
    offset_days = _int_or_none(member.get("offset_days"))
    set_d0 = str(member.get("d0") or "")[:10]
    done_est = int(position) < int(actual_qty or 0)

    related = _match_set_exceptions(member, exc_entries)
    open_excs = [e for e in related if str(e.get("status") or "pending") != "closed"]
    # 暂停：该套存在未关闭异常，且本工序 offset > 异常工序 offset（异常工序自身不暂停）
    paused = any(
        _int_or_none(e.get("offset_days")) is not None
        and offset_days is not None
        and int(e.get("offset_days")) < int(offset_days)
        for e in open_excs
    )

    # ---- 生效计划日（展示口径，每套各自算）----
    anchor_raw = (cutting_anchor or {}).get(set_d0) if set_d0 else None
    anchor = parse_date(anchor_raw) if anchor_raw else None
    for e in related:
        if str(e.get("status") or "") != "closed":
            continue
        exc_offset = _int_or_none(e.get("offset_days"))
        closed_at = _date10(e.get("closed_at"))
        if exc_offset is None or not closed_at or offset_days is None:
            continue
        if exc_offset >= offset_days:
            continue          # 只后推「异常工序之后」的工序
        cand = parse_date(closed_at)
        if cand is None:
            continue
        cand = cand - timedelta(days=exc_offset)
        if anchor is None or cand > anchor:
            anchor = cand
    display_date = plan_date
    if anchor is not None and offset_days is not None:
        display_date = (anchor + timedelta(days=offset_days)).strftime("%Y-%m-%d")

    # ---- 逐套状态（仅展示；不做任何统计汇总）----
    if done_est:
        status_display, label_display = "done", "🟢 已完成"
    elif paused:
        status_display, label_display = "exception_paused", "⏸ 异常暂停"
    elif anchor is None:
        status_display, label_display = "waiting_material", "⏸ 待下料"
    else:
        parsed = parse_date(display_date)
        if parsed is None:
            status_display, label_display = "pending", "⚪ 未开始"
        elif today_date < parsed:
            status_display, label_display = "pending", "⚪ 未开始"
        elif today_date == parsed:
            status_display, label_display = "in_progress", "🔵 进行中"
        else:
            status_display, label_display = "overdue", "🔴 逾期未完成"

    return {
        "set_seq": _int_or_none(member.get("set_seq")),
        # 该套的生效计划日（闸门开 → 按该套 offset 重算）与原始计划日（前端据此显示「原 X」）
        "plan_date": display_date,
        "plan_date_plan": plan_date,
        "d0": set_d0,
        "offset_days": offset_days,
        "duration_days": _int_or_none(member.get("duration_days")),
        "actual_qty_est": 1 if done_est else 0,
        "status_display": status_display,
        "label_display": label_display,
        # 逐套完成必然是按 set_seq 升序「推定」的（合并填报，无逐套实际值）
        "derived": True,
        "source": str(member.get("source") or "backfill"),
        "exception_paused": bool(paused),
        "has_open_exception": bool(open_excs),
        "exception_processes": sorted({
            str(e.get("process_name") or "") for e in open_excs if e.get("process_name")
        }),
    }


def attach_set_details(rows: list[dict], set_index: Optional[dict],
                       exc_entries: Optional[dict], *, plans: Optional[list[dict]] = None,
                       actuals: Optional[dict] = None, today=None) -> list[dict]:
    """给富化后的节点行挂「第 N 套」明细（原地写新增字段，**不动任何既有字段**）。

    🔴 展开三条件门禁（缺一即回退到今天完全一致的整行渲染）：
      ① ``plan_qty >= 2``（1 套的行没有「第 1 套」的意义）；
      ② ``set_index[(process_name, 原始排产计划日)]`` 非空；
      ③ ``len(该行套成员) == plan_qty``（套数与计划套数必须严格对齐，宁可不对也不错）
      —— 满足三条 → ``has_set_detail=True`` 并输出 ``sets[]``；否则
         ``sets=[] / set_count=0 / set_detail_state='none'``。

    🔴 匹配必须用**覆盖前的原始排产计划日**：``build_process_detail`` 在 ``enrich_rows``
    之前就把 ``plan_date`` 覆盖成 ``eff_plan_date``（重算后的日期）。富化行的
    ``plan_date_plan`` 正是覆盖前的原值（未重算行两者相等），故以它为准；
    若误用 ``plan_date``，凡「闸门已开、日期被重算」的行都会静默匹配失败、不再展开。

    独立工序（90/91）与无计划日的占位行天然不展开（前者显式跳过，后者无原始日期）。

    Args:
        rows: ``enrich_rows`` 产出的节点行（原地修改）
        set_index: ``build_set_index`` 产物
        exc_entries: 异常锚点 dict（``{d0: [entry, ...]}``，可含 set_seq/set_d0 元数据）
        plans: 项目全部计划行（用于算下料闸门锚点；None → 不重算日期，直接按原计划日展示）
        actuals: {node_plan_id: {actual_qty, report_date}}
        today: 判定基准日

    Returns:
        list[dict]: 传入的 rows（原地补字段后原样返回，便于链式调用）
    """
    index = set_index or {}
    exc_flat = _flatten_exception_entries(exc_entries)
    anchor_map = cutting_anchor_map(plans or [], actuals or {})
    today_date = parse_date(today) or business_today()

    for row in rows:
        # 新增字段默认值：任何提前 return 的分支都保证字段齐备（前端无需判空）
        row["sets"] = []
        row["has_set_detail"] = False
        row["set_count"] = 0
        row["set_detail_state"] = "none"

        process_name = str(row.get("process_name") or "").strip()
        if not process_name or process_name in INDEPENDENT_PROCESS_NAMES:
            continue
        # 覆盖前的原始排产计划日（plan_date 可能已是 eff_plan_date）
        orig_plan_date = _date10(row.get("plan_date_plan")) or _date10(row.get("plan_date"))
        if not orig_plan_date:
            continue
        plan_qty = _int_or_none(row.get("plan_qty")) or 0
        if plan_qty < 2:                      # 门禁①
            continue
        members = index.get((process_name, orig_plan_date)) or []
        if not members:                       # 门禁②
            continue
        if len(members) != plan_qty:           # 门禁③
            continue
        sets = [
            judge_set_display_status(
                member,
                position=position,
                plan_qty=plan_qty,
                actual_qty=_int_or_none(row.get("actual_qty")) or 0,
                today=today_date,
                cutting_anchor=anchor_map,
                exc_entries=exc_flat,
            )
            for position, member in enumerate(members)
        ]
        row["sets"] = sets
        row["has_set_detail"] = True
        row["set_count"] = len(sets)
        # 'ok'     = 全部成员来自正式导入（套号可信）
        # 'partial'= 存在 'backfill' 成员（套号属推定，UI 标「（推定套号）」）
        row["set_detail_state"] = (
            "ok" if all(s.get("source") == "import" for s in sets) else "partial"
        )
    return rows


def _segment_delay_tags(tags: list, grp: list[dict],
                        seg_map: dict[int, tuple[int, int]], today: date) -> list:
    """按段填报标签（v7.1 行级化 + 未来计划预警门槛）：
    该工序任一节点有段记录且未填满 → 追加「部分完成」；预警/延期按计划日门槛分级：
      1) 已开始（plan_date ≤ today，无日期保守视为已开始）节点中存在 plan_date + 7 天
         仍早于今天 → 「部分完成」+「延期」；
      2) 否则已开始节点中存在未填满 → 「部分完成」+「预警」；
      3) 仅未来计划（plan_date > today）未填满 → 只给「部分完成」，**不给预警/延期**
         （用户口径：预警仅在该套计划已开始后才触发，未来计划不触发任何预警）；
      4) 填满（done>=total）或无段记录 → 不加任何标签。
    ⚠️ 卡片主状态/status/label 一律不改（tags 仅追加，其余字段不动）。
    ⚠️ 逐词判重（P2-1）：业务层可能已产出「部分完成」（0<actual<plan 且 plan<today），
       追加段标签前对三个词逐一判重，已在 tags 里的不再重复 append；
       「延期」替换「预警」的现有逻辑保持不变。
    """
    # 活跃节点：该工序的行中，有段记录且 done < total 的节点
    active = [
        (r, seg_map[r["id"]]) for r in grp
        if r.get("id") in seg_map and 0 <= seg_map[r["id"]][1] < seg_map[r["id"]][0]
    ]
    if not active:
        return tags
    # 按 plan_date 分两组：started = plan_date ≤ today（无日期保守视为已开始）；future = > today
    started, future = [], []
    for r, seg in active:
        pd_str = str(r.get("plan_date") or "")[:10]
        if pd_str and date.fromisoformat(pd_str) > today:
            future.append((r, seg))
        else:
            started.append((r, seg))

    def _over7(row):
        d = str(row.get("plan_date") or "")[:10]
        return bool(d) and (date.fromisoformat(d) + timedelta(days=7)) < today

    if any(_over7(r) for r, (_t, _d) in started):
        seg_tags = ["部分完成", "延期"]
    elif started:
        seg_tags = ["部分完成", "预警"]
    else:
        # 仅未来计划未填满：不触发预警/延期
        seg_tags = ["部分完成"]
    # 逐词判重追加（保序）：「预警」已被业务层加入时不重复；「延期」始终以替换语义处理
    out = list(tags)
    for t in seg_tags:
        if t == "延期":
            if "延期" in out:
                continue
            if "预警" in out:
                out = [x for x in out if x != "预警"]  # 「预警」换「延期」
            out.append("延期")
        elif t not in out:
            out.append(t)
    return out


def build_overview(project_id: int, plans: list[dict], actuals: dict, today=None, monthly_plan: int = 0,
                   contract_count=None, durations: Optional[dict] = None) -> dict:
    """节点计划总览：指标 + 工序卡片 + 时间轴 + 分组数据。

    - kpis: 总套数/工序数/节点总数/达标节点/逾期节点
    - processes: 按 SCHEDULE_PROCESS_NAMES 顺序的工序卡片（名称/状态/进度/分组）
    - timeline: 时间轴所需行
    - contract_count: 项目主表合同总数（独立工序卡片的「合同总数」单一数据源；None 时回退占位行）
    """
    # ⚠️ today 统一归一化为 date：下游 _segment_delay_tags 做 date 比较，
    # 调用方传 'YYYY-MM-DD' 字符串时原会 TypeError（防御性收口）
    today = parse_date(today) or business_today()
    # 按段填报（v7.1 行级化）：{node_plan_id: (segment_total, segment_done)}
    # ⚠️ 必须在 enrich_rows 之前加载——状态判定需要它（按段提报的行 → 进行中，不判逾期）
    seg_map = _load_node_segments(project_id)
    # 未关闭异常按工序聚合：工序卡片「存在异常」标签 + 预警态
    exc_map = _load_open_exceptions(project_id)
    # 异常暂停 / 解决后重算（2026-10）：按「该套下料计划日」聚合的异常锚点 + 按节点兜底索引
    # ⚠️ 同样必须在 enrich_rows 之前加载——状态判定（暂停 / 新计划日）需要它
    exc_anchors, exc_by_node = _load_exception_context(project_id, durations, plans)
    rows = enrich_rows(plans, actuals, today, durations, seg_map=seg_map,
                       exceptions=exc_anchors, node_exceptions=exc_by_node)

    proc_groups: dict[str, list[dict]] = {}
    for r in rows:
        proc_groups.setdefault(r["process_name"], []).append(r)

    per_proc_sets = {pn: sum(r["plan_qty"] for r in grp) for pn, grp in proc_groups.items()}
    total_sets = max(per_proc_sets.values()) if per_proc_sets else 0
    done_count = sum(1 for r in rows if r["status"] == "done")
    overdue_count = len(compute_real_overdue(rows, monthly_plan))

    processes = []
    for pn in SCHEDULE_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = proc_groups[pn]
        # 工序卡片状态：双维度判定（总套数完成度 + 当日计划完成度），
        # 替代原节点级 level 汇总——只有全部套数完成才显示"已完成"
        proc_status = judge_process_card_status(grp, actuals, today, monthly_plan)
        total_plan = sum(r["plan_qty"] for r in grp)
        total_actual = sum(r["actual_qty"] for r in grp)
        current_plan = sum(
            r["plan_qty"] for r in grp
            if str(r["plan_date"])[:10] == str(today)[:10]
        )
        # 今日有计划：存在 plan_date 为今天的节点 且 实际 < 计划（今天仍有未完成节点）
        has_today_plan = any(
            str(r["plan_date"])[:10] == str(today)[:10]
            and actuals.get(r["id"], {}).get("actual_qty", 0) < r["plan_qty"]
            for r in grp
        )
        progress = (total_actual / total_plan * 100) if total_plan else 0
        proc_tags = _segment_delay_tags(
            list(proc_status.get("tags", [])), grp, seg_map, today,
        )
        processes.append({
            "process_name": pn,
            "status": proc_status["status"],
            "label": proc_status["label"],
            "tags": proc_tags,
            "has_today_plan": has_today_plan,
            "has_exception": exc_map.get(pn, 0) > 0,
            "exception_count": exc_map.get(pn, 0),
            "total_plan": total_plan,
            "total_plan_qty": total_plan,      # 总计划套数（前端进度条分母）
            "total_actual": total_actual,
            "current_plan_qty": current_plan,  # 当日计划累计（前端/诊断用）
            "progress_pct": round(min(progress, 100), 1),
            "node_count": len(grp),
            "independent": False,
        })

    # 独立工序卡片（累计完成总数/累计发运总数）：追加在 11 道工序之后。
    # 合同总数（total_plan）**单一数据源 = projects.contract_count**；为空时回退占位行 plan_qty（兼容旧数据）。
    # total_actual = 所有行 actual_qty 之和（每次填报一条；总和 = 累计填报）
    for pn in INDEPENDENT_PROCESS_NAMES:
        if pn not in proc_groups:
            continue
        grp = proc_groups[pn]
        # 合同占位行：plan_date 为 NULL，plan_qty = contract_count
        placeholder = [r for r in grp if not str(r.get("plan_date") or "")]
        if contract_count is not None:
            total_plan = int(contract_count or 0)
        else:
            total_plan = sum(r["plan_qty"] for r in placeholder) if placeholder else sum(r["plan_qty"] for r in grp)
        total_actual = sum(r["actual_qty"] for r in grp)
        done = total_actual >= total_plan and total_plan > 0
        status = "done" if done else "in_progress"
        progress = (total_actual / total_plan * 100) if total_plan else 0
        processes.append({
            "process_name": pn,
            "status": status,
            "label": "🟢 已完成" if done else "🔵 进行中",
            "tags": [],
            "has_today_plan": False,
            "has_exception": exc_map.get(pn, 0) > 0,
            "exception_count": exc_map.get(pn, 0),
            "total_plan": total_plan,
            "total_plan_qty": total_plan,
            "total_actual": total_actual,
            "current_plan_qty": 0,
            "progress_pct": round(min(progress, 100), 1),
            "node_count": len(grp),
            "independent": True,
        })

    return {
        "kpis": {
            "total_sets": total_sets,
            "process_count": len(proc_groups),
            "node_count": len(rows),
            "done_count": done_count,
            "overdue_count": overdue_count,
        },
        "processes": processes,
        "timeline": rows,
        "visible_processes": [pn for pn in SCHEDULE_PROCESS_NAMES if pn in proc_groups],
    }


def build_process_detail(process_name: str, plans: list[dict], actuals: dict, today=None,
                         contract_count=None, durations: Optional[dict] = None,
                         project_id: int | None = None, manager: Optional[str] = None,
                         month: Optional[str] = None,
                         set_index: Optional[dict] = None) -> dict:
    """某工序节点列表：按 今日/逾期/未来/已完成 四组返回（填报弹窗数据源）。

    独立工序特殊处理：
      - groups.done 按 plan_date 降序（最新填报在上）
      - 卡片（build_overview）total_plan **单一数据源 = projects.contract_count**
      - 卡片 total_actual = 所有行 actual_qty 之和（每次填报一条）
      - 返回值额外带 contract_count，供前端「合同总数」直接读取（避免依赖占位行 plan_qty）
    v7.1 按段填报（行级化）：project_id 非空时每个节点行（nodes/groups 行）带
      segment_total/segment_done（该套的分段进度；无记录为 None），供填报 tab 回显 +
      节点详情 tab 展示；旧调用（不传参）行为不变。
    异常暂停（2026-10）：project_id 非空时额外加载该项目的异常锚点（含已关闭），
      使弹窗内状态与总览同口径——未关闭异常 → 后续工序 ⏸ 异常暂停（不计逾期）；
      已关闭异常 → 后续工序按「解决时间」重算后的新计划日判定。
      project_id 为 None（旧调用/单测）→ 不加载异常，行为与改动前一致。
    「第 N 套」展示（2026-10）：结尾调用 ``attach_set_details`` 给每个节点行挂
      ``sets[] / has_set_detail / set_count / set_detail_state``（**只新增、不改旧字段**）。
      套成员来自 ``project_process_durations`` 的逐套原始行（project_id 非空时才读，
      读取失败降级为「无套明细」→ 前端回退到与今天完全一致的整行渲染）。
      ``manager``/``month`` 只用于让套明细与计划行**同口径**（同负责人、同归属月），
      不传时按跨月/汇总口径读取（与 plans 的取数口径一致由调用方保证）。

    Args:
        process_name: 工序名
        plans: 项目全部计划行（⚠️ 必须是全量，闸门/异常锚点要全项目的「下料」行）
        actuals: {node_plan_id: {actual_qty, report_date}}
        today: 判定基准日
        contract_count: 项目合同总数（独立工序卡片数据源）
        durations: 中位数归并的 durations（判定层口径，不变）
        project_id: 项目 ID（None → 不加载异常/段/套明细，行为同改动前）
        manager: 负责人过滤（仅用于读取套明细，与读计划行同口径）
        month: 排产归属月（仅用于读取套明细）
        set_index: 可选的已构建套明细索引（调用方已加载时传入，避免重复查询）

    Returns:
        dict: {process_name, is_independent, contract_count, nodes[], groups{}}
    """
    today = parse_date(today) or business_today()
    # 「第 N 套」套明细索引：只读，先于异常锚点加载——异常锚点需要它来补「指向第几套」的元数据
    if set_index is None:
        set_index = _load_set_index(project_id, manager, month)
    # 异常暂停 / 解决后重算（2026-10）：按「该套下料计划日」聚合的异常锚点 + 按节点兜底索引
    # ⚠️ 闸门锚点与异常锚点都必须基于【全项目】计划行（找「下料」行），不能只用本工序的行
    if project_id is not None:
        exc_anchors, exc_by_node = _load_exception_context(project_id, durations, plans, set_index)
    else:
        exc_anchors, exc_by_node = {}, {}
    rules = build_time_rules(plans, actuals, durations, exc_anchors)
    proc_nodes = sorted(
        (r for r in plans if r["process_name"] == process_name),
        key=lambda r: str(r["plan_date"]),
    )
    # 分组/展示统一使用「重算后的计划日期」（闸门开时）——与节点详情、时间轴口径一致
    # ⚠️ 覆盖前必须把原计划日收进 plan_date_plan（QA D1）：enrich_rows / groups 都靠它输出
    #    「原 X」对照，而 enrich_rows 拿到的 r["plan_date"] 此时已是重算后的日期，
    #    原值若不在此处留存就永久丢失（前端删除线恒不渲染）。
    # ⚠️ plan_date 语义不变：接口对外仍表示「生效（重算后）计划日」，是逾期判定基准。
    proc_nodes = [
        ({**p,
          "plan_date_plan": (_date10(p.get("plan_date_plan")) or _date10(p.get("plan_date"))),
          "plan_date": rules[p["id"]]["eff_plan_date"]}
         if rules.get(p["id"], {}).get("eff_plan_date") else p)
        for p in proc_nodes
    ]
    # 按段填报（v7.1 行级化）：每套（计划行）各自的段进度——无记录为 None。
    # 由 enrich_rows 一并写入行字段并参与状态判定（按段提报未填满 → 进行中，不判逾期未完成）
    seg_map = _load_node_segments(project_id) if project_id is not None else {}
    groups = split_node_groups(proc_nodes, actuals, today)
    rows = enrich_rows(proc_nodes, actuals, today, durations, rules, seg_map=seg_map,
                       exceptions=exc_anchors, node_exceptions=exc_by_node)

    # 独立工序的 done 组按日期降序展示（最新填报在上）
    if process_name in INDEPENDENT_PROCESS_NAMES:
        groups['done'] = sorted(
            groups['done'],
            key=lambda p: str(p.get('plan_date') or ''),
            reverse=True,
        )

    # 「第 N 套」展示层收尾（只新增字段）：sets[] 挂在 nodes 上；
    # groups 只挂轻量标记（has_set_detail/set_count/set_detail_state），**不带 sets**
    # —— 填报表单只需知道「有没有套明细」，明细通过 id 回查 nodes，避免表单体积翻倍。
    attach_set_details(rows, set_index, exc_anchors, plans=plans, actuals=actuals, today=today)
    set_flags = {
        r["id"]: {
            "has_set_detail": bool(r.get("has_set_detail")),
            "set_count": int(r.get("set_count") or 0),
            "set_detail_state": r.get("set_detail_state") or "none",
        }
        for r in rows
    }

    return {
        "process_name": process_name,
        "is_independent": process_name in INDEPENDENT_PROCESS_NAMES,
        "contract_count": contract_count,   # 项目主表合同总数（独立工序「合同总数」单一数据源；可为 None）
        "nodes": rows,
        "groups": {
            g: [{"id": p["id"],
                 "plan_date": (str(p["plan_date"])[:10] if p.get("plan_date") is not None else ""),
                 # 原排产计划日（重算前）：未重算行与 plan_date 相等 → 前端不显示「原 X」
                 "plan_date_plan": (_date10(p.get("plan_date_plan"))
                                    or _date10(p.get("plan_date"))),
                 "plan_qty": p["plan_qty"],
                 "actual_qty": actuals.get(p["id"], {}).get("actual_qty", 0),
                 # 按段填报回显（v7.1 行级化；无记录为 None）
                 "segment_total": seg_map.get(int(p["id"]), (None, None))[0],
                 "segment_done": seg_map.get(int(p["id"]), (None, None))[1],
                 # 「第 N 套」轻量标记（2026-10）：明细 sets[] 在 nodes 上，按 id 回查
                 "has_set_detail": set_flags.get(p["id"], {}).get("has_set_detail", False),
                 "set_count": set_flags.get(p["id"], {}).get("set_count", 0),
                 "set_detail_state": set_flags.get(p["id"], {}).get("set_detail_state", "none")}
                for p in nodes]
            for g, nodes in groups.items()
        },
    }
