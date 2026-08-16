# -*- coding: utf-8 -*-
"""
QA 复现 - 手工保存 status/lag_days 陈旧缓存问题
模拟页面流程（与 pages/2_项目详情.py manual 保存逻辑一致）：
  页面加载 get_project_processes 填充缓存 → update_process 改日期 →
  再 get_project_processes（命中缓存返回旧数据）→ refresh → 写回 status/lag
"""
import os
import sys

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

from database import get_connection, get_project_processes, update_process, update_project_risk_level
from utils import refresh_processes_from_db

PID = 3  # 卷板: 原 plan_end=2026-08-05, status=delayed, lag=7
NEW_PS = "2026-08-07"
NEW_PE = "2026-08-07"

# ---- 快照 ----
conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT id, plan_start_date, plan_end_date, status, lag_days FROM processes WHERE project_id=1 ORDER BY id")
        snap = cur.fetchall()
        cur.execute("SELECT risk_level FROM projects WHERE id=1")
        snap_risk = cur.fetchone()["risk_level"]
finally:
    conn.close()

print("=== 快照 ===")
print("proc3 orig:", snap[2])

try:
    # ---- 1. 模拟页面加载（填充缓存）----
    procs0 = get_project_processes(1)
    print("\n=== 1. 页面加载 get_project_processes(1) → 缓存填充 ===")
    print("proc3 cache:", next(p for p in procs0 if p['id'] == PID)['plan_end_date'])

    # ---- 2. 手工保存: 先 update_process 改日期 ----
    update_process(PID, {"plan_start_date": NEW_PS, "plan_end_date": NEW_PE})
    print("\n=== 2. update_process 已写入新日期 ===")

    # ---- 3. 页面保存流程: 再 get_project_processes (同页面未清缓存) ----
    all_procs = get_project_processes(1)
    p3 = next(p for p in all_procs if p['id'] == PID)
    print("\n=== 3. 保存流程中再 get_project_processes(1) ===")
    print(f"proc3 plan_end 读到: {p3['plan_end_date']}  (期望新值 {NEW_PE}，命中缓存则旧值 2026-08-05)")
    stale = p3['plan_end_date'] != NEW_PE

    refreshed = refresh_processes_from_db(all_procs)
    r3 = next(p for p in refreshed if p['id'] == PID)
    print(f"refresh 结果: status={r3['status']} lag_days={r3['lag_days']} (基于读到数据)")

    # 写回
    for up in refreshed:
        update_process(up["id"], {"status": up["status"], "lag_days": up["lag_days"]})

    # ---- 4. 清缓存后重读（页面第3步 risk 重算路径）----
    st = __import__("streamlit")
    st.cache_data.clear()
    fresh = get_project_processes(1)
    f3 = next(p for p in fresh if p['id'] == PID)
    freshed = refresh_processes_from_db(fresh)
    fr3 = next(p for p in freshed if p['id'] == PID)
    print("\n=== 4. 清缓存后重读 ===")
    print(f"proc3 plan_end 读到: {f3['plan_end_date']}  → refresh: status={fr3['status']} lag_days={fr3['lag_days']}")
    update_project_risk_level(1)

    # ---- 5. 落库对比 ----
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT plan_start_date, plan_end_date, status, lag_days FROM processes WHERE id=%s", (PID,))
            db3 = cur.fetchone()
    finally:
        conn.close()
    print("\n=== 5. 最终落库 ===")
    print(f"proc3 落库: {db3}")
    print(f"一致性判定: plan日期已新({db3['plan_end_date']==NEW_PE}) 但 lag_days 基于旧日期({db3['lag_days']})")
finally:
    # ---- 恢复 ----
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for p in snap:
                cur.execute("UPDATE processes SET plan_start_date=%s, plan_end_date=%s, status=%s, lag_days=%s WHERE id=%s",
                            (p["plan_start_date"], p["plan_end_date"], p["status"], p["lag_days"], p["id"]))
            cur.execute("UPDATE projects SET risk_level=%s WHERE id=1", (snap_risk,))
            conn.commit()
    finally:
        conn.close()
    st = __import__("streamlit")
    st.cache_data.clear()
    print("\n=== 已恢复快照 ===")
