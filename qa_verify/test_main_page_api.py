# -*- coding: utf-8 -*-
"""
主页面迁移 —— 后端接口回归测试（QA 工程师：严过关）

覆盖被测接口：
  - GET  /api/projects            （搜索 / 负责人 / 状态 / 分页）
  - POST /api/projects            （手动添加：校验 / 查重 / 初始化工序）
  - POST /api/projects/import-dispatch  （月度调度令 Excel 导入）
  - GET  /api/dashboard/stats     （看板指标）

运行方式（在 tower_production_system/ 根目录下）：
  backend\\.venv\\Scripts\\python.exe -m pytest qa_verify\\test_main_page_api.py -v

说明：
  - 依赖 MySQL（core/config.py），测试产生的新数据将在 teardown 中清理。
  - 状态(status)筛选按 PRD/前端语义应为「风险等级」过滤（normal/warning/delayed），
    而非 projects.status 生命周期字段。相关断言以此为准。
"""
import os
import sys
import tempfile

# ---------- 路径准备：确保 backend 包、根级 database/utils 可导入 ----------
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402
import database as db  # 仅用于测试数据清理（delete_project / get_project_by_name）  # noqa: E402

# Excel 构造需要 pandas + openpyxl（与 utils/excel_parser 一致）
import pandas as pd  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# ======================================================================
# Fixtures
# ======================================================================
@pytest.fixture(scope="module")
def client():
    """共享 TestClient（应用为单例，避免重复建连）。"""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def created_ids():
    """收集测试过程中新建的 project_id，teardown 统一清理。"""
    ids = []
    yield ids
    for pid in ids:
        try:
            db.delete_project(pid)
        except Exception:
            pass


@pytest.fixture
def created_names():
    """收集测试过程中新建的 project_name，按名称清理（导入用例用）。"""
    names = []
    yield names
    for name in names:
        try:
            rec = db.get_project_by_name(name)
            if rec:
                db.delete_project(rec["id"])
        except Exception:
            pass


def _make_dispatch_excel(path: str, rows):
    """构造一份「合法」的月度调度令 Excel（含必需 序号 列 + 必填字段表头）。"""
    columns = [
        "序号", "项目名称", "钢塔厂家", "截止上月月底出品",
        "本月计划出品", "交付负责人", "计划开工日期", "计划交付日期",
    ]
    data = []
    for i, r in enumerate(rows, start=1):
        data.append({
            "序号": i,
            "项目名称": r["project_name"],
            "钢塔厂家": r["factory_name"],
            "截止上月月底出品": r.get("last_month_output", 0),
            "本月计划出品": r["monthly_plan"],
            "交付负责人": r["delivery_person"],
            "计划开工日期": r.get("plan_start_date", "2026-08-01"),
            "计划交付日期": r.get("plan_end_date", "2026-09-01"),
        })
    pd.DataFrame(data, columns=columns).to_excel(path, index=False)


