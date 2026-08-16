# -*- coding: utf-8 -*-
"""验证 stale-cache 修复：手工保存 / 导入确认后 status/lag_days 按新计划日期重算
复现 QA 场景并恢复 DB（含 business 字段快照；updated_at 为预期刷新不参与比较）
"""
import os
import sys
import io
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
    return (
        mysql_all(f"SELECT {PROC_FIELDS} FROM processes WHERE project_id=%s ORDER BY id",
                  (PROJECT_ID,)),
        mysql_one("SELECT risk_level FROM projects WHERE id=%s", (PROJECT_ID,)),
    )


def restore(proc_before, proj_before):
    for r in proc_before:
        mysql_exec(
            "UPDATE processes SET plan_start_date=%s, plan_end_date=%s, status=%s, "
            "lag_days=%s, actual_end_date=%s, completion_pct=%s WHERE id=%s",
            (r["plan_start_date"], r["plan_end_date"], r["status"], r["lag_days"],
             r["actual_end_date"], r["completion_pct"], r["id"]))
    if proj_before is not None:
        mysql_exec("UPDATE projects SET risk_level=%s WHERE id=%s",
                   (proj_before["risk_level"], PROJECT_ID))


def click(at, key):
    find(at.button, key).click()


# ============================================================
# 测试1：手工保存 —— 工序3 卷板 plan_end 08-05 → 08-07，期望 lag_days=5
# ============================================================
proc0, proj0 = snapshot()

at = AppTest.from_file("pages/2_项目详情.py", default_timeout=120)
at.session_state["selected_project_id"] = PROJECT_ID
at.run()
click(at, f"btn_edit_project_{PROJECT_ID}")
at.run()
click(at, f"mode_manual_{PROJECT_ID}")
at.run()
# 仅把工序3 计划结束改为 2026-08-07（开始保持 08-05，ps<=pe 校验通过）
find(at.date_input, f"manual_pe_{PROJECT_ID}_3").set_value(datetime.date(2026, 8, 7))
at.run()
click(at, f"save_manual_dates_{PROJECT_ID}")
at.run()

excs = [str(e) for e in at.exception]
p3 = mysql_one("SELECT plan_start_date, plan_end_date, status, lag_days FROM processes WHERE id=3")
check("manual_no_exception", len(excs) == 0, repr(excs))
check("manual_plan_written", p3 and p3["plan_end_date"] == "2026-08-07", repr(p3))
check("manual_lag_recomputed", p3 and p3["lag_days"] == 5, repr(p3))
check("manual_status_ok", p3 and p3["status"] == "delayed", repr(p3))

restore(proc0, proj0)

# ============================================================
# 测试2：导入确认 —— 12 道工序全部 +1 天，期望 proc1-5 lag = -2/-1/6/4/2
# ============================================================
proc0, proj0 = snapshot()

procs = mysql_all(
    "SELECT process_name, plan_start_date, plan_end_date FROM processes "
    "WHERE project_id=%s ORDER BY process_order", (PROJECT_ID,))
rows = []
for p in procs:
    ps = (datetime.date.fromisoformat(p["plan_start_date"]) + datetime.timedelta(days=1)).isoformat()
    pe = (datetime.date.fromisoformat(p["plan_end_date"]) + datetime.timedelta(days=1)).isoformat()
    rows.append({"工序名称": p["process_name"], "计划开始": ps, "计划结束": pe})
import pandas as pd
buf = io.BytesIO()
pd.DataFrame(rows).to_excel(buf, index=False)
xlsx_bytes = buf.getvalue()

at2 = AppTest.from_file("pages/2_项目详情.py", default_timeout=120)
at2.session_state["selected_project_id"] = PROJECT_ID
at2.run()
click(at2, f"btn_edit_project_{PROJECT_ID}")
at2.run()
click(at2, f"mode_import_{PROJECT_ID}")
at2.run()
find(at2.file_uploader, f"import_date_file_{PROJECT_ID}").upload(
    "plan_dates_plus1.xlsx", xlsx_bytes,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
at2.run()
# 预览渲染后再确认导入
has_confirm = any(getattr(b, "key", None) == f"confirm_import_dates_{PROJECT_ID}" for b in at2.button)
check("import_preview_confirm_btn", has_confirm, "confirm button should appear after upload")
click(at2, f"confirm_import_dates_{PROJECT_ID}")
at2.run()

excs2 = [str(e) for e in at2.exception]
p1 = mysql_one("SELECT plan_end_date, status, lag_days FROM processes WHERE id=1")
p2 = mysql_one("SELECT plan_end_date, status, lag_days FROM processes WHERE id=2")
p3 = mysql_one("SELECT plan_start_date, plan_end_date, status, lag_days FROM processes WHERE id=3")
p4 = mysql_one("SELECT plan_end_date, status, lag_days FROM processes WHERE id=4")
p5 = mysql_one("SELECT plan_end_date, status, lag_days FROM processes WHERE id=5")
check("import_no_exception", len(excs2) == 0, repr(excs2))
check("import_plan_written", p3 and p3["plan_end_date"] == "2026-08-06", repr(p3))
check("import_lag_proc1", p1 and p1["lag_days"] == -2, repr(p1))
check("import_lag_proc2", p2 and p2["lag_days"] == -1, repr(p2))
check("import_lag_proc3", p3 and p3["lag_days"] == 6, repr(p3))
check("import_lag_proc4", p4 and p4["lag_days"] == 4, repr(p4))
check("import_lag_proc5", p5 and p5["lag_days"] == 2, repr(p5))

restore(proc0, proj0)

# ============================================================
# 收尾：确认 DB 已恢复
# ============================================================
procF, projF = snapshot()
check("db_restored_after_tests", procF[0] == proc0[0] and projF == proj0,
      "DB restored to snapshot")

out = []
for name, ok, detail in results:
    out.append(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
out.append(f"TOTAL={len(results)} PASS={sum(1 for r in results if r[1])} "
           f"FAIL={sum(1 for r in results if not r[1])}")
open("qa_verify/_fix_verify.txt", "w", encoding="utf-8").write("\n".join(out))
print("\n".join(out))
sys.exit(0 if all(r[1] for r in results) else 1)
