"""模拟业务真实 Excel 格式测试"""
import sys; sys.path.insert(0, '.')
import pandas as pd
import os

# === 生成业务实际格式的 Excel ===
# 第1行：大标题（合并单元格风格）
# 第2行：真实表头
# 第3行起：数据行
# 末尾：合计行、空行

title_row = ["8月份塔筒出品指标", "", "", "", ""]
header_row = ["项目", "钢塔厂家", "8月计划", "交付负责人", "截止7月底出品"]
data_rows = [
    ["XX风电场T01", "XX钢构", 8, "张三", 4],
    ["YY风电场T02", "YY重工", 6, "李四", 2],
    ["ZZ风电场T03", "ZZ制造", 4, "王五", 0],
    ["AA风电场T04", "AA装备", 8, "赵六", 3],
    ["BB风电场T05", "BB钢构", 6, "钱七", 1],
    ["合计", "", "", "", ""],  # 汇总行
    ["", "", "", "", ""],       # 空行
]

df_out = pd.DataFrame([title_row, header_row] + data_rows)
df_out.to_excel("test_business.xlsx", index=False, header=False)

# === 测试读取 ===
from utils.excel_parser import read_excel_headers, auto_detect_mapping, parse_schedule_excel

headers = read_excel_headers("test_business.xlsx")
print(f"Headers ({len(headers)}): {headers}")
assert len(headers) >= 5, f"表头列数不足: {len(headers)}"

mapping = auto_detect_mapping(headers)
print(f"Auto mapping: {mapping}")
assert mapping.get("项目") == "project_name", f"项目映射失败: {mapping}"
assert mapping.get("8月计划") == "monthly_plan", f"8月计划映射失败: {mapping}"
assert mapping.get("截止7月底出品") == "last_month_output", f"截止7月底出品映射失败: {mapping}"

data, errors = parse_schedule_excel("test_business.xlsx", mapping)
print(f"Parsed: {len(data)} rows, {len(errors)} errors")
assert len(data) == 5, f"应解析5条数据, 实际{len(data)}条"
assert len(errors) == 0, f"应有0条错误, 实际{len(errors)}"

for d in data:
    print(f"  - {d['project_name']} | {d['factory_name']} | "
          f"计划{d['monthly_plan']}段 | 上月{d['last_month_output']}段 | {d['delivery_person']}")

print("\nOK 业务格式全链路通过")

os.remove("test_business.xlsx")
