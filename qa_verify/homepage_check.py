# -*- coding: utf-8 -*-
"""
QA 验证 - 步骤6: 首页 app.py 回归（MySQL 数据 + project 1 风险与详情页一致）
"""
import os
import sys

os.environ.setdefault("MYSQL_PASSWORD", "123456")
BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, BASE)

from streamlit.testing.v1 import AppTest
from database import get_project_by_id

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")


at = AppTest.from_file("app.py", default_timeout=30)
at.run()
check("app.py 加载无异常", len(at.exception) == 0,
      f"exceptions={[str(e.value) for e in at.exception]}")

# 页面应显示项目列表相关内容（标题/文本）
all_text = " | ".join(t.value for t in at.markdown) + " | " + " | ".join(t.value for t in at.title)
check("页面有标题输出", len(all_text.strip()) > 0, f"head={all_text[:120]}")

# project 1 数据一致性（直接查库与详情页一致）
proj = get_project_by_id(1)
check("MySQL 查询 project 1 正常", proj is not None and proj["id"] == 1,
      f"name={proj['project_name'][:20] if proj else None} risk={proj['risk_level'] if proj else None}")
check("project 1 风险等级为 delayed（与详情页一致）", proj and proj["risk_level"] == "delayed",
      f"risk={proj['risk_level'] if proj else None}")

# 页面文本中出现项目名（说明列表来自 MySQL）
found_name = any(proj and "国能投" in t.value for t in at.markdown)
check("页面渲染 project 1 项目名", found_name)

passed = sum(1 for _, ok, _ in RESULTS if ok)
total = len(RESULTS)
print(f"\n===== 首页回归汇总: {passed}/{total} PASS =====")
sys.exit(0 if passed == total else 1)
