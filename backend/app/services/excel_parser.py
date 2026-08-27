"""
excel_parser.py — Excel调度令解析与表头映射模块

支持功能：
- 读取 .xlsx 文件
- 表头自动识别与手动映射
- 数据校验（必填字段检查）
- 返回标准化项目数据列表

Author: Senior Developer
Date: 2026-08-03
"""

import os
from datetime import datetime
from typing import Optional

import pandas as pd


# 系统必选字段
REQUIRED_FIELDS = [
    "project_name",      # 项目名称
    "factory_name",      # 钢塔厂家
    "monthly_plan",      # 本月计划出品数量
    "delivery_person",   # 交付负责人
]

# 系统可选字段
OPTIONAL_FIELDS = [
    "last_month_output",  # 截止上月月底出品数量
    "plan_start_date",    # 计划开工日期
    "plan_end_date",      # 计划交付日期
    "machine_type",       # 机型（v3.1 新增，Excel 有机型列则自动匹配）
    "big_area_person",    # 大区负责人（选填）
]

# 所有系统字段
ALL_SYSTEM_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

# 字段中文名映射
FIELD_LABELS = {
    "project_name": "项目名称",
    "factory_name": "钢塔厂家",
    "last_month_output": "截止上月月底出品",
    "monthly_plan": "本月计划出品",
    "delivery_person": "交付负责人",
    "plan_start_date": "计划开工日期",
    "plan_end_date": "计划交付日期",
    "machine_type": "机型",
    "big_area_person": "大区负责人",
}


def _clean_col_name(col) -> str:
    """清洗单个列名：去换行符、制表符、多余空格"""
    s = str(col).replace('\n', '').replace('\r', '').replace('\t', '')
    s = ' '.join(s.split()).strip()
    return s


def _read_business_excel(file_path: str) -> tuple[pd.DataFrame, int]:
    """
    读取业务调度令 Excel，双策略容错定位表头行。

    策略1: header=0（表头在首行，适配实际文件格式）
    策略2: skiprows=2, header=0（跳过标题行+空行，适配用户描述的模板格式）

    自动选择能找到「项目」列的策略。

    Returns:
        (DataFrame, skiprows_used) — skiprows_used 为实际跳过的行数
    """
    xl = pd.ExcelFile(file_path)

    # 定位包含「出品」或「塔筒」的 sheet
    target_sheet = None
    for s in xl.sheet_names:
        if '出品' in s or '塔筒' in s:
            target_sheet = s
            break
    if target_sheet is None:
        target_sheet = xl.sheet_names[0]

    # 策略1: header=0（无跳行）
    df1 = pd.read_excel(file_path, sheet_name=target_sheet, header=0)
    df1.columns = [_clean_col_name(c) for c in df1.columns]
    if '项目' in df1.columns:
        return df1, 0

    # 策略2: skiprows=2（跳过标题+空行）
    try:
        df2 = pd.read_excel(file_path, sheet_name=target_sheet, skiprows=2, header=0)
        df2.columns = [_clean_col_name(c) for c in df2.columns]
        if '项目' in df2.columns:
            return df2, 2
    except Exception:
        pass

    # 两种策略都未找到 → 返回策略1的结果（让上层报错）
    return df1, 0


