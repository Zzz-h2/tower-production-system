# -*- coding: utf-8 -*-
"""Excel 排产导入服务：1:1 复用 utils/schedule_import.parse_schedule_excel。"""
from typing import Optional


def parse_schedule_excel(file_path: str) -> tuple[list[dict], list[str]]:
    """解析排产 Excel → (plans, warnings)。

    plans: [{process_name, plan_date, plan_qty, process_order}, ...]（按 (process_name, plan_date) 聚合）
    """
    from utils.schedule_import import parse_schedule_excel as _fn
    return _fn(file_path)


def parse_upload(file_bytes: bytes, filename: str) -> tuple[list[dict], list[str]]:
    """接收上传文件字节流 → 临时落盘 → 解析。"""
    import tempfile
    import os
    from fastapi import HTTPException
    suffix = os.path.splitext(filename or "")[1] or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        plans, warnings = parse_schedule_excel(tmp_path)
        if not plans:
            raise HTTPException(status_code=400, detail="未解析到任何工序节点计划，请检查 Excel 格式。")
        return plans, warnings
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
