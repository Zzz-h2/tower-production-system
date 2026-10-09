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
import re
from typing import Optional

import pandas as pd

from ..core import db

# 预览时每列展示的样例值条数
SAMPLE_ROWS = 5

# 从文件名猜调度令归属月的模式（如 2026.10 / 2026-10 / 2026年10月）
# ⚠️ 必须用 [0-9] 而不是 \d：Python 的 \d 在 str 模式下匹配任意 Unicode Nd 类数字
#    （阿拉伯-印度数字 ٢٠٢٦、全角 ２０２６ 等），会让非规范月份通过校验并落库。
_MONTH_PATTERNS = (
    re.compile(r"(20[0-9]{2})\s*[.\-/年]\s*([0-9]{1,2})"),
    re.compile(r"([0-9]{4})\s*年\s*([0-9]{1,2})\s*月"),
)


def resolve_plan_month(explicit: Optional[str], file_name: str = "") -> str:
    """解析归属月（'YYYY-MM'）：显式参数 > 文件名 > 当前自然月。

    调度令导入与排产导入共用同一套解析与校验（口径一致，避免两处漂移）。

    文件名示例：``10月份塔筒调度令指标管控表-2026.10.3.xlsx`` → ``2026-10``。

    Raises:
        ValueError: explicit 非空但不是 YYYY-MM（或月份越界）
    """
    if explicit:
        # 只认 ASCII 数字（[0-9]），年份也过 int() 归一，避免 '٢٠٢٦-٠٩' / '２０２６-０９'
        # 这类 Unicode 数字被接受后原样落库 → 该项目永远匹配不上真实月过滤。
        m = re.match(r"^\s*([0-9]{4})-([0-9]{1,2})\s*$", str(explicit))
        if m and 1 <= int(m.group(2)) <= 12:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
        raise ValueError(f"归属月份格式错误：{explicit}（应为 YYYY-MM）")

    name = str(file_name or "")
    for pat in _MONTH_PATTERNS:
        m = pat.search(name)
        if m and 1 <= int(m.group(2)) <= 12:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

    # 文件名只有「10月份」这类（无年份）→ 取当前年份
    m = re.search(r"([0-9]{1,2})\s*月", name)
    if m and 1 <= int(m.group(1)) <= 12:
        return f"{dt.date.today().year}-{int(m.group(1)):02d}"

    return dt.date.today().strftime("%Y-%m")


def preview_dispatch(tmp_path: str, file_name: str = "") -> dict:
    """预览调度令 Excel：只解析不写库。

    Args:
        tmp_path: 上传文件落盘的临时路径
        file_name: 原始文件名（用于推断建议的调度令归属月）

    Returns:
        dict: {
            headers: 清洗后的表头名列表,
            samples: {表头名: [前N条有效数据行的取值]},
            suggested_mapping: {表头名: 系统字段名} 自动识别建议,
            suggested_plan_month: 由文件名推断的归属月（'YYYY-MM'）,
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
        "suggested_plan_month": resolve_plan_month(None, file_name),
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


def parse_and_import(tmp_path: str, file_name: str, field_mapping: Optional[dict] = None,
                     plan_month: Optional[str] = None) -> dict:
    """解析调度令 Excel 并导入（项目主表 upsert + 月度调度令快照 dispatch_records）。

    Args:
        tmp_path: 上传文件落盘的临时路径
        file_name: 原始文件名（用于写导入日志 + 推断归属月）
        field_mapping: 前端确认后的字段映射 {Excel列名: 系统字段名}；
                       传入时直接使用（跳过自动识别 auto_detect_mapping），
                       传 None 走自动识别；传入的表头读取只用于映射消毒
        plan_month: 调度令归属月 'YYYY-MM'；不传则按文件名推断，再退化为当前自然月

    Returns:
        dict: {success, created, updated, plan_month, skipped, errors, message, accounts_ready}
        created/updated: 本次 upsert 的新建 / 更新条数（跨月重复导入的项目计入 updated）。
        accounts_ready: 本次自动开通/更新的大区账号数（去重后计数）。

    Raises:
        HTTPException 400: 表头读取失败 / 必填字段映射缺失 / 归属月格式错误
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

    # 4') 归属月解析（显式参数 > 文件名 > 当前月）；格式非法直接 400，不静默兜底
    try:
        resolved_month = resolve_plan_month(plan_month, file_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 本次 Excel 实际映射到的系统字段：传给 upsert_project 做「覆盖保护」
    # （未映射的列不参与 UPDATE，避免跨月重复导入冲掉历史月份口径）
    mapped_fields = set(mapping.values())

    # 5) 逐行建项目（upsert）→ 新建项目即建项目记录（废弃 processes 初始化与风险写入）
    #    + 写入「项目 × 归属月」调度令快照（同一项目可同时出现在多个月份，各月计划数互不覆盖）
    created = updated = 0
    for row in rows:
        pid, is_new = db.upsert_project(row, mapped_fields=mapped_fields)
        db.upsert_dispatch_record(pid, resolved_month, row, source_file=file_name)
        if is_new:
            created += 1
        else:
            updated += 1
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
        "created": created,
        "updated": updated,
        "plan_month": resolved_month,
        "skipped": len(parse_errors),
        "errors": parse_errors[:20],
        "message": (
            f"导入完成（调度令归属 {resolved_month}）：新增 {created} 条、更新 {updated} 条"
            f"（共 {len(rows)} 条），跳过 {len(parse_errors)} 条，开通大区账号 {accounts_ready} 个"
        ),
        "accounts_ready": accounts_ready,
    }
