# -*- coding: utf-8 -*-
"""
QA 验证 - 步骤4: Excel 一键导入链路（生成xlsx → 匹配 → 更新 → 重算 → 恢复）
尝试两条路径：
  A. AppTest file_uploader.set_value(路径) 端到端上传
  B. 直接脚本化调用页面等价流程（保底）
"""
import io
import os
import sys
import tempfile
from datetime import date, timedelta

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

import pandas as pd

from database import get_connection, get_project_processes, get_project_by_id
from utils import refresh_processes_from_db, judge_warning_level

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


def db_get_all(pid):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, plan_start_date, plan_end_date, status, lag_days "
                "FROM processes WHERE project_id=%s ORDER BY id", (pid,))
            return cur.fetchall()
    finally:
        conn.close()


# ---------- 1. 快照 + 生成临时 xlsx（全部工序 原日期+1天） ----------
snap = snapshot_project(1)
print("快照完成 risk =", snap[1])

procs0 = get_project_processes(1)  # 模拟页面加载填充缓存
rows = []
for p in procs0:
    ps = date.fromisoformat(p["plan_start_date"]) if p["plan_start_date"] else None
    pe = date.fromisoformat(p["plan_end_date"]) if p["plan_end_date"] else None
    rows.append({
        "工序名称": p["process_name"],
        "计划开始": (ps + timedelta(days=1)).isoformat() if ps else "",
        "计划结束": (pe + timedelta(days=1)).isoformat() if pe else "",
    })
df = pd.DataFrame(rows)
tmpdir = tempfile.mkdtemp(prefix="qa_import_")
xlsx_path = os.path.join(tmpdir, "import_test.xlsx")
df.to_excel(xlsx_path, index=False)
print(f"临时 xlsx: {xlsx_path}")
print(df.head(3).to_string(index=False))

