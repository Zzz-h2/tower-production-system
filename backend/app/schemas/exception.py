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
    # 「异常精确到套」（2026-10，均可空）：不传 = 整套/不指定，判定层走历史中位数反推
    set_seq: Optional[int] = Field(
        None, description="异常指向的套号（project_process_durations.set_seq）；None=不指定")
    set_d0: Optional[date] = Field(
        None, description="该套下料计划日快照（plan_date − 该套 offset）；None=不指定")


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
    # 「异常精确到套」（2026-10）：历史记录为 NULL（= 整套/不指定）
    set_seq: Optional[int] = None
    set_d0: Optional[date] = None
    created_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime]

    class Config:
        from_attributes = True
