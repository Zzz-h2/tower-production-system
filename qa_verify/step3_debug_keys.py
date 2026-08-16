# -*- coding: utf-8 -*-
"""QA Step3-debug: 打印 information_schema 查询返回的原始 key"""
import pymysql

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="123456",
    database="tower_production", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)
try:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE() ORDER BY table_name"
        )
        rows = cursor.fetchall()
        print("ROW_COUNT:", len(rows))
        if rows:
            print("ROW_KEYS:", list(rows[0].keys()))
            print("FIRST_ROW:", rows[0])
        # 顺带验证 migrate 脚本同款查询
        cursor.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = DATABASE() AND table_name = 'projects' "
            "ORDER BY ordinal_position LIMIT 3"
        )
        col_rows = cursor.fetchall()
        print("COL_KEYS:", list(col_rows[0].keys()) if col_rows else None)
        print("COL_ROWS:", col_rows)
finally:
    conn.close()
