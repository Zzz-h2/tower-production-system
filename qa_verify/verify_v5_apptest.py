# -*- coding: utf-8 -*-
"""
QA v5 验证：页面 AppTest（pages/2_项目详情.py + app.py 首页）
Phase A: project 1 回归 —— 6 Tab 渲染、甘特 plotly、工序表头、风险异常、里程碑、
         编辑弹窗、导入入口(file_uploader+确认导入按钮)、节点计划/预警空态
Phase B: 测试项目 999998 —— 节点计划指标/时间轴/分组列表、节点预警四态计数+红黄列表、
         填报 selectbox→number_input→保存链路、排产导入 confirm 链路；验证后清理
用法: MYSQL_PASSWORD=123456 python qa_verify/verify_v5_apptest.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("MYSQL_PASSWORD", "123456")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from streamlit.testing.v1 import AppTest

import database as db

TODAY = date.today()
print(f"TODAY={TODAY}")

RESULTS = []
PASS = []
FAIL = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    if cond:
        PASS.append(name)
        print(f"  PASS {name} {detail}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name} {detail}")


def exists(at, kind, key):
    try:
        getattr(at, kind)(key=key)
        return True
    except KeyError:
        return False


def sql_count(sql, params=None):
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute(sql, params)
            return c.fetchone()['n']
    finally:
        conn.close()


# ============================================================
# Phase A: project 1 回归
# ============================================================
print("== Phase A: project 1 回归 ==")
at1 = AppTest.from_file("pages/2_项目详情.py", default_timeout=90)
at1.session_state["selected_project_id"] = 1
at1.run()
check("A1 页面加载无异常", len(at1.exception) == 0,
      f"exceptions={[str(e.value) for e in at1.exception]}")

tab_labels = [t.label for t in at1.tabs]
print("  TABS:", tab_labels)
expected_tabs = ["工序甘特图", "工序明细", "风险与异常", "里程碑倒排", "节点计划", "节点预警"]
missing = [x for x in expected_tabs if not any(x in lbl for lbl in tab_labels)]
check("A2 六个Tab齐全", len(tab_labels) >= 6 and not missing, f"missing={missing}")

# 甘特图 plotly
n_plotly = len(at1.get("plotly_chart"))
check("A3 甘特图 plotly 渲染", n_plotly >= 1, f"plotly_charts={n_plotly}")

# 工序明细表头
md_texts = [m.value for m in at1.markdown]
header_hits = [h for h in ["工序名称", "计划开始", "计划结束", "实际完成时间", "状态", "偏差"]
               if any(h in t for t in md_texts)]
check("A4 工序明细表头", len(header_hits) >= 5, f"hits={header_hits}")

# 风险异常 tab：全局提报 selectbox 存在
check("A5 风险异常-关联工序selectbox", exists(at1, "selectbox", "global_anom_proc"))

# 里程碑倒排（st.subheader → at.subheader）
check("A6 里程碑倒排标题",
      any("里程碑倒排" in s.value for s in at1.subheader),
      f"subheaders={[s.value for s in at1.subheader]}")

# 编辑项目弹窗
check("A7 编辑按钮存在", exists(at1, "button", "btn_edit_project_1"))
try:
    at1.button(key="btn_edit_project_1").click()
    at1.run()
    check("A8 编辑弹窗打开无异常", len(at1.exception) == 0)
    check("A8b 编辑弹窗含日期/文本控件", exists(at1, "date_input", "edit_start_1")
          and exists(at1, "text_input", "edit_factory_1"))
except Exception as e:
    check("A8 编辑弹窗打开无异常", False, repr(e))

# 导入入口（file_uploader + 上传后确认导入按钮）
check("A9 导入 file_uploader 存在", exists(at1, "file_uploader", "node_schedule_upload_1"))
try:
    xlsx_path = os.path.join(PROJECT_ROOT, "qa_verify", "test_schedule_matrix.xlsx")
    with open(xlsx_path, "rb") as fh:
        content = fh.read()
    at1.file_uploader(key="node_schedule_upload_1").upload("test_schedule_matrix.xlsx", content)
    at1.run()
    check("A10 上传后无异常", len(at1.exception) == 0,
          f"exceptions={[str(e.value) for e in at1.exception]}")
    check("A10b 确认导入按钮出现", exists(at1, "button", "confirm_node_schedule_1"))
except Exception as e:
    check("A10 上传后无异常", False, repr(e))
    check("A10b 确认导入按钮出现", False, "")

# 节点计划/预警空态（st.info → at.info；project 1 当前无节点计划，且未点确认导入 → 无写库）
info_texts = [i.value for i in at1.info]
check("A11 节点计划空态提示", any("暂无工序节点计划" in t for t in info_texts),
      f"infos={info_texts[:3]}")

# 首页 app.py 项目列表
print("== Phase A2: 首页 app.py ==")
at_home = AppTest.from_file("app.py", default_timeout=90)
at_home.run()
check("A12 首页加载无异常", len(at_home.exception) == 0,
      f"exceptions={[str(e.value) for e in at_home.exception]}")
home_text = " ".join([m.value for m in at_home.markdown])
check("A13 首页含项目列表", len(at_home.dataframe) >= 1 or "国能投" in home_text,
      f"dataframes={len(at_home.dataframe)}")

# ============================================================
# Phase B: 测试项目 999998（写库全部使用测试 project_id，验证后清理）
# ============================================================
print("== Phase B: 测试项目 999998 ==")
TEST_PID = 999998
today_str = TODAY.strftime("%Y-%m-%d")


def cleanup_999998():
    conn = db.get_connection()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM node_actual_progress WHERE project_id=%s", (TEST_PID,))
            c.execute("DELETE FROM process_node_plans WHERE project_id=%s", (TEST_PID,))
            c.execute("DELETE FROM projects WHERE id=%s", (TEST_PID,))
        conn.commit()
    finally:
        conn.close()


cleanup_999998()  # 清残留

# 建测试项目（显式 id 999998，带 12 道工序）
conn = db.get_connection()
try:
    with conn.cursor() as c:
        now = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        c.execute("""
            INSERT INTO projects
                (id, project_name, factory_name, monthly_plan, delivery_person,
                 plan_start_date, plan_end_date, created_at, updated_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (TEST_PID, "QA_TMP_NODE_PLAN_999998", "QA工厂", 10, "QA验证",
              "2026-08-01", "2026-09-30", now, now))
    conn.commit()
