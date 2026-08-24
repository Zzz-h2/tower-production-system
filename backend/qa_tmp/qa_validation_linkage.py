# -*- coding: utf-8 -*-
"""validate_today_quota 前序联动校验回归测试（覆盖 5 个场景）。

直接 import backend 真实函数验证，避免 deploy 后才发现算法回归。
场景基于用户截图：黑塔 4/15 已有实际，但门框焊接=0、环缝=0、组对=0、卷制=0，
钢板到货 4/4、下料 1/15；旧逻辑因累计 4+1=5 >= 4 而放行黑塔（bug），
新逻辑要求紧邻的前一工序「门框焊接」必须已开工才能填报黑塔。

运行：
    python backend/qa_tmp/qa_validation_linkage.py
"""
import sys
from pathlib import Path

# 找到项目根（backend/qa_tmp/qa_xxx.py 的上两级），加入 sys.path 以便 import backend.app.*
ROOT = Path(__file__).resolve().parents[2]  # backend/qa_tmp -> backend -> 项目根
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.business_logic import validate_today_quota
from backend.app.core.config import SCHEDULE_PROCESS_NAMES


# ===== 测试 fixture：模拟截图场景的节点计划 =====
plans = [
    # 钢板到货 (idx 0)
    {"id": 101, "process_name": "钢板到货", "plan_date": "2026-08-17", "plan_qty": 2},
    {"id": 102, "process_name": "钢板到货", "plan_date": "2026-08-25", "plan_qty": 2},
    # 法兰到货 (idx 1)
    {"id": 201, "process_name": "法兰到货", "plan_date": "2026-08-20", "plan_qty": 2},
    {"id": 202, "process_name": "法兰到货", "plan_date": "2026-08-28", "plan_qty": 2},
    # 下料 (idx 2)
    {"id": 301, "process_name": "下料", "plan_date": "2026-08-30", "plan_qty": 5},
    {"id": 302, "process_name": "下料", "plan_date": "2026-09-05", "plan_qty": 5},
    {"id": 303, "process_name": "下料", "plan_date": "2026-09-12", "plan_qty": 5},
    # 卷制 (idx 3)
    {"id": 401, "process_name": "卷制", "plan_date": "2026-09-02", "plan_qty": 5},
    {"id": 402, "process_name": "卷制", "plan_date": "2026-09-08", "plan_qty": 5},
    # 组对 (idx 4)
    {"id": 501, "process_name": "组对", "plan_date": "2026-09-05", "plan_qty": 5},
    {"id": 502, "process_name": "组对", "plan_date": "2026-09-11", "plan_qty": 5},
    # 环缝 (idx 5)
    {"id": 601, "process_name": "环缝", "plan_date": "2026-09-08", "plan_qty": 5},
    {"id": 602, "process_name": "环缝", "plan_date": "2026-09-14", "plan_qty": 5},
    # 门框焊接 (idx 6)
    {"id": 701, "process_name": "门框焊接", "plan_date": "2026-09-11", "plan_qty": 5},
    {"id": 702, "process_name": "门框焊接", "plan_date": "2026-09-17", "plan_qty": 5},
    # 黑塔 (idx 7)
    {"id": 801, "process_name": "黑塔", "plan_date": "2026-09-14", "plan_qty": 5},
    {"id": 802, "process_name": "黑塔", "plan_date": "2026-09-20", "plan_qty": 5},
]

# 截图复现的 actuals：钢板到货 4/4、下料 1/15、黑塔已有 4 套（老数据/越序）
actuals_screenshot = {
    101: {"actual_qty": 2},
    102: {"actual_qty": 2},
    301: {"actual_qty": 1},
    801: {"actual_qty": 4},
}


def assert_match(label, got, expected_substr):
    if expected_substr is None and got is None:
        print(f"  PASS  {label}")
        return True
    if expected_substr is None or got is None:
        print(f"  FAIL  {label}\n        got     = {got!r}\n        expect  = {expected_substr!r}")
        return False
    if expected_substr in got:
        print(f"  PASS  {label}")
        return True
    print(f"  FAIL  {label}\n        got     = {got!r}\n        expect  = contains {expected_substr!r}")
    return False


results = []

# 场景 A —— 截图复现：黑塔拟再填 4，前一工序 门框焊接=0
# 旧逻辑：累计 4+1=5 >= 4 → 放行（bug）；新逻辑：门框焊接未开始 → 拒绝
print("\n[A] 黑塔拟填报 4，截图场景（门框焊接=0）")
err = validate_today_quota(
    "黑塔", plans, actuals_screenshot,
    [{"id": 802, "plan_date": "2026-09-20"}], {802: 4},
)
results.append(assert_match("黑塔 应被「前一工序未开始 门框焊接」拒绝", err, "前一工序未开始"))
results.append(assert_match("错误信息应点名「门框焊接」", err, "门框焊接"))

# 场景 B —— 门框焊接开工后，黑塔填 3 应通过
print("\n[B] 门框焊接已开工后，黑塔填报 3")
actuals_ok = dict(actuals_screenshot)
actuals_ok[701] = {"actual_qty": 3}  # 门框焊接第一个节点开工 3
err = validate_today_quota(
    "黑塔", plans, actuals_ok,
    [{"id": 802, "plan_date": "2026-09-20"}], {802: 3},
)
results.append(assert_match("门框焊接已开工，黑塔填 3 应通过", err, None))

# 场景 C —— 累计上限仍生效（门框焊接开了 1，但黑塔拟填 100 → 累计才 4+1+3=8）
print("\n[C] 累计上限：门框焊接开了，黑塔拟填 100（累计不足）")
err = validate_today_quota(
    "黑塔", plans, actuals_ok,
    [{"id": 802, "plan_date": "2026-09-20"}], {802: 100},
)
results.append(assert_match("黑塔填 100 应被「数量校验未通过」拒绝", err, "数量校验未通过"))

# 场景 D —— 未知工序名「纵缝」不再静默跳过
print("\n[D] 未知工序名「纵缝」")
err = validate_today_quota(
    "纵缝", plans, actuals_screenshot,
    [{"id": 999, "plan_date": "2026-09-20"}], {999: 1},
)
results.append(assert_match("纵缝 应被「配置缺失」拒绝（不再静默跳过）", err, "配置缺失"))
results.append(assert_match("错误信息应点名 SCHEDULE_PROCESS_NAMES", err, "SCHEDULE_PROCESS_NAMES"))

# 场景 E —— 第一道工序「钢板到货」不限制联动
print("\n[E] 第一道工序 钢板到货")
err = validate_today_quota(
    "钢板到货", plans, {},
    [{"id": 102, "plan_date": "2026-08-25"}], {102: 99},
)
results.append(assert_match("钢板到货 不限制联动", err, None))

# 汇总
passed = sum(results)
total = len(results)
print(f"\n{'=' * 60}\n结果：{passed}/{total} 通过  (SCHEDULE_PROCESS_NAMES 共 {len(SCHEDULE_PROCESS_NAMES)} 道工序)")
sys.exit(0 if passed == total else 1)