def read_excel_headers(file_path: str) -> list[str]:
    """
    读取 Excel 文件表头（双策略容错）。

    自动适配两种格式：
    - 格式A: 表头在首行（实际文件）
    - 格式B: 标题行+空行+表头在第3行（用户描述的模板）

    Returns:
        list[str]: 清洗后的有效表头列表
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    try:
        df, _ = _read_business_excel(file_path)

        cleaned = []
        for col in df.columns:
            col_str = _clean_col_name(col)
            if not col_str or col_str.lower().startswith('unnamed'):
                continue
            cleaned.append(col_str)

        if not cleaned:
            raise ValueError("未能识别到有效表头列，请使用标准月度调度令模板")

        return cleaned

    except ImportError:
        raise ValueError("缺少 openpyxl 依赖，请执行: pip install openpyxl")
    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"文件格式异常，请使用标准月度调度令模板: {e}")


def auto_detect_mapping(excel_headers: list[str]) -> dict[str, str]:
    """
    自动检测 Excel 表头与系统字段的映射关系。

    采用关键词评分匹配：
    - 精确匹配（= 系统字段名或中文名）→ 最高优先级
    - 关键词组合匹配 → 按命中数评分，得分高者胜
    - 每个 Excel 列只匹配一个系统字段，每个系统字段只被匹配一次

    Args:
        excel_headers: Excel 列名列表

    Returns:
        dict[str, str]: {excel_column: system_field} 映射
    """
    # 系统字段 ←→ 关键词组（按优先级排列，前面的子列表优先级更高）
    FIELD_KEYWORDS = {
        "project_name": [
            ["项目名称"], ["项目", "名称"], ["项目名"], ["工程名称"], ["风场", "名称"],
            ["名称"], ["项目"], ["project"],
        ],
        "factory_name": [
            ["钢塔厂家"], ["厂家"], ["钢塔"], ["加工厂"], ["生产厂家"], ["制造厂"],
            ["供应商"], ["factory"], ["manufacturer"],
        ],
        "monthly_plan": [
            ["本月计划"], ["本月", "计划"], ["月度计划"], ["本月", "出品"],
            ["本月", "目标"], ["计划", "出品"], ["计划", "数量"], ["月计划"],
        ],
        "delivery_person": [
            ["交付负责人"], ["负责人"], ["交付", "负责人"], ["责任人"], ["交付人"],
            ["经理"], ["owner"], ["manager"], ["pic"],
        ],
        "last_month_output": [
            ["截止上月月底出品"], ["截止上月"], ["上月", "出品"], ["上月", "累计"],
            ["累计", "出品"], ["截止"], ["上月"],
        ],
        "plan_start_date": [
            ["计划开工日期"], ["开工日期"], ["开始日期"], ["开工"], ["开始时间"],
            ["start"],
        ],
        "plan_end_date": [
            ["计划交付日期"], ["交付日期"], ["完成日期"], ["结束日期"], ["截止日期"],
            ["end"], ["deadline"],
        ],
        "machine_type": [
            ["机型"], ["型号"], ["塔型"], ["塔筒", "型号"], ["机型", "规格"],
            ["model"], ["type"],
        ],
        "big_area_person": [
            ["大区负责人"], ["大区"], ["区域负责人"], ["片区负责人"],
            ["大区", "负责人"], ["区域", "负责人"],
        ],
    }

    mapping = {}

    # 业务专属精确别名（优先级最高，先于通用关键词）
    EXACT_ALIASES = {
        "项目": "project_name",
        "项目名称": "project_name", "项目名": "project_name", "名称": "project_name",
        "钢塔厂家": "factory_name", "厂家": "factory_name", "加工厂": "factory_name",
        # 业务实际列名：X月计划、截止X月底出品
        "本月计划出品": "monthly_plan", "本月计划": "monthly_plan",
        "交付负责人": "delivery_person", "负责人": "delivery_person",
        "截止上月月底出品": "last_month_output",
        "计划开工日期": "plan_start_date", "开工日期": "plan_start_date",
        "计划交付日期": "plan_end_date", "交付日期": "plan_end_date",
        # v3.1: 机型
        "机型": "machine_type", "型号": "machine_type", "塔型": "machine_type",
        # 大区负责人（业务专属别名）
        "大区负责人": "big_area_person", "大区": "big_area_person",
        "区域负责人": "big_area_person", "片区负责人": "big_area_person",
    }

    # 动态别名：匹配「X月计划」「截止X月底出品」等月度变化列名
    import re
    headers = [str(h).strip() for h in excel_headers]
    for header in headers:
        if header in EXACT_ALIASES:
            continue
        # 只匹配「数字月 + 计划」（如 8月计划），不匹配「调度令计划」「塔筒出品计划」
        if re.match(r'^\d+月计划$', header):
            EXACT_ALIASES[header] = "monthly_plan"
        if re.match(r'^截止\d+月底出品$', header):
            EXACT_ALIASES[header] = "last_month_output"

    # 第一步：精确别名匹配，每个字段只匹配一次（去重）
    matched_fields = set()
    for header in headers:
        if header in EXACT_ALIASES:
            field = EXACT_ALIASES[header]
            if field not in matched_fields:
                mapping[header] = field
                matched_fields.add(field)

    # 第二步：关键词评分匹配（未被精确匹配的列）
    matched_fields = set(mapping.values())
    for header in headers:
        if header in mapping:
            continue  # 已有精确匹配

        best_field = None
        best_score = 0

        for field, keyword_groups in FIELD_KEYWORDS.items():
            if field in matched_fields:
                continue  # 已被其他列匹配

            for group in keyword_groups:
                hits = sum(1 for kw in group if kw in header)
                if hits == len(group) and hits > 0:  # 全部关键词命中
                    score = hits * 10 + len(group)  # 得分：命中数×10 + 关键词组长度
                    if score > best_score:
                        best_score = score
                        best_field = field
                    break  # 该组已完全匹配，不再检查同字段的下一组

        if best_field:
            mapping[header] = best_field
            matched_fields.add(best_field)

    return mapping


def parse_schedule_excel(
    file_path: str,
    field_mapping: Optional[dict[str, str]] = None
) -> tuple[list[dict], list[str]]:
    """
    解析调度令 Excel 文件，返回标准化项目数据列表。

    处理流程：
    1. 读取 Excel 全部数据行
    2. 按 field_mapping 映射列名到系统字段
    3. 校验必填字段
    4. 去除空行
    5. 处理数据格式异常

    Args:
        file_path: Excel 文件路径
        field_mapping: 字段映射字典，格式 {Excel列名: 系统字段名}
                       若为 None，则调用 auto_detect_mapping 自动识别

    Returns:
        tuple[list[dict], list[str]]:
            - list[dict]: 标准化项目数据列表
            - list[str]: 错误提示列表

    Example:
        >>> mapping = {"项目名称": "project_name", "加工厂": "factory_name"}
        >>> data, errors = parse_schedule_excel("调度令.xlsx", mapping)
        >>> len(data)
        15
    """
    errors = []
    standardized_data = []

    # === 读取文件：双策略容错（header=0 或 skiprows=2） ===
    try:
        df, skiprows_used = _read_business_excel(file_path)
    except Exception as e:
        return [], [f"文件格式异常，请使用标准月度调度令模板: {e}"]

    if df.empty:
        return [], ["Excel 文件为空"]

    # 自动检测映射
    if field_mapping is None:
        field_mapping = auto_detect_mapping(list(df.columns))

    if not field_mapping:
        return [], ["未能识别任何字段映射，请手动配置"]

    # 检查必填字段是否都已映射
    mapped_fields = set(field_mapping.values())
    missing_required = set(REQUIRED_FIELDS) - mapped_fields
    if missing_required:
        missing_labels = [FIELD_LABELS.get(f, f) for f in missing_required]
        errors.append(f"缺少必填字段映射: {', '.join(missing_labels)}")
        return [], errors

    # 构建反向映射：系统字段 → Excel列名
    reverse_mapping = {v: k for k, v in field_mapping.items()}

    # 获取项目名称列对应的 Excel 列名
    project_col = reverse_mapping.get("project_name", None)

    # === 逐行解析：只保留有效项目数据行 ===
    for idx, row in df.iterrows():
        row_num = idx + skiprows_used + 2  # 真实 Excel 行号（skiprows + header + 1-based）

        # ---- 过滤非数据行 ----
        # 条件1: 序号列为有效数字（排除二级表头行、空行）
        seq_val = row.get('序号') if '序号' in df.columns else None
        if pd.isna(seq_val):
            continue
        try:
            int(float(seq_val))
        except (ValueError, TypeError):
            continue  # 序号非数字 → 子表头/空行，跳过

        # 条件2: 项目列不为空
        project_raw = row.get(project_col) if project_col and project_col in df.columns else None
        if pd.isna(project_raw):
            continue
        project_str = str(project_raw).strip()
        if not project_str:
            continue

        # 条件3: 排除汇总行
        SUMMARY_KEYWORDS = ["合计", "总计", "小计", "汇总", "平均", "备注", "说明"]
        if any(kw in project_str for kw in SUMMARY_KEYWORDS):
            continue

        # ---- 提取有效字段 ----
        project_data = {}
        row_errors = []

        for system_field in ALL_SYSTEM_FIELDS:
            excel_col = reverse_mapping.get(system_field)
            if excel_col and excel_col in df.columns:
                value = row[excel_col]
                if pd.isna(value):
                    value = None
                project_data[system_field] = value
            else:
                project_data[system_field] = None

        # 校验必填字段
        for field in REQUIRED_FIELDS:
            value = project_data.get(field)
            if value is None or (isinstance(value, str) and value.strip() == ''):
                row_errors.append(f"第{row_num}行: 缺少{FIELD_LABELS.get(field, field)}")

        # 校验数据类型
        try:
            if project_data.get("monthly_plan") is not None:
                project_data["monthly_plan"] = int(float(project_data["monthly_plan"]))
        except (ValueError, TypeError):
            row_errors.append(f"第{row_num}行: 本月计划出品数量格式错误，应为整数")

        try:
            if project_data.get("last_month_output") is not None:
                project_data["last_month_output"] = int(float(project_data["last_month_output"]))
            else:
                project_data["last_month_output"] = 0
        except (ValueError, TypeError):
            project_data["last_month_output"] = 0

        # 日期字段：用 parse_date 兼容多种格式（str/datetime/Timestamp/数字日期）
        from .workday_calendar import parse_date as _parse_date
        for date_field in ["plan_start_date", "plan_end_date"]:
            val = project_data.get(date_field)
            if val is None:
                continue
            # pandas NaN 检查
            try:
                if pd.isna(val):
                    project_data[date_field] = None
                    continue
            except (TypeError, ValueError):
                pass
            parsed = _parse_date(val)
            if parsed:
                project_data[date_field] = parsed.strftime('%Y-%m-%d')
            else:
                project_data[date_field] = None

        if row_errors:
            errors.extend(row_errors)
            continue

        # 确保字符串字段不为 None
        project_data["project_name"] = str(project_data.get("project_name", "")).strip()
        project_data["factory_name"] = str(project_data.get("factory_name", "")).strip()
        project_data["delivery_person"] = str(project_data.get("delivery_person", "")).strip()
        project_data["big_area_person"] = str(project_data.get("big_area_person", "") or "").strip()

        standardized_data.append(project_data)

    return standardized_data, errors


def generate_sample_excel(output_path: str) -> str:
    """
    生成一份示例调度令 Excel 模板，供用户参考。

    Args:
        output_path: 输出文件路径

    Returns:
        str: 生成的文件路径
    """
    sample_data = {
        "项目名称": [
            "XX风电场T01项目", "XX风电场T02项目", "YY风电场T01项目",
            "ZZ风电场T01项目", "AA风电场T01项目",
        ],
        "钢塔厂家": [
            "XX钢结构有限公司", "XX钢结构有限公司", "YY重工制造有限公司",
            "ZZ机械制造有限公司", "AA新能源装备有限公司",
        ],
        "截止上月月底出品": [4, 2, 6, 0, 3],
        "本月计划出品": [8, 6, 4, 8, 6],
        "交付负责人": ["张三", "张三", "李四", "王五", "赵六"],
        "大区负责人": ["华北大区", "华北大区", "西北大区", "西南大区", "华东大区"],
        "计划开工日期": ["2026-08-01", "2026-08-05", "2026-07-15", "2026-08-10", "2026-07-20"],
        "计划交付日期": ["2026-09-05", "2026-09-10", "2026-08-20", "2026-09-15", "2026-08-25"],
    }

    df = pd.DataFrame(sample_data)
    df.to_excel(output_path, index=False)
    return output_path


if __name__ == '__main__':
    # 最小演示：生成示例文件并解析（自测用）
    sample_path = os.path.join(os.path.dirname(__file__), "..", "示例调度令.xlsx")
    generate_sample_excel(sample_path)
    headers = read_excel_headers(sample_path)
    data, errors = parse_schedule_excel(sample_path, auto_detect_mapping(headers))
    print(f"已生成示例文件并解析：{len(data)} 条记录，{len(errors)} 个错误")
