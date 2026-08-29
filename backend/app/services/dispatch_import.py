# -*- coding: utf-8 -*-
"""月度调度令导入服务：解析 + 逐行建项目 + 自动开通大区账号 + 写日志。

与排产导入服务 services/schedule_import.py 区分：本服务面向「调度令建项目」，
复用的解析器是 utils/excel_parser.py（REQUIRED_FIELDS 必填映射校验）。

T05 导入联动：逐行 upsert 项目后，自动为本批 Excel 中出现的大区负责人
开通/更新 users 表账号（role=big_area，初始密码 DEFAULT_BIG_AREA_PWD；
已存在账号保留原密码哈希，不重置密码）。
"""
import datetime as dt
import math
from typing import Optional

import pandas as pd

from ..core import db

# 预览时每列展示的样例值条数
SAMPLE_ROWS = 5


def preview_dispatch(tmp_path: str) -> dict:
    """预览调度令 Excel：只解析不写库。

    Returns:
        dict: {
            headers: 清洗后的表头名列表,
            samples: {表头名: [前N条有效数据行的取值]},
            suggested_mapping: {表头名: 系统字段名} 自动识别建议,
            system_fields: [{field, label, required}, ...]
        }

    Raises:
        HTTPException 400: 表头读取失败
    """
    from fastapi import HTTPException
    from .excel_parser import (
        _read_business_excel,
        read_excel_headers,
        auto_detect_mapping,
        ALL_SYSTEM_FIELDS,
        REQUIRED_FIELDS,
        FIELD_LABELS,
    )

    try:
        headers = read_excel_headers(tmp_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"读取 Excel 失败：{e}")

    # 同一个双策略读取（与 parse_schedule_excel 同源），用于取样例值
    df, _skiprows_used = _read_business_excel(tmp_path)

    suggested_mapping = auto_detect_mapping(headers)

    # 项目列用于行过滤（复用 parse_schedule_excel 的过滤口径）
    project_col = None
    for excel_col, field in suggested_mapping.items():
        if field == "project_name":
            project_col = excel_col
            break

    row_indexes = _valid_data_row_indexes(df, project_col, SAMPLE_ROWS)

    samples = {col: _column_samples(df, col, row_indexes) for col in headers}

    system_fields = [
        {
            "field": f,
            "label": FIELD_LABELS.get(f, f),
            "required": f in REQUIRED_FIELDS,
        }
        for f in ALL_SYSTEM_FIELDS
    ]

    return {
        "headers": headers,
        "samples": samples,
        "suggested_mapping": suggested_mapping,
        "system_fields": system_fields,
    }


def _valid_data_row_indexes(df, project_col: Optional[str], limit: int) -> list:
    """筛出「有效数据行」的行索引，口径与 parse_schedule_excel 逐行解析一致。

    过滤条件：
    1. 序号列存在时为有效数字（排除二级表头行、空行）
    2. 项目列非空（project_col 为 None 时跳过该条件）
    3. 非合计/总计/汇总等汇总行
    """
    has_seq = "序号" in df.columns
    summary_keywords = ("合计", "总计", "小计", "汇总", "平均", "备注", "说明")

    indexes = []
    for idx, row in df.iterrows():
        if has_seq:
            seq_val = row.get("序号")
            if pd.isna(seq_val):
                continue
            try:
                int(float(seq_val))
            except (ValueError, TypeError):
                continue

        if project_col and project_col in df.columns:
            raw = row.get(project_col)
            if pd.isna(raw):
                continue
            text = str(raw).strip()
            if not text or any(kw in text for kw in summary_keywords):
                continue

        indexes.append(idx)
        if len(indexes) >= limit:
            break

    return indexes


def _column_samples(df, col: str, row_indexes: list) -> list:
    """取某列在指定行上的样例值，转成 JSON 可序列化原生类型。"""
    if col not in df.columns:
        return []

    series = df[col]
    if isinstance(series, pd.DataFrame):  # 重名列 → 取第一列
        series = series.iloc[:, 0]

    values = []
    for idx in row_indexes:
        try:
            raw = series.loc[idx]
        except (KeyError, IndexError):
            continue
        value = _to_jsonable(raw)
        if value is None or value == "":
            continue
        values.append(value)
    return values


def _to_jsonable(value):
    """pandas/numpy 取值 → JSON 可序列化原生类型（不返回 NaN/Timestamp 对象）。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, dt.time):
        return value.strftime("%H:%M:%S")

    item = getattr(value, "item", None)  # numpy 标量 → python 原生
    if callable(item):
        try:
            value = value.item()
        except (ValueError, TypeError, AttributeError):
            pass

    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return int(value) if value.is_integer() else value
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _sanitize_mapping(field_mapping: dict, headers: Optional[list] = None) -> dict:
    """消毒前端传来的映射，避免脏数据静默写错库。

    规则：
    1. key 必须是非空字符串，且在真实表头中存在（headers 传入时校验）
    2. value 必须属于 ALL_SYSTEM_FIELDS
    3. 同一系统字段被多列选中时，保留最先出现的那一列（保证结果确定）

    key 校验很关键：parse_schedule_excel 内部用 {field: excel_col} 反向映射，
    若混入不存在的列名，会覆盖掉正确列 → 该字段整列变 None → 全批数据被跳过。
    """
    from .excel_parser import ALL_SYSTEM_FIELDS

    if not isinstance(field_mapping, dict):
        return {}

    header_set = {str(h).strip() for h in headers} if headers else None

    cleaned = {}
    used_fields = set()
    for excel_col, field in field_mapping.items():
        if not isinstance(excel_col, str):
            continue
        excel_col = excel_col.strip()
        if not excel_col:
            continue
        if field not in ALL_SYSTEM_FIELDS:
            continue
        if header_set is not None and excel_col not in header_set:
            continue
        if field in used_fields:
            continue
        cleaned[excel_col] = field
        used_fields.add(field)
    return cleaned


def parse_and_import(tmp_path: str, file_name: str, field_mapping: Optional[dict] = None) -> dict:
    """解析调度令 Excel 并导入。

    Args:
        tmp_path: 上传文件落盘的临时路径
        file_name: 原始文件名（用于写导入日志）
        field_mapping: 前端确认后的字段映射 {Excel列名: 系统字段名}；
                       传入时直接使用（跳过自动识别 auto_detect_mapping），
                       传 None 走自动识别；传入的表头读取只用于映射消毒

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

    if field_mapping is not None:
        # 2') 使用用户在前端确认的映射，跳过自动识别（auto_detect_mapping）。
        #     表头仍要读一次，仅用于映射消毒（剔除不存在的列名），不参与映射推导。
        try:
            headers = read_excel_headers(tmp_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"读取 Excel 失败：{e}")
        mapping = _sanitize_mapping(field_mapping, headers)
    else:
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
        # 独立工序节点计划（累计完成总数/累计发运总数）：plan_qty=合同数量，重新导入幂等
        db.sync_independent_plans(pid, row.get("contract_count"))

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
