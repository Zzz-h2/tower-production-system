"""
business_logic.py — 塔筒生产进度管控核心业务逻辑（v4.0 节点/工序状态判定）

FastAPI 运行路径实际在用的函数（保留）：
- judge_node_status：节点五态判定（done/pending/in_progress/warning/overdue）
- judge_process_card_status：工序卡片双维度状态（总进度 + 时间维度标签）
- split_node_groups / _group_nodes：今日/逾期/未来/已完成 四组互斥切分
- validate_today_quota / validate_today_quota_nodes：前序联动校验
  （前序联动已于 2026-10-16 按业务要求停用：两者恒放行，保留骨架仅为兼容调用点与响应结构）

已清理的历史遗留死代码：Streamlit 版 正向/倒排计划（12 道制造工序）、
工序进度计算、预警判定、预计交付、里程碑对比、日计划拆解等不再被引用的函数。
"""
from datetime import timedelta
from typing import Optional

from .workday_calendar import parse_date
from ..core.config import (SCHEDULE_PROCESS_NAMES, INDEPENDENT_PROCESS_NAMES,
                           MATERIAL_PROCESS_NAMES, MANUFACTURE_PROCESS_NAMES)
from ..core.timeutil import business_today


# ============================================================
# 异常「到期失效」判定（2026-11）：active / expired 的**唯一实现处**
# ------------------------------------------------------------
# PRD 定死口径（其他模块一律调用本节的三个纯函数，禁止各写一份）：
#   active(e)  := e.status <> 'closed' AND (e.planned_close_date IS NULL
#                                            OR business_today() <= e.planned_close_date)
#   expired(e) := e.status <> 'closed' AND e.planned_close_date IS NOT NULL
#                                            AND business_today() > e.planned_close_date
# 要点：
#   · 全部**实时派生**：不写库、不加列、不做定时任务；到期失效的记录 status 仍是 pending；
#   · planned_close_date IS NULL = 永不到期（历史异常保持暂停，向后兼容）；
#   · 🔴 expired ≠ closed：到期失效**不触发** closed_at 锚点重算，
#     下游一律按**原** eff_plan_date 判逾期。
# ============================================================
def _today_text(today=None) -> str:
    """把基准日统一成 ``'YYYY-MM-DD'`` 字符串（None → 业务时区今天；date/str 均兼容）。

    纯函数，无 IO。所有 active/expired 判定都经此收口，保证「字符串比较」与
    「日期比较」不会因类型不同而产生两套口径。
    """
    if today is None:
        return business_today().strftime("%Y-%m-%d")
    parsed = parse_date(today)
    if parsed is not None:
        return parsed.strftime("%Y-%m-%d")
    return str(today)[:10]


def _planned_close_text(exc: dict) -> str:
    """取异常的计划关闭日（``'YYYY-MM-DD'``）；无值 / 空串 / 字符串 'None' → ``''``。"""
    if not isinstance(exc, dict):
        return ""
    text = str(exc.get("planned_close_date") or "").strip()
    if not text or text == "None":
        return ""
    return text[:10]


def _exception_is_closed(exc: dict) -> bool:
    """异常是否已关闭（status 为空陈旧数据按「未关闭」处理，与历史口径一致）。"""
    if not isinstance(exc, dict):
        return False
    return str(exc.get("status") or "pending").strip() == "closed"


def exception_is_active(exc: dict, today=None) -> bool:
    """异常是否「生效中」（未关闭 且 未到计划关闭日之后）。

    Args:
        exc: 异常记录（dict，需含 status / planned_close_date）
        today: 基准日（None → 业务时区今天；date / 'YYYY-MM-DD' 均可）

    Returns:
        bool: True = 生效中（参与暂停/异常态判定）；False = 已关闭或已到期失效
    """
    if not isinstance(exc, dict) or _exception_is_closed(exc):
        return False
    planned_close = _planned_close_text(exc)
    if not planned_close:
        # planned_close_date 为空 = 永不到期（历史异常：保持暂停）
        return True
    return _today_text(today) <= planned_close


def exception_is_expired(exc: dict, today=None) -> bool:
    """异常是否「已到期失效」（未关闭 且 已超过计划关闭日）。

    🔴 到期失效 **不等于** 关闭：不接受 closed_at 锚点重算，下游按原 eff_plan_date 判逾期。

    Args:
        exc: 异常记录（dict）
        today: 基准日（None → 业务时区今天）

    Returns:
        bool: True = 已超计划关闭日但仍未关闭（暂停失效、恢复逾期判定）
    """
    if not isinstance(exc, dict) or _exception_is_closed(exc):
        return False
    planned_close = _planned_close_text(exc)
    if not planned_close:
        return False
    return _today_text(today) > planned_close


