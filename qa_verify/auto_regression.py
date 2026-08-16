# -*- coding: utf-8 -*-
"""
QA 验证 - 步骤5: 自动重算回归
验证 auto 模式保存链路：regenerate_process_plan → refresh status/lag → risk 重算
（快照全部工序 + 项目字段，验证后恢复，避免污染）
"""
import os
import sys

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

from database import (
    get_connection, get_project_processes, update_process,
    update_project_risk_level, regenerate_process_plan,
)
from utils import refresh_processes_from_db, judge_warning_level

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def snapshot(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, process_order, process_name, standard_days, plan_start_date, "
                "plan_end_date, status, lag_days FROM processes WHERE project_id=%s ORDER BY id", (pid,))
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
                    "UPDATE processes SET process_name=%s, standard_days=%s, "
                    "plan_start_date=%s, plan_end_date=%s, status=%s, lag_days=%s WHERE id=%s",
                    (p["process_name"], p["standard_days"], p["plan_start_date"],
                     p["plan_end_date"], p["status"], p["lag_days"], p["id"]))
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
                "SELECT id, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE project_id=%s ORDER BY process_order", (pid,))
            return cur.fetchall()
    finally:
        conn.close()


# ---------- 1. 快照 ----------
snap = snapshot(1)
print("快照完成，project plan_start =", snap[1]["plan_start_date"], "risk =", snap[1]["risk_level"])

try:
    # ---------- 2. 回归A：同日期重算（确定性回归，不改数据） ----------
    import streamlit as st
    st.cache_data.clear()
    n = regenerate_process_plan(1, snap[1]["plan_start_date"])
    check("同日期 regenerate 返回12", n == 12, f"n={n}")
    now_procs = db_procs(1)
    same_dates = all(
        p["plan_start_date"] == o["plan_start_date"] and p["plan_end_date"] == o["plan_end_date"]
        for p, o in zip(now_procs, snap[0]))
    check("同日期重算后计划日期不变（确定性）", same_dates)

    # ---------- 3. 回归B：新开工日期 2026-09-01 重算（模拟 auto 保存链路） ----------
    NEW_START = "2026-09-01"
    n2 = regenerate_process_plan(1, NEW_START)
    check("新日期 regenerate 返回12", n2 == 12, f"n={n2}")
    now_procs = db_procs(1)
    check("工序1(下料) plan_start == 新开工日期", now_procs[0]["plan_start_date"] == NEW_START,
          f"got={now_procs[0]['plan_start_date']}")
    # 验证所有工序日期均为 2026-09 之后（整体平移）
    all_after = all(
        (p["plan_start_date"] or "") >= NEW_START and (p["plan_end_date"] or "") >= NEW_START
        for p in now_procs)
    check("全部工序日期 >= 新开工日期（整体平移）", all_after)

    # 页面保存链路后续步骤：refresh status/lag + risk 重算
    st.cache_data.clear()
    all_procs = get_project_processes(1)
    refreshed = refresh_processes_from_db(all_procs)
    for up in refreshed:
        update_process(up["id"], {"status": up["status"], "lag_days": up["lag_days"]})
    st.cache_data.clear()
    update_project_risk_level(1)
    st.cache_data.clear()

    # 校验 status/lag 与当前日期一致
    final_procs = db_procs(1)
    fresh = get_project_processes(1)
    exp = {p["id"]: p for p in refresh_processes_from_db(fresh)}
    ok = all(final_procs[i]["status"] == exp[final_procs[i]["id"]]["status"]
             and final_procs[i]["lag_days"] == exp[final_procs[i]["id"]]["lag_days"]
             for i in range(len(final_procs)))
    check("重算后 status/lag_days 与期望一致", ok)
    print("    工序1 重算结果:", final_procs[0]["status"], final_procs[0]["lag_days"])

    # 风险重算
    from database import get_project_by_id
    exp_risk, _ = judge_warning_level(fresh)
    proj = get_project_by_id(1)
    check("项目 risk_level 已重算", proj["risk_level"] == exp_risk,
          f"db={proj['risk_level']} expected={exp_risk}")
finally:
    # ---------- 4. 恢复 ----------
    restore(1, snap)
    now_procs, now_proj = snapshot(1)
    ok = all(p == o for p, o in zip(now_procs, snap[0])) and now_proj == snap[1]
    check("恢复后全量快照一致（DB 纯净）", ok)
    import streamlit as st
    st.cache_data.clear()

passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== 自动重算回归汇总: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
