# -*- coding: utf-8 -*-
"""节点异常提报 API。"""
from fastapi import APIRouter, HTTPException

from ..core import db
from ..schemas.exception import NodeExceptionCreate, NodeExceptionUpdate

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])


@router.post("/projects/{project_id}/nodes/{node_id}")
def create_exception(project_id: int, node_id: int, req: NodeExceptionCreate):
    """节点异常提报（校验节点归属项目后写入）。"""
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
def list_exceptions(project_id: int):
    """项目下全部异常。"""
    return {"items": db.get_node_exceptions_by_project(project_id)}


@router.get("/projects/{project_id}/exceptions/closed")
def list_closed_exceptions(project_id: int):
    """列出项目下已关闭的历史异常记录（按关闭时间倒序）。"""
    return {"items": db.get_closed_exceptions_by_project(project_id)}


@router.get("/{exc_id}")
def get_exception(exc_id: int):
    """单条异常详情。"""
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    return exc


@router.put("/{exc_id}")
def update_exception(exc_id: int, req: NodeExceptionUpdate):
    """更新异常（字段/状态；status=closed 自动写关闭时间）。"""
    exc = db.get_node_exception_by_id(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="异常记录不存在")
    db.update_node_exception(exc_id, req.model_dump(exclude_unset=True))
    return {"message": "✅ 异常更新成功"}


@router.get("/nodes/{node_id}")
def list_exceptions_by_node(node_id: int):
    """节点下的异常（供详情弹窗展示）。"""
    return {"items": db.get_node_exceptions_by_node(node_id)}
