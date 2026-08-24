# -*- coding: utf-8 -*-
"""月度调度令导入 API（批量新建项目）。

与既有排产导入 ``POST /api/projects/{pid}/import-schedule`` 是**不同接口**：
- 本接口：解析调度令 Excel → 新建/更新项目（含初始化工序、风险）。
- 排产导入：在已有项目下导入工序节点计划。
"""
import os
import tempfile

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..core import db
from ..core.deps import require_admin
from ..services.dispatch_import import parse_and_import

router = APIRouter(prefix="/api/projects", tags=["dispatch-import"])

# 允许的文件后缀
ALLOWED_EXT = (".xlsx", ".xls")


@router.post("/import-dispatch")
async def import_dispatch(file: UploadFile = File(...), user: dict = Depends(require_admin)):
    """上传月度调度令 Excel → 解析 → 批量建项目。（仅 admin）"""
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_EXT):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    # 临时落盘（parse_schedule_excel 走文件路径解析）
    content = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = parse_and_import(tmp_path, filename)
        return result
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