def has_active_exception(rows, today=None) -> bool:
    """给定异常集合中是否存在**生效中**的异常（项目级 exception 态的判定入口）。

    Args:
        rows: 异常记录列表；也接受 ``{key: [异常, ...]}`` 的索引结构
              （如 ``build_node_exception_index`` 的产物），内部自动摊平
        today: 基准日（None → 业务时区今天）

    Returns:
        bool: 是否存在生效中的异常
    """
    today_text = _today_text(today)
    candidates: list = []
    if isinstance(rows, dict):
        for value in rows.values():
            if isinstance(value, (list, tuple)):
                candidates.extend(value)
            elif isinstance(value, dict):
                candidates.append(value)
    elif rows:
        candidates = list(rows)
    for exc in candidates:
        if exception_is_active(exc, today_text):
            return True
    return False


def prev_process_total(process_name: str, plans_all: list[dict], actuals: dict,
                       before_date: Optional[str] = None) -> Optional[int]:
    """某工序之前所有工序的累计实际完成数（前序联动上限）。

    process_name 为第一道工序 → 返回 None（不限制）。
    before_date: 传入时仅累加 ``plan_date <= before_date`` 的节点——按目标节点的 plan_date
    收口，避免"很后期前序节点已有实际"令 future 组误放行；None 时保持全量（today 组兼容）。
    """
    proc_idx = SCHEDULE_PROCESS_NAMES.index(process_name) if process_name in SCHEDULE_PROCESS_NAMES else -1
    if proc_idx <= 0:
        return None
    prev_procs = set(SCHEDULE_PROCESS_NAMES[:proc_idx])
    total = 0
    for pn in plans_all:
        if pn["process_name"] not in prev_procs:
            continue
        if before_date and str(pn["plan_date"])[:10] > str(before_date)[:10]:
            continue
        total += int(actuals.get(pn["id"], {}).get("actual_qty", 0) or 0)
    return total


def cutting_anchor_map(plans_all: list[dict], actuals: dict) -> dict[str, str]:
    """下料闸门锚点表 → ``{下料计划日 'YYYY-MM-DD': 该套最早实际下料日 'YYYY-MM-DD'}``。

    纯函数（无 IO），从 ``build_time_rules`` 内部**等价提出**，供展示层（「第 N 套」的
    逐套生效计划日）复用**同一个**闸门锚点，保证展示与判定同源、不出现两套口径。

    口径（与改造前 build_time_rules 内部逻辑逐字一致）：
      - 只统计「下料」工序的行（``MANUFACTURE_PROCESS_NAMES[0]``）；
      - 该行 plan_date 非空、actual_qty > 0 且 report_date 非空才构成锚点；
      - 同一 plan_date 有多条实际填报时取**最早**的 report_date。

    Args:
        plans_all: 项目全部节点计划行（含 id/process_name/plan_date）
        actuals: {node_plan_id: {actual_qty, report_date}}

    Returns:
        dict[str, str]: 下料计划日 → 最早实际下料日（无下料实际填报时为空 dict）
    """
    cutting_name = MANUFACTURE_PROCESS_NAMES[0] if MANUFACTURE_PROCESS_NAMES else "下料"
    anchor: dict[str, str] = {}
    for p in plans_all or []:
        if p.get("process_name") != cutting_name:
            continue
        pd = str(p.get("plan_date") or "")[:10]
        act = (actuals or {}).get(p.get("id"), {}) or {}
        aq = int(act.get("actual_qty", 0) or 0)
        rd = str(act.get("report_date") or "")[:10]
        if pd and aq > 0 and rd:
            cur = anchor.get(pd)
            if cur is None or rd < cur:
                anchor[pd] = rd
    return anchor


