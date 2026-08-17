"""
utils/schedule_import.py — 排产矩阵 Excel 解析（工序节点计划导入，v4.0）

解析「排产计划 Excel」：多套塔筒 × 9 道排产工序 × 计划完成日期矩阵。
排产工序顺序由 config.SCHEDULE_PROCESS_NAMES 定义（独立于 processes 表 12 道制造工序）。

Excel 预期格式（第一个 sheet，header=None 逐行读取）：
    ┌────────┬──────────┬──────────┬──────┬──────────┐
    │ 套序号  │ 钢板到货  │ 法兰到货  │ ...  │ 具备验收  │
    ├────────┼──────────┼──────────┼──────┼──────────┤
    │ 第1套  │ 2026-08-05│ 2026-08-06│ ...  │ 2026-09-10│
    │ 第2套  │ 2026-08-06│ 2026-08-07│ ...  │ (空)      │
    └────────┴──────────┴──────────┴──────┴──────────┘

解析规则：
- 自动跳过标题/说明行（首行或前几行含「编号/工序/第」等字样，且在工序名行之前）。
- 定位「工序名行」：该行含 钢板到货/法兰到货 等 9 个排产工序名之一。
- 数据行：首列（或含「套」的列）为套序号（如「第1套」）；
  后续 9 列按 SCHEDULE_PROCESS_NAMES 顺序对应各工序计划完成日期。
- 单元格非空且可被 pd.to_datetime 解析 → 记为 (process_name, plan_date)；空/非日期跳过并记错误。
- 输出聚合：按 (process_name, plan_date) 分组，plan_qty = 套数计数；
  process_order = SCHEDULE_PROCESS_NAMES.index(process_name) + 1。

可命令行调用：python utils/schedule_import.py <xlsx路径>   （打印解析结果，便于 QA 测试）

Author: Engineer
Date: 2026-08-12
"""

import os
import re
import sys
from collections import Counter
from typing import Optional

# 兼容两种运行方式：
# 1) 作为包内模块被页面导入（from backend.app.services.schedule_import import ...）
# 2) 命令行直接运行（python backend/app/services/schedule_import.py <xlsx>）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))

import pandas as pd  # noqa: E402

from ..core.config import SCHEDULE_PROCESS_NAMES  # noqa: E402


# ============================================================
# 内部辅助
# ============================================================

