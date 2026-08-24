# -*- coding: utf-8 -*-
"""Excel 排产导入 API。"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..core import db
from ..core.deps import require_admin, require_project_access
from ..services.schedule_import import parse_upload

router = APIRouter(prefix="/api/projects", tags=["import"])


@router.post("/{pid}/import-schedule")
async def import_schedule(pid: int, file: UploadFile = File(...),
                          user: dict = Depends(require_admin)):
    """上传排产 Excel → 解析聚合 → 写入 process_node_plans。（仅 admin，归属兜底）"""
    if not file.filename or not (file.filename.endswith(".xlsx") or file.filename.endswith(".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx / .xls 文件")

    project = db.get_project_by_id(pid)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_access(project, user)

    content = await file.read()
    plans, warnings = parse_upload(content, file.filename)

    success = db.insert_node_plans(pid, plans)
    return {
        "message": f"✅ 导入成功：{success} 个节点计划（工序：{file.filename}）",
        "success": success,
        "warnings": warnings[:20],
    }