# ======================================================================
# 1) GET /api/projects —— 结构 / 默认值 / 各类筛选 / 分页
# ======================================================================
class TestListProjects:
    def _baseline(self, client):
        """拉取全量（page_size 足够大）作为基线，用于稳定断言。"""
        resp = client.get("/api/projects", params={"page": 1, "page_size": 1000})
        assert resp.status_code == 200
        return resp.json()

    def test_default_structure_and_pagination_defaults(self, client):
        """① 无筛选：返回 {items,total,page,page_size}，page/page_size 有默认值。"""
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        body = resp.json()
        for key in ("items", "total", "page", "page_size"):
            assert key in body, f"响应缺少字段 {key}"
        assert body["page"] == 1
        assert body["page_size"] == 10
        # 当总量不超过默认页大小时，items 数量等于总量
        assert len(body["items"]) == min(body["total"], body["page_size"])
        assert body["total"] >= 1

    def test_keyword_fuzzy_filter(self, client):
        """② keyword 模糊过滤（命中 project_name 或 machine_type 子串）。"""
        base = self._baseline(client)
        # 取第一个项目名的前 4 个字符作为子串，保证至少命中 1 条
        kw = base["items"][0]["project_name"][:4]
        resp = client.get("/api/projects", params={"keyword": kw})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        for it in items:
            hay = (it.get("project_name") or "") + " " + (it.get("machine_type") or "")
            assert kw in hay, f"返回项未包含关键字 {kw!r}: {it}"

    def test_person_exact_filter(self, client):
        """③ person 精确过滤（delivery_person 完全相等）。"""
        base = self._baseline(client)
        person = base["items"][0]["delivery_person"]
        resp = client.get("/api/projects", params={"person": person})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) >= 1
        for it in items:
            assert it["delivery_person"] == person

    def test_status_risk_level_filter(self, client):
        """④ status 按「风险等级」过滤（normal/warning/delayed/all）。

        依据 PRD 与前端 ProjectListView.statusOptions：
        all→全部；warning/delayed/normal 应只返回对应 risk_level 的项目。
        期望总量由各 risk_level 实际分布推导（与无筛选基线一致），不写死数值。
        """
        base = self._baseline(client)
        from collections import Counter
        expected = Counter(it["risk_level"] for it in base["items"])
        expected_total = base["total"]

        # all 应等于全量
        resp_all = client.get("/api/projects", params={"status": "all"})
        assert resp_all.status_code == 200
        assert resp_all.json()["total"] == expected_total

        for level in ("delayed", "warning", "normal"):
            resp = client.get("/api/projects", params={"status": level})
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == expected.get(level, 0), \
                f"status={level} 总量应为 {expected.get(level, 0)}，实际 {body['total']}"
            for it in body["items"]:
                assert it["risk_level"] == level, \
                    f"status={level} 过滤出非该等级项目: {it}"

    def test_pagination_page_size(self, client):
        """⑤ page_size=2 且总量>2 时：items 长度=2、total=全量、page=1。"""
        base = self._baseline(client)
        total = base["total"]
        resp = client.get("/api/projects", params={"page": 1, "page_size": 2})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 2
        assert body["total"] == total
        assert len(body["items"]) == (2 if total > 2 else total)

    def test_pagination_page2_slicing(self, client):
        """⑥ page=2 切片正确（skip 生效，分页与全量顺序一致）。"""
        base = self._baseline(client)
        full = base["items"]
        p1 = client.get("/api/projects", params={"page": 1, "page_size": 3}).json()
        p2 = client.get("/api/projects", params={"page": 2, "page_size": 3}).json()
        assert p1["page"] == 1 and p1["page_size"] == 3
        assert p2["page"] == 2 and p2["page_size"] == 3
        # 切片与全量顺序一致（按 id 比较，避免字段顺序差异）
        p1_ids = [it["id"] for it in p1["items"]]
        p2_ids = [it["id"] for it in p2["items"]]
        full_ids = [it["id"] for it in full]
        assert p1_ids == full_ids[:3]
        assert p2_ids == full_ids[3:6]


# ======================================================================
# 2) POST /api/projects —— 校验 / 查重 / 工序初始化
# ======================================================================
class TestCreateProject:
    _BASE = {
        "project_name": "QA有效创建_唯一20260815",
        "machine_type": "机型X型",
        "factory_name": "QA钢塔厂X",
        "delivery_person": "QA负责人X",
        "monthly_plan": 6,
        "last_month_output": 2,
        "plan_start_date": "2026-08-01",
        "plan_end_date": "2026-09-01",
    }

    def test_valid_creation_returns_id(self, client, created_ids):
        """① 合法体 → 200/201 且含 id；带 plan_start_date → 工序被初始化。"""
        resp = client.post("/api/projects", json=self._BASE)
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert "id" in data and data["id"]
        created_ids.append(data["id"])

        # 带 plan_start_date 的新项目应已初始化工序
        procs = db.get_project_processes(data["id"])
        assert len(procs) >= 1, "新建项目未初始化标准工序"

    def test_missing_required_fields_returns_400(self, client):
        """② 缺必填 → 400（空 name / 缺 monthly_plan / 类型错）。"""
        # 空 project_name
        payload = dict(self._BASE)
        payload["project_name"] = "   "
        r = client.post("/api/projects", json=payload)
        assert r.status_code == 400, r.text

        # 缺 monthly_plan
        payload = dict(self._BASE)
        del payload["monthly_plan"]
        r = client.post("/api/projects", json=payload)
        assert r.status_code == 400, r.text

        # monthly_plan 类型错误：Pydantic 模型(Optional[int])会在进入路由前
        # 以 422 拒绝；规格写的是 400。两者均为客户端错误，统一断言为 4xx，
        # 并在报告中标注「400 vs 422」的规格/实现差异（供 PM 确认）。
        payload = dict(self._BASE)
        payload["monthly_plan"] = "不是数字"
        r = client.post("/api/projects", json=payload)
        assert r.status_code in (400, 422), r.text

        # 空 factory_name
        payload = dict(self._BASE)
        payload["factory_name"] = ""
        r = client.post("/api/projects", json=payload)
        assert r.status_code == 400, r.text

    def test_monthly_plan_zero_is_accepted(self, client):
        """OBS-2 已确认为缺陷并修复：本月计划出品必须为正整数（>0）。

        与原版 Streamlit _render_add_project_form 校验一致（monthly_plan <= 0 → 报错），
        故 monthly_plan=0 必须被拒绝，返回 400。"""
        payload = dict(self._BASE)
        payload["project_name"] = "QA零计划_唯一20260815"
        payload["monthly_plan"] = 0
        r = client.post("/api/projects", json=payload)
        assert r.status_code == 400, r.text

    def test_duplicate_four_fields_returns_409(self, client, created_ids):
        """③ 四字段重复（名称+厂家+负责人+机型）→ 409 且 detail 含「已存在」。"""
        dup_name = "QA重复唯一测试_20260815"
        payload = dict(self._BASE)
        payload["project_name"] = dup_name

        # 首次创建
        r1 = client.post("/api/projects", json=payload)
        assert r1.status_code in (200, 201), r1.text
        created_ids.append(r1.json()["id"])

        # 相同四字段再次提交 → 409
        r2 = client.post("/api/projects", json=payload)
        assert r2.status_code == 409, r2.text
        assert "已存在" in r2.json()["detail"], r2.json()


