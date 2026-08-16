"""
qa_verify/verify_v4_node_plan.py — v4.0 工序节点计划管控验证脚本

覆盖：
1. 建表：从 db_schema_mysql.sql 提取并执行 process_node_plans / node_actual_progress 两条 DDL
2. database.py 新增 4 函数冒烟：
   insert_node_plans / get_node_plans / upsert_node_actual / get_node_actuals
3. 清理：删除本次测试写入的临时数据（project_id=SCRATCH_PROJECT_ID）

运行：
    MYSQL_PASSWORD=123456 python qa_verify/verify_v4_node_plan.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pymysql  # noqa: E402

from config import MYSQL_CONFIG  # noqa: E402

SCRATCH_PROJECT_ID = 999999  # 测试用虚拟项目ID（新表无外键，允许任意ID）


def get_conn():
    return pymysql.connect(**MYSQL_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def create_new_tables() -> None:
    """从 db_schema_mysql.sql 中提取两条新表 DDL 并执行。"""
    schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'db_schema_mysql.sql')
    with open(schema_path, encoding='utf-8') as fh:
        script = fh.read()

    statements = []
    for statement in script.split(';'):
        lines = [ln for ln in statement.splitlines() if not ln.strip().startswith('--')]
        stmt = '\n'.join(lines).strip()
        if not stmt:
            continue
        if 'process_node_plans' in stmt or 'node_actual_progress' in stmt:
            statements.append(stmt)

    assert len(statements) == 2, f'应提取到 2 条新表 DDL，实际 {len(statements)}'

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
        conn.commit()
        print('✅ 已从 db_schema_mysql.sql 执行 2 条新表 DDL（IF NOT EXISTS，幂等）')
    finally:
        conn.close()


def cleanup() -> None:
    """清理测试数据。"""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM node_actual_progress WHERE project_id = %s', (SCRATCH_PROJECT_ID,))
            cur.execute('DELETE FROM process_node_plans WHERE project_id = %s', (SCRATCH_PROJECT_ID,))
        conn.commit()
        print('🧹 已清理测试数据 (project_id=%s)' % SCRATCH_PROJECT_ID)
    finally:
        conn.close()


def main() -> None:
    import streamlit as st  # 仅用 st.cache_data.clear() 模拟应用内写后清缓存

    from database import (
        insert_node_plans, get_node_plans,
        upsert_node_actual, get_node_actuals,
    )

    # ---- 1. 建表 ----
    create_new_tables()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES LIKE 'process_node_plans'")
            assert cur.fetchone() is not None, 'process_node_plans 未创建'
            cur.execute("SHOW TABLES LIKE 'node_actual_progress'")
            assert cur.fetchone() is not None, 'node_actual_progress 未创建'
        print('✅ 两新表均已存在')
    finally:
        conn.close()

    cleanup()  # 清理可能残留的旧测试数据

    # ---- 2. 函数冒烟 ----
    plans = [
        {"process_name": "钢板到货", "process_order": 1, "plan_date": "2026-08-05", "plan_qty": 4},
        {"process_name": "钢板到货", "process_order": 1, "plan_date": "2026-08-06", "plan_qty": 6},
        {"process_name": "下料", "process_order": 3, "plan_date": "2026-08-07", "plan_qty": 5},
        {"process_name": "下料", "process_order": 3, "plan_date": "2026-08-08", "plan_qty": 5},
    ]
    n = insert_node_plans(SCRATCH_PROJECT_ID, plans)
    assert n == 4, f'insert_node_plans 应插入 4 条，实际 {n}'
    print('✅ insert_node_plans 插入 4 条')

    # 覆盖式导入：同项目重复导入 → 旧计划被清空
    n2 = insert_node_plans(SCRATCH_PROJECT_ID, plans[:2])
    assert n2 == 2, f'覆盖导入应返回 2，实际 {n2}'
    st.cache_data.clear()  # 模拟应用内写后清缓存
    got = get_node_plans(SCRATCH_PROJECT_ID)
    assert len(got) == 2, f'覆盖后应剩 2 条，实际 {len(got)}'
    print('✅ insert_node_plans 覆盖式导入生效（旧计划被清空）')

    # 恢复 4 条供后续校验
    insert_node_plans(SCRATCH_PROJECT_ID, plans)
    st.cache_data.clear()
    got = get_node_plans(SCRATCH_PROJECT_ID)
    assert len(got) == 4, f'get_node_plans 应返回 4 条，实际 {len(got)}'
    assert got[0]['process_order'] <= got[1]['process_order'], '应按 process_order 排序'
    first_id = got[0]['id']
    print('✅ get_node_plans 返回 4 条且按工序顺序排序')

    # upsert 实际进度
    upsert_node_actual(SCRATCH_PROJECT_ID, first_id, '钢板到货', 2, '2026-08-12')
    upsert_node_actual(SCRATCH_PROJECT_ID, first_id, '钢板到货', 4, '2026-08-12')  # 同节点覆盖更新
    st.cache_data.clear()
    actuals = get_node_actuals(SCRATCH_PROJECT_ID)
    assert actuals.get(first_id) == 4, f'同节点覆盖后应=4，实际 {actuals.get(first_id)}'
    print('✅ upsert_node_actual / get_node_actuals 生效（同节点可重复修改）')

    # 汇总校验：各工序应完成套数
    total_by_proc = {}
    for p in get_node_plans(SCRATCH_PROJECT_ID):
        total_by_proc[p['process_name']] = total_by_proc.get(p['process_name'], 0) + p['plan_qty']
    assert total_by_proc.get('钢板到货') == 10, total_by_proc
    assert total_by_proc.get('下料') == 10, total_by_proc
    print('✅ 套数聚合正确:', total_by_proc)

    print('\n🎉 v4.0 数据库函数冒烟测试全部通过')


if __name__ == '__main__':
    try:
        main()
    finally:
        cleanup()