finally:
    conn.close()
db.init_project_processes(TEST_PID, "2026-08-01")

# 种子节点计划（四态齐全）: 钢板到货 done+overdue / 法兰到货 warning / 下料 pending / 具备验收 pending
seed_plans = [
    {"process_name": "钢板到货", "process_order": 1, "plan_date": "2026-08-10", "plan_qty": 5},
    {"process_name": "钢板到货", "process_order": 1, "plan_date": "2026-08-12", "plan_qty": 5},
    {"process_name": "法兰到货", "process_order": 2, "plan_date": "2026-08-11", "plan_qty": 5},
    {"process_name": "下料", "process_order": 3, "plan_date": "2026-08-20", "plan_qty": 10},
    {"process_name": "具备验收", "process_order": 9, "plan_date": "2026-08-25", "plan_qty": 10},
]
db.insert_node_plans(TEST_PID, seed_plans)
seed_rows = db.get_node_plans(TEST_PID)
pid_by_proc_date = {(r["process_name"], str(r["plan_date"])): r["id"] for r in seed_rows}
# 实际：钢板到货 08-10 → 5(达标)；钢板到货 08-12 → 0(逾期)；法兰到货 08-11 → 3(部分)
db.upsert_node_actual(TEST_PID, pid_by_proc_date[("钢板到货", "2026-08-10")], "钢板到货", 5, today_str)
db.upsert_node_actual(TEST_PID, pid_by_proc_date[("法兰到货", "2026-08-11")], "法兰到货", 3, today_str)

# ---- B-run1: 节点计划/预警渲染 ----
print("== B-run1: 节点计划+预警渲染 ==")
atb = AppTest.from_file("pages/2_项目详情.py", default_timeout=90)
atb.query_params["project_id"] = str(TEST_PID)
atb.run()
check("B1 无异常", len(atb.exception) == 0,
      f"exceptions={[str(e.value) for e in atb.exception]}")

