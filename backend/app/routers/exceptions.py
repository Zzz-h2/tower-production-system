# -*- coding: utf-8 -*-
"""节点异常提报 API。"""
from fastapi import APIRouter, Depends, HTTPException

from ..core import db
from ..core.deps import get_current_user, require_admin, require_project_access
from ..core.timeutil import business_today
from ..schemas.exception import NodeExceptionCreate, NodeExceptionUpdate
from ..services.node_service import decorate_exception_records

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


@router.post("/projects/{project_id}/nodes/{node_id}")
def create_exception(project_id: int, node_id: int, req: NodeExceptionCreate,
                     user: dict = Depends(get_current_user)):
    """节点异常提报（校验节点归属项目后写入）。

    行级隔离：big_area 用户仅可提报本大区项目（非本区返回 404 防探测）；admin 全量。
    「异常精确到套」（2026-10）：body 可选带 ``set_seq``（指向第几套）/``set_d0``
    （该套下料计划日快照）。不传 → 两个字段写 NULL，判定层走历史的中位数反推（行为不变）。
    """
    project = db.get_project_by_id(project_id)
    require_project_access(project, user)
    node = db.get_node_plan_by_id(node_id)
    if not node or node["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="节点不存在")
    exc_id = db.create_node_exception({
        "project_id": project_id,
        "node_id": node_id,
        "process_name": node["process_name"],
        "plan_date": node["plan_date"],
        "responsibility_category": req.responsibility_category,
        "reason_detail": req.reason_detail,
        "handler": req.handler,
        "planned_close_date": req.planned_close_date,
        "measures": req.measures,
        "status": "pending",
        # 可选：异常指向的具体套（不指定 = None → 老口径）
        "set_seq": req.set_seq,
        "set_d0": req.set_d0,
    })
    return {"id": exc_id, "message": "✅ 异常提报成功"}


@router.get("/projects/{project_id}")
def list_exceptions(project_id: int, user: dict = Depends(get_current_user)):
    """项目下**全部**异常（含已关闭 / 已到期失效），并附显示状态与计数条。

    行级隔离：非本大区项目返回 404 防探测。

    2026-11 改造（异常记录页看本项目全部异常）：
      - 每条记录补 ``display_status``(active|expired|closed) / ``is_active`` / ``is_expired`` /
        ``days_to_close`` / ``days_overdue`` / ``age_days`` / ``set_label``；
      - 额外返回 ``summary = {total, active, expired, closed}`` 供计数条渲染；
      - **保留 ``items`` 键**（向后兼容：老前端直接读 res.items）。
      - 状态全部**实时派生**（不写库）：到期失效的记录库里 status 仍是 pending。
    """
    project = db.get_project_by_id(project_id)
    require_project_access(project, user)
    # 基准日：本入口取一次（禁止 SQL CURDATE / date.today()）
    today = business_today()
    return decorate_exception_records(db.get_node_exceptions_by_project(project_id), today)


@router.get("/projects/{project_id}/exceptions/closed")
def list_closed_exceptions(project_id: int, user: dict = Depends(get_current_user)):
    """列出项目下已关闭的历史异常记录（按关闭时间倒序）。行级隔离：非本大区项目返回 404。"""
    project = db.get_project_by_id(project_id)
    require_project_access(project, user)
    return {"items": db.get_closed_exceptions_by_project(project_id)}


@router.get("/{exc_id}")
def get_exception(exc_id: int, user: dict = Depends(get_current_user)):
    """单条异常详情。行级隔离：异常所属项目非本大区返回 404 防探测。"""
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    project = db.get_project_by_id(exc["project_id"])
    require_project_access(project, user)
    return exc


@router.put("/{exc_id}")
def update_exception(exc_id: int, req: NodeExceptionUpdate,
                     user: dict = Depends(get_current_user)):
    """更新异常（字段/状态；status=closed 自动写关闭时间）。行级隔离：非本大区项目返回 404。

    「编辑异常」入口（2026-11）：可改 责任分类 / 异常原因 / 处理人 / 计划关闭日 / 处理措施
    共 5 个字段（全部在 ``NodeExceptionUpdate`` 内，均可选）。
    - 只更新**请求体实际出现的字段**（``exclude_unset``），未提交字段保持原值 —— 历史异常
      ``planned_close_date`` 为 NULL 时，只改原因/措施不会被「不得早于今天」校验拦下；
    - 提交了 ``planned_close_date`` 则必须 ≥ 业务今天（schema 已验证，过去日期 422）；
    - 状态字段刻意不参与「编辑」语义（关闭仍走本接口的 status='closed'，由「关闭」按钮调用）。
    """
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    project = db.get_project_by_id(exc["project_id"])
    require_project_access(project, user)
    db.update_node_exception(exc_id, req.model_dump(exclude_unset=True))
    return {"message": "✅ 异常更新成功"}


@router.delete("/{exc_id}")
def delete_exception(exc_id: int, user: dict = Depends(require_admin)):
    """删除单条异常记录（**仅 admin**）。2026-11 新增，供「编辑异常」弹窗内的删除入口。

    权限与隔离（🔴 与「幂等」正交，互不影响）：
      - ``require_admin`` 是**路由依赖层**（``Depends(require_admin)``），FastAPI 在进入本函数体
        之前就完成校验 → 非 admin 一律 **403**，**与本函数返回什么、记录是否存在完全无关**
        （不依赖删除结果，删不掉也照样 403）；
      - 仍做项目归属校验（``require_project_access``）：admin 全量通过，其它角色 403/404，
        保证即使未来放开角色也不会越区删除。

    删除范围（🔴 只删一行）：
      - 只删 ``node_exceptions`` 该行；**不动** ``node_actual_progress`` / ``process_node_plans``；
      - 该异常的「暂停 / 关闭后重算计划日」影响随记录消失**同时解除**（判定逻辑不改，
        下次读取自然回到无异常口径）。

    幂等语义（2026-11 用户拍板：DELETE 按 HTTP 语义幂等，不因"已不存在"报错）：
      - ``deleted=1`` → 本次确实删掉了这一行；
      - ``deleted=0`` → 记录已不存在（**重复删** / 连点两次 / 超时重试 / 从未存在），
        统一返回 **200** 且 ``ok=true``：资源最终状态一致，不产生副作用；
      - 前端据 ``deleted`` 区分提示（成功 / 温和提示），**不弹红色错误**。
      - 记录不存在时无法再做项目归属校验（没有 project_id 可查），此处直接返回 deleted:0 ——
        这不会构成探测风险：非 admin 在依赖层已 403，admin 本就是全量权限。

    Returns:
        dict: ``{"ok": True, "deleted": 1|0, "id": exc_id}``
    """
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        # 幂等：已不存在（从未存在 / 重复删）→ 200 + deleted:0，最终状态即「不存在」
        return {"ok": True, "deleted": 0, "id": exc_id}
    project = db.get_project_by_id(exc["project_id"])
    require_project_access(project, user)
    # db 层已带 @_invalidates_dashboard：删除后首页 KPI 缓存立即失效（异常项目数随之下降）
    deleted = db.delete_exception_by_id(exc_id)
    # 并发下另一请求可能已先删掉该行 → deleted=0，同样按幂等返回 200
    return {"ok": True, "deleted": int(deleted or 0), "id": exc_id}



@router.get("/nodes/{node_id}")
def list_exceptions_by_node(node_id: int, user: dict = Depends(get_current_user)):
    """节点下的异常（供详情弹窗展示）。行级隔离：节点所属项目非本大区返回 404 防探测。"""
    node = db.get_node_plan_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    project = db.get_project_by_id(node["project_id"])
    require_project_access(project, user)
    return {"items": db.get_node_exceptions_by_node(node_id)}
