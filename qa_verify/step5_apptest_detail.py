# -*- coding: utf-8 -*-
"""QA Step5-detail: AppTest 详情页回归
验证：6 Tab 渲染、工序明细表头、更新工序进度弹窗、保存日报、DB 持久化
"""
import os
import sys
from datetime import date, datetime

PROJECT_ROOT = r"E:\budy date\project one\tower_production_system"
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


def mysql_one(sql, params=None):
    conn = pymysql.connect(
        host="127.0.0.1", port=3306, user="root", password="123456",
        database="tower_production", charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        conn.close()


TODAY = date.today().strftime('%Y-%m-%d')
PROJECT_ID = 1
# 更新进度目标工序：process 5（组对，计划 08-08 ~ 08-09）
TARGET_PROC = 5
NEW_END = "2026-08-10"

at = AppTest.from_file("pages/2_项目详情.py", default_timeout=90)
at.session_state["selected_project_id"] = PROJECT_ID
at.run()
check("detail_initial_no_exception", len(at.exception) == 0, repr(at.exception))

# --- 项目标题 ---
try:
    titles = [t.value for t in at.title]
    check("detail_title_rendered", len(titles) > 0, repr(titles[:1]))
except Exception as e:
    check("detail_title", False, repr(e))

# --- 6 Tab 渲染 ---
try:
    tab_labels = [t.label for t in at.tabs]
    print("TABS:", tab_labels)
    expected_tabs = ["工序甘特图", "工序明细", "风险与异常", "里程碑倒排", "每日进度填报", "每日执行看板"]
    missing = [x for x in expected_tabs if not any(x in lbl for lbl in tab_labels)]
    check("detail_6_tabs", len(tab_labels) >= 6 and not missing, f"tabs={tab_labels} missing={missing}")
except Exception as e:
    check("detail_6_tabs", False, repr(e))

# --- 工序明细表头 ---
try:
    md_texts = [m.value for m in at.markdown]
    header_hits = [h for h in ["工序名称", "计划开始", "计划结束", "实际完成时间", "状态", "偏差", "操作"] if any(h in t for t in md_texts)]
    check("detail_process_headers", len(header_hits) >= 6, str(header_hits))
except Exception as e:
    check("detail_process_headers", False, repr(e))

# --- 顶部风险标签与工序明细一致性（风险等级标签出现在 info card 的 markdown 中） ---
try:
    risk_key = f"update_proc_{TARGET_PROC}"
    check("detail_update_btn_exists", any(getattr(b, "key", None) == risk_key for b in at.button),
          f"key={risk_key}")
except Exception as e:
    check("detail_update_btn_exists", False, repr(e))

# ============ 更新工序进度弹窗 ============
try:
    find(at.button, f"update_proc_{TARGET_PROC}").click()
    at.run()
    check("detail_modal_open_no_exception", len(at.exception) == 0, repr(at.exception))
    di = find(at.date_input, f"upd_end_proc_{TARGET_PROC}")
    di.set_value(date(2026, 8, 10))
    at.run()
    check("detail_modal_setdate_no_exception", len(at.exception) == 0, repr(at.exception))
    find(at.button, f"save_proc_{TARGET_PROC}").click()
    at.run()
    check("detail_save_progress_no_exception", len(at.exception) == 0, repr(at.exception))
    row = mysql_one("SELECT actual_end_date, status, lag_days, completion_pct FROM processes WHERE id=%s", (TARGET_PROC,))
    print("PROC_AFTER_UPDATE:", row)
    check("detail_progress_persisted",
          row and row["actual_end_date"] == NEW_END and row["status"] == "completed",
          repr(row))
except Exception as e:
    import traceback
    check("detail_update_progress_flow", False, traceback.format_exc()[-800:])

# ============ 保存日报 ============
try:
    # 对 process 3（卷板，进行中/延期，今日应执行）填实际值
    target_daily_proc = 3
    ni = find(at.number_input, f"daily_qty_{target_daily_proc}_{TODAY}")
    ni.set_value(1.0)
    at.run()
    find(at.button, "save_daily").click()
    at.run()
    check("detail_save_daily_no_exception", len(at.exception) == 0, repr(at.exception))
    cnt = mysql_one(
        "SELECT COUNT(*) AS c FROM daily_progress WHERE project_id=%s AND report_date=%s",
        (PROJECT_ID, TODAY),
    )
    print("DAILY_ROW_COUNT:", cnt)
    check("detail_daily_saved", cnt and cnt["c"] > 0, repr(cnt))
    drow = mysql_one(
        "SELECT actual_qty, daily_status FROM daily_progress WHERE process_id=%s AND report_date=%s",
        (target_daily_proc, TODAY),
    )
    print("DAILY_PROC3:", drow)
    check("detail_daily_proc3_value", drow and float(drow["actual_qty"]) == 1.0, repr(drow))
except Exception as e:
    import traceback
    check("detail_save_daily_flow", False, traceback.format_exc()[-800:])

failed = [r for r in results if not r[1]]
print("===SUMMARY===")
print(f"TOTAL={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}")
if failed:
    for name, _, detail in failed:
        print(f"  FAILED: {name} | {detail}")
    sys.exit(1)
print("STEP5_DETAIL: ALL PASS")