def build_time_rules(plans_all: list[dict], actuals: dict, durations: Optional[dict] = None,
                     exceptions: Optional[dict] = None, today=None) -> dict:
    """按「每一套（每个计划行）」计算闸门与 effective 计划日期（工序时间/延期判定规则升级核心）。

    闸门 = 该行所属套的「下料」是否已有实际填报（actual_qty>0）。
    - 钢板到货：不参与闸门，始终按计划日期判定，**计入**逾期/风险/排名（保证闭环）。
    - 法兰到货：不参与闸门，按计划日期展示，但**不计入**逾期/风险/排名（不作主指标）。
    - 制造链（下料~具备验收）：
        · 闸门关 → waiting_material=True（⏸ 待下料，灰），不计入统计；
        · 闸门开 → eff_plan_date = 实际下料日 + 该行所属套的 offset_days，计入统计。
        · 该套存在**生效中**（未关闭且未过计划关闭日）异常工序 → 其后序工序（offset 更大）
          exception_paused=True（⏸ 异常暂停，灰），暂停**优先于**等待下料，
          不计入逾期/风险/排名。
        · 该套存在**已关闭**异常 → 以「异常解决时间」为新锚点重算后续工序计划日：
          eff_plan_date = max(下料实际日, max_i(closed_at_i − offset_i)) + 该行 offset。
        · 🔴 该套存在**已到期失效**（未关闭但已过计划关闭日）异常 → 暂停失效，
          **不**参与 closed_at 锚点重算（expired ≠ closed），下游按原 eff_plan_date 判逾期。
        · 本行自身即为生效中异常所在工序 → self_exception=True（🟠 异常，第 4 态），
          count_as_overdue=False（不计入逾期/风险/排名）。

    Args:
        plans_all: 项目全部节点计划行（含 id/process_name/plan_date）
        actuals: {node_plan_id: {actual_qty, report_date}}
        durations: {(process_name, 'YYYY-MM-DD'): {"offset_days": int}}；为 None/缺该键 → 回退现规则
                   （该行不做闸门抑制、不重算日期，行为与升级前一致）
        exceptions: 可选，{该套下料计划日 d0 ('YYYY-MM-DD'): [
                        {"process_name": str, "offset_days": int,
                         "status": 'pending'|'processing'|'closed', "closed_at": 'YYYY-MM-DD'|None,
                         "planned_close_date": 'YYYY-MM-DD'|None, "active": bool},
                        ...]}；为 None/缺该 d0 → 与升级前完全一致（向后兼容红线）。
                    ⚠️ ``active`` 由 ``build_exception_anchors`` 统一写入（active/expired 单源），
                    本函数只读该标记，不自行比较日期。
        today: 基准日（None → 业务时区今天）。当前实现只做兜底归一，
               异常是否生效由 ``active`` 决定（保证「一处实现」）。

    Returns:
        {node_id: {"waiting_material": bool, "eff_plan_date": str|None, "count_as_overdue": bool,
                   "exception_paused": bool, "set_date": str|None,
                   "self_exception": bool, "self_close_date": str|None}}
        ⚠️ 后两个键为 2026-11 新增（默认 False / None），既有调用方按 key 取值，不感知新增字段。
    """
    mfg = set(MANUFACTURE_PROCESS_NAMES)
    steel_name = MATERIAL_PROCESS_NAMES[0] if MATERIAL_PROCESS_NAMES else "钢板到货"
    exc_map = exceptions or {}
    # 基准日：本函数**不**自行取业务今天（由入口取一次后透传，见模块文档）；
    # 生效判定一律读 build_exception_anchors 写入的 ``active``，杜绝两套日期比较。
    # `today` 仅作为签名占位，供未来需要行级日期计算时使用（保持接口稳定）。
    _ = today

    # 下料行：plan_date -> 该套最早实际下料日（闸门锚点）
    # ⚠️ 等价重构（2026-10）：原内联循环已提取为模块级纯函数 cutting_anchor_map，
    #    供展示层复用同一锚点；此处调用结果与改造前逐项一致（顺序/取最小值口径不变）。
    cutting_anchor: dict[str, str] = cutting_anchor_map(plans_all, actuals)

    def _rule(waiting: bool, eff: Optional[str], count: bool,
              paused: bool = False, set_date: Optional[str] = None,
              self_exception: bool = False,
              self_close_date: Optional[str] = None) -> dict:
        """统一规则结构（新增字段集中在唯一出口，避免各分支漏字段）。"""
        return {"waiting_material": waiting, "eff_plan_date": eff, "count_as_overdue": count,
                "exception_paused": paused, "set_date": set_date,
                "self_exception": self_exception, "self_close_date": self_close_date}

    rules: dict = {}
    for p in plans_all:
        nid = p.get("id")
        pn = p.get("process_name")
        pd = str(p.get("plan_date") or "")[:10]
        if pn not in mfg:
            # 到货类（及其它非制造链）：钢板计入主指标，法兰不计入
            rules[nid] = _rule(False, None, pn == steel_name)
            continue
        info = (durations or {}).get((pn, pd))
        if not info:
            # 无时长数据（存量项目/未重新导入）→ 回退现规则（异常也无从定位所属套）
            # ⚠️ 项目级 exception 仍由 raw 异常表判定（见 db.get_projects_filtered），
            #    工序级无法定位所属套 → 不标异常（PRD 明确口径）。
            rules[nid] = _rule(False, None, True)
            continue
        offset = int(info.get("offset_days") or 0)
        base = parse_date(p.get("plan_date"))
        d0 = (base - timedelta(days=offset)).strftime("%Y-%m-%d") if base else None
        anchor = cutting_anchor.get(d0) if d0 else None
        exc_list = (exc_map.get(d0) or []) if d0 else []

        # ---- 0) 本行「自身异常」（2026-11 第 4 态）：本行 offset == 生效中异常的 offset ----
        # 优先级 done > exception > exception_paused > waiting_material > 常规；
        # 这里只产出标记，最终优先级由 judge_node_status 统一裁决。
        self_exceptions = [
            e for e in exc_list
            if e.get("active") is True and int(e.get("offset_days") or 0) == offset
        ]
        self_exception = bool(self_exceptions)
        # 展示用「计划关闭日」：多条生效中异常时取最早的（最紧迫）那一日
        self_close_dates = sorted(
            _planned_close_text(e) for e in self_exceptions if _planned_close_text(e)
        )
        self_close_date = self_close_dates[0] if self_close_dates else None

        # ---- A) 生效中异常：该套「后续工序」暂停（暂停优先于待下料）----
        # 「后续工序」判定：本行 offset > 异常工序 offset；异常工序自身不暂停（它确实逾期了）
        # 🔴 2026-11：条件由 ``status != 'closed'`` 改为 ``active is True``
        #    —— 已过计划关闭日的异常（expired）暂停失效，下游恢复逾期判定。
        paused = any(
            e.get("active") is True
            and int(e.get("offset_days") or 0) < offset
            for e in exc_list
        )

        # ---- B) 已关闭异常：解决时间回推锚点，重算后续工序计划日 ----
        # 候选锚点 = closed_at − 异常工序 offset；仅对本行 offset > 异常 offset 的行生效
        # （否则把「更早工序」的计划日也往后推，会掩盖真实逾期；异常工序自身保持原计划判定）
        # 🔴 2026-11：本段一行不改 —— 仍然**只认 status == 'closed'**；
        #    到期失效（expired）的异常绝不参与锚点重算（expired ≠ closed）。
        new_anchor = parse_date(anchor) if anchor else None
        for e in exc_list:
            if str(e.get("status") or "") != "closed":
                continue
            exc_offset = int(e.get("offset_days") or 0)
            closed_at = str(e.get("closed_at") or "")[:10]
            if not closed_at or exc_offset >= offset:
                continue
            cand = parse_date(closed_at)
            if cand is None:
                continue
            cand = cand - timedelta(days=exc_offset)
            if new_anchor is None or cand > new_anchor:
                new_anchor = cand

        if paused:
            # 灰态「⏸ 异常暂停」：不判逾期、不计入逾期统计/风险等级/排名；
            # 仍保留可填报性（计划日回退原计划日由 enrich_rows 处理）
            rules[nid] = _rule(False, None, False, paused=True, set_date=d0,
                               self_exception=self_exception,
                               self_close_date=self_close_date)
        elif new_anchor is None:
            # 闸门关（该套尚未实际下料，且无已关闭异常可作锚点）
            rules[nid] = _rule(True, None, False, set_date=d0,
                               self_exception=self_exception,
                               self_close_date=self_close_date)
        else:
            eff = (new_anchor + timedelta(days=offset)).strftime("%Y-%m-%d")
            # 自身异常的行不计入逾期统计（第 4 态独立，level=0）
            rules[nid] = _rule(False, eff, not self_exception, set_date=d0,
                               self_exception=self_exception,
                               self_close_date=self_close_date)
    return rules


