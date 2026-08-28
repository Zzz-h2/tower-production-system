# -*- coding: utf-8 -*-
"""月度调度令导入 API（批量新建项目）。

与既有排产导入 ``POST /api/projects/{pid}/import-schedule`` 是**不同接口**：
- 本接口：解析调度令 Excel → 新建/更新项目（含初始化工序、风险）。
- 排产导入：在已有项目下导入工序节点计划。

两步导入：先 ``preview-dispatch`` 拿表头+样例+建议映射，前端确认/修正映射后
再 ``import-dispatch``（可选 form 字段 mapping，JSON 字符串）。
"""
import json
import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..core import db
from ..core.deps import require_admin
from ..services.dispatch_import import parse_and_import
from ..services.dispatch_import import preview_dispatch as build_preview

router = APIRouter(prefix="/api/projects", tags=["dispatch-import"])

# 允许的文件后缀
ALLOWED_EXT = (".xlsx", ".xls")


def _save_to_temp(filename: str, content: bytes) -> str:
    """把上传内容落盘为临时文件，返回路径。"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        tmp.write(content)
        return tmp.name


def _cleanup(tmp_path: str):
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


@router.post("/preview-dispatch")
async def preview_dispatch(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    """上传月度调度令 Excel → 返回表头/样例值/建议映射/系统字段，只预览不写库。（仅 admin）"""
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    tmp_path = _save_to_temp(filename, await file.read())
    try:
        return build_preview(tmp_path)
    finally:
        _cleanup(tmp_path)


@router.post("/import-dispatch")
async def import_dispatch(
    file: UploadFile = File(...),
    mapping: Optional[str] = Form(None),
    user: dict = Depends(require_admin),
):
    """上传月度调度令 Excel → 按（可选）字段映射解析 → 批量建项目。（仅 admin）

    mapping: JSON 字符串，格式 {"Excel列名": "系统字段名"}；不传则走自动识别。
    """
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    field_mapping = None
    if mapping:
        try:
            field_mapping = json.loads(mapping)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="字段映射格式错误")
        if not isinstance(field_mapping, dict):
            raise HTTPException(status_code=400, detail="字段映射格式错误")

    # 临时落盘（parse_schedule_excel 走文件路径解析）
    tmp_path = _save_to_temp(filename, await file.read())

    try:
        result = parse_and_import(tmp_path, filename, field_mapping)
        return result
    finally:
        _cleanup(tmp_path)
