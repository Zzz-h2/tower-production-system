# -*- coding: utf-8 -*-
"""节点异常提报 Pydantic 模型。"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from ..core.timeutil import business_today


def _check_planned_close(value: Optional[date]) -> Optional[date]:
    """校验「计划关闭日」不得早于今天（业务时区）。

    PRD 口径（2026-11）：「计划关闭日」是异常**到期失效**的唯一依据，
    提报时必须给出一个未来（含今天）的日期，否则提报即失效、暂停立刻不成立。
    存量异常（历史 NULL）不强制补，但**一旦提交了值**同样不得早于今天。

    Args:
        value: 计划关闭日（None 表示未提交/不修改）

    Returns:
        Optional[date]: 原值（校验通过）

    Raises:
        ValueError: 早于业务今天
    """
    if value is None:
        return None
    if value < business_today():
        raise ValueError("计划关闭日期不能早于今天")
    return value


class NodeExceptionCreate(BaseModel):
    """异常提报请求体（node_id/project_id 从 URL 路径获取，不在 body 中）。"""
    responsibility_category: str = Field(..., description="责任分类")
    reason_detail: str = Field(..., description="异常原因详情")
    handler: Optional[str] = Field(None, description="处理人")
    # 🔴 2026-11：计划关闭日改为**必填**（到期失效的判定依据）
    planned_close_date: date = Field(..., description="计划关闭日期（必填，不得早于今天）")
    measures: Optional[str] = Field(None, description="处理措施")
    # 「异常精确到套」（2026-10，均可空）：不传 = 整套/不指定，判定层走历史中位数反推
    set_seq: Optional[int] = Field(
        None, description="异常指向的套号（project_process_durations.set_seq）；None=不指定")
    set_d0: Optional[date] = Field(
        None, description="该套下料计划日快照（plan_date − 该套 offset）；None=不指定")

    @field_validator("planned_close_date")
    @classmethod
    def _validate_planned_close_date(cls, value: date) -> date:
        """计划关闭日不得早于今天（必填字段，None 会先被必填校验拦下）。"""
        return _check_planned_close(value)


class NodeExceptionUpdate(BaseModel):
    """异常更新请求体（仅更新提交的字段）。

    ``planned_close_date`` 保持 Optional：历史异常（NULL = 永不到期）不强制补；
    但**提交了值**时同样拒绝早于今天（否则等于提交即失效）。
    """
    responsibility_category: Optional[str] = None
    reason_detail: Optional[str] = None
    handler: Optional[str] = None
    planned_close_date: Optional[date] = None
    measures: Optional[str] = None
    status: Optional[str] = None  # pending/processing/closed

    @field_validator("planned_close_date")
    @classmethod
    def _validate_planned_close_date(cls, value: Optional[date]) -> Optional[date]:
        """提交值（非 None）不得早于今天；None = 不修改 / 清空。"""
        return _check_planned_close(value)


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