def judge_node_status(plan_date, plan_qty, actual_qty, today, completion_date=None, *,
                      eff_plan_date=None, waiting_material=False, count_as_overdue=True,
                      segment_active=False, exception_paused=False,
                      exception_active=False, exception_close_date=None):
    """
    判定单个工序节点计划状态（六态 + 完成日期偏差 + 待下料态 + 异常暂停态 + 异常态）。

    新增（工序时间/延期判定规则升级）：
    - waiting_material=True：闸门关（该套尚未实际下料）的制造链工序 → 返回 ⏸ 待下料（灰），
      不判延期、不计入逾期/风险/排名（count_as_overdue=False）；**但不影响可填报性**
      （分组不变，下料仍可填报，否则闸门永远打不开）。
    - eff_plan_date：闸门开时以「实际下料日 + 该工序相对下料的计划偏移」重算的计划日期，
      作为延期判定基准（替代原始 plan_date）。
    - count_as_overdue：该节点是否计入逾期统计/风险等级/排名（法兰到货、待下料为 False）。
    - segment_active（按段填报已开工，v7.1 行级化）：该套已有按段记录且已完成段数 > 0
      → 视为「已开工但未整套完成」，返回 🔵 进行中（未来计划日为 🔵 提前进行中），
      **不再判 🔴 逾期未完成**（用户 2026-10-09 口径：按段提报后状态应为进行中）。
      注意：按段填报不写 actual_qty，故不能靠 actual_qty>0 分支兜住，必须单独判。
    - exception_paused（异常暂停，2026-10）：该行所属套存在**生效中**异常且本行是其后序工序
      → 返回 ⏸ 异常暂停（灰），level=0、不计入逾期统计/风险/排名、偏差显示 '-'。
      优先级高于 waiting_material（暂停期间连"待下料"提示都不再显示）。
      ⚠️ 已完成的行（actual_qty >= plan_qty）**不**回退为暂停态——暂停是「计划口径」，
         已经发生的完成事实不应被抹掉，否则 KPI「达标节点」会凭空减少。
    - exception_active / exception_close_date（异常第 4 态，2026-11）：本行**自身**即为
      生效中异常所在工序 → 返回 🟠 异常，level=0、count_as_overdue=False、
      偏差显示「计划关闭 MM-DD」。优先级 **done > exception > exception_paused**。
      🔴 同样遵守「done 最高优先」：已完成的行不回退为异常态（完成事实不可抹掉）。

    规则（按此顺序）：
    - done:        actual_qty >= plan_qty              → 🟢 已完成（提前完成）
    - exception:   exception_active 且未完成            → 🟠 异常（第 4 态）
    - exception_paused: 该套上游有生效中异常            → ⏸ 异常暂停
    - waiting_material: 闸门关                          → ⏸ 待下料
    - pending:     plan_date > today 且无任何进度       → ⚪ 未开始
    - in_progress: plan_date > today 且有进度/有段记录  → 🔵 提前进行中
    - in_progress: plan_date == today                  → 🔵 进行中（当日不再显示逾期）
    - warning:     plan_date < today 且 actual_qty > 0 → 🟡 部分完成
    - in_progress: plan_date < today 且已按段提报（segment_active）→ 🔵 进行中（不判逾期）
    - overdue:     plan_date < today 且 actual_qty == 0 且无按段进度 → 🔴 逾期未完成

    Args:
        plan_date: 计划完成日期（str 'YYYY-MM-DD' 或 date 对象，内部统一 parse_date）
        plan_qty:  应完成套数（整数）
        actual_qty: 实际完成套数（整数）
        today:     当前日期（date 对象或 str，内部统一 parse_date）
        completion_date: 实际完成日期（date/str/None；有值时用于计算偏差）
        exception_active: 本行自身是否为「生效中异常」所在工序（build_time_rules 的 self_exception）
        exception_close_date: 该异常的计划关闭日（'YYYY-MM-DD'；None → 偏差显示「计划关闭 —」）

    Returns:
        dict: {"status", "label", "level", "lag_qty",
               "completion_date", "deviation_days", "deviation_label", "deviation_color"}
            - status: done | pending | in_progress | warning | overdue | waiting_material |
                      exception_paused | exception
            - level:  overdue=4 > warning=3 > in_progress=2 > pending=0 = done=0 = exception=0
            - lag_qty: 部分完成=plan-actual；逾期=plan；其余 0
            - deviation_label: 提前X天 / 准时 / 延期X天 / 还有X天 / 进行中 / 逾期X天 / 计划关闭 MM-DD
            - deviation_color: 提前/准时/进行中 #38a169；未到 #718096；warning #d69e2e；
                               overdue #e53e3e；exception #dd6b20
    """
    # 已完成的行不回退状态：暂停/异常只作用于「尚未完成」的行（done 最高优先）
    if int(actual_qty or 0) < int(plan_qty or 0):
        # 异常第 4 态（2026-11）：本行自身即为生效中异常所在工序
        # 🔴 优先级高于 exception_paused / waiting_material，低于 done
        if exception_active:
            close_text = str(exception_close_date or "")[:10]
            close_label = f"计划关闭 {close_text[5:]}" if len(close_text) >= 10 else "计划关闭 —"
            return {
                "status": "exception", "label": "🟠 异常", "level": 0, "lag_qty": 0,
                "completion_date": None,
                "deviation_days": 0, "deviation_label": close_label,
                "deviation_color": "#dd6b20",
                "count_as_overdue": False,
            }
        if exception_paused:
            # 异常暂停态（该套存在生效中异常，本行为其后序工序）：灰态、不判延期、不计入统计
            return {
                "status": "exception_paused", "label": "⏸ 异常暂停", "level": 0, "lag_qty": 0,
                "completion_date": None,
                "deviation_days": 0, "deviation_label": "-", "deviation_color": "#a0aec0",
                "count_as_overdue": False,
            }

    # 待下料态（闸门关的制造链工序）：灰态、不判延期、不计入逾期/风险/排名
    if waiting_material:
        return {
            "status": "waiting_material", "label": "⏸ 待下料", "level": 0, "lag_qty": 0,
            "completion_date": None,
            "deviation_days": 0, "deviation_label": "-", "deviation_color": "#a0aec0",
            "count_as_overdue": False,
        }

    # 统一解析日期（str / date / datetime / Timestamp 均兼容）
    # 闸门开时用重算后的 effective 计划日期作为延期判定基准
    base_plan = eff_plan_date if eff_plan_date is not None else plan_date
    parsed_plan = parse_date(base_plan)
    if parsed_plan is None and base_plan is not None:
        parsed_plan = base_plan

    if today is None:
        today = business_today()
    parsed_today = parse_date(today) or today

    plan_qty = int(plan_qty or 0)
    actual_qty = int(actual_qty or 0)
    parsed_comp = parse_date(completion_date) if completion_date is not None else None

    # ---- 状态判定（按用户指定顺序）----
    if actual_qty >= plan_qty:
        # done 保持最高优先级；未来日期完成 → 「提前完成」语义
        if parsed_plan is not None and parsed_today < parsed_plan:
            status, label, level, lag = "done", "🟢 提前完成", 0, 0
        else:
            status, label, level, lag = "done", "🟢 已完成", 0, 0
    elif parsed_plan is not None and parsed_today < parsed_plan:
        # 未来计划节点：支持提前进行中语义（有实际填报 或 已按段提报 → 提前进行中）
        if actual_qty > 0 or segment_active:
            status, label, level, lag = "in_progress", "🔵 提前进行中", 2, 0
        else:
            status, label, level, lag = "pending", "⚪ 未开始", 0, 0
    elif parsed_plan is not None and parsed_today == parsed_plan:
        status, label, level, lag = "in_progress", "🔵 进行中", 2, 0
    elif actual_qty > 0:
        status, label, level, lag = "warning", "🟡 部分完成", 3, plan_qty - actual_qty
    elif segment_active:
        # 按段提报已开工（已完成段数 > 0）但尚未整套填报 → 进行中，不再判逾期未完成
        # （用户 2026-10-09 口径；按段填报不写 actual_qty，故必须在此单判）
        status, label, level, lag = "in_progress", "🔵 进行中", 2, 0
    else:
        status, label, level, lag = "overdue", "🔴 逾期未完成", 4, plan_qty

    # ---- 偏差计算 ----
    if parsed_comp is not None and parsed_plan is not None:
        delta = (parsed_comp - parsed_plan).days
        if delta < 0:
            dev_days, dev_label, dev_color = -delta, f"提前{-delta}天", "#38a169"
        elif delta > 0:
            dev_days, dev_label, dev_color = delta, f"延期{delta}天", "#e53e3e"
        else:
            dev_days, dev_label, dev_color = 0, "准时", "#38a169"
    elif parsed_plan is not None:
        if parsed_today < parsed_plan:
            d = (parsed_plan - parsed_today).days
            dev_days, dev_label, dev_color = d, f"还有{d}天", "#718096"
        elif parsed_today == parsed_plan:
            dev_days, dev_label, dev_color = 0, "进行中", "#38a169"
        else:
            d = (parsed_today - parsed_plan).days
            dev_days, dev_label, dev_color = d, f"逾期{d}天", "#e53e3e"
    else:
        dev_days, dev_label, dev_color = 0, "-", "#718096"

    return {
        "status": status, "label": label, "level": level, "lag_qty": lag,
        "completion_date": parsed_comp if status == "done" else None,
        "deviation_days": dev_days,
        "deviation_label": dev_label,
        "deviation_color": dev_color,
        "count_as_overdue": bool(count_as_overdue),
    }


