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
- 定位「工序名行」：该行含 钢板到货/法兰到货 等 11 个排产工序名之一。
- 数据行：首列（或含「套」的列）为套序号（如「第1套」）；
  后续 11 列（含新增环缝 / 门框焊接）按 SCHEDULE_PROCESS_NAMES 顺序对应各工序计划完成日期。
- 单元格非空且可被 pd.to_datetime 解析 → 记为 (process_name, plan_date)；空跳过。
- 【v4.1 已完成文本识别】单元格非空、无法解析为日期，但文本**包含**完成关键词
  （见 COMPLETION_KEYWORDS，匹配忽略前后/内部空白与全半角差异）→ 不报错，
  改为累加该工序的「已完成套数」，最终产出一条 plan_date=导入当天、
  plan_qty=actual_qty=完成套数的计划行，表示该工序这几套已完成。
  排除词（COMPLETION_EXCLUDE_KEYWORDS，如「未完成」「待完成」）优先命中时**不**判定为完成，
  宁可漏收也不误判——误判会导致完成量虚高、出品排名失真。
- 其它无法识别的非时间文本（如「待定」「N/A」「2026年8月」）→ 保持原状态跳过并记录提示。
- 输出聚合：按 (process_name, plan_date) 分组，plan_qty = 套数计数；
  process_order = SCHEDULE_PROCESS_NAMES.index(process_name) + 1。

可命令行调用：python utils/schedule_import.py <xlsx路径>   （打印解析结果，便于 QA 测试）