metrics = {m.label: m.value for m in atb.metric}
print("  METRICS:", metrics)
check("B2 节点计划指标-总套数10", metrics.get("总套数") == "10 套", f"got {metrics.get('总套数')}")
check("B2 节点计划指标-工序数4", metrics.get("工序数") == "4 道", f"got {metrics.get('工序数')}")
check("B2 节点计划指标-节点总数5", metrics.get("节点总数") == "5 个", f"got {metrics.get('节点总数')}")
check("B2 节点计划指标-达标节点1", metrics.get("达标节点") == "1 个", f"got {metrics.get('达标节点')}")
check("B2 预警四态-达标1", metrics.get("🟢 达标") == "1", f"got {metrics.get('🟢 达标')}")
check("B2 预警四态-部分1", metrics.get("🟡 部分完成") == "1", f"got {metrics.get('🟡 部分完成')}")
check("B2 预警四态-逾期1", metrics.get("🔴 逾期未完成") == "1", f"got {metrics.get('🔴 逾期未完成')}")
check("B2 预警四态-未到2", metrics.get("⚪ 未到") == "2", f"got {metrics.get('⚪ 未到')}")

# Plotly 时间轴（甘特 + 节点时间轴 ≥2）
n_plotly_b = len(atb.get("plotly_chart"))
check("B3 节点时间轴 plotly 渲染", n_plotly_b >= 2, f"plotly_charts={n_plotly_b}")

# 分组节点列表（工序级状态 = 该工序节点最高 level：钢板到货→🔴逾期 / 法兰到货→🟡部分 / 下料、具备验收→⚪未到）
md_b = [m.value for m in atb.markdown]
check("B4 分组列表-钢板到货工序级状态=逾期", any("钢板到货" in t and "🔴 逾期未完成" in t for t in md_b),
      f"hits={[t for t in md_b if '钢板到货' in t]}")
check("B4 分组列表-法兰到货工序级状态=部分", any("法兰到货" in t and "🟡 部分完成" in t for t in md_b))
check("B4 分组列表-逾期标签", any("🔴 逾期未完成" in t for t in md_b))
check("B4 分组列表-部分标签", any("🟡 部分完成" in t for t in md_b))

# 预警红黄列表：Streamlit 将前导 emoji 提取为 alert 图标(proto.icon)，正文不含 emoji
err_texts = [e.value for e in atb.error]
warn_texts = [w.value for w in atb.warning]
err_icons = [e.proto.icon for e in atb.error]
warn_icons = [w.proto.icon for w in atb.warning]
print("  ERRORS:", err_texts)
print("  ERROR ICONS:", err_icons)
print("  WARNINGS:", warn_texts[:3])
print("  WARNING ICONS:", warn_icons)
check("B5 预警-🔴图标=error图标", any(i == "🔴" for i in err_icons), f"icons={err_icons}")
check("B5 预警-逾期节点列在 error",
      any("钢板到货" in t and "滞后 5 套" in t for t in err_texts), f"errors={err_texts}")
check("B5 预警-🟡图标=warning图标", any(i == "🟡" for i in warn_icons), f"icons={warn_icons}")
check("B5 预警-部分节点列在 warning",
      any("法兰到货" in t and "滞后 2 套" in t for t in warn_texts), f"warnings={warn_texts}")

# ---- B-run2: 填报 selectbox → number_input ----
print("== B-run2: 填报 selectbox→number_input ==")
try:
    check("B6 填报 selectbox 存在", exists(atb, "selectbox", f"node_sel_proc_{TEST_PID}"))
    ni_keys = [n.key for n in atb.number_input if n.key and n.key.startswith(f"node_actual_{TEST_PID}_")]
    check("B6 默认工序(钢板到货)出现2个number_input", len(ni_keys) == 2, f"keys={ni_keys}")
    sel = atb.selectbox(key=f"node_sel_proc_{TEST_PID}")
    print("  SELECTBOX value:", sel.value)
    sel.set_value("法兰到货")
    atb.run()
    check("B6 切换工序后无异常", len(atb.exception) == 0)
    ni_keys2 = [n.key for n in atb.number_input if n.key and n.key.startswith(f"node_actual_{TEST_PID}_")]
    check("B6 切换后法兰到货出现1个number_input", len(ni_keys2) == 1, f"keys={ni_keys2}")
except Exception as e:
    import traceback
    check("B6 填报 selectbox 链路", False, traceback.format_exc()[-500:])