def compute_real_overdue(rows: list[dict], monthly_plan: int) -> list[dict]:
    """计算「真逾期」节点列表（逾期判定规则变更后口径）。

    真逾期 = 节点状态为 overdue **且** 该节点所属工序的累计完成套数 < 调度令本月计划数。
    即：某工序已完成/到达套数已达调度令计划时，其后续超产套数的逾期不再算作「延期」。

    ⚠️ 边界（用户 2026-09-01 选定方案 B）：
    monthly_plan <= 0（项目无调度令计划数据）时**回退原有逻辑**——所有 overdue 节点都算真逾期。
    原因：没有月计划阈值就无法判断什么是"超产"，若返回空集会漏报真实延期。
    此处与 judge_process_card_status 的 monthly_plan<=0 分支保持一致（卡片仍显示"已逾期"），
    保证项目级风险等级与工序卡片状态不打架。

    Args:
        rows: enrich_rows() 产出的节点行列表（每行含 process_name / actual_qty / status）
        monthly_plan: 调度令本月计划数（projects.monthly_plan）；
                      <=0 表示无调度令计划 → 回退原有逻辑，返回全部 overdue 节点

    Returns:
        list[dict]: 真逾期节点行（可能为空列表）
    """
    all_overdue = [r for r in rows if r["status"] == "overdue" and r.get("count_as_overdue", True)]
    if monthly_plan <= 0:
        # 无调度令计划 → 无法判定"超产"，回退原有逻辑（避免漏报延期）
        return all_overdue
    proc_actual: dict[str, int] = {}
    for r in rows:
        proc_actual[r["process_name"]] = proc_actual.get(r["process_name"], 0) + int(r["actual_qty"] or 0)
    return [
        r for r in all_overdue
        if proc_actual.get(r["process_name"], 0) < monthly_plan
    ]


