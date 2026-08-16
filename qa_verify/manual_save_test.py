# -*- coding: utf-8 -*-
"""
QA 验证 - 步骤3: 手工修改日期保存真实链路（AppTest 端到端 + DB 校验 + 恢复）
流程：
  1. 快照 project 1 全部 12 道工序 (plan_start/plan_end/status/lag_days) + 项目 risk_level
  2. AppTest: 编辑项目 → manual 模式 → 将工序3(卷板) ps/pe 各推后2天(2026-08-05→2026-08-07)
  3. 点「💾 保存工序日期」→ 校验 DB: 工序3日期已更新、status/lag_days 重算、项目 risk_level 重算
  4. 恢复快照，校验纯净
"""
import os
import sys
from datetime import date

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

from streamlit.testing.v1 import AppTest
from database import get_connection, get_project_processes, get_project_by_id

TARGET_PROC_ID = 3          # 卷板
NEW_PS = date(2026, 8, 7)   # 原 2026-08-05 + 2 天
NEW_PE = date(2026, 8, 7)   # 原 2026-08-05 + 2 天

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def snapshot_project(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE project_id=%s ORDER BY id", (pid,))
            procs = cur.fetchall()
            cur.execute("SELECT risk_level FROM projects WHERE id=%s", (pid,))
            risk = cur.fetchone()["risk_level"]
    finally:
        conn.close()
    return procs, risk


def restore_project(pid, snap):
    procs, risk = snap
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for p in procs:
                cur.execute(
                    "UPDATE processes SET plan_start_date=%s, plan_end_date=%s, "
                    "status=%s, lag_days=%s WHERE id=%s",
                    (p["plan_start_date"], p["plan_end_date"], p["status"], p["lag_days"], p["id"]))
            cur.execute("UPDATE projects SET risk_level=%s WHERE id=%s", (risk, pid))
            conn.commit()
    finally:
        conn.close()


def db_get_proc(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE id=%s", (pid,))
            return cur.fetchone()
    finally:
        conn.close()


def db_get_project(pid):
    return get_project_by_id(pid)


# ---------- 1. 快照 ----------
snap = snapshot_project(1)
print("快照完成，项目 risk_level =", snap[1])
try:
    # ---------- 2. AppTest 手工修改并保存 ----------
    at = AppTest.from_file("pages/2_项目详情.py", default_timeout=30)
    at.query_params["project_id"] = "1"
    at.run()
    check("页面加载无异常", len(at.exception) == 0, f"{[str(e.value) for e in at.exception]}")

    at.button(key="btn_edit_project_1").click().run()
    at.button(key="mode_manual_1").click().run()
    check("manual 模式切换无异常", len(at.exception) == 0)

    # 修改工序3 ps/pe（推后2天，ps<=pe）
    at.date_input(key=f"manual_ps_1_{TARGET_PROC_ID}").set_value(NEW_PS).run()
    at.date_input(key=f"manual_pe_1_{TARGET_PROC_ID}").set_value(NEW_PE).run()
    check("date_input 设置无异常", len(at.exception) == 0,
          f"{[str(e.value) for e in at.exception]}")

    at.button(key="save_manual_dates_1").click().run()
    check("保存无异常", len(at.exception) == 0, f"{[str(e.value) for e in at.exception]}")
    success_texts = [s.value for s in at.success]
    check("出现成功提示", any("工序日期已保存" in t for t in success_texts),
          f"success={success_texts}")

    # ---------- 3. DB 校验 ----------
    p3 = db_get_proc(TARGET_PROC_ID)
    check("工序3 plan_start_date 已更新", p3["plan_start_date"] == "2026-08-07",
          f"got={p3['plan_start_date']}")
    check("工序3 plan_end_date 已更新", p3["plan_end_date"] == "2026-08-07",
          f"got={p3['plan_end_date']}")

    # status/lag_days 重算一致性：以 refresh_processes_from_db 当前结果为准
    from utils import refresh_processes_from_db
    all_procs = get_project_processes(1)
    refreshed = {p["id"]: p for p in refresh_processes_from_db(all_procs)}
    r3 = refreshed[TARGET_PROC_ID]
    check("工序3 status 已重算", p3["status"] == r3["status"],
          f"db={p3['status']} expected={r3['status']}")
    check("工序3 lag_days 已重算", p3["lag_days"] == r3["lag_days"],
          f"db={p3['lag_days']} expected={r3['lag_days']}")
    print(f"    工序3 重算结果: status={p3['status']} lag_days={p3['lag_days']} "
          f"(推后2天，原 delayed/7)")

    # 其余工序不应被手工保存误改日期（status 可能因重算变化，属正常）
    for p in all_procs:
        if p["id"] != TARGET_PROC_ID:
            orig = next(x for x in snap[0] if x["id"] == p["id"])
            check(f"工序{p['id']} 计划日期未被误改",
                  p["plan_start_date"] == orig["plan_start_date"]
                  and p["plan_end_date"] == orig["plan_end_date"],
                  f"db_ps={p['plan_start_date']} orig_ps={orig['plan_start_date']}")

    # 项目 risk_level 重算（注意：与快照一致也是合法的，只要与当前数据一致）
    proj = db_get_project(1)
    from utils import judge_warning_level
    exp_risk, _ = judge_warning_level(get_project_processes(1))
    check("项目 risk_level 已重算", proj["risk_level"] == exp_risk,
          f"db={proj['risk_level']} expected={exp_risk}")
finally:
    # ---------- 4. 恢复 ----------
    restore_project(1, snap)
    p3r = db_get_proc(TARGET_PROC_ID)
    projr = db_get_project(1)
    check("工序3 已恢复原日期", p3r["plan_start_date"] == snap[0][2]["plan_start_date"]
          and p3r["plan_end_date"] == snap[0][2]["plan_end_date"],
          f"ps={p3r['plan_start_date']} pe={p3r['plan_end_date']}")
    check("工序3 已恢复原 status/lag",
          p3r["status"] == snap[0][2]["status"] and p3r["lag_days"] == snap[0][2]["lag_days"],
          f"status={p3r['status']} lag={p3r['lag_days']}")
    check("项目 risk_level 已恢复", projr["risk_level"] == snap[1],
          f"risk={projr['risk_level']}")

    # 全量比对恢复
    now_procs, now_risk = snapshot_project(1)
    all_same = now_risk == snap[1] and all(
        p == o for p, o in zip(sorted(now_procs, key=lambda x: x["id"]),
                               sorted(snap[0], key=lambda x: x["id"])))
    check("全量快照比对一致（DB 纯净）", all_same)

passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== 手工保存链路汇总: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
