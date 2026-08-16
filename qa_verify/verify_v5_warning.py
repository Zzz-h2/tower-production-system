# -*- coding: utf-8 -*-
"""
QA v5 验证：工序节点预警逻辑
- judge_node_status 四态（pending/done/warning/overdue）+ lag_qty
- judge_process_node_status 工序级聚合
用法: python qa_verify/verify_v5_warning.py
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.business_logic import judge_node_status, judge_process_node_status

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
    today = date(2026, 8, 13)

    print("== [4.1] judge_node_status 四态 ==")
    # pending: today < plan_date
    r = judge_node_status("2026-08-20", 10, 0, today)
    check("pending: 未到", r['status'] == 'pending' and r['level'] == 0 and r['lag_qty'] == 0,
          f"got {r}")
    # done: today >= plan_date, actual >= plan
    r = judge_node_status("2026-08-10", 10, 10, today)
    check("done: 达标", r['status'] == 'done' and r['level'] == 0 and r['lag_qty'] == 0,
          f"got {r}")
    # done 超额完成
    r = judge_node_status("2026-08-10", 10, 12, today)
    check("done: 超额完成仍达标", r['status'] == 'done' and r['lag_qty'] == 0, f"got {r}")
    # warning: today >= plan_date, 0 < actual < plan
    r = judge_node_status("2026-08-10", 10, 6, today)
    check("warning: 部分完成", r['status'] == 'warning' and r['level'] == 1 and r['lag_qty'] == 4,
          f"got {r}")
    # overdue: today >= plan_date, actual == 0
    r = judge_node_status("2026-08-10", 10, 0, today)
    check("overdue: 逾期未完成", r['status'] == 'overdue' and r['level'] == 2 and r['lag_qty'] == 10,
          f"got {r}")
    # 边界: today == plan_date 且未完成 → overdue（不是 pending）
    r = judge_node_status("2026-08-13", 5, 0, today)
    check("边界: today==plan_date 未完成 → overdue", r['status'] == 'overdue', f"got {r}")
    # 边界: today == plan_date 且完成 → done
    r = judge_node_status("2026-08-13", 5, 5, today)
    check("边界: today==plan_date 完成 → done", r['status'] == 'done', f"got {r}")
    # lag_qty 语义: warning = plan - actual
    r = judge_node_status("2026-08-10", 10, 3, today)
    check("warning lag_qty = plan-actual", r['lag_qty'] == 7, f"got {r}")

    print("== [4.2] judge_process_node_status 工序级聚合 ==")
    # 空 → pending
    r = judge_process_node_status([])
    check("空列表 → 未到", r['status'] == 'pending', f"got {r}")
    # 全部 done → done
    r = judge_process_node_status([
        judge_node_status("2026-08-10", 10, 10, today),
        judge_node_status("2026-08-11", 10, 12, today),
    ])
    check("全部达标 → 达标", r['status'] == 'done', f"got {r}")
    # 全部 pending → pending
    r = judge_process_node_status([
        judge_node_status("2026-08-20", 10, 0, today),
        judge_node_status("2026-08-21", 10, 0, today),
    ])
    check("全部未到 → 未到", r['status'] == 'pending', f"got {r}")
    # 混合 pending+done → pending（无预警）
    r = judge_process_node_status([
        judge_node_status("2026-08-20", 10, 0, today),
        judge_node_status("2026-08-10", 10, 10, today),
    ])
    check("pending+done → 未到(level0)", r['status'] == 'pending' and r['level'] == 0, f"got {r}")
    # 含 warning → warning
    r = judge_process_node_status([
        judge_node_status("2026-08-10", 10, 5, today),
        judge_node_status("2026-08-11", 10, 10, today),
    ])
    check("含部分完成 → 部分完成", r['status'] == 'warning' and r['level'] == 1, f"got {r}")
    # 含 overdue → overdue（取最高 level）
    r = judge_process_node_status([
        judge_node_status("2026-08-10", 10, 0, today),
        judge_node_status("2026-08-11", 10, 5, today),
    ])
    check("含逾期 → 逾期(最高level)", r['status'] == 'overdue' and r['level'] == 2, f"got {r}")
    # 含 done+warning+overdue → overdue
    r = judge_process_node_status([
        judge_node_status("2026-08-10", 10, 10, today),   # done
        judge_node_status("2026-08-11", 10, 5, today),    # warning
        judge_node_status("2026-08-12", 10, 0, today),    # overdue
    ])
    check("done+warning+overdue → 逾期", r['status'] == 'overdue' and r['level'] == 2,
          f"got {r}")
    # 聚合 lag_qty 传递自最高 level 节点
    r = judge_process_node_status([
        judge_node_status("2026-08-10", 10, 5, today),   # warning lag 5
        judge_node_status("2026-08-11", 10, 0, today),    # overdue lag 10
    ])
    check("聚合 lag_qty=10(来自逾期)", r['lag_qty'] == 10, f"got {r}")

    print(f"\n== 小结: PASS {len(PASS)} / FAIL {len(FAIL)} ==")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)


if __name__ == '__main__':
    main()