def judge_project_risk(rows: list[dict], monthly_plan: int = 0, today=None, *,
                       has_active_exception: bool = False) -> str:
    """项目级风险等级判定（四态互斥）——**唯一实现处**（列表/KPI 与详情共用）。

    优先级：``exception > delayed > warning > normal``

    - exception: 项目下存在**生效中**的异常（未关闭且未过计划关闭日）。
      ⚠️ 由调用方用 ``has_active_exception`` 算出后传入（单源），本函数不自行查库；
      无 durations 的存量项目同样成立（异常表口径，不依赖能否反推所属套）。
    - delayed:   存在「真逾期」节点（``compute_real_overdue`` 口径）
    - warning:   无逾期，但存在「今天计划且未完成」的 in_progress 节点
      （未来日期的 in_progress「提前进行中」不算预警）
    - normal:    以上皆无

    Args:
        rows: ``enrich_rows`` 产出的节点行
        monthly_plan: 调度令本月计划数（真逾期判定阈值）
        today: 基准日（None → 业务时区今天）
        has_active_exception: 项目是否存在生效中异常（关键字参数，语义显式）

    Returns:
        str: 'exception' | 'delayed' | 'warning' | 'normal'
    """
    if has_active_exception:
        return "exception"
    today_s = _today_text(today)
    if compute_real_overdue(rows or [], int(monthly_plan or 0)):
        return "delayed"
    has_today_unfinished = any(
        r.get("status") == "in_progress"
        and str(r.get("plan_date") or "")[:10] == today_s
        and int(r.get("actual_qty") or 0) < int(r.get("plan_qty") or 0)
        for r in (rows or [])
    )
    if has_today_unfinished:
        return "warning"
    return "normal"