# ---- B-run3: 保存链路（写测试项目 999998，验证后清理） ----
print("== B-run3: 保存节点进度链路 ==")
try:
    node_id = pid_by_proc_date[("法兰到货", "2026-08-11")]
    ni = atb.number_input(key=f"node_actual_{TEST_PID}_{node_id}")
    ni.set_value(4.0)
    atb.run()
    check("B7 设置实际值无异常", len(atb.exception) == 0)
    atb.button(key=f"save_node_actual_{TEST_PID}").click()
    atb.run()
    check("B7 保存无异常", len(atb.exception) == 0,
          f"exceptions={[str(e.value) for e in atb.exception]}")
    check("B7 保存成功提示", any("已保存" in s.value for s in atb.success), f"success={[s.value for s in atb.success]}")
    actual = sql_count(
        "SELECT COUNT(*) n FROM node_actual_progress WHERE project_id=%s AND node_plan_id=%s AND actual_qty=4",
        (TEST_PID, node_id))
    check("B7 DB 持久化 actual_qty=4", actual == 1, f"count={actual}")
except Exception as e:
    import traceback
    check("B7 保存链路", False, traceback.format_exc()[-500:])

# ---- B-run4: 导入链路（上传矩阵 → 确认导入 → 27节点） ----
print("== B-run4: 导入链路（覆盖式） ==")
try:
    ati = AppTest.from_file("pages/2_项目详情.py", default_timeout=90)
    ati.query_params["project_id"] = str(TEST_PID)
    ati.run()
    xlsx_path = os.path.join(PROJECT_ROOT, "qa_verify", "test_schedule_matrix.xlsx")
    with open(xlsx_path, "rb") as fh:
        content = fh.read()
    ati.file_uploader(key=f"node_schedule_upload_{TEST_PID}").upload("test_schedule_matrix.xlsx", content)
    ati.run()
    check("B8 上传解析无异常", len(ati.exception) == 0,
          f"exceptions={[str(e.value) for e in ati.exception]}")
    check("B8 确认导入按钮出现", exists(ati, "button", f"confirm_node_schedule_{TEST_PID}"))
    ati.button(key=f"confirm_node_schedule_{TEST_PID}").click()
    ati.run()
    check("B8 确认导入无异常", len(ati.exception) == 0,
          f"exceptions={[str(e.value) for e in ati.exception]}")
    cnt = sql_count("SELECT COUNT(*) n FROM process_node_plans WHERE project_id=%s", (TEST_PID,))
    check("B8 导入后 DB 27 个节点", cnt == 27, f"count={cnt}")
    metrics_i = {m.label: m.value for m in ati.metric}
    print("  METRICS AFTER IMPORT:", metrics_i)
    check("B8 导入后指标-总套数10", metrics_i.get("总套数") == "10 套", f"got {metrics_i.get('总套数')}")
    check("B8 导入后指标-工序数9", metrics_i.get("工序数") == "9 道", f"got {metrics_i.get('工序数')}")
    check("B8 导入后指标-节点总数27", metrics_i.get("节点总数") == "27 个", f"got {metrics_i.get('节点总数')}")
except Exception as e:
    import traceback
    check("B8 导入链路", False, traceback.format_exc()[-500:])

# ============================================================
# 清理 + DB 纯净检查
# ============================================================
print("== Phase C: 清理 + DB 纯净 ==")
cleanup_999998()
c1 = sql_count("SELECT COUNT(*) n FROM process_node_plans WHERE project_id=%s", (TEST_PID,))
c2 = sql_count("SELECT COUNT(*) n FROM node_actual_progress WHERE project_id=%s", (TEST_PID,))
c3 = sql_count("SELECT COUNT(*) n FROM projects WHERE id=%s", (TEST_PID,))
check("C1 测试项目节点计划已清理", c1 == 0, f"left={c1}")
check("C1 测试项目实际进度已清理", c2 == 0, f"left={c2}")
check("C1 测试项目已删除", c3 == 0, f"left={c3}")
p1_plans = sql_count("SELECT COUNT(*) n FROM process_node_plans WHERE project_id=1")
p1_actuals = sql_count("SELECT COUNT(*) n FROM node_actual_progress WHERE project_id=1")
check("C2 project 1 节点计划未被污染(0)", p1_plans == 0, f"left={p1_plans}")
check("C2 project 1 实际进度未被污染(0)", p1_actuals == 0, f"left={p1_actuals}")

print(f"\n== 小结: PASS {len(PASS)} / FAIL {len(FAIL)} ==")
if FAIL:
    print("FAILED:")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  - {name} | {detail}")
    sys.exit(1)
print("ALL PASS")
sys.exit(0)