# ======================================================================
# 3) POST /api/projects/import-dispatch —— 调度令导入
# ======================================================================
class TestImportDispatch:
    def test_valid_dispatch_excel_imports(self, client, created_names, tmp_path):
        """合法调度令（含 序号 列）→ 200，success>=1，message 含「成功」。"""
        rows = [
            {
                "project_name": "QA导入唯一_甲",
                "factory_name": "QA导入厂甲",
                "delivery_person": "QA导入人甲",
                "monthly_plan": 5,
                "last_month_output": 1,
                "plan_start_date": "2026-08-01",
                "plan_end_date": "2026-09-01",
            },
            {
                "project_name": "QA导入唯一_乙",
                "factory_name": "QA导入厂乙",
                "delivery_person": "QA导入人乙",
                "monthly_plan": 7,
                "last_month_output": 0,
                "plan_start_date": "2026-08-05",
                "plan_end_date": "2026-08-30",
            },
        ]
        xlsx = os.path.join(str(tmp_path), "dispatch_valid.xlsx")
        _make_dispatch_excel(xlsx, rows)

        created_names.extend([r["project_name"] for r in rows])

        with open(xlsx, "rb") as f:
            resp = client.post(
                "/api/projects/import-dispatch",
                files={"file": ("dispatch_valid.xlsx", f,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] >= 1, f"导入成功数为 0: {body}"
        assert "成功" in body["message"], f"message 未含『成功』: {body['message']}"

    def test_missing_required_fields_mapping_returns_400(self, client):
        """必填字段映射缺失 → 400（复用仓库内 test_business.xlsx，其表头无法映射）。"""
        path = os.path.join(PROJECT_ROOT, "test_business.xlsx")
        if not os.path.exists(path):
            pytest.skip("test_business.xlsx 不存在，跳过映射缺失用例")
        with open(path, "rb") as f:
            resp = client.post(
                "/api/projects/import-dispatch",
                files={"file": ("test_business.xlsx", f,
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
        assert resp.status_code == 400, resp.text

    def test_non_excel_extension_returns_400(self, client, tmp_path):
        """非 .xlsx/.xls 文件 → 400。"""
        bad = os.path.join(str(tmp_path), "note.txt")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("hello")
        with open(bad, "rb") as f:
            resp = client.post(
                "/api/projects/import-dispatch",
                files={"file": ("note.txt", f, "text/plain")},
            )
        assert resp.status_code == 400, resp.text


# ======================================================================
# 4) GET /api/dashboard/stats —— 看板指标
# ======================================================================
class TestDashboardStats:
    def test_stats_fields(self, client):
        """返回含 total_projects / warning_count / delayed_count / total_monthly_plan。"""
        resp = client.get("/api/dashboard/stats")
        assert resp.status_code == 200
        data = resp.json()
        for field in ("total_projects", "warning_count", "delayed_count", "total_monthly_plan"):
            assert field in data, f"看板缺少字段 {field}"
        # 与项目列表全量一致（看板仅统计 in_progress 项目，当前全部 in_progress）
        base = client.get("/api/projects", params={"status": "all"}).json()
        assert data["total_projects"] == base["total"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
