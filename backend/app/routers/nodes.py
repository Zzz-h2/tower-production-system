# -*- coding: utf-8 -*-
"""节点实际进度保存 API：按分组独立保存（互不覆盖）。"""
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta

from ..core import db
from ..core.deps import get_current_user, require_project_access
from ..core.timeutil import business_today
from ..schemas import SaveNodeProgressRequest, SaveSegmentRequest
from ..services.business_logic import (
    validate_today_quota, validate_today_quota_nodes, split_node_groups, build_time_rules,
)
# 异常锚点：与展示端（node_service.build_process_detail）复用同一读取函数，
# 保证「保存校验的分组」与「弹窗展示的分组」口径完全一致（含查询失败 → {} 的兜底）。
from ..services.node_service import load_exception_anchors
from ..core.config import GROUP_LABELS, INDEPENDENT_PROCESS_NAMES

router = APIRouter(prefix="/api/projects", tags=["nodes"])

# 大区账号（big_area）可回填的日期窗口天数。
# ⚠️ 与前端 frontend/src/components/ProcessDetailDialog.vue 的 BACKFILL_DAYS 必须同值
#   （前后端各写一份常量、无法共享，任何改动必须两侧同步）。
# 允许区间 = [今天 − BACKFILL_DAYS, 今天]（闭区间，含今天）；未来日期一律越界。
BACKFILL_DAYS = 7


def _auto_close_resolved_exceptions(pid: int, process_name: str, node_ids: set,
                                    today) -> list[dict]:
    """提报进度后自动关闭该工序在本批节点上的异常（2026-10 用户口径）。

    口径：「填了进度 = 异常已解决」。只在**有计划关闭日且 today <= 计划关闭日**时自动关闭：
      · 已到期失效（today > 计划关闭日）的异常**不**自动关闭 —— 避免补录历史进度把
        过期异常"洗白"（过期记录应留在超期列表等人工处理）；
      · ``planned_close_date`` 为空的（历史异常，永不到期）**不**自动关闭，保持原状。
    关闭后 ``closed_at=NOW()``（由 ``db.update_node_exception`` 统一写），下游工序会按
    closed_at 锚点重算计划日 —— 与「手动点关闭」完全同一条链路。

    Args:
        pid: 项目 id
        process_name: 本次保存的工序名（异常必须属于同一工序）
        node_ids: 本次成功写入进度的节点 id 集合
        today: 业务今天（date）

    Returns:
        list[dict]: 已关闭的异常（``id/process_name/planned_close_date``），供响应提示
    """
    if not node_ids:
        return []
    today_text = today.strftime("%Y-%m-%d")
    closed: list[dict] = []
    try:
        exc_rows = db.get_node_exceptions_by_project(pid)
    except Exception as exc:      # noqa: BLE001 — 自动关闭属增强，失败不得影响保存本身
        print(f"[warn] 自动关闭异常：读取异常失败（跳过）：{exc}")
        return []
    for e in exc_rows or []:
        if str(e.get("status") or "").strip() == "closed":
            continue
        if str(e.get("process_name") or "").strip() != process_name:
            continue
        try:
            if int(e.get("node_id") or 0) not in node_ids:
                continue
        except (TypeError, ValueError):
            continue
        planned = str(e.get("planned_close_date") or "")[:10]
        if not planned or today_text > planned:
            continue
        try:
            if db.update_node_exception(e["id"], {"status": "closed"}):
                closed.append({
                    "id": e["id"],
                    "process_name": process_name,
                    "planned_close_date": planned,
                })
        except Exception as exc:   # noqa: BLE001
            print(f"[warn] 自动关闭异常 {e.get('id')} 失败：{exc}")
    return closed