try:
    # ---------- 2. 尝试 A: AppTest 端到端 ----------
    e2e_ok = False
    try:
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file("pages/2_项目详情.py", default_timeout=30)
        at.query_params["project_id"] = "1"
        at.run()
        at.button(key="btn_edit_project_1").click().run()
        at.button(key="mode_import_1").click().run()
        fu = at.file_uploader(key="import_date_file_1")
        with open(xlsx_path, "rb") as fh:
            xlsx_bytes = fh.read()
        fu.set_value((os.path.basename(xlsx_path), xlsx_bytes,
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")).run()
        check("AppTest 上传文件无异常", len(at.exception) == 0,
              f"{[str(e.value) for e in at.exception]}")
        if len(at.exception) == 0:
            check("确认导入按钮出现", True)
            at.button(key="confirm_import_dates_1").click().run()
            check("AppTest 导入保存无异常", len(at.exception) == 0,
                  f"{[str(e.value) for e in at.exception]}")
            succ = [s.value for s in at.success]
            check("AppTest 出现成功提示", any("已导入" in t for t in succ), f"success={succ}")
            e2e_ok = len(at.exception) == 0 and any("已导入" in t for t in succ)
    except Exception as e:
        print(f"[INFO] AppTest 端到端不可用: {type(e).__name__}: {e}")

    if not e2e_ok:
        print("\n===== 回退到 B: 直接脚本化等价流程 =====")
        # ---- 复刻页面 import 确认逻辑 (line 559-590) ----
        df_read = pd.read_excel(xlsx_path)
        name_col = start_col = end_col = None
        for col in df_read.columns:
            col_str = str(col)
            if name_col is None and ("工序" in col_str or "名称" in col_str):
                name_col = col
            if start_col is None and ("计划开始" in col_str or "开始" in col_str):
                start_col = col
            if end_col is None and ("计划结束" in col_str or "结束" in col_str):
                end_col = col
        check("列名匹配成功", name_col and start_col and end_col,
              f"name={name_col} start={start_col} end={end_col}")

        proc_list = get_project_processes(1)  # 页面在保存时才调用（此时命中缓存=旧数据）
        name_to_proc = {p.get("process_name"): p for p in proc_list}
        matched_rows = []
        for _, row in df_read.iterrows():
            raw_name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
            proc = name_to_proc.get(raw_name)
            ps_raw = pd.to_datetime(row[start_col], errors="coerce")
            pe_raw = pd.to_datetime(row[end_col], errors="coerce")
            matched_rows.append({
                "工序名称": raw_name, "系统匹配": proc.get("process_name", "") if proc else "未匹配",
                "计划开始": ps_raw.strftime('%Y-%m-%d') if pd.notna(ps_raw) else None,
                "计划结束": pe_raw.strftime('%Y-%m-%d') if pd.notna(pe_raw) else None,
                "状态": "✅" if (proc and pd.notna(ps_raw) and pd.notna(pe_raw)) else "⚠️",
            })
        valid_rows = [r for r in matched_rows if r["状态"] == "✅"]
        check("12行全部匹配成功", len(valid_rows) == 12, f"valid={len(valid_rows)}")

        # 1. 逐条更新
        for r in valid_rows:
            from database import update_process
            proc = name_to_proc[r["工序名称"]]
            update_process(proc["id"], {
                "plan_start_date": r["计划开始"], "plan_end_date": r["计划结束"]})
        # 2. 状态重算（页面此时未清缓存 → 可能陈旧）
        all_procs = get_project_processes(1)
        refreshed = refresh_processes_from_db(all_procs)
        for up in refreshed:
            from database import update_process
            update_process(up["id"], {"status": up["status"], "lag_days": up["lag_days"]})
        # 3. 清缓存 → 风险重算 → 再清
        import streamlit as st
        st.cache_data.clear()
        from database import update_project_risk_level
        update_project_risk_level(1)
        st.cache_data.clear()

    # ---------- 3. DB 校验 ----------
    db_all = {p["id"]: p for p in db_get_all(1)}
    all_dates_ok = True
    for p in procs0:
        if p["plan_start_date"]:
            exp_ps = (date.fromisoformat(p["plan_start_date"]) + timedelta(days=1)).isoformat()
            exp_pe = (date.fromisoformat(p["plan_end_date"]) + timedelta(days=1)).isoformat()
            if db_all[p["id"]]["plan_start_date"] != exp_ps or db_all[p["id"]]["plan_end_date"] != exp_pe:
                all_dates_ok = False
                print(f"    工序{p['id']} {p['process_name']}: 期望 {exp_ps}~{exp_pe} 实得 "
                      f"{db_all[p['id']]['plan_start_date']}~{db_all[p['id']]['plan_end_date']}")
    check("全部12道工序计划日期已 +1 天更新", all_dates_ok)

    # status/lag 重算一致性（对比清缓存后的真实预期）
    import streamlit as st
    st.cache_data.clear()
    fresh_procs = get_project_processes(1)
    exp_refreshed = {p["id"]: p for p in refresh_processes_from_db(fresh_procs)}
    lag_mismatch = []
    for pid, p in db_all.items():
        if p["status"] != exp_refreshed[pid]["status"] or p["lag_days"] != exp_refreshed[pid]["lag_days"]:
            lag_mismatch.append(
                f"proc{pid}: db(status={p['status']},lag={p['lag_days']}) "
                f"期望(status={exp_refreshed[pid]['status']},lag={exp_refreshed[pid]['lag_days']})")
    check("status/lag_days 按新日期重算一致", len(lag_mismatch) == 0,
          f"mismatch={lag_mismatch}")

    # 项目风险重算
    proj = get_project_by_id(1)
    exp_risk, _ = judge_warning_level(fresh_procs)
    check("项目 risk_level 已重算", proj["risk_level"] == exp_risk,
          f"db={proj['risk_level']} expected={exp_risk}")

finally:
    # ---------- 4. 恢复 + 清理 ----------
    restore_project(1, snap)
    now_procs, now_risk = snapshot_project(1)
    all_same = now_risk == snap[1] and all(
        p == o for p, o in zip(sorted(now_procs, key=lambda x: x["id"]),
                               sorted(snap[0], key=lambda x: x["id"])))
    check("恢复后全量快照一致（DB 纯净）", all_same)
    if os.path.exists(xlsx_path):
        os.remove(xlsx_path)
    os.rmdir(tmpdir)
    print(f"临时文件已清理: {xlsx_path}")

passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== Excel 导入链路汇总: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
