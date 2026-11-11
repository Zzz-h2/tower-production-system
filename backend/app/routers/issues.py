# -*- coding: utf-8 -*-
"""问题管控看板接口（v7.10，2026-11）。

数据源：**复用 node_exceptions**（工序里提报的异常），不新建业务表。
本次只新增一个字段 ``severity``（high/medium/low，默认 medium）。

口径：
  - 月份：按 ``created_at`` 提报月过滤（与「项目详情 → 异常记录」同口径，方案 A 严格按月）；
  - 状态：pending（计划中）/ processing（执行中）/ closed（已完成）；
  - 超期：``status <> 'closed'`` 且 ``planned_close_date`` 非空且 < 今天；
  - 来源部门：用 ``projects.big_area_person``（大区）代替（筒仓业务无部门概念）；
  - 排序：超期未关闭优先 → severity 高>中>低 → 解决时间升序。

权限：与异常列表一致 —— admin 全量，大区账号只见本大区（``get_scope_big_area``）。
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core import db
from ..core.deps import get_current_user, get_scope_big_area, require_admin
from ..core.timeutil import business_today

router = APIRouter(prefix="/api", tags=["issues"])

# 状态 / 严重等级的展示文案（与前端标签一致，后端回给前端直接用，避免两处硬编码）
STATUS_LABELS = {"pending": "计划中", "processing": "执行中", "closed": "已完成"}
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低"}
SEVERITY_ORDER = ("high", "medium", "low")
STATUS_ORDER = ("pending", "processing", "closed")


def _month_key(month: Optional[str]) -> Optional[str]:
    """规范化月份参数：空 → None（全部）；否则 'YYYY-MM'，格式非法 → 400。"""
    if not month or not str(month).strip():
        return None
    m = str(month).strip()[:7]
    try:
        y, mm = map(int, m.split("-"))
        assert 2000 <= y <= 2100 and 1 <= mm <= 12
    except Exception:
        raise HTTPException(status_code=400, detail="month 格式应为 YYYY-MM")
    return f"{y:04d}-{mm:02d}"


def _date_text(value) -> Optional[str]:
    """把 date/datetime 统一成 'YYYY-MM-DD'（None 保持 None）。"""
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _decorate(rows: list[dict], today: date) -> list[dict]:
    """补展示字段：状态/等级文案、是否超期、超期天数。"""
    items: list[dict] = []
    for r in rows:
        status = str(r.get("status") or "pending")
        pcd = _date_text(r.get("planned_close_date"))
        is_overdue = False
        overdue_days = 0
        if status != "closed" and pcd:
            try:
                delta = (today - date.fromisoformat(pcd)).days
            except ValueError:
                delta = 0
            if delta > 0:
                is_overdue = True
                overdue_days = delta
        created = r.get("created_at")
        items.append({
            "id": int(r["id"]),
            "project_id": int(r.get("project_id") or 0),
            "project_name": r.get("project_name") or "",
            "area": r.get("area") or "",
            "process_name": r.get("process_name") or "",
            "reason_detail": r.get("reason_detail") or "",
            "severity": str(r.get("severity") or "medium"),
            "severity_label": SEVERITY_LABELS.get(str(r.get("severity") or "medium"), "中"),
            "handler": r.get("handler") or "",
            "planned_close_date": pcd,
            "status": status,
            "status_label": STATUS_LABELS.get(status, status),
            "created_at": (created.strftime("%Y-%m-%d %H:%M")
                           if hasattr(created, "strftime") else (str(created)[:16] if created else None)),
            "is_overdue": is_overdue,
            "overdue_days": overdue_days,
            # 关闭时间（编辑弹窗/核对「关闭是否留痕」用；未关闭为 None）
            "closed_at": (r.get("closed_at").strftime("%Y-%m-%d %H:%M")
                          if hasattr(r.get("closed_at"), "strftime")
                          else (str(r.get("closed_at"))[:16] if r.get("closed_at") else None)),
            "set_seq": r.get("set_seq"),
        })
    return items


@router.get("/issues/board")
def issue_board(month: Optional[str] = None, status: Optional[str] = None,
                severity: Optional[str] = None, project_id: Optional[int] = None,
                overdue_only: bool = False, keyword: Optional[str] = None,
                user: dict = Depends(get_current_user)):
    """问题管控看板：KPI + 三个维度分布 + 明细列表（**一条 SQL** 取数）。

    Args:
        month: 'YYYY-MM'（按提报月，None=全部）
        status: pending / processing / closed
        severity: high / medium / low
        project_id: 单项目
        overdue_only: 只看超期未关闭
        keyword: 模糊匹配（项目名 / 问题描述 / 工序 / 责任人）

    Returns:
        dict: ``{kpis, by_status, by_severity, by_area, items}``
            kpis = {total, closed, open, overdue, close_rate, target_rate}
            target_rate 为关闭率目标（当前固定 100，仅用于展示「当前 X / 目标 Y」）
    """
    m = _month_key(month)
    st = (str(status).strip() if status else "") or None
    if st and st not in STATUS_LABELS:
        raise HTTPException(status_code=400, detail="status 只能是 pending / processing / closed")
    sv = (str(severity).strip() if severity else "") or None
    if sv and sv not in SEVERITY_LABELS:
        raise HTTPException(status_code=400, detail="severity 只能是 high / medium / low")

    today = business_today()
    rows = db.get_issue_board_rows(
        month=m, status=st, severity=sv, project_id=project_id,
        keyword=keyword, big_area_person=get_scope_big_area(user),
        today=today.isoformat(),
    )
    items = _decorate(rows, today)
    if overdue_only:
        items = [it for it in items if it["is_overdue"]]

    total = len(items)
    closed = sum(1 for it in items if it["status"] == "closed")
    overdue = sum(1 for it in items if it["is_overdue"])
    close_rate = round(closed / total * 100, 1) if total else 0.0

    # ---- 三个维度分布（全部基于同一份过滤后的 items，保证与列表/ KPI 同源）----
    by_status = [
        {"key": k, "label": STATUS_LABELS[k],
         "count": sum(1 for it in items if it["status"] == k)}
        for k in STATUS_ORDER
    ]
    by_severity = [
        {"key": k, "label": SEVERITY_LABELS[k],
         "count": sum(1 for it in items if it["severity"] == k)}
        for k in SEVERITY_ORDER
    ]
    area_counts: dict[str, int] = {}
    for it in items:
        area = it["area"] or "未指定"
        area_counts[area] = area_counts.get(area, 0) + 1
    by_area = [{"label": k, "count": v}
               for k, v in sorted(area_counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    return {
        "kpis": {
            "total": total,
            "closed": closed,
            "open": total - closed,
            "overdue": overdue,
            "close_rate": close_rate,
            # 关闭率目标（当前业务口径为 100%，产品若调整只改这里）
            "target_rate": 100,
        },
        "by_status": by_status,
        "by_severity": by_severity,
        "by_area": by_area,
        "items": items,
        "month": m,
        "today": today.isoformat(),
    }


class IssueUpdateRequest(BaseModel):
    """问题看板编辑请求体：所有字段可选，只更新传入的。"""
    severity: Optional[str] = Field(None, description="high / medium / low")
    status: Optional[str] = Field(None, description="pending / processing / closed")
    handler: Optional[str] = Field(None, max_length=64, description="责任人")
    planned_close_date: Optional[str] = Field(None, description="解决时间 YYYY-MM-DD")
    reason_detail: Optional[str] = Field(None, description="问题描述")


@router.patch("/issues/{exception_id}")
def update_issue(exception_id: int, payload: IssueUpdateRequest,
                 user: dict = Depends(get_current_user)):
    """编辑一条问题（2026-11-11：**admin 全量 + 大区账号仅限本大区**）。

    权限（🔴 服务端强制，不依赖前端是否显示按钮）：
      - ``admin`` → 放行；
      - ``big_area`` → 该异常所属项目的 ``projects.big_area_person`` 必须等于
        自己的 ``big_area_name``（``get_scope_big_area``；``'ALL'`` 全区哨兵返回 None → 放行全部）；
        不一致 / 项目大区为空 → **403** ``{"code":"OUT_OF_SCOPE"}``；
      - 其它角色 → 403。

    校验顺序：① 资源存在(404) → ② 权限范围(403) → ③ 字段白名单/格式(400) → ④ 落库。

    - 只更新传入字段；``severity``/``status`` 白名单校验；``planned_close_date`` 需 YYYY-MM-DD；
    - ``status='closed'`` 且原先 ``closed_at`` 为空 → 由 ``db.update_node_exception`` 自动写 closed_at（与异常关闭语义一致）；
    - 写操作会失效首页 KPI 缓存（装饰器 ``_invalidates_dashboard`` 已挂在 db 层）。

    Returns:
        dict: 更新后的整行（与看板 items 同构，前端可直接替换）
    """
    # ---- ① 资源存在 ----
    row = db.get_node_exception_by_id(exception_id)
    if not row:
        raise HTTPException(status_code=404, detail="问题不存在")

    # ---- ② 权限范围（越权不能靠前端：直接调 PATCH 也必须被拒）----
    role = str(user.get("role") or "")
    if role != "admin":
        if role != "big_area":
            raise HTTPException(
                status_code=403,
                detail={"code": "FORBIDDEN", "message": "无权修改该问题"},
            )
        scope = get_scope_big_area(user)            # 'ALL' 哨兵 → None（全区大区可编辑全部）
        if scope is not None:
            project = db.get_project_by_id(int(row.get("project_id") or 0)) or {}
            area = str(project.get("big_area_person") or "").strip()
            if not area or area != str(scope).strip():
                raise HTTPException(
                    status_code=403,
                    detail={"code": "OUT_OF_SCOPE", "message": "只能修改本大区的问题"},
                )

    # ---- ③ 字段校验 ----
    fields: dict = {}
    if payload.severity is not None:
        sv = str(payload.severity).strip()
        if sv not in SEVERITY_LABELS:
            raise HTTPException(status_code=400, detail="severity 只能是 high / medium / low")
        fields["severity"] = sv
    if payload.status is not None:
        st = str(payload.status).strip()
        if st not in STATUS_LABELS:
            raise HTTPException(status_code=400, detail="status 只能是 pending / processing / closed")
        fields["status"] = st
    if payload.handler is not None:
        fields["handler"] = str(payload.handler).strip() or None
    if payload.reason_detail is not None:
        fields["reason_detail"] = str(payload.reason_detail)
    if payload.planned_close_date is not None:
        pcd = str(payload.planned_close_date).strip()
        if pcd:
            try:
                date.fromisoformat(pcd)
            except ValueError:
                raise HTTPException(status_code=400, detail="解决时间格式应为 YYYY-MM-DD")
            fields["planned_close_date"] = pcd
        else:
            fields["planned_close_date"] = None

    if not fields:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")

    ok = db.update_node_exception(exception_id, fields)
    if not ok:
        raise HTTPException(status_code=404, detail="问题不存在或未更新")

    fresh = db.get_node_exception_by_id(exception_id) or row
    project = db.get_project_by_id(int(fresh.get("project_id") or 0)) or {}
    decorated = _decorate([{
        **fresh,
        "project_name": project.get("project_name"),
        "area": project.get("big_area_person"),
    }], business_today())
    return decorated[0]
