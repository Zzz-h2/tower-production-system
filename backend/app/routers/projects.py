# -*- coding: utf-8 -*-
"""项目相关 API：列表（搜索/筛选/分页）、手动添加、详情、节点计划、预警。"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..core import db
from ..schemas import ProjectUpdateRequest
from ..services.node_service import build_overview, build_process_detail, enrich_rows

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ============ 手动添加项目请求体 ============
class ProjectCreate(BaseModel):
    """手动添加项目：5 必填 + 3 选填；服务端做非空/整数校验。"""
    project_name: Optional[str] = None       # 项目名称 *
    machine_type: Optional[str] = None         # 机型 *
    factory_name: Optional[str] = None         # 钢塔厂家 *
    delivery_person: Optional[str] = None      # 交付负责人 *
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
):
    """项目列表（总览页）：支持模糊搜索、负责人/状态筛选、调度令月份过滤、服务端分页。"""
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    skip = (page - 1) * page_size
    items, total = db.get_projects_filtered(keyword, person, status, skip, page_size, month)
    # 兜底字段，保证前端渲染不报错
    for p in items:
        p.setdefault("progress_pct", 0)
        p.setdefault("risk_level", "normal")
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/export")
def export_projects(month: Optional[str] = None):
    """导出指定调度令月份计划完成情况（全量，不分页）。

    口径与列表/KPI 完全一致：按 projects.created_at 年月过滤，进度为附件安装实时完成率。
    """
    items, total = db.get_projects_filtered(None, None, None, 0, 100000, month)
    result = []
    for p in items:
        result.append({
            "project_name": p.get("project_name", ""),
            "machine_type": p.get("machine_type", ""),
            "factory_name": p.get("factory_name", ""),
            "last_month_output": int(p.get("last_month_output", 0) or 0),
            "monthly_plan": int(p.get("monthly_plan", 0) or 0),
            "progress_pct": float(p.get("progress_pct", 0.0) or 0.0),
            "delivery_person": p.get("delivery_person", ""),
        })
    return {"month": month, "total": total, "items": result}


@router.post("")
def create_project(payload: ProjectCreate):
    """手动添加项目：四字段唯一键查重；新项目自动初始化工序 + 风险。"""
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
def list_persons():
    """返回所有交付负责人（去重排序，供主页面下拉框使用；与筛选结果隔离）。"""
    return {"items": db.get_all_persons()}


@router.get("/{pid}")
def get_project(pid: int):
    """项目详情（基本信息 / 进度 / 风险）。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 风险等级：基于 node_plans + node_actuals 实时判定
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    rows = enrich_rows(plans, actuals)

    today_s = str(date.today())

    # 1) 历史逾期
    has_overdue = any(r["status"] == "overdue" for r in rows)

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
def clear_node_plans(pid: int):
    """清空项目的全部节点计划（用于重置脏数据/历史测试数据）。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.insert_node_plans(pid, [])  # 传入空列表会清空该项目所有节点计划
    return {"message": "✅ 已清空该项目的节点计划"}


@router.put("/{pid}")
def update_project(pid: int, payload: ProjectUpdateRequest):
    """编辑项目信息（仅更新提交的字段；空项目名/非法整数返回 400）。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

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
def delete_project(pid: int):
    """删除项目（含工序/异常/里程碑等关联数据，行为与原版一致）。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete_project(pid)
    return {"message": f"✅ 项目「{project['project_name']}」已删除", "id": pid}


@router.get("/{pid}/node-plans")
def get_node_plans_overview(pid: int):
    """节点计划总览（指标 / 工序卡片 / 时间轴 / 可见工序）。"""
    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    return build_overview(pid, plans, actuals)


@router.get("/{pid}/nodes/{process_name}")
def get_process_nodes(pid: int, process_name: str):
    """某工序节点列表（四分组 + 富化行）。"""
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    return build_process_detail(process_name, plans, actuals)


@router.get("/{pid}/alerts")
def get_alerts(pid: int):
    """节点预警列表（逾期未完成 / 部分完成 / 进行中 重点节点）。"""
    plans = db.get_node_plans(pid)
    actuals = db.get_node_actuals(pid)
    from ..services.node_service import enrich_rows
    rows = enrich_rows(plans, actuals)
    focus = [r for r in rows if r["status"] in ("overdue", "warning", "in_progress")]
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
def milestone_backward(pid: int, deadline: str = None):
    """里程碑倒排：给定交付截止日，返回倒排计划与偏差分析。"""
    if not deadline:
        raise HTTPException(status_code=400, detail="缺少 deadline 参数")
    try:
        dl = date.fromisoformat(deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="deadline 格式应为 YYYY-MM-DD")
    if not db.get_project_by_id(pid):
        raise HTTPException(status_code=404, detail="项目不存在")
    from ..services import milestone as milestone_svc
    return milestone_svc.build_milestone_backward(pid, dl)


class MilestoneBackwardRequest(BaseModel):
    """里程碑倒排请求体：交付截止日 + 可选的自定义工序工期。"""
    delivery_deadline: str
    custom_durations: Optional[dict[str, int]] = None


@router.post("/{pid}/milestone-backward")
def milestone_backward_with_durations(pid: int, req: MilestoneBackwardRequest):
    """里程碑倒排（支持按工序自定义工期）：delivery_deadline + custom_durations。"""
    try:
        dl = date.fromisoformat(req.delivery_deadline)
    except ValueError:
        raise HTTPException(status_code=400, detail="delivery_deadline 格式应为 YYYY-MM-DD")
    if not db.get_project_by_id(pid):
        raise HTTPException(status_code=404, detail="项目不存在")
    if req.custom_durations:
        for name, days in req.custom_durations.items():
            if not isinstance(days, int) or days < 1 or days > 365:
                raise HTTPException(status_code=400, detail=f"工序 {name} 工期必须是 1~365 的整数")
    from ..services import milestone as milestone_svc
    return milestone_svc.build_milestone_backward(pid, dl, req.custom_durations)