def judge_process_card_status(proc_nodes: list[dict], actuals: dict, today=None, monthly_plan: int = 0) -> dict:
    """工序卡片状态：主状态(总进度) + 附加标签(时间维度偏差)。

    主状态（总进度）：
    - waiting_material 待下料: 整道工序所有行都是「闸门关」（该套尚未实际下料）
    - exception_paused 异常暂停: 整道工序所有行都是「待下料 / 异常暂停」且至少一行异常暂停
    - exception   异常:     整道工序所有行都是「异常 / 异常暂停 / 待下料」且至少一行本身是异常（第 4 态）
    - done_early 提前完成: 总实际 ≥ 总计划 且 所有 plan_date > today
    - done        已完成:   总实际 ≥ 总计划
    - matches_dispatch 符合调度令进度: 存在历史逾期但总实际 >= 调度令本月计划（monthly_plan>0）
    - overdue     已逾期:   存在 plan_date < today 且 actual < plan（严格历史逾期，不含今天）
    - in_progress 进行中:   0 < 总实际 < 总计划 且无历史逾期
    - pending     未开始:   总实际 == 0 且无历史逾期

    附加标签 tags：
    - 部分完成: 存在 plan_date ≤ today 且 0 < actual < plan（含历史逾期部分完成）
    - 已提前:   存在 plan_date > today 且 actual ≥ plan，且该工序无历史逾期
    - 当主状态为「已逾期」或 tags 含「部分完成」时，不再显示「已提前」
    """
    today = today or business_today()
    today_s = str(today)[:10]
    if not proc_nodes:
        return {"status": "pending", "label": "⚪ 未开始", "tags": []}

    total_plan = sum(int(n["plan_qty"] or 0) for n in proc_nodes)
    total_actual = sum(
        int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0) for n in proc_nodes
    )

    # 闸门关（整道工序均为待下料）→ 卡片显示 ⏸ 待下料，不判延期
    if all(n.get("status") == "waiting_material" for n in proc_nodes):
        return {"status": "waiting_material", "label": "⏸ 待下料", "tags": []}

    # 异常暂停（2026-10）：整道工序的行全部处于「待下料 / 异常暂停」且至少有行是异常暂停
    # → 卡片显示 ⏸ 异常暂停（与节点级同视觉层级，灰态、不判延期）。
    # 只要还有任何一行可判定（已完成 / 进行中 / 逾期），就仍走下面的常规判定，
    # 避免个别套暂停就把整道工序的真实逾期藏起来。
    if any(n.get("status") == "exception_paused" for n in proc_nodes) and all(
            n.get("status") in ("exception_paused", "waiting_material") for n in proc_nodes):
        return {"status": "exception_paused", "label": "⏸ 异常暂停", "tags": []}

    # 异常（2026-11，项目级第 4 态在工序卡片上的投影）：整道工序的行全部处于
    # 「异常 / 异常暂停 / 待下料」且**至少有一行本身是异常** → 卡片 🟠 异常（不判逾期）。
    # 只要还有任何一行可判定（已完成 / 进行中 / 逾期），就仍走下面的常规判定，
    # 避免个别套的异常把整道工序的真实逾期藏起来（与上面两档灰态的收口口径一致）。
    if any(n.get("status") == "exception" for n in proc_nodes) and all(
            n.get("status") in ("exception", "exception_paused", "waiting_material")
            for n in proc_nodes):
        return {"status": "exception", "label": "🟠 异常", "tags": []}

    # 严格历史逾期：plan_date < today 且未完成（不含今天）；仅计入 count_as_overdue 的节点
    # （法兰到货、待下料不参与逾期/风险/排名）
    overdue_nodes = [
        n for n in proc_nodes
        if n.get("count_as_overdue", True)
        and str(n["plan_date"])[:10] < today_s
        and int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        < int(n["plan_qty"] or 0)
    ]
    has_overdue = bool(overdue_nodes)

    # 逾期判定规则：本月计划达成后，超产套数的逾期不再显示「延期」
    if has_overdue and monthly_plan > 0 and total_actual >= monthly_plan:
        return {"status": "matches_dispatch", "label": "✅ 符合调度令进度", "tags": []}

    # 部分完成节点：截至今天(含)已有进度但未达到计划数量
    partial_nodes = [
        n for n in proc_nodes
        if str(n["plan_date"])[:10] <= today_s
        and 0 < int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        < int(n["plan_qty"] or 0)
    ]
    has_partial = bool(partial_nodes)

    # 提前完成节点：未来日期且已完成
    early_nodes = [
        n for n in proc_nodes
        if str(n["plan_date"])[:10] > today_s
        and int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        >= int(n["plan_qty"] or 0)
    ]
    has_early = bool(early_nodes)

    # 附加标签：有逾期时只补充"部分完成"，不显示"已提前"
    tags = []
    if has_overdue:
        if has_partial:
            tags.append("部分完成")
    else:
        if has_early:
            tags.append("已提前")

    # 主状态
    if total_actual >= total_plan:
        if min(str(n["plan_date"])[:10] for n in proc_nodes) > today_s:
            return {"status": "done_early", "label": "🟢 提前完成", "tags": tags}
        return {"status": "done", "label": "🟢 已完成", "tags": tags}
    if has_overdue:
        return {"status": "overdue", "label": "🔴 已逾期", "tags": tags}
    if total_actual > 0:
        return {"status": "in_progress", "label": "🔵 进行中", "tags": tags}
    return {"status": "pending", "label": "⚪ 未开始", "tags": tags}


