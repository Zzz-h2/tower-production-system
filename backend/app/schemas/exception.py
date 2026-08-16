# -*- coding: utf-8 -*-
"""节点异常提报 Pydantic 模型。"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class NodeExceptionCreate(BaseModel):
    """异常提报请求体（node_id/project_id 从 URL 路径获取，不在 body 中）。"""
    responsibility_category: str = Field(..., description="责任分类")
    reason_detail: str = Field(..., description="异常原因详情")
    handler: Optional[str] = Field(None, description="处理人")
    planned_close_date: Optional[date] = Field(None, description="计划关闭日期")
    measures: Optional[str] = Field(None, description="处理措施")


class NodeExceptionUpdate(BaseModel):
    responsibility_category: Optional[str] = None
    reason_detail: Optional[str] = None
    handler: Optional[str] = None
    planned_close_date: Optional[date] = None
    measures: Optional[str] = None
    status: Optional[str] = None  # pending/processing/closed


class NodeExceptionOut(BaseModel):
    id: int
    project_id: int
    node_id: int
    process_name: str
    plan_date: date
    responsibility_category: str
    reason_detail: str
    handler: Optional[str]
    planned_close_date: Optional[date]
    measures: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True
