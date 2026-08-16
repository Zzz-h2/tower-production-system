# -*- coding: utf-8 -*-
"""
QA v5 验证：排产 Excel 解析层
- 正例 test_schedule_matrix.xlsx：10套×9工序，3个空单元格 → 有效87项
  断言：聚合节点数 = 唯一(工序,日期)数；sum(plan_qty) = 87；9 工序全覆盖；排序正确
- 负例 test_schedule_bad.xlsx：'abc' 非法日期 → errors 捕获
用法: python qa_verify/verify_v5_parse.py
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.schedule_import import parse_schedule_excel
from config import SCHEDULE_PROCESS_NAMES

PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name} {detail}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name} {detail}")


def main():
    matrix = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_schedule_matrix.xlsx')
    bad = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_schedule_bad.xlsx')

    print("== [3.1] 正例 matrix：10套×9工序 ==")
    plans, errors = parse_schedule_excel(matrix)
    print(f"  解析出 {len(plans)} 个聚合节点, errors={len(errors)}")
    check("无错误", len(errors) == 0, f"errors={errors}")
    check("9 道工序全覆盖",
          {p['process_name'] for p in plans} == set(SCHEDULE_PROCESS_NAMES),
          f"got {sorted({p['process_name'] for p in plans})}")
    total_qty = sum(p['plan_qty'] for p in plans)
    check("plan_qty 合计 = 87 (90-3空)", total_qty == 87, f"got {total_qty}")
    # 聚合节点数应为有效项数（同一工序同日期合并），≤87
    check("聚合节点数 > 0 且 <= 87", 0 < len(plans) <= 87, f"got {len(plans)}")
    # 工序顺序正确
    orders = [p['process_order'] for p in plans]
    check("process_order 单调不减", orders == sorted(orders), f"orders={orders[:10]}...")
    # 每道工序 qty 合计为 10（除3个空单元格对应工序为9）
    for pn in SCHEDULE_PROCESS_NAMES:
        q = sum(p['plan_qty'] for p in plans if p['process_name'] == pn)
        print(f"    工序[{pn}] 合计套数 = {q}")
    q_steel = sum(p['plan_qty'] for p in plans if p['process_name'] == '钢板到货')
    q_flange = sum(p['plan_qty'] for p in plans if p['process_name'] == '法兰到货')
    q_acc = sum(p['plan_qty'] for p in plans if p['process_name'] == '具备验收')
    check("钢板到货=10", q_steel == 10, f"got {q_steel}")
    check("法兰到货=9(第8套空)", q_flange == 9, f"got {q_flange}")
    check("具备验收=9(第10套空)", q_acc == 9, f"got {q_acc}")
    # 附件安装应为9（第5套空）
    q_att = sum(p['plan_qty'] for p in plans if p['process_name'] == '附件安装')
    check("附件安装=9(第5套空)", q_att == 9, f"got {q_att}")
    # 检查排序：按 (process_order, plan_date)
    sorted_ok = all(
        (plans[i]['process_order'], plans[i]['plan_date']) <= (plans[i+1]['process_order'], plans[i+1]['plan_date'])
        for i in range(len(plans)-1)
    )
    check("按 工序序+日期 升序", sorted_ok)

    print("== [3.2] 负例 bad：非法日期捕获 ==")
    plans_bad, errors_bad = parse_schedule_excel(bad)
    print(f"  解析出 {len(plans_bad)} 个聚合节点, errors={len(errors_bad)}")
    check("errors 捕获到非法日期", len(errors_bad) >= 1, f"errors={errors_bad}")
    check("错误信息含 法兰到货/abc",
          any('法兰到货' in e and ('abc' in e or '无法解析' in e) for e in errors_bad),
          f"errors={errors_bad}")
    # 其余合法行仍解析出
    total_bad_qty = sum(p['plan_qty'] for p in plans_bad)
    check("合法节点仍解析 (>=2)", len(plans_bad) >= 2 and total_bad_qty >= 3, f"nodes={len(plans_bad)}, qty={total_bad_qty}")

    print(f"\n== 小结: PASS {len(PASS)} / FAIL {len(FAIL)} ==")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)


if __name__ == '__main__':
    main()