Author: Engineer
Date: 2026-08-12
Update: 2026-08-20 v4.1 新增「已完成」文本识别（见 COMPLETION_KEYWORDS）
"""

import os
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

# 兼容两种运行方式：
# 1) 作为包内模块被页面导入（from backend.app.services.schedule_import import ...）
# 2) 命令行直接运行（python backend/app/services/schedule_import.py <xlsx>）
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..'))

import pandas as pd  # noqa: E402

from ..core.config import SCHEDULE_PROCESS_NAMES  # noqa: E402


# ============================================================
# 常量：「已完成」文本识别
# ============================================================

# 表示「已完成」的文本关键词（可维护列表，后续扩展直接往这里加）。
# 匹配规则：单元格文本先经 _normalize_completion_text() 归一化（NFKC 统一全半角/兼容字符
#           → 去前后空白 → 去内部空白），归一化后若**包含**任一关键词即判定为已完成。
# 收录原则：**宁可漏收、不可误判**（误判 → 完成量虚高 → 出品排名失真），
#           因此只收录「单独出现即明确表示事情已经做完」的词，
#           不收录「结束/交付」这类既能表示完成、也能表示「计划中截止点」的裸词。
COMPLETION_KEYWORDS: list[str] = [
    "已完成", "完成",      # 用户点名必收
    "已到齐", "到齐",      # 用户点名必收
    "已完工", "完工",
    "已交付",
    "已结束",
    "已具备",
    "已到货", "已齐套",    # 用户追加：到货/齐套（已-前缀 → 「未到货」「未齐套」不会误命中）
]

# 排除词（优先级高于 COMPLETION_KEYWORDS）：命中任意一个即**不**判定为完成。
# 作用：挡住「未完成 / 待完成 / 计划完成 / 预计完成」这类**排程中态**——
#       它们都包含「完成」二字，但语义是「还没做」，误收会让完成量虚高。
COMPLETION_EXCLUDE_KEYWORDS: list[str] = [
    "未完成", "未到齐", "未完工", "未交付", "未结束", "未具备",
    "待完成", "待到齐", "待完工", "待交付",
    "计划完成", "计划完工", "计划交付",
    "预计完成", "预计完工", "预计交付",
]


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


def _normalize_completion_text(s) -> str:
    """归一化文本用于「已完成」关键词匹配。

    归一化三步：
    1. ``unicodedata.normalize('NFKC', s)``：统一全角/半角与兼容字符
       （如 ``ＣＯＭＰＬＥＴＥ``→``COMPLETE``、全角空格 U+3000 → 半角空格）；
    2. ``.strip()``：去掉首尾空白；
    3. ``re.sub(r'\\s+', '', s)``：去掉**内部**空白（含全角空格、制表符）。

    这样「已 完成」「已完成　」（全角空格）「已完成（）」都能命中同一个关键词。

    Args:
        s: 任意值（单元格原始值或关键词常量）；None/NaN → ''

    Returns:
        str: 归一化后的字符串；入参为空时返回 ''
    """
    if s is None:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s)).strip())


def _is_completion_text(cell) -> bool:
    """判断单元格文本是否表示「已完成」（忽略空白与全半角差异，包含匹配）。

    判定顺序：
    1. 归一化文本；空 → False；
    2. 命中任一 COMPLETION_EXCLUDE_KEYWORDS（未完成/待完成/计划完成…）→ False（优先，防误判）；
    3. 包含任一 COMPLETION_KEYWORDS → True。

    关键词常量本身也走同一套归一化，避免常量里混入全半角差异导致漏配。

    Args:
        cell: 单元格原始值或其字符串形式

    Returns:
        bool: 是否判定为「已完成」
    """
    text = _normalize_completion_text(cell)
    if not text:
        return False
    if any(_normalize_completion_text(kw) in text for kw in COMPLETION_EXCLUDE_KEYWORDS):
        return False
    return any(_normalize_completion_text(kw) in text for kw in COMPLETION_KEYWORDS)


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


# Excel 序列日期：以 1899-12-30 为第 0 天（兼容 Excel 1900 闰年 bug 的业界约定）。
# 合理年份区间 20000~80000 ≈ 1954-10 ~ 2119-01；区间外的数值（如 0/1/工时/数量）不当日期处理。
_EXCEL_EPOCH = datetime(1899, 12, 30)
_EXCEL_SERIAL_MIN = 20000
_EXCEL_SERIAL_MAX = 80000


def _excel_serial_to_date(val):
    """数值型单元格按 Excel 序列日期解析；不在合理区间返回 None。

    背景（缺陷根因）：日期单元格若为「常规」格式，openpyxl/pandas 读出的是原始序列数
    （如 46173 = 2026-06-08）。pd.to_datetime(46173) 会把整数当**纳秒**解析 → 1970-01-01，
    且不报错，导致全部计划静默坍缩到 epoch。数值必须先走 Excel 序列换算。
    """
    if isinstance(val, bool):
        return None
    if not isinstance(val, (int, float)):
        return None
    try:
        serial = float(val)
    except (TypeError, ValueError, OverflowError):
        return None
    if not (_EXCEL_SERIAL_MIN <= serial <= _EXCEL_SERIAL_MAX):
        return None
    return (_EXCEL_EPOCH + timedelta(days=serial)).date()


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
            由「已完成」文本识别产出的项**额外带** actual_qty（= 完成套数，与 plan_qty 相等），
            plan_date 为导入当天；正常日期解析产出的项不带 actual_qty（下游行为不变）。
        errors: list[str]，无法解析的行号/工序名提示，以及「已完成识别」信息性提示（【信息】前缀）。
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
            "组对/环缝/门框焊接/黑塔/防腐/附件安装/具备验收）"
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
    # 「已完成」文本识别：工序名 → 完成套数（无日期语义，聚合时落到「导入当天」）
    completed_counts: Counter = Counter()
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
            # 数值型单元格：Excel 序列日期（如 46173=2026-06-08），绝不能交给 pd.to_datetime
            # （整数会被当纳秒解析成 1970-01-01 且不报错）。见 _excel_serial_to_date 注释。
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                serial_date = _excel_serial_to_date(val)
                if serial_date is not None:
                    node_items.append((pn, serial_date.strftime('%Y-%m-%d')))
                    continue
                errors.append(
                    f"第{excel_row_num}行 工序「{pn}」数值 {val} 不是有效的 Excel 日期序列号"
                    f"（已保持原状态跳过，请检查单元格是否为日期格式）"
                )
                continue
            try:
                parsed = pd.to_datetime(val, errors="raise")
            except (ValueError, TypeError) as e:  # noqa: PERF203
                if _is_completion_text(cell):
                    # 非日期，但文本表示「已完成」→ 记为完成量（不记 error，不丢量）
                    completed_counts[pn] += 1
                    continue
                # 其它无法识别的非时间文本：保持原状态跳过，仅记录提示，绝不当成完成
                errors.append(
                    f"第{excel_row_num}行 工序「{pn}」日期无法解析: {cell}（{e}）"
                    f"（非日期且非完成词，已保持原状态跳过）"
                )
                continue
            if pd.isna(parsed):
                continue
            node_items.append((pn, parsed.strftime('%Y-%m-%d')))

    if not node_items and not completed_counts:
        return [], ["未解析到任何有效节点计划：请检查套序号列与工序日期列格式"]

    # ---- 5. 聚合：按 (process_name, plan_date) 分组，plan_qty = 套数计数 ----
    counter = Counter(node_items)
    plans: list[dict] = []
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

    # ---- 5b. 合并「已完成」识别结果 ----
    # 「已完成」单元格本身没有日期，plan_date 取**导入当天**（本地时区）：
    # 语义是「这几套在导入时点已经做完了」，因此完成量落在导入当天，
    # 既不会凭空造出一个未来/过去的计划日期，也能让当月/当日出品统计立刻看到这部分产出。
    completion_date = datetime.now().strftime('%Y-%m-%d')
    plan_index = {(p["process_name"], p["plan_date"]): p for p in plans}
    for pn in SCHEDULE_PROCESS_NAMES:
        qty = int(completed_counts.get(pn, 0))
        if qty <= 0:
            continue
        existing = plan_index.get((pn, completion_date))
        if existing is not None:
            # 极端情况：该工序当天恰好也有一条正常日期计划行。
            # process_node_plans 唯一键 (project_id, process_name, plan_date, manager) 不允许两行并存，
            # 故此处**叠加**而非覆盖：plan_qty += 完成套数、actual_qty += 完成套数，
            # 两侧套数互不重叠（来自 Excel 的不同行），既不丢量也不重复计数。
            existing["plan_qty"] = int(existing["plan_qty"]) + qty
            existing["actual_qty"] = int(existing.get("actual_qty") or 0) + qty
        else:
            item = {
                "process_name": pn,
                "process_order": SCHEDULE_PROCESS_NAMES.index(pn) + 1,
                "plan_date": completion_date,
                "plan_qty": qty,
                "actual_qty": qty,
            }
            plans.append(item)
            plan_index[(pn, completion_date)] = item

    plans.sort(key=lambda p: (p["process_order"], p["plan_date"]))

    # 信息性提示（不是错误，供前端/日志核对完成了多少套）
    for pn in SCHEDULE_PROCESS_NAMES:
        qty = int(completed_counts.get(pn, 0))
        if qty > 0:
            errors.append(
                f"【信息】工序「{pn}」：{qty} 套识别为「已完成」，已记为完成量"
            )

    return plans, errors


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
