# -*- coding: utf-8 -*-
"""一键初始化数据库：创建库（若不存在）+ 建表。

使用方式（在 tower_production_system/ 目录下、且已安装 pymysql 后运行）：
    $env:MYSQL_PASSWORD = "123456"
    python init_db.py

- 数据库连接参数读取自 config.MYSQL_CONFIG（可用环境变量 MYSQL_HOST/PORT/USER/PASSWORD/DATABASE 覆盖）
- 建库用 CREATE DATABASE IF NOT EXISTS，建表用 init_database()（表已存在则跳过），可重复执行，安全
"""
import pymysql
from config import MYSQL_CONFIG
from database import init_database


def main():
    cfg = dict(MYSQL_CONFIG)
    cfg.setdefault("charset", "utf8mb4")  # MYSQL_CONFIG 已含 charset，避免重复传参报错
    db_name = cfg.pop("database")

    # 1) 连 MySQL 服务器（不指定库），创建数据库
    conn = pymysql.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
                f"CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
            )
        conn.commit()
        print(f"[DB] 数据库已就绪: {db_name}")
    finally:
        conn.close()

    # 2) 建表（projects / 节点计划 / 实际进度 等）
    init_database()


if __name__ == "__main__":
    main()
