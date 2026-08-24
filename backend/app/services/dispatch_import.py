# -*- coding: utf-8 -*-
"""月度调度令导入服务：解析 + 逐行建项目 + 自动开通大区账号 + 写日志。

与排产导入服务 services/schedule_import.py 区分：本服务面向「调度令建项目」，
复用的解析器是 utils/excel_parser.py（REQUIRED_FIELDS 必填映射校验）。

T05 导入联动：逐行 upsert 项目后，自动为本批 Excel 中出现的大区负责人
开通/更新 users 表账号（role=big_area，初始密码 DEFAULT_BIG_AREA_PWD；
已存在账号保留原密码哈希，不重置密码）。
"""
from typing import Optional

from ..core import db


def parse_and_import(tmp_path: str, file_name: str) -> dict:
    """解析调度令 Excel 并导入。

    Args:
        tmp_path: 上传文件落盘的临时路径
        file_name: 原始文件名（用于写导入日志）

    Returns:
        dict: {success, skipped, errors, message, accounts_ready}
        accounts_ready: 本次自动开通/更新的大区账号数（去重后计数）。

    Raises:
        HTTPException 400: 表头读取失败 / 必填字段映射缺失
    """
    from fastapi import HTTPException
    from .excel_parser import (
        read_excel_headers,
        auto_detect_mapping,
        parse_schedule_excel,
        REQUIRED_FIELDS,
        FIELD_LABELS,
    )
    from ..core.security import hash_password
    from .auth_service import DEFAULT_BIG_AREA_PWD

    # 1) 读取表头
    try:
        headers = read_excel_headers(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取 Excel 失败：{e}")

    # 2) 自动映射表头 → 系统字段
    mapping = auto_detect_mapping(headers)

    # 3) 校验必填字段（REQUIRED_FIELDS）必须全部映射上，否则禁用导入
    mapped_fields = set(mapping.values())
    missing_required = [f for f in REQUIRED_FIELDS if f not in mapped_fields]
    if missing_required:
        labels = "、".join(FIELD_LABELS.get(f, f) for f in missing_required)
        raise HTTPException(status_code=400, detail=f"缺少必填字段映射：{labels}")

    # 4) 解析（标准化行 + 行级错误；失败行被跳过）
    rows, parse_errors = parse_schedule_excel(tmp_path, mapping)

    # 5) 逐行建项目（upsert）→ 新建项目即建项目记录（废弃 processes 初始化与风险写入）
    for row in rows:
        pid, is_new = db.upsert_project(row)

    # 6) 导入联动（T05）：为本批出现的大区负责人自动开通/更新账号
    #    upsert_user 语义：已存在 → 更新 big_area_name/status='active'，保留原密码哈希；
    #    不存在 → 新建（初始密码 DEFAULT_BIG_AREA_PWD，role=big_area）。
    accounts_ready = 0
    big_area_names = {
        str(r.get("big_area_person", "")).strip()
        for r in rows
        if r.get("big_area_person")
    }
    for name in sorted(big_area_names):
        if not name:
            continue
        db.upsert_user(
            username=name,
            password_hash=hash_password(DEFAULT_BIG_AREA_PWD),
            role="big_area",
            big_area_name=name,
            status="active",
        )
        accounts_ready += 1

    # 7) 写导入日志（总条数 = 成功 + 跳过）
    db.insert_import_log(
        file_name,
        len(rows) + len(parse_errors),
        len(rows),
        len(parse_errors),
        "\n".join(parse_errors[:50]),
    )

    return {
        "success": len(rows),
        "skipped": len(parse_errors),
        "errors": parse_errors[:20],
        "message": f"导入完成：成功{len(rows)}条，跳过{len(parse_errors)}条，开通大区账号{accounts_ready}个",
        "accounts_ready": accounts_ready,
    }
