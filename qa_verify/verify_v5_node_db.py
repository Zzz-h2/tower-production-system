# -*- coding: utf-8 -*-
"""
QA v5 验证：工序节点计划数据层链路（MySQL）
- 表存在性（information_schema）
- insert_node_plans → get_node_plans（排序）→ upsert_node_actual（2→5）→ get_node_actuals
- 验证后 DELETE 清理测试数据（project_id=999998）
用法: MYSQL_PASSWORD=123456 python qa_verify/verify_v5_node_db.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database as db

TEST_PID = 999998
PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
        print(f"  PASS {name} {detail}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name} {detail}")


def cleanup():
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM node_actual_progress WHERE project_id=%s", (TEST_PID,))
            c.execute("DELETE FROM process_node_plans WHERE project_id=%s", (TEST_PID,))
        conn.commit()
    finally:
        conn.close()


def main():
    print("== [2.1] 表存在性 ==")
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name IN ('process_node_plans', 'node_actual_progress')
            """)
            tables = {r.get('table_name') or r.get('TABLE_NAME') for r in c.fetchall()}
        check("process_node_plans 表存在", 'process_node_plans' in tables)
        check("node_actual_progress 表存在", 'node_actual_progress' in tables)
    finally:
        conn.close()

    print("== [2.2] insert_node_plans (project 999998) ==")
    cleanup()
    plans = [
        {"process_name": "下料", "process_order": 3, "plan_date": "2026-09-01", "plan_qty": 10},
        {"process_name": "钢板到货", "process_order": 1, "plan_date": "2026-08-20", "plan_qty": 10},
        {"process_name": "具备验收", "process_order": 9, "plan_date": "2026-09-15", "plan_qty": 10},
    ]
    n = db.insert_node_plans(TEST_PID, plans)
    check("insert_node_plans 插入3条", n == 3, f"got {n}")

    print("== [2.3] get_node_plans 排序 ==")
    rows = db.get_node_plans(TEST_PID)
    check("get_node_plans 返回3条", len(rows) == 3, f"got {len(rows)}")
    if len(rows) == 3:
        orders = [r['process_order'] for r in rows]
        check("按 process_order 排序", orders == sorted(orders), f"orders={orders}")
        check("首个为 钢板到货(order1)", rows[0]['process_name'] == '钢板到货',
              f"got {rows[0]['process_name']}")
        first_pid = rows[0]['id']
    else:
        first_pid = None

    print("== [2.4] upsert_node_actual 2 → 5 ==")
    if first_pid is None:
        check("upsert 前置条件(有 node_plan_id)", False)
    else:
        db.upsert_node_actual(TEST_PID, first_pid, "钢板到货", 2, "2026-08-13")
        db.upsert_node_actual(TEST_PID, first_pid, "钢板到货", 5, "2026-08-13")
        actuals = db.get_node_actuals(TEST_PID)
        check("get_node_actuals 返回 {node_plan_id: qty}", actuals.get(first_pid) == 5,
              f"got {actuals.get(first_pid)}")
        check("覆盖更新生效(2→5)", actuals.get(first_pid) == 5)

    print("== [2.5] 清理测试数据（直接 SQL 验证，避开 st.cache_data） ==")
    cleanup()
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute("SELECT COUNT(*) AS n FROM process_node_plans WHERE project_id=%s", (TEST_PID,))
            left_plans = c.fetchone()['n']
            c.execute("SELECT COUNT(*) AS n FROM node_actual_progress WHERE project_id=%s", (TEST_PID,))
            left_actuals = c.fetchone()['n']
    finally:
        conn.close()
    check("清理后 process_node_plans 为空", left_plans == 0, f"left={left_plans}")
    check("清理后 node_actual_progress 为空", left_actuals == 0, f"left={left_actuals}")

    print(f"\n== 小结: PASS {len(PASS)} / FAIL {len(FAIL)} ==")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)


if __name__ == '__main__':
    main()
