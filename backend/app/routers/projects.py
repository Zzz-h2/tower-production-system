# -*- coding: utf-8 -*-
"""项目相关 API：列表（搜索/筛选/分页）、手动添加、详情、节点计划、预警。"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core import db
from ..core.deps import get_current_user, get_scope_big_area, require_admin, require_project_access
from ..schemas import ManualCompleteRequest, ProjectUpdateRequest
from ..services.node_service import build_overview, build_process_detail, enrich_rows
from ..services.business_logic import compute_real_overdue

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ============ 手动添加项目请求体 ============
class ProjectCreate(BaseModel):
    """手动添加项目：5 必填 + 3 选填；服务端做非空/整数校验。"""
    project_name: Optional[str] = None       # 项目名称 *
    machine_type: Optional[str] = None         # 机型 *
    factory_name: Optional[str] = None         # 钢塔厂家 *
    delivery_person: Optional[str] = None      # 交付负责人 *
    big_area_person: Optional[str] = None      # 大区负责人（选填）
    monthly_plan: Optional[int] = None          # 本月计划出品数量 *
    last_month_output: Optional[int] = None    # 截止上月出品（选填）
    plan_start_date: Optional[str] = None      # 计划开工日期（选填）
    plan_end_date: Optional[str] = None        # 计划交付日期（选填）


@router.get("")
def list_projects(
    keyword: Optional[str] = None,
    person: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
    month: Optional[str] = None,
    big_area_person: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    """项目列表（总览页）：支持模糊搜索、负责人/大区负责人/状态筛选、调度令月份过滤、服务端分页。

    行级隔离：big_area 用户强制只看本大区（忽略前端 big_area_person 参数）；admin 透传前端筛选。
    """
    scope = get_scope_big_area(user)
    eff = scope if user["role"] == "big_area" else big_area_person
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    skip = (page - 1) * page_size
    items, total = db.get_projects_filtered(
        keyword, person, status, skip, page_size, month, eff
    )
    # 兜底字段，保证前端渲染不报错
    for p in items:
        p.setdefault("progress_pct", 0)
        p.setdefault("risk_level", "normal")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/export")
def export_projects(month: Optional[str] = None, user: dict = Depends(get_current_user)):
    """导出指定调度令月份计划完成情况（全量，不分页）。

    口径与列表/KPI 完全一致：按 projects.created_at 年月过滤，进度为附件安装实时完成率。
    行级隔离：big_area 用户导出仅本大区；admin 导出全量。
    """
    scope = get_scope_big_area(user)
    items, total = db.get_projects_filtered(None, None, None, 0, 100000, month, scope)
    result = []
    for p in items:
        result.append({
            "project_name": p.get("project_name", ""),
            "machine_type": p.get("machine_type", ""),
            "factory_name": p.get("factory_name", ""),
            "contract_count": p.get("contract_count"),
            "last_month_output": int(p.get("last_month_output", 0) or 0),
            "monthly_plan": int(p.get("monthly_plan", 0) or 0),
            "progress_pct": float(p.get("progress_pct", 0.0) or 0.0),
            "delivery_person": p.get("delivery_person", ""),
            "big_area_person": p.get("big_area_person", ""),
        })
    return {"month": month, "total": total, "items": result}


@router.post("")
def create_project(payload: ProjectCreate, user: dict = Depends(require_admin)):
    """手动添加项目：四字段唯一键查重；新项目自动初始化工序 + 风险。（仅 admin）"""
    data = payload.model_dump()

    # 1) 5 必填非空校验
    for f in ["project_name", "machine_type", "factory_name", "delivery_person"]:
        if not data.get(f) or not str(data[f]).strip():
            raise HTTPException(status_code=400, detail=f"字段 {f} 不能为空")
    if data.get("monthly_plan") is None:
        raise HTTPException(status_code=400, detail="本月计划出品数量不能为空")
    try:
        data["monthly_plan"] = int(data["monthly_plan"])
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="本月计划出品数量必须为整数")
    # 与原版 Streamlit _render_add_project_form 一致：本月计划出品必须为正整数
    if data["monthly_plan"] <= 0:
        raise HTTPException(status_code=400, detail="本月计划出品必须大于 0")
    if data.get("last_month_output") is not None:
        try:
            data["last_month_output"] = int(data["last_month_output"])
        except (ValueError, TypeError):
            data["last_month_output"] = 0
    else:
        data["last_month_output"] = 0

    # 2) 四字段唯一键查重（名称+厂家+负责人+机型）
    dup = db.get_duplicate_project(
        data["project_name"], data["factory_name"],
        data["delivery_person"], data["machine_type"],
    )
    if dup:
        raise HTTPException(
            status_code=409,
            detail="该项目已存在（名称+厂家+负责人+机型重复）",
        )

    # 3) 写入（upsert 返回 (project_id, is_new)）
    pid, is_new = db.upsert_project(data)
    # 废弃 processes 表初始化与 risk_level 写入：风险等级由 node_plans+node_actuals 实时计算

    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目创建后未找到")
    return project


@router.get("/persons")
def list_persons(user: dict = Depends(get_current_user)):
    """返回所有交付负责人（去重排序，供主页面下拉框使用；与筛选结果隔离）。

    行级隔离：big_area 用户仅返回本大区的负责人；admin 返回全量。
    """
    return {"items": db.get_all_persons(big_area_person=get_scope_big_area(user))}


@router.get("/big-area-persons")
def list_big_area_persons(user: dict = Depends(get_current_user)):
    """返回所有大区负责人（去重排序，供主页面下拉框使用；与筛选结果隔离）。

    行级隔离：big_area 用户仅返回自己所属大区；admin 返回全量。
    """
    if user.get("role") == "big_area":
        name = user.get("big_area_name")
        return {"items": [name] if name else []}
    return {"items": db.get_all_big_area_persons()}


@router.get("/{pid}")
def get_project(pid: int, user: dict = Depends(get_current_user)):
    """项目详情（基本信息 / 进度 / 风险）。行级隔离：非本大区项目返回 404 防探测。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    # 风险等级：基于 node_plans + node_actuals 实时判定
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    rows = enrich_rows(plans, actuals)

    today_s = str(date.today())

    # 1) 历史逾期（只统计「真逾期」：工序累计完成 < 调度令本月计划）
    has_overdue = bool(compute_real_overdue(rows, int(project.get("monthly_plan") or 0)))

    # 2) 今日计划且未完成（未来日期的 in_progress 不算预警）
    has_today_unfinished = any(
        r["status"] == "in_progress"
        and str(r["plan_date"])[:10] == today_s
        and r["actual_qty"] < r["plan_qty"]
        for r in rows
    )

    if has_overdue:
        project["risk_level"] = "delayed"
    elif has_today_unfinished:
        project["risk_level"] = "warning"
    else:
        project["risk_level"] = "normal"

    return project