def _cell_str(value) -> str:
    """统一把单元格值转为去除空白后的字符串；NaN/None → ''。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _is_set_no(value) -> bool:
    """判断单元格是否为套序号（如 第1套 / 1套 / 1）。"""
    s = _cell_str(value)
    if not s:
        return False
    # 汇总/备注行不当作数据行
    if any(kw in s for kw in ("合计", "总计", "小计", "汇总", "平均", "备注", "说明")):
        return False
    if "套" in s:
        return bool(re.search(r"\d", s))  # 含「套」且带数字 → 套序号
    return bool(re.fullmatch(r"第?\s*\d+", s))  # 纯数字/第N 序号


def _find_header_row(rows: list[list]) -> Optional[int]:
    """定位工序名行：该行包含至少一个 SCHEDULE_PROCESS_NAMES 工序名。"""
    for r_idx, row in enumerate(rows):
        joined = "".join(_cell_str(v) for v in row)
        if any(pn in joined for pn in SCHEDULE_PROCESS_NAMES):
            return r_idx
    return None


def _find_set_col(rows: list[list], header_row_idx: int) -> int:
    """定位套序号列：优先找第一个值含「套」的列，否则用首列。"""
    ncols = max(len(row) for row in rows) if rows else 0
    for c_idx in range(ncols):
        for r_idx in range(header_row_idx + 1, len(rows)):
            row = rows[r_idx]
            if c_idx < len(row) and "套" in _cell_str(row[c_idx]):
                return c_idx
    return 0


# ============================================================
# 主函数
# ============================================================

def parse_schedule_excel(file_path: str) -> tuple[list[dict], list[str]]:
    """
    解析排产矩阵 Excel，返回 (plans, errors)。

    Args:
        file_path: .xlsx 文件路径

    Returns:
        plans: list[dict]，每项
            {process_name, process_order, plan_date('YYYY-MM-DD'), plan_qty}
            已按 process_order, plan_date 排序。
        errors: list[str]，无法解析的行号/工序名提示。
    """
    errors: list[str] = []

    # ---- 1. 读取第一个 sheet，header=None 保留原始行 ----
    try:
        raw = pd.read_excel(file_path, sheet_name=0, header=None)
    except Exception as e:  # noqa: BLE001
        return [], [f"文件读取失败: {e}"]

    if raw is None or raw.empty:
        return [], ["Excel 文件为空或第一个 sheet 无内容"]

    rows: list[list] = []
    for _, row in raw.iterrows():
        rows.append([None if pd.isna(v) else v for v in row.tolist()])

    # ---- 2. 定位工序名行（该行之前的标题行自动跳过） ----
    header_row_idx = _find_header_row(rows)
    if header_row_idx is None:
        return [], [
            "未找到工序名行：需包含排产工序名（钢板到货/法兰到货/下料/卷制/"
            "组对/黑塔/防腐/附件安装/具备验收）"
        ]

    header_vals = rows[header_row_idx]

    # ---- 3. 确定每个工序名对应的列索引 ----
    # 优先按表头名称匹配；匹配不到时按 SCHEDULE_PROCESS_NAMES 顺序取 套序号列 后第 N 列
    set_col = _find_set_col(rows, header_row_idx)
    proc_cols: list[int] = []
    for pn in SCHEDULE_PROCESS_NAMES:
        col = None
        for c_idx, v in enumerate(header_vals):
            if _cell_str(v) == pn:
                col = c_idx
                break
        if col is None:
            col = set_col + 1 + SCHEDULE_PROCESS_NAMES.index(pn)
        proc_cols.append(col)

    # ---- 4. 逐数据行解析（记录每个 工序×日期 出现一次 = 一套） ----
    node_items: list[tuple[str, str]] = []
    for r_idx in range(header_row_idx + 1, len(rows)):
        row = rows[r_idx]
        set_val = row[set_col] if set_col < len(row) else None

        if not _is_set_no(set_val):
            # 跳过空行 / 汇总行 / 备注行（但保留可定位到的套序号行）
            continue

        excel_row_num = r_idx + 1  # Excel 行号（1-based）
        for i, pn in enumerate(SCHEDULE_PROCESS_NAMES):
            col = proc_cols[i]
            val = row[col] if col < len(row) else None
            cell = _cell_str(val)
            if not cell:
                continue  # 空单元格 → 该套该工序无计划日期，跳过
            try:
                parsed = pd.to_datetime(val, errors="raise")
            except (ValueError, TypeError) as e:  # noqa: PERF203
                errors.append(
                    f"第{excel_row_num}行 工序「{pn}」日期无法解析: {cell}（{e}）"
                )
                continue
            if pd.isna(parsed):
                continue
            node_items.append((pn, parsed.strftime('%Y-%m-%d')))

    if not node_items:
        return [], ["未解析到任何有效节点计划：请检查套序号列与工序日期列格式"]

    # ---- 5. 聚合：按 (process_name, plan_date) 分组，plan_qty = 套数计数 ----
    counter = Counter(node_items)
    plans = []
    for (pn, plan_date), qty in sorted(
        counter.items(),
        key=lambda kv: (SCHEDULE_PROCESS_NAMES.index(kv[0][0]), kv[0][1]),
    ):
        plans.append({
            "process_name": pn,
            "process_order": SCHEDULE_PROCESS_NAMES.index(pn) + 1,
            "plan_date": plan_date,
            "plan_qty": qty,
        })

    return plans, errors


# ============================================================
# 命令行入口（QA 测试用）
# ============================================================

def _print_result(plans: list[dict], errors: list[str]) -> None:
    print(f"解析完成: {len(plans)} 个节点计划, {len(errors)} 个错误")
    for p in plans:
        print(
            f"  - {p['process_name']}(工序{p['process_order']}) | "
            f"{p['plan_date']} | 应完成 {p['plan_qty']} 套"
        )
    if errors:
        print("\n错误提示:")
        for e in errors:
            print(f"  ! {e}")


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
