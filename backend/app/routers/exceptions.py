# -*- coding: utf-8 -*-
"""节点异常提报 API。"""
from fastapi import APIRouter, Depends, HTTPException

from ..core import db
from ..core.deps import get_current_user, require_project_access
from ..schemas.exception import NodeExceptionCreate, NodeExceptionUpdate

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


@router.post("/projects/{project_id}/nodes/{node_id}")
def create_exception(project_id: int, node_id: int, req: NodeExceptionCreate,
                     user: dict = Depends(get_current_user)):
    """节点异常提报（校验节点归属项目后写入）。

    行级隔离：big_area 用户仅可提报本大区项目（非本区返回 404 防探测）；admin 全量。
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
    })
    return {"id": exc_id, "message": "✅ 异常提报成功"}


@router.get("/projects/{project_id}")
def list_exceptions(project_id: int, user: dict = Depends(get_current_user)):
    """项目下全部异常。行级隔离：非本大区项目返回 404 防探测。"""
    project = db.get_project_by_id(project_id)
    require_project_access(project, user)
    return {"items": db.get_node_exceptions_by_project(project_id)}


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
    """更新异常（字段/状态；status=closed 自动写关闭时间）。行级隔离：非本大区项目返回 404。"""
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    project = db.get_project_by_id(exc["project_id"])
    require_project_access(project, user)
    db.update_node_exception(exc_id, req.model_dump(exclude_unset=True))
    return {"message": "✅ 异常更新成功"}


@router.get("/nodes/{node_id}")
def list_exceptions_by_node(node_id: int, user: dict = Depends(get_current_user)):
    """节点下的异常（供详情弹窗展示）。行级隔离：节点所属项目非本大区返回 404 防探测。"""
    node = db.get_node_plan_by_id(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    project = db.get_project_by_id(node["project_id"])
    require_project_access(project, user)
    return {"items": db.get_node_exceptions_by_node(node_id)}