@router.delete("/{pid}/node-plans")
def clear_node_plans(pid: int, user: dict = Depends(require_admin)):
    """清空项目的全部节点计划（用于重置脏数据/历史测试数据）。（仅 admin）"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)
    db.delete_all_node_plans(pid)  # 彻底清空该项目所有节点计划（含独立工序）
    return {"message": "✅ 已清空该项目的节点计划"}


@router.post("/{pid}/manual-complete")
def manual_complete(pid: int, payload: ManualCompleteRequest, user: dict = Depends(require_admin)):
    """手动完成：为「提前完工但无排产计划」的项目补录『附件安装』完成数量。（仅 admin）"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    # ---- 负责人解析与校验（v6.0 多负责人；手动完成必须归属，否则排名漏统计）----
    managers = db.split_managers(project.get("delivery_person"))
    mgr = payload.manager.strip() if (payload.manager and payload.manager.strip()) else None
    if len(managers) > 1:
        if not mgr:
            raise HTTPException(
                status_code=400,
                detail=f"该项目有 {len(managers)} 位负责人（{'/'.join(managers)}），请先选择本次手动完成归属的负责人",
            )
        if mgr not in managers:
            raise HTTPException(
                status_code=400,
                detail=f"负责人「{mgr}」不在该项目的负责人名单内（{'/'.join(managers)}）",
            )
    elif len(managers) == 1:
        mgr = mgr or managers[0]

    complete_date = (payload.complete_date or "").strip()
    try:
        datetime.strptime(complete_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_DATE", "message": "完成时间格式必须为 YYYY-MM-DD"},
        )

    try:
        complete_qty = int(payload.complete_qty)
    except (TypeError, ValueError):
        complete_qty = 0
    if complete_qty <= 0 or complete_qty != payload.complete_qty:
        raise HTTPException(
            status_code=400,
            detail={"code": "BAD_QTY", "message": "完成套数必须为正整数"},
        )

    # 剩余上限口径（用户 2026-08-31 澄清）：contract_count = 项目总数；monthly_plan = 本月待完成套数，语义不同，不做回退
    _total = int(project.get("contract_count") or 0)
    if _total <= 0:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_REMAINING",
                    "message": "该项目未设置合同总数，无法确定剩余未完成数量，请先在项目中填写合同总数"},
        )
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    att_plans = [n for n in plans if n.get("process_name") == "附件安装"]
    done = sum(
        int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
        for n in att_plans
    )
    # 同日覆盖：本次提交将「替代」同日期那条记录，它的旧值不该计入已完成（否则报满后想改小会被误拒）
    same_date = [n for n in att_plans if str(n.get("plan_date") or "")[:10] == complete_date]
    if same_date:
        done -= sum(
            int(actuals.get(n["id"], {}).get("actual_qty", 0) or 0)
            for n in same_date
        )
    remaining = max(0, _total - done)

    if complete_qty > remaining:
        raise HTTPException(
            status_code=400,
            detail={"code": "QTY_EXCEED_REMAINING",
                    "message": f"完成套数不能超过剩余未完成 {remaining} 套"},
        )

    node_plan_id = db.upsert_manual_complete(pid, complete_qty, complete_date, mgr)
    return {
        "message": f"✅ 已手动完成 {complete_qty} 套",
        "node_plan_id": node_plan_id,
        "manager": mgr,
        "completed_sets": done + complete_qty,
        "remaining_sets": remaining - complete_qty,
    }