@router.post("/{pid}/nodes/{process_name}/save")
def save_node_progress(pid: int, process_name: str, req: SaveNodeProgressRequest,
                       user: dict = Depends(get_current_user)):
    """按分组保存节点实际进度。

    - 行级隔离：big_area 用户仅可填报本大区项目（非本区返回 404 防探测）；admin 全量；
    - 只写当前分组节点（其他分组数据不被触碰）；
    - group=today/overdue/future：前序工序数量联动校验（累计 ≤ 前序累计实际，防越序），各节点 ≤ 计划数；
    - group=done：已完成分组为「无法编辑」只读模式，后端直接拒绝写操作（不接受减少/修改）；
    - 填报日期：大区账号（big_area）可回填最近 BACKFILL_DAYS 天内的日期（含今天），
      越界（早于今天 − BACKFILL_DAYS 或晚于今天）返回 400 REPORT_DATE_OUT_OF_RANGE；
      「只改数量、日期沿用库中原值」放行（不因旧日期越界被误拦）；管理员不受窗口限制。
    - 业务校验一律返回 400 + {code,message} 结构，前端可读友好文案。
    - v6.0 多负责人：req.manager 非空时，只加载/校验/写入该负责人名下的节点，
      各负责人提报相互独立、互不影响；实际写入的 manager 以节点计划行自身的值为准（防跨负责人误写）。
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)

    mgr = (req.manager or "").strip() or None   # 本次填报归属负责人（空=汇总/不区分）
    # v7.4 排产按月隔离：填报所见的计划行必须与详情页同一月份口径，
    # 否则会出现「前端展示该月行、后端按跨月全集校验」的口径漂移。
    mth = (req.month or "").strip() or None

    if req.group not in GROUP_LABELS:
        raise HTTPException(status_code=400, detail={"code": "UNKNOWN_GROUP", "message": f"未知分组：{req.group}"})
    if req.group == "done" and user.get("role") != "admin" and process_name not in INDEPENDENT_PROCESS_NAMES:
        # done 分组对普通用户为「无法编辑」只读模式（前端禁用输入）；admin 可编辑补录。
        # 独立工序（累计完成/累计发运）例外：每次填报都是新增一条「本次记录」而非修改已有"已完成"记录，
        # 所以大区账号也允许在 done 分组写入（前端在「已填报」行允许再填一次）。
        raise HTTPException(status_code=400, detail={"code": "DONE_READONLY", "message": "已完成分组不可编辑（无法填报）"})

    # 多负责人：只取该负责人名下的节点计划（前序联动校验也随之限定在其内部，互不干扰）
    # v7.4：叠加月份作用域，与详情页展示口径一致
    plans = db.get_node_plans(pid, mgr, mth)
    actuals = db.get_node_actuals(pid)
    durations = db.get_project_process_durations(pid, mgr, mth)

    # 「今天」用业务时区（Asia/Shanghai）单一来源，不依赖运行环境时区，
    # 避免容器 UTC 与用户东八区在 00:00–08:00 出现跨天窗口错位。
    # 提前到分组计算之前取：异常锚点（active/expired）需要同一「今天」。
    today = business_today()

    # 🔴 分组口径必须与展示端（node_service.build_process_detail）**完全相同**，否则
    #    「界面上在 A 组、保存时后端认为在 B 组」→ 400 NODE_NOT_IN_GROUP / 分组为空。
    #    2026-11 线上 bug：此前这里调 build_time_rules 时**没传异常锚点**，而展示端传了。
    #    异常「生效中」时因暂停/重算对同组影响小；一旦**关闭异常**，展示端按关闭时间重算
    #    计划日（该行移入未来计划/已完成），保存端仍按无异常口径判为逾期 → 用户点保存必失败，
    #    且「分组为空」那条 400 的 detail 是字符串，前端只能显示 UNKNOWN「请求失败」。
    #    修法：复用展示端同一个带兜底的读取函数 load_exception_anchors（查询失败 → {} 不阻塞），
    #    判定内核 build_time_rules / split_node_groups 一行未改。
    exc_anchors = load_exception_anchors(pid, durations, plans, today=today)
    rules = build_time_rules(plans, actuals, durations, exc_anchors, today=today)
    plans_for_group = [
        ({**p, "plan_date": rules[p["id"]]["eff_plan_date"]}
         if rules.get(p["id"], {}).get("eff_plan_date") else p)
        for p in plans
    ]
    proc_nodes = [p for p in plans_for_group if p["process_name"] == process_name]
    if not proc_nodes:
        tip = f"（负责人：{mgr}）" if mgr else ""
        raise HTTPException(
            status_code=404,
            detail={"code": "NO_NODES",
                    "message": f"工序「{process_name}」在当月没有可填报的节点{tip}，请刷新后重试"},
        )

    plan_qty_by_id = {p["id"]: int(p["plan_qty"] or 0) for p in proc_nodes}
    # 写入时的负责人以节点计划行自身的值为准（权威来源），避免前端传错导致串档
    plan_manager_by_id = {p["id"]: p.get("manager") for p in proc_nodes}

    is_independent = process_name in INDEPENDENT_PROCESS_NAMES  # 独立工序：不设日期、不限 qty 上限

    # today 已在分组计算之前取好（异常锚点与分组必须共用同一个「今天」），此处不再重复取
    groups = split_node_groups(proc_nodes, actuals, today)
    target_ids = {p["id"] for p in groups[req.group]}
    if not target_ids:
        # 🔴 必须是 {code, message} 对象：此前这里是字符串 detail，前端 code 取不到 → 显示
        #    UNKNOWN「未分类错误: 请求失败」，线上问题因此无从定位（2026-11）。
        raise HTTPException(
            status_code=400,
            detail={
                "code": "GROUP_EMPTY",
                "message": (
                    f"当前分组「{GROUP_LABELS[req.group]}」已没有可保存的节点"
                    f"（可能因异常关闭/日期重算被移入其它分组），请关闭弹窗重新打开后重试"
                ),
            },
        )

    # 校验：提交的节点必须属于当前分组；数量非负（schema ge=0）且不超过计划数
    input_values = {}
    for v in req.values:
        if v.node_id not in target_ids:
            raise HTTPException(
                status_code=400,
                detail={"code": "NODE_NOT_IN_GROUP", "message": f"节点 {v.node_id} 不属于当前分组 {req.group}"},
            )
        limit = plan_qty_by_id.get(v.node_id, 0)
        if not is_independent and v.qty > limit:
            raise HTTPException(
                status_code=400,
                detail={"code": "QTY_EXCEED_PLAN", "message": f"节点 {v.node_id} 数量不能超过计划数 {limit}"},
            )
        input_values[v.node_id] = v.qty

    # 业务前序联动校验：today / overdue / future 三组都跑（done 仍只读、不可改）。
    # partial_ok=True（一键提报部分成功模式）：前序联动逐节点校验，失败节点跳过而非
    # 整批 400，跳过明细随响应返回；分组归属 / 数量上限等请求构造类校验仍整批拒绝。
    skipped_details: list[dict] = []
    values_to_write = req.values
    if req.group in ("today", "overdue", "future"):
        if req.partial_ok:
            node_errors = validate_today_quota_nodes(
                process_name, plans, actuals, groups[req.group], input_values,
            )
            if node_errors:
                plan_date_by_id = {p["id"]: str(p.get("plan_date") or "")[:10] for p in groups[req.group]}
                skipped_details = [
                    {
                        "node_id": nid,
                        "plan_date": plan_date_by_id.get(nid, ""),
                        "qty": int(input_values.get(nid, 0) or 0),
                        "message": node_errors[nid],
                    }
                    for nid in node_errors
                ]
                values_to_write = [v for v in req.values if v.node_id not in node_errors]
        else:
            err = validate_today_quota(process_name, plans, actuals, groups[req.group], input_values)
            if err:
                raise HTTPException(
                    status_code=400,
                    detail={"code": "PREV_PROC_QUOTA_EXCEEDED", "message": err},
                )

    # 写入（只写当前分组，每行独立填报日期；大区账号可回填近 BACKFILL_DAYS 天；独立工序按日期 find-or-create）
    # partial_ok 模式下只写通过前序联动校验的节点
    lock_date = user.get("role") == "big_area"

    # big_area 窗口校验「前移」到写入循环之前（原子性）：先对全部待写行整体校验，
    # 任一行日期非法/越界即整批 400，且一行都不落库 —— 与 NODE_NOT_IN_GROUP /
    # QTY_EXCEED_PLAN 的「先校验后写入」风格一致。旧实现把校验放循环内，越界行在
    # 后面时前面的行已先落库，存在顺序相关的部分写入。
    # 仅对 big_area 的「非独立工序」生效；admin 不受窗口限制，独立工序按自身分支处理。
    if lock_date and not is_independent:
        _earliest = today - timedelta(days=BACKFILL_DAYS)
        for v in values_to_write:
            rd = v.report_date or today.strftime("%Y-%m-%d")
            try:
                rd_date = datetime.strptime(rd, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
            # 「只改数量、未改日期」放行：库中原 report_date 可能远早于窗口（如 1 个月前），
            # rd 等于该节点现有值即视为未修改日期。actuals 里可能是 date 或 str，统一截断到 10 位。
            existing_rd = str(actuals.get(v.node_id, {}).get("report_date") or "")[:10]
            if rd != existing_rd and (rd_date < _earliest or rd_date > today):  # 晚于今天（未来）同样越界
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "REPORT_DATE_OUT_OF_RANGE",
                        "message": (
                            f"填报日期 {rd} 超出允许范围（仅可回填最近 {BACKFILL_DAYS} 天，"
                            f"即 {_earliest.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')}）"
                        ),
                    },
                )

    saved = 0
    saved_ids: set[int] = set()   # 供「提报进度→自动关闭异常」精确圈定本次提交的节点
    for v in values_to_write:
        if is_independent:
            rd = v.report_date or today.strftime("%Y-%m-%d")
            try:
                datetime.strptime(rd, "%Y-%m-%d")
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
            # 「已完成」记录改日期（管理员）：移动该条记录到新日期（后端合并冲突）；
            # 占位行（plan_date IS NULL）或未改日期：按日期 find-or-create（每日一条新行，同日累加到同条）
            plan = next((p for p in proc_nodes if p["id"] == v.node_id), None)
            is_move = (
                plan is not None
                and plan.get("plan_date") is not None
                and rd != str(plan["plan_date"])[:10]
            )
            if is_move:
                if user.get("role") != "admin":
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "DONE_READONLY", "message": "已完成记录的填报日期仅管理员可调整"},
                    )
                # 管理员可能同时改了数量和日期 → 移动时同步新数量（后端合并/移动用新 qty）
                db.move_independent_fill_date(pid, process_name, v.node_id, rd, int(v.qty))
            else:
                db.save_independent_fill(pid, process_name, int(v.qty), rd,
                                         plan_manager_by_id.get(v.node_id))
            saved += 1
            saved_ids.add(v.node_id)
        elif lock_date:
            # 大区账号（big_area）：日期已在写入前「整体校验」通过（见上方 pre-validation），
            # 此处直接落库。不再硬编码为今天 —— 可回填 [today − BACKFILL_DAYS, today]，
            # 与 frontend ProcessDetailDialog.vue 的 isDateDisabled 同口径。
            # ⚠️ BACKFILL_DAYS 与前端 ProcessDetailDialog.vue 的同名常量必须同值。
            rd = v.report_date or today.strftime("%Y-%m-%d")
            db.upsert_node_actual(pid, v.node_id, process_name, int(v.qty), rd,
                                  plan_manager_by_id.get(v.node_id))
            saved += 1
            saved_ids.add(v.node_id)
        else:
            rd = v.report_date or req.report_date or today.strftime("%Y-%m-%d")
            try:
                datetime.strptime(rd, "%Y-%m-%d")
            except (ValueError, TypeError):
                raise HTTPException(
                    status_code=400,
                    detail={"code": "BAD_REPORT_DATE", "message": "report_date 格式必须为 YYYY-MM-DD"},
                )
            db.upsert_node_actual(pid, v.node_id, process_name, int(v.qty), rd,
                                  plan_manager_by_id.get(v.node_id))
            saved += 1
            saved_ids.add(v.node_id)

    # ---- 2026-10：提报进度 = 异常已解决 → 自动关闭（仅限计划关闭日当天或之前）----
    # 用户口径：异常在「计划关闭日当天」转为预警态（不再暂停、按正常流程判延期），
    # 只要当天或提前提报了该工序进度，就代表问题已解决，可自动关闭该异常。
    auto_closed = _auto_close_resolved_exceptions(pid, process_name, saved_ids, today)

    message = f"✅ 已保存 {saved} 个节点进度（工序：{process_name}，{GROUP_LABELS[req.group]}）"
    if auto_closed:
        message += f"；已自动关闭 {len(auto_closed)} 条异常（进度已提报，视为异常解决）"
    if req.partial_ok and skipped_details:
        message += f"；跳过 {len(skipped_details)} 条（前序联动校验未通过）"
    resp = {
        "message": message,
        "saved": saved,
        "group": req.group,
    }
    if auto_closed:
        resp["auto_closed_exceptions"] = auto_closed
    if req.partial_ok:
        resp["skipped"] = skipped_details
    return resp


@router.post("/{pid}/nodes/{process_name}/save-segments")
def save_segment_progress(pid: int, process_name: str, req: SaveSegmentRequest,
                          user: dict = Depends(get_current_user)):
    """按段填报（v7.1 行级化）：录入某套（计划行）的「总段数 + 已完成段数」。

    - 行级隔离：big_area 用户仅可填报本大区项目（非本区返回 404 防探测）；admin 全量；
    - 段数唯一挂在 node_plan_id 上（node_segment_progress 表，uk_node_seg），同套重复提交 = 覆盖；
      不折算、不写 actual_qty，联动校验/出品排名/进度百分比零影响——不影响现有 save 端点任何逻辑；
    - 校验 node_id 对应计划行存在且属于该项目+该工序（不符 → 400 NODE_MISMATCH / 404）；
    - 校验 0 <= segment_done <= segment_total（违者 400 SEGMENT_INVALID）。
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)

    if req.segment_done > req.segment_total:
        raise HTTPException(
            status_code=400,
            detail={"code": "SEGMENT_INVALID",
                    "message": f"已完成段数（{req.segment_done}）不能超过总段数（{req.segment_total}）"},
        )

    # 计划行归属校验：必须存在且属于该项目+该工序（防跨项目/跨工序误挂段数）
    plan = db.get_node_plan_by_id(req.node_id)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail={"code": "NODE_NOT_FOUND",
                    "message": f"计划行 {req.node_id} 不存在"},
        )
    if int(plan.get("project_id") or 0) != int(pid) \
            or str(plan.get("process_name") or "") != str(process_name):
        raise HTTPException(
            status_code=400,
            detail={"code": "NODE_MISMATCH",
                    "message": f"计划行 {req.node_id} 不属于项目 {pid} 的工序「{process_name}」"},
        )

    db.upsert_node_segment(pid, req.node_id, req.segment_total, req.segment_done)
    return {"ok": True}


