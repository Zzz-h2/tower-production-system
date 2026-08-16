# -*- coding: utf-8 -*-
"""QA Step6: AppTest 详情页「工序计划日期」三模式回归

验证（只验证控件存在与模式切换；保存链路用「改后恢复」防污染真实数据）：
1. 点「✏️ 编辑项目」→ 三个模式按钮出现
2. 切「✏️ 手工修改日期」→ 12 道工序 manual_ps_/manual_pe_ date_input（12×2）+ 保存按钮
   点保存（不改数据）→ 无异常 → 恢复 DB 快照
3. 切「📥 一键导入日期」→ file_uploader + 模板下载按钮存在
4. 切回「🔄 自动重算」→ 原表单 edit_start/edit_end/edit_factory 正常

说明：AppTest 在「del session_state + st.rerun()」后树节点不会清理（已知限制），
因此「点保存」单独用独立 AppTest 会话验证，模式切换用另一会话验证。
"""
import os
import sys

PROJECT_ROOT = r"E:\budy date\project one\tower_production_system"
os.environ["MYSQL_PASSWORD"] = "123456"  # 必须在 import config/database 之前设置
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
    print(f"{'PASS' if cond else 'FAIL'} | {name} | {detail}")


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
    """执行写操作并提交（供测试恢复用）"""
    conn = _conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


PROJECT_ID = 1
# 业务字段快照（不含 updated_at：任何 update_process 都会刷新时间戳，属预期行为）
PROC_FIELDS = "id, plan_start_date, plan_end_date, status, lag_days, actual_end_date, completion_pct"


def snapshot():
    return (
        mysql_all(f"SELECT {PROC_FIELDS} FROM processes WHERE project_id=%s ORDER BY id", (PROJECT_ID,)),
        mysql_one("SELECT risk_level FROM projects WHERE id=%s", (PROJECT_ID,)),
    )


def restore(proc_before, proj_before):
    for r in proc_before:
        mysql_exec(
            "UPDATE processes SET plan_start_date=%s, plan_end_date=%s, "
            "status=%s, lag_days=%s, actual_end_date=%s, completion_pct=%s WHERE id=%s",
            (r["plan_start_date"], r["plan_end_date"], r["status"],
             r["lag_days"], r["actual_end_date"], r["completion_pct"], r["id"]))
    if proj_before is not None:
        mysql_exec("UPDATE projects SET risk_level=%s WHERE id=%s",
                   (proj_before["risk_level"], PROJECT_ID))


# ============================================================
# 会话 A：编辑弹窗 → 三模式按钮 → 手工模式控件 + 点保存无异常（改后恢复）
# ============================================================
proc_before, proj_before = snapshot()

at = AppTest.from_file("pages/2_项目详情.py", default_timeout=120)
at.session_state["selected_project_id"] = PROJECT_ID
at.run()
check("initial_no_exception", len(at.exception) == 0, repr(at.exception))

try:
    find(at.button, f"btn_edit_project_{PROJECT_ID}").click()
    at.run()
    check("edit_open_no_exception", len(at.exception) == 0, repr(at.exception))
    mode_keys = [f"mode_auto_{PROJECT_ID}", f"mode_manual_{PROJECT_ID}", f"mode_import_{PROJECT_ID}"]
    missing = [k for k in mode_keys if not any(getattr(b, "key", None) == k for b in at.button)]
    check("three_mode_buttons", not missing, f"missing={missing}")
except Exception as e:
    import traceback
    check("three_mode_buttons", False, traceback.format_exc()[-500:])

try:
    find(at.button, f"mode_manual_{PROJECT_ID}").click()
    at.run()
    check("manual_mode_no_exception", len(at.exception) == 0, repr(at.exception))
    ps_keys = [d.key for d in at.date_input if getattr(d, "key", "").startswith(f"manual_ps_{PROJECT_ID}_")]
    pe_keys = [d.key for d in at.date_input if getattr(d, "key", "").startswith(f"manual_pe_{PROJECT_ID}_")]
    check("manual_ps_count_12", len(ps_keys) == 12, f"count={len(ps_keys)}")
    check("manual_pe_count_12", len(pe_keys) == 12, f"count={len(pe_keys)}")
    check("manual_save_btn",
          any(getattr(b, "key", None) == f"save_manual_dates_{PROJECT_ID}" for b in at.button),
          "save_manual_dates button missing")
except Exception as e:
    import traceback
    check("manual_mode_flow", False, traceback.format_exc()[-500:])

# 不改数据直接点保存：无异常即通过（此会话结束后不再交互，规避 AppTest 树残留限制）
try:
    find(at.button, f"save_manual_dates_{PROJECT_ID}").click()
    at.run()
    check("manual_save_no_exception", len(at.exception) == 0, repr(at.exception))
except Exception as e:
    import traceback
    check("manual_save_no_exception", False, traceback.format_exc()[-500:])

# 改后恢复：把点保存可能触发的状态重算恢复为快照
restore(proc_before, proj_before)
proc_now, proj_now = snapshot()
if proc_now != proc_before or proj_now != proj_before:
    for x, y in zip(proc_before, proc_now):
        if isinstance(x, dict) and isinstance(y, dict):
            diffs = {k: (x[k], y[k]) for k in x if x[k] != y[k]}
            if diffs:
                print(f"  [DEBUG] proc {x['id']} delta: {diffs}")
    print(f"  [DEBUG] project delta: before={proj_before} now={proj_now}")
check("db_restored_after_save",
      proc_now == proc_before and proj_now == proj_before,
      "DB restored to pre-save snapshot")

# ============================================================
# 会话 B：导入模式 + 切回自动重算（同一会话内模式切换不点保存）
# ============================================================
at2 = AppTest.from_file("pages/2_项目详情.py", default_timeout=120)
at2.session_state["selected_project_id"] = PROJECT_ID
at2.run()
try:
    find(at2.button, f"btn_edit_project_{PROJECT_ID}").click()
    at2.run()
    find(at2.button, f"mode_import_{PROJECT_ID}").click()
    at2.run()
    check("import_mode_no_exception", len(at2.exception) == 0, repr(at2.exception))
    check("import_file_uploader",
          any(getattr(f, "key", None) == f"import_date_file_{PROJECT_ID}" for f in at2.file_uploader),
          "file_uploader missing")
    check("import_template_download",
          any(getattr(d, "key", None) == f"download_template_{PROJECT_ID}" for d in at2.get("download_button")),
          "download_button missing")
except Exception as e:
    import traceback
    check("import_mode_flow", False, traceback.format_exc()[-500:])

try:
    find(at2.button, f"mode_auto_{PROJECT_ID}").click()
    at2.run()
    check("auto_back_no_exception", len(at2.exception) == 0, repr(at2.exception))
    check("auto_edit_start",
          any(getattr(d, "key", None) == f"edit_start_{PROJECT_ID}" for d in at2.date_input),
          "edit_start missing")
    check("auto_edit_end",
          any(getattr(d, "key", None) == f"edit_end_{PROJECT_ID}" for d in at2.date_input),
          "edit_end missing")
    check("auto_edit_factory",
          any(getattr(t, "key", None) == f"edit_factory_{PROJECT_ID}" for t in at2.text_input),
          "edit_factory missing")
except Exception as e:
    import traceback
    check("auto_back_flow", False, traceback.format_exc()[-500:])

failed = [r for r in results if not r[1]]
print("===SUMMARY===")
print(f"TOTAL={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}")
if failed:
    for name, _, detail in failed:
        print(f"  FAILED: {name} | {detail}")
    sys.exit(1)
print("STEP6_PLAN_DATES: ALL PASS")