@router.put("/{pid}")
def update_project(pid: int, payload: ProjectUpdateRequest, user: dict = Depends(require_admin)):
    """编辑项目信息（仅更新提交的字段；空项目名/非法整数返回 400）。（仅 admin，归属兜底）"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    data = {k: v for k, v in payload.model_dump().items() if v is not None}
    if "project_name" in data and not str(data["project_name"]).strip():
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    for f in ("last_month_output", "monthly_plan"):
        if f in data and data[f] is not None:
            try:
                data[f] = int(data[f])
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail=f"字段 {f} 必须为整数")
            if data[f] < 0:
                raise HTTPException(status_code=400, detail=f"字段 {f} 不能为负数")

    if data:
        db.update_project(pid, data)
    # 废弃 processes 表工序重排与 risk_level 写入：风险等级由 node_plans+node_actuals 实时计算

    return db.get_project_by_id(pid)


@router.delete("/{pid}")
def delete_project(pid: int, user: dict = Depends(require_admin)):
    """删除项目（含工序/异常/里程碑等关联数据，行为与原版一致）。（仅 admin，归属兜底）"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)
    db.delete_project(pid)
    return {"message": f"✅ 项目「{project['project_name']}」已删除", "id": pid}


@router.get("/{pid}/managers")
def list_project_managers(pid: int, user: dict = Depends(get_current_user)):
    """项目的负责人清单（供「多负责人管理」弹窗 / 详情筛选器使用）。行级隔离：非本大区项目返回 404。

    返回：{project_id, delivery_person, managers: [{manager, monthly_plan, plan_rows, has_imported}]}
    """
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)
    return {
        "project_id": pid,
        "delivery_person": project.get("delivery_person") or "",
        "project_monthly_plan": int(project.get("monthly_plan") or 0),
        "managers": db.list_project_managers(pid),
    }


class ManagerPlanRequest(BaseModel):
    """设置某负责人对本项目的本月计划数。"""
    monthly_plan: int


