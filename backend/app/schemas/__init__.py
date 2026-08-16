# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""
from typing import Optional
from pydantic import BaseModel, Field


# ---------- 节点保存 ----------

class NodeValue(BaseModel):
    node_id: int
    qty: int = Field(ge=0)


class SaveNodeProgressRequest(BaseModel):
    """按分组保存节点实际进度（分组独立，互不覆盖）。

    group: today | overdue | future | done
    values: [{node_id, qty}, ...]
    """
    group: str
    values: list[NodeValue]


# ---------- Excel 导入 ----------

class ImportResult(BaseModel):
    success: int
    warnings: list[str]
    message: str


# ---------- 项目编辑 ----------

class ProjectUpdateRequest(BaseModel):
    """项目信息更新（仅提交需要修改的字段，其余保持原值）。"""
    project_name: Optional[str] = None
    factory_name: Optional[str] = None
    last_month_output: Optional[int] = None
    monthly_plan: Optional[int] = None
    delivery_person: Optional[str] = None
    plan_start_date: Optional[str] = None
    plan_end_date: Optional[str] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    remarks: Optional[str] = None
