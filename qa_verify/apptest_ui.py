# -*- coding: utf-8 -*-
"""
QA 验证 - 步骤2: AppTest 模式与控件验证
验证 pages/2_项目详情.py 三模式切换 UI 控件（不改数据库）
适配 streamlit 1.60 AppTest API（元素访问返回单元素，未找到抛 KeyError）
"""
import os
import sys

os.environ.setdefault("MYSQL_PASSWORD", "123456")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from streamlit.testing.v1 import AppTest

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


def exists(at, kind, key):
    try:
        getattr(at, kind)(key=key)
        return True
    except KeyError:
        return False


# 1. 加载页面
at = AppTest.from_file("pages/2_项目详情.py", default_timeout=30)
at.query_params["project_id"] = "1"
at.run()
check("页面加载无异常", len(at.exception) == 0,
      f"exceptions={[str(e.value) for e in at.exception]}")

# 2. 点「✏️ 编辑项目」
check("编辑按钮存在", exists(at, "button", "btn_edit_project_1"))
at.button(key="btn_edit_project_1").click()
at.run()
check("点击编辑后无异常", len(at.exception) == 0)

# 3. 三模式按钮出现
for mk in ["mode_auto_1", "mode_manual_1", "mode_import_1"]:
    check(f"模式按钮 {mk} 存在", exists(at, "button", mk))

# 4. 切 manual
at.button(key="mode_manual_1").click()
at.run()
check("切 manual 无异常", len(at.exception) == 0)
ps_keys = [d.key for d in at.date_input if d.key and d.key.startswith("manual_ps_1_")]
pe_keys = [d.key for d in at.date_input if d.key and d.key.startswith("manual_pe_1_")]
check("manual 出现12个计划开始 date_input", len(ps_keys) == 12, f"keys={ps_keys}")
check("manual 出现12个计划结束 date_input", len(pe_keys) == 12, f"keys={pe_keys}")
check("保存工序日期按钮存在", exists(at, "button", "save_manual_dates_1"))

# 5. 切 import
at.button(key="mode_import_1").click()
at.run()
check("切 import 无异常", len(at.exception) == 0)
check("file_uploader import_date_file_1 存在", exists(at, "file_uploader", "import_date_file_1"))
check("下载按钮 download_template_1 存在", exists(at, "download_button", "download_template_1"))

# 6. 切回 auto
at.button(key="mode_auto_1").click()
at.run()
check("切回 auto 无异常", len(at.exception) == 0)
check("edit_start_1 存在", exists(at, "date_input", "edit_start_1"))
check("edit_end_1 存在", exists(at, "date_input", "edit_end_1"))
check("edit_factory_1 存在", exists(at, "text_input", "edit_factory_1"))

# 汇总
passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== UI AppTest 汇总: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
