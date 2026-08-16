# -*- coding: utf-8 -*-
"""
QA 补充验证 - auto 模式保存链路（AppTest 端到端，快照+恢复）
关注：auto 模式 line 356 all_procs = get_project_processes() 在 clear(364) 之前，
    是否也存在 stale-cache 导致 status/lag 按旧日期重算的问题（疑似 pre-existing）
"""
import os
import sys

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

from streamlit.testing.v1 import AppTest
from database import get_connection, get_project_by_id
from utils import refresh_processes_from_db

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def snapshot(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, process_name, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE project_id=%s ORDER BY id", (pid,))
            procs = cur.fetchall()
            cur.execute("SELECT plan_start_date, plan_end_date, risk_level FROM projects WHERE id=%s", (pid,))
            proj = cur.fetchone()
    finally:
        conn.close()
    return procs, proj


def restore(pid, snap):
    procs, proj = snap
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for p in procs:
                cur.execute(
                    "UPDATE processes SET plan_start_date=%s, plan_end_date=%s, "
                    "status=%s, lag_days=%s WHERE id=%s",
                    (p["plan_start_date"], p["plan_end_date"], p["status"], p["lag_days"], p["id"]))
            cur.execute("UPDATE projects SET plan_start_date=%s, plan_end_date=%s, risk_level=%s WHERE id=%s",
                        (proj["plan_start_date"], proj["plan_end_date"], proj["risk_level"], pid))
            conn.commit()
    finally:
        conn.close()


def db_procs(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, process_name, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE project_id=%s ORDER BY id", (pid,))
            return cur.fetchall()
    finally:
        conn.close()


snap = snapshot(1)
print("快照完成 risk =", snap[1]["risk_level"])
try:
    at = AppTest.from_file("pages/2_项目详情.py", default_timeout=30)
    at.query_params["project_id"] = "1"
    at.run()
    at.button(key="btn_edit_project_1").click().run()
    # auto 是默认模式，直接改 edit_start 并保存
    at.date_input(key="edit_start_1").set_value(__import__("datetime").date(2026, 9, 1)).run()
    at.button(key="save_edit_1").click().run()
    check("auto 保存无异常", len(at.exception) == 0, f"{[str(e.value) for e in at.exception]}")
    # 说明：保存处理内的 st.success("✅ 项目信息已更新") 在 st.rerun() 前发出，AppTest 重渲染后瞬态元素被清空，
    # 无法断言该文案；改而验证保存后重渲染状态：风险区出现「当前无预警/延期工序」= 保存→rerun→风险重算链路成功
    succ = [s.value for s in at.success]
    check("保存后页面重渲染（风险区无预警，间接证明保存成功）",
          any("当前无预警" in t for t in succ), f"success={succ}")

    procs = db_procs(1)
    check("工序计划日期已整体重算到 2026-09", procs[0]["plan_start_date"] == "2026-09-01",
          f"proc1 ps={procs[0]['plan_start_date']}")

    # status/lag 一致性：与"新日期"理论值对比
    from database import get_project_processes
    import streamlit as st
    st.cache_data.clear()
    fresh = get_project_processes(1)
    exp = {p["id"]: p for p in refresh_processes_from_db(fresh)}
    mism = []
    for p in procs:
        if p["status"] != exp[p["id"]]["status"] or p["lag_days"] != exp[p["id"]]["lag_days"]:
            mism.append(f"proc{p['id']}: db(status={p['status']},lag={p['lag_days']}) "
                        f"期望(status={exp[p['id']]['status']},lag={exp[p['id']]['lag_days']})")
    check("auto 保存后 status/lag 按新日期一致", len(mism) == 0, f"mismatch={mism}")
finally:
    restore(1, snap)
    import streamlit as st
    st.cache_data.clear()
    now = db_procs(1)
    ok = all(p == o for p, o in zip(now, snap[0]))
    proj_now = get_project_by_id(1)
    check("恢复后全量快照一致（DB 纯净）", ok and proj_now["risk_level"] == snap[1]["risk_level"],
          f"risk={proj_now['risk_level']}")

passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== auto 保存链路补充验证: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
