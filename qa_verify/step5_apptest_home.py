# -*- coding: utf-8 -*-
"""QA Step5-home: AppTest 首页回归
验证：项目列表（10条）、统计卡片、风险筛选、搜索、无异常
"""
import os
import sys

PROJECT_ROOT = r"E:\budy date\project one\tower_production_system"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

import streamlit as st
from streamlit.testing.v1 import AppTest

st.cache_data.clear()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'} | {name} | {detail}")


at = AppTest.from_file("app.py", default_timeout=90)
at.run()
check("home_initial_run_no_exception", len(at.exception) == 0, repr(at.exception))

# --- 统计卡片 ---
try:
    metrics = {m.label: m.value for m in at.metric}
    print("METRICS_DICT:", metrics)
    check("home_metrics_present", len(metrics) >= 4, str(metrics))
    check("home_total_projects_10", str(metrics.get("在产项目总数")) == "10",
          f"got={metrics.get('在产项目总数')!r}")
    for label in ["预警项目", "延期项目", "本月计划出品总量"]:
        check(f"home_metric_{label}", label in metrics, repr(metrics.get(label)))
except Exception as e:
    check("home_metrics_parse", False, repr(e))

# --- 项目列表（分页文本）---
try:
    md_texts = [md.value for md in at.markdown]
    pag = [t for t in md_texts if "条项目记录" in t]
    check("home_pagination_text", len(pag) > 0, repr(pag[:1]))
    if pag:
        check("home_project_count_10", "共 10 条项目记录" in pag[0], pag[0])
except Exception as e:
    check("home_pagination_parse", False, repr(e))

# --- 风险筛选：延期 ---
try:
    at.selectbox(key="project_risk_filter").set_value("延期")
    at.run()
    check("home_risk_filter_no_exception", len(at.exception) == 0, repr(at.exception))
except Exception as e:
    check("home_risk_filter", False, repr(e))

# --- 搜索：明阳 ---
try:
    at.text_input(key="project_search").set_value("明阳")
    at.run()
    check("home_search_no_exception", len(at.exception) == 0, repr(at.exception))
except Exception as e:
    check("home_search", False, repr(e))

# --- 实时风险函数直查（DATEDIFF 语法）---
try:
    from database import get_all_projects, get_dashboard_stats
    st.cache_data.clear()
    projs = get_all_projects()
    stats = get_dashboard_stats()
    check("db_get_all_projects_ok", isinstance(projs, list), f"len={len(projs)}")
    check("db_get_dashboard_stats_ok", isinstance(stats, dict), repr(stats))
    risk_types = {p.get("risk_level") for p in projs}
    check("db_risk_levels_valid", risk_types <= {"normal", "warning", "delayed"}, str(risk_types))
except Exception as e:
    import traceback
    check("db_functions", False, traceback.format_exc()[-800:])

failed = [r for r in results if not r[1]]
print("===SUMMARY===")
print(f"TOTAL={len(results)} PASS={len(results)-len(failed)} FAIL={len(failed)}")
if failed:
    for name, _, detail in failed:
        print(f"  FAILED: {name} | {detail}")
    sys.exit(1)
print("STEP5_HOME: ALL PASS")