@router.delete("/{pid}/nodes/{process_name}/segments/{node_id}")
def cancel_segment_progress(pid: int, process_name: str, node_id: int,
                            user: dict = Depends(get_current_user)):
    """取消按段提报：清除某套（计划行）的按段进度记录，该行回落到整行填报口径。

    - 行级隔离：big_area 用户仅可操作本大区项目（非本区 404 防探测）；admin 全量；
    - 只删除 node_segment_progress 中该 node_plan_id 的记录（一行最多一条，uk_node_seg）；
    - **不改动 process_node_actuals**：actual_qty / report_date 是已发生的既成事实，
      取消按段只是不再按段展示与按段判定，该行状态由后端按 actual_qty 走常规判定
      （segment_active 消失 → 逾期/进行中/未开始等常规口径自然生效）；
    - 归属校验与 save-segments 完全一致：计划行必须属于该项目 + 该工序；
    - 幂等：本来没有按段记录时返回 deleted=0，不报错（避免重复点击造成 404 噪音）。
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)

    # 计划行归属校验（防跨项目/跨工序误删）
    plan = db.get_node_plan_by_id(node_id)
    if not plan:
        raise HTTPException(
            status_code=404,
            detail={"code": "NODE_NOT_FOUND",
                    "message": f"计划行 {node_id} 不存在"},
        )
    if int(plan.get("project_id") or 0) != int(pid) \
            or str(plan.get("process_name") or "") != str(process_name):
        raise HTTPException(
            status_code=400,
            detail={"code": "NODE_MISMATCH",
                    "message": f"计划行 {node_id} 不属于项目 {pid} 的工序「{process_name}」"},
        )

    deleted = db.delete_node_segment(pid, node_id)
    return {"ok": True, "deleted": deleted}