def _group_nodes(proc_nodes: list[dict], actuals: dict, today) -> dict:
    """按 今日/逾期/未来/已完成 严格互斥分组（与原版口径一致）。

    独立工序（累计完成/累计发运）特殊口径：
      - plan_date IS NULL → today（合同占位行，可继续填）
      - plan_date IS NOT NULL → done（每次填报生成的"本次记录"行，date 即填报日期）
      - 不再走 act >= plan_qty 判定（独立工序每行 plan_qty = 本次填报量，actual = plan，已自洽）
    """
    today_nodes, overdue_nodes, future_nodes, done_nodes = [], [], [], []
    for p in proc_nodes:
        act = actuals.get(p["id"], {}).get("actual_qty", 0)
        is_independent = p.get("process_name") in INDEPENDENT_PROCESS_NAMES
        if p.get("plan_date") is None and is_independent:
            # 独立工序的合同占位行：始终留在「今日待填报」供继续填报
            today_nodes.append(p)
        elif p.get("plan_date") is not None and is_independent:
            # 独立工序的填报记录行：按日期归档到「已完成」
            done_nodes.append(p)
        elif act >= p["plan_qty"]:
            done_nodes.append(p)
        elif p.get("plan_date") is None:
            # 非独立工序且 plan_date 为 NULL（理论上不应出现，兜底）
            today_nodes.append(p)
        elif str(p["plan_date"])[:10] == str(today)[:10]:
            today_nodes.append(p)
        elif str(p["plan_date"])[:10] < str(today)[:10]:
            overdue_nodes.append(p)
        else:
            future_nodes.append(p)
    return {
        "today": today_nodes,
        "overdue": overdue_nodes,
        "future": future_nodes,
        "done": done_nodes,
    }


def split_node_groups(proc_nodes: list[dict], actuals: dict, today=None) -> dict:
    """对外：按四组切分节点（前端填报弹窗四分组手风琴数据源）。"""
    today = today or business_today()
    return _group_nodes(proc_nodes, actuals, today)


def validate_today_quota_nodes(process_name: str, plans_all: list[dict], actuals: dict,
                               target_nodes: list[dict], input_values: dict) -> dict:
    """节点级前序联动校验（部分成功模式核心）：返回 ``{node_id: 错误文案}``，全部合规返回 ``{}``。

    !! 前序联动已于 2026-10-16 按业务要求停用：后置工序完全独立填报——前序未开工亦可填报、
    填报量也不受前序完成量限制。为保持调用点与响应结构不变（一键提报 partial_ok 的
    ``skipped`` 字段、逐条保存的整批拒绝路径），此处保留函数骨架但恒返回空字典。
    如需恢复联动，请从版本管理历史回退本函数与 ``validate_today_quota`` 的实现。

    入参保留原签名，纯粹为兼容既有调用点（``nodes.py``）与 QA 脚本的 import。
    """
    return {}


def validate_today_quota(process_name: str, plans_all: list[dict], actuals: dict,
                         target_nodes: list[dict], input_values: dict) -> Optional[str]:
    """填报前序联动校验（手动逐条保存路径：整批硬卡，任一节点失败即整批拒绝）。

    !! 前序联动已于 2026-10-16 按业务要求停用（详见 ``validate_today_quota_nodes``）。
    恒返回 ``None``（无错误），使 ``nodes.py`` 的逐条保存路径不再因前序未完成而拒绝。
    """
    return None
