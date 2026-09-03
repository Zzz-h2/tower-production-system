# -*- coding: utf-8 -*-
"""Pydantic 请求/响应模型。"""
from typing import Optional
from pydantic import BaseModel, Field


# ---------- 节点保存 ----------

class NodeValue(BaseModel):
    node_id: int
    qty: int = Field(ge=0)
    report_date: Optional[str] = None  # 新增：该行填报日期 YYYY-MM-DD；为空则回退顶层或服务端当天


class SaveNodeProgressRequest(BaseModel):
    """按分组保存节点实际进度（分组独立，互不覆盖）。

    group: today | overdue | future | done
    values: [{node_id, qty}, ...]
    """
    group: str
    values: list[NodeValue]
    report_date: Optional[str] = None  # 新增：填报日期 YYYY-MM-DD；为空则用服务端当天
    manager: Optional[str] = None      # v6.0 多负责人：本次填报归属的负责人（空=汇总/不区分）
    partial_ok: bool = False           # 一键提报部分成功模式：前序联动校验失败的节点跳过而非整批 400


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
    big_area_person: Optional[str] = None
    plan_start_date: Optional[str] = None
    plan_end_date: Optional[str] = None
    risk_level: Optional[str] = None
    status: Optional[str] = None
    remarks: Optional[str] = None


# ---------- 手动完成 ----------

class ManualCompleteRequest(BaseModel):
    """手动完成：为提前完工但无排产计划的项目补录『附件安装』产出。

    manager：归属负责人（v6.0 多负责人）。单负责人项目由路由层自动推导；
    多负责人项目（delivery_person 含 '/'）必须显式指定，否则 400。
    """
    complete_qty: int
    complete_date: str
    manager: Optional[str] = None
