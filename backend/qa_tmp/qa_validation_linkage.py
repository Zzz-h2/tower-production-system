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
results.append(assert_match("文案应含旧版量化 前序累计实际仅 0 套", err, "前序累计实际仅 0 套"))

# 场景 B —— 累计口径（2026-09-03 修复 pid=60 防腐超填后更新预期）：
# 旧口径「单条 qty ≤ 前序累计」允许一批多条逐条 1≤1 全过、合计超额，已废弃。
# 新口径：填报后「本工序累计（存量+本批）」≤「前序累计实际」。
print("\n[B] 门框焊接=3、黑塔存量2（未超额），增量填 1 → 累计 3≤3 应通过")
actuals_ok = dict(actuals_screenshot)
actuals_ok[701] = {"actual_qty": 3}   # 门框焊接累计 3
actuals_ok[801] = {"actual_qty": 2}   # 黑塔存量修正为不超额形态
err = validate_today_quota(
    "黑塔", plans, actuals_ok,
    [{"id": 802, "plan_date": "2026-09-20"}], {802: 1},
)
results.append(assert_match("门框焊接=3、黑塔存量2、填1（累计3≤3）应通过", err, None))

print("\n[B2] 存量已超填（黑塔4 > 门框焊接3，pid=60 同款），再填 1 → 应拒绝")
actuals_b2 = dict(actuals_ok)
actuals_b2[801] = {"actual_qty": 4}   # 黑塔存量超填
err = validate_today_quota(
    "黑塔", plans, actuals_b2,
    [{"id": 802, "plan_date": "2026-09-20"}], {802: 1},
)
results.append(assert_match("存量超填时任何新增都应拒绝（累计口径）", err, "数量校验未通过"))
results.append(assert_match("文案应含「累计将达 5 套」", err, "累计将达 5 套"))

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

# 场景 F —— 法兰到货（idx 1）同样不做任何限制（原材料到货）
print("\n[F] 第二道工序 法兰到货")
err = validate_today_quota(
    "法兰到货", plans, {},
    [{"id": 202, "plan_date": "2026-08-28"}], {202: 99},
)
results.append(assert_match("法兰到货 不限制联动", err, None))

# 场景 G —— 下料硬卡2：拟填报超过 钢板到货 实际累计（截止该日钢板=2+1=3，报5）
print("\n[G] 下料拟填报 5 > 钢板到货实际累计 3")
plans_g = [
    {"id": 1, "process_name": "钢板到货", "plan_date": "2026-08-17", "plan_qty": 2},
    {"id": 2, "process_name": "钢板到货", "plan_date": "2026-08-25", "plan_qty": 2},
    {"id": 3, "process_name": "法兰到货", "plan_date": "2026-08-20", "plan_qty": 2},
    {"id": 4, "process_name": "下料", "plan_date": "2026-08-30", "plan_qty": 5},
]
actuals_g = {1: {"actual_qty": 2}, 2: {"actual_qty": 1}, 3: {"actual_qty": 1}}
err = validate_today_quota(
    "下料", plans_g, actuals_g,
    [{"id": 4, "plan_date": "2026-08-30"}], {4: 5},
)
results.append(assert_match("下料报5 应被「数量校验未通过」拒绝", err, "数量校验未通过"))
results.append(assert_match("文案应点名「钢板到货累计实际仅 3 套」", err, "钢板到货累计实际仅 3 套"))

# 场景 H —— 下料硬卡2：拟填报 3 = 钢板到货实际累计 3 → 等于上限允许
print("\n[H] 下料拟填报 3 = 钢板到货实际累计 3，应通过")
err = validate_today_quota(
    "下料", plans_g, actuals_g,
    [{"id": 4, "plan_date": "2026-08-30"}], {4: 3},
)
results.append(assert_match("下料报3 等于上限应通过", err, None))

# 场景 M —— 卷制 qty 不超过紧邻前序(下料)实际累计 → 通过
print("\n[M] 卷制 qty=3 ≤ 下料实际3")
plans_m = [
    {"id": 21, "process_name": "钢板到货", "plan_date": "2026-08-25", "plan_qty": 4},
    {"id": 22, "process_name": "下料",     "plan_date": "2026-08-28", "plan_qty": 4},
    {"id": 23, "process_name": "卷制",     "plan_date": "2026-09-01", "plan_qty": 4},
]
actuals_m = {22: {"actual_qty": 3}}   # 下料 实际 3
err = validate_today_quota("卷制", plans_m, actuals_m,
                           [{"id": 23, "plan_date": "2026-09-01"}], {23: 3})
results.append(assert_match("卷制 qty=3 ≤ 下料实际3 → 通过", err, None))

# 场景 N —— 卷制 qty 超过紧邻前序(下料)实际累计 → 拦截，点名下料
print("\n[N] 卷制 qty=5 > 下料实际3")
err = validate_today_quota("卷制", plans_m, actuals_m,
                           [{"id": 23, "plan_date": "2026-09-01"}], {23: 5})
results.append(assert_match("卷制 qty=5 > 下料实际3 → 拦截", err, "数量校验未通过"))
results.append(assert_match("文案应点名前一工序「下料」", err, "下料"))

# 场景 O —— 卷制前置(下料)尚未开工 → 硬卡1 拦截
print("\n[O] 卷制 前置下料未开工")
actuals_o = {}   # 下料 0 实际
err = validate_today_quota("卷制", plans_m, actuals_o,
                           [{"id": 23, "plan_date": "2026-09-01"}], {23: 1})
results.append(assert_match("卷制 应被「下料未开工」拒绝", err, "下料"))

# 场景 P —— 黑塔 qty 超过紧邻前序(门框焊接)实际累计 → 拦截（验证链传导）
print("\n[P] 黑塔 qty=4 > 门框焊接实际2")
plans_p = [
    {"id": 31, "process_name": "门框焊接", "plan_date": "2026-09-05", "plan_qty": 4},
    {"id": 32, "process_name": "黑塔",     "plan_date": "2026-09-10", "plan_qty": 4},
]
actuals_p = {31: {"actual_qty": 2}}   # 门框焊接 2
err = validate_today_quota("黑塔", plans_p, actuals_p,
                           [{"id": 32, "plan_date": "2026-09-10"}], {32: 4})
results.append(assert_match("黑塔 qty=4 > 门框焊接实际2 → 拦截", err, "门框焊接"))

# 场景 Q —— 下料+钢板到货全部完成 → 多填放行（保留原特例）
print("\n[Q] 钢板到货全部完成，下料 qty=100 放行")
plans_q = [
    {"id": 41, "process_name": "钢板到货", "plan_date": "2026-08-25", "plan_qty": 4},
    {"id": 42, "process_name": "下料",     "plan_date": "2026-08-30", "plan_qty": 5},
]
actuals_q = {41: {"actual_qty": 4}}   # 钢板到货 4/4 全部完成
err = validate_today_quota("下料", plans_q, actuals_q,
                           [{"id": 42, "plan_date": "2026-08-30"}], {42: 100})
results.append(assert_match("钢板到货全部完成，下料 qty=100 放行", err, None))

# 汇总
passed = sum(results)
total = len(results)
print(f"\n{'=' * 60}\n结果：{passed}/{total} 通过  (SCHEDULE_PROCESS_NAMES 共 {len(SCHEDULE_PROCESS_NAMES)} 道工序)")
sys.exit(0 if passed == total else 1)
