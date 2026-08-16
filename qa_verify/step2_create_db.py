# -*- coding: utf-8 -*-
"""QA Step2: 用 pymysql 创建 tower_production 数据库（验证用临时密码 root/123456）"""
import pymysql

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="123456",
    charset="utf8mb4",
)
try:
    with conn.cursor() as cursor:
        cursor.execute(
            "CREATE DATABASE IF NOT EXISTS tower_production "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
    conn.commit()
    print("CREATE_DATABASE_OK")
finally:
    conn.close()