@router.put("/{pid}/managers/{manager}/monthly-plan")
def set_manager_monthly_plan(pid: int, manager: str, payload: ManagerPlanRequest,
                             user: dict = Depends(require_admin)):
    """写入/更新「某负责人 对 某项目」申报的本月计划数（方案P：独立申报，不校验求和）。（仅 admin）"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)
    mgr = (manager or "").strip()
    if not mgr:
        raise HTTPException(status_code=400, detail="负责人姓名不能为空")
    val = int(payload.monthly_plan or 0)
    if val < 0:
        raise HTTPException(status_code=400, detail="本月计划数不能为负")
    db.upsert_manager_monthly_plan(pid, mgr, val)
    return {"message": f"✅ 已设置负责人「{mgr}」本月计划数为 {val}", "manager": mgr, "monthly_plan": val}


@router.get("/{pid}/node-plans")
def get_node_plans_overview(pid: int, manager: Optional[str] = None,
                            user: dict = Depends(get_current_user)):
    """节点计划总览（指标 / 工序卡片 / 时间轴 / 可见工序）。行级隔离：非本大区项目返回 404。

    多负责人（v6.0）：
      - manager 为空   → 汇总视图：全部负责人数据，月计划用 projects.monthly_plan 判定；
      - manager='张三' → 单人视图：仅该负责人名下行，月计划用其申报值判定。
    """
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    mgr = manager.strip() if manager and manager.strip() else None
    plans = db.get_node_plans(pid, mgr)
    # actuals 按 node_plan_id 索引：plans 已按负责人过滤，多余 actual 项不会被引用，无需再过滤
    actuals = db.get_node_actuals(pid)

    if mgr:
        # 单人视图：用该负责人自己申报的本月计划数
        monthly_plan = int(db.get_manager_monthly_plan_map(pid).get(mgr, 0))
    else:
        # 汇总视图：用项目整体本月计划数
        monthly_plan = int(project.get("monthly_plan") or 0)

    result = build_overview(pid, plans, actuals, monthly_plan=monthly_plan)
    result["manager"] = mgr                          # 当前口径（null=汇总）
    result["managers"] = db.list_project_managers(pid)  # 供前端渲染筛选器
    return result


@router.get("/{pid}/nodes/{process_name}")
def get_process_nodes(pid: int, process_name: str, manager: Optional[str] = None,
                      user: dict = Depends(get_current_user)):
    """某工序节点列表（四分组 + 富化行）。行级隔离：非本大区项目返回 404。

    多负责人（v6.0）：带 manager 时只看该负责人名下的该工序节点（单独查看 / 单独提报）。
    """
    project = db.get_project_by_id(pid)
    require_project_access(project, user)
    mgr = manager.strip() if manager and manager.strip() else None
    plans = db.get_node_plans(pid, mgr)
    actuals = db.get_node_actuals(pid)
    return build_process_detail(process_name, plans, actuals)


@router.get("/{pid}/alerts")
def get_alerts(pid: int, user: dict = Depends(get_current_user)):
    """节点预警列表（逾期未完成 / 部分完成 / 进行中 重点节点）。行级隔离：非本大区项目返回 404。"""
    project = db.get_project_by_id(pid)
    require_project_access(project, user)
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    from ..services.node_service import enrich_rows
    rows = enrich_rows(plans, actuals)
    from ..core.config import INDEPENDENT_PROCESS_NAMES
    # 独立工序（累计完成/累计发运）不参与预警：无日期语义，仅作为参考指标
    focus = [
        r for r in rows
        if r["status"] in ("overdue", "warning", "in_progress")
        and r["process_name"] not in INDEPENDENT_PROCESS_NAMES
    ]
    focus.sort(key=lambda r: {"overdue": 0, "warning": 1, "in_progress": 2}[r["status"]])

    # 携带节点异常提报（按 node_id 分组，供预警「管理」按钮展示）
    exceptions = db.get_node_exceptions_by_project(pid)
    exc_map = {}
    for e in exceptions:
        exc_map.setdefault(e["node_id"], []).append(e)

    items = []
    for r in focus:
        item = {**r}
        item["exceptions"] = exc_map.get(r["id"], [])
        item["has_exception"] = len(item["exceptions"]) > 0
        items.append(item)

    return {"items": items, "total": len(items)}


@router.get("/{pid}/milestone-backward")
def milestone_backward(pid: int, deadline: str = None, user: dict = Depends(get_current_user)):
    """里程碑倒排：给定交付截止日，返回倒排计划与偏差分析。行级隔离：非本大区项目返回 404。"""
    if not deadline:
        raise HTTPException(status_code=400, detail="缺少 deadline 参数")
    try:
        dl = date.fromisoformat(deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="deadline 格式应为 YYYY-MM-DD")
    project = db.get_project_by_id(pid)
    require_project_access(project, user)
    from ..services import milestone as milestone_svc
    return milestone_svc.build_milestone_backward(pid, dl)


class MilestoneBackwardRequest(BaseModel):
    """里程碑倒排请求体：交付截止日 + 可选的自定义工序工期。"""
    delivery_deadline: str
    custom_durations: Optional[dict[str, int]] = None


@router.post("/{pid}/milestone-backward")
def milestone_backward_with_durations(pid: int, req: MilestoneBackwardRequest,
                                      user: dict = Depends(get_current_user)):
    """里程碑倒排（支持按工序自定义工期）：delivery_deadline + custom_durations。行级隔离。"""
    try:
        dl = date.fromisoformat(req.delivery_deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="delivery_deadline 格式应为 YYYY-MM-DD")
    project = db.get_project_by_id(pid)
    require_project_access(project, user)
    if req.custom_durations:
        for name, days in req.custom_durations.items():
            if not isinstance(days, int) or days < 1 or days > 365:
                raise HTTPException(status_code=400, detail=f"工序 {name} 工期必须是 1~365 的整数")
    from ..services import milestone as milestone_svc
    return milestone_svc.build_milestone_backward(pid, dl, req.custom_durations)
