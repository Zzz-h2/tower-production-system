# -*- coding: utf-8 -*-
"""验证 auto 模式 stale-cache 修复：改 edit_start 保存后 status/lag 按新计划日期重算
复现 QA 场景（edit_start=2026-09-01），保存后校验 proc1/proc3，最后恢复 DB 全量快照
"""
import os
import sys
import datetime

PROJECT_ROOT = r"E:\budy date\project one\tower_production_system"
os.environ["MYSQL_PASSWORD"] = "123456"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
from streamlit.testing.v1 import AppTest
import pymysql
import pymysql.cursors

st.cache_data.clear()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


def find(el_list, key):
    for e in el_list:
        if getattr(e, "key", None) == key:
            return e
    raise KeyError(f"element key={key} not found")


def _conn():
    return pymysql.connect(
        host="127.0.0.1", port=3306, user="root", password="123456",
        database="tower_production", charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def mysql_all(sql, params=None):
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    finally:
        conn.close()


def mysql_one(sql, params=None):
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        conn.close()


def mysql_exec(sql, params=None):
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


PROJECT_ID = 1
PROC_FIELDS = ("id, process_order, plan_start_date, plan_end_date, status, "
               "lag_days, actual_end_date, completion_pct")


def snapshot():
    procs = mysql_all(f"SELECT {PROC_FIELDS} FROM processes WHERE project_id=%s ORDER BY id",
                      (PROJECT_ID,))
    proj = mysql_one("SELECT * FROM projects WHERE id=%s", (PROJECT_ID,))
    return procs, proj


def restore(procs0, proj0):
    for r in procs0:
        mysql_exec(
            "UPDATE processes SET plan_start_date=%s, plan_end_date=%s, status=%s, "
            "lag_days=%s, actual_end_date=%s, completion_pct=%s WHERE id=%s",
            (r["plan_start_date"], r["plan_end_date"], r["status"], r["lag_days"],
             r["actual_end_date"], r["completion_pct"], r["id"]))
    # 恢复项目全量字段（auto 保存会改 projects 的多列）
    if proj0 is not None:
        cols = [k for k in proj0.keys() if k not in ("id",)]
        sets = ", ".join(f"{k}=%s" for k in cols)
        vals = [proj0[k] for k in cols] + [PROJECT_ID]
        mysql_exec(f"UPDATE projects SET {sets} WHERE id=%s", vals)


proc0, proj0 = snapshot()

at = AppTest.from_file("pages/2_项目详情.py", default_timeout=120)
at.session_state["selected_project_id"] = PROJECT_ID
at.run()
find(at.button, f"btn_edit_project_{PROJECT_ID}").click()
at.run()
# auto 模式默认；把计划开工改为 2026-09-01
find(at.date_input, f"edit_start_{PROJECT_ID}").set_value(datetime.date(2026, 9, 1))
at.run()
find(at.button, f"save_edit_{PROJECT_ID}").click()
at.run()

excs = [str(e) for e in at.exception]
p1 = mysql_one("SELECT plan_start_date, plan_end_date, status, lag_days, actual_end_date FROM processes WHERE id=1")
p3 = mysql_one("SELECT plan_start_date, plan_end_date, status, lag_days FROM processes WHERE id=3")
proj = mysql_one("SELECT plan_start_date, risk_level FROM projects WHERE id=1")

check("auto_no_exception", len(excs) == 0, repr(excs))
check("auto_plan_recomputed", p3 and p3["plan_start_date"] == "2026-09-05" and p3["plan_end_date"] == "2026-09-05",
      repr(p3))
check("auto_proc1_lag", p1 and p1["lag_days"] == -32,
      f"proc1 lag={p1['lag_days'] if p1 else None} expect -32 (actual_end {p1['actual_end_date'] if p1 else None} - plan_end {p1['plan_end_date'] if p1 else None})")
check("auto_proc3_status", p3 and p3["status"] == "not_started" and p3["lag_days"] == 0,
      repr(p3))
check("auto_project_start_written", proj and proj["plan_start_date"] == "2026-09-01", repr(proj))
check("auto_risk_recomputed", proj and proj["risk_level"] == "normal",
      f"risk={proj['risk_level'] if proj else None} expect normal (全部工序未开始/无滞后)")

restore(proc0, proj0)

procF, projF = snapshot()
check("db_restored", procF[0] == proc0[0] and projF == proj0,
      "DB restored to full snapshot")

out = []
for name, ok, detail in results:
    out.append(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
out.append(f"TOTAL={len(results)} PASS={sum(1 for r in results if r[1])} "
           f"FAIL={sum(1 for r in results if not r[1])}")
open("qa_verify/_auto_fix_verify.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
sys.exit(0 if all(r[1] for r in results) else 1)
