# -*- coding: utf-8 -*-
"""QA Step3-verify: 查询 information_schema 确认 7 张表存在
注: MySQL information_schema 列名返回大写 (TABLE_NAME)"""
import pymysql

EXPECTED = {
    'projects', 'processes', 'anomalies', 'milestones',
    'system_config', 'import_logs', 'daily_progress'
}

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="123456",
    database="tower_production", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)
try:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT TABLE_NAME FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY TABLE_NAME"
        )
        tables = {r['TABLE_NAME'] for r in cursor.fetchall()}
    print("FOUND_TABLES:", sorted(tables))
    missing = EXPECTED - tables
    if missing:
        print("MISSING:", sorted(missing))
        print("STEP3_TABLES: FAIL")
    else:
        print("STEP3_TABLES: PASS (7 tables)")
finally:
    conn.close()
