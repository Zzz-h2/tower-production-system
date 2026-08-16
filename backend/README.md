# 塔筒生产进度管控系统 —— 前后端分离式单体

Streamlit 单体重构为 **Vue3 + FastAPI + MySQL** 前后端分离式单体。旧 Streamlit 应用保留可并行运行，直到前端达标再切换。

## 目录结构

```
backend/                    # FastAPI 后端
  app/
    main.py                 # FastAPI 实例 / CORS / 路由挂载
    core/config.py          # 数据库配置 + 业务常量（九工序顺序等）
    core/db.py              # 数据库访问（复用原 database.py，绕过 st.cache_data）
    schemas/                # Pydantic 请求/响应模型（含 exception.py 异常模型）
    services/business_logic.py   # 状态机/前序联动/分组保存（1:1 复用 utils）
    services/schedule_import.py  # Excel 解析（1:1 复用 utils）
    services/node_service.py     # 节点聚合：指标/卡片/时间轴/分组
    routers/                # projects / nodes / schedule_import / dashboard / exceptions
  requirements.txt

frontend/                   # Vue3 前端
  src/
    api/                    # axios 封装 + 请求函数（含 exception.js 异常 API）
    store/                  # Pinia（项目/节点状态）
    router/                 # Vue Router
    views/                  # 项目列表 / 项目详情
    components/             # 信息卡/时间轴/卡片网格/详情弹窗/预警列表/异常提报
    styles/theme.css        # 浅色工业风主题（对齐原配色）
```

## 异常提报模块

- 表 `node_exceptions`（项目/节点/工序/计划日期/责任分类/原因/处理人/计划关闭/措施/状态 closed_at）
- API：`POST /api/exceptions/projects/{pid}/nodes/{nid}`（提报）、`GET /projects/{pid}`（全部）、
  `GET /projects/{pid}/exceptions/closed`（已关闭历史）、`GET /nodes/{nid}`（节点异常）、`PUT /{exc_id}`（更新/关闭）
- 节点预警接口 `GET /api/projects/{pid}/alerts` 按 node_id 携带 exceptions + has_exception

## 风险/进度实时口径（v1.1）

- 风险等级、整体进度、首页总览均基于 `node_plans + node_actuals` 实时计算（弃用 processes 表）
- 详情/列表/总览/预警 四处口径一致；整体进度 = 附件安装工序进度

## 启动方式

### 后端（FastAPI，端口 8000）

```bash
cd tower_production_system\backend
pip install -r requirements.txt
# 配置数据库连接（环境变量，与 config.py 一致）
[Environment]::SetEnvironmentVariable("MYSQL_PASSWORD", "123456", "User")
uvicorn app.main:app --reload --port 8000
```

API 文档：http://localhost:8000/docs

### 前端（Vite，端口 5173）

```bash
cd tower_production_system\frontend
npm install
npm run dev        # 开发服务器，/api 自动代理到 http://localhost:8000
npm run build      # 生产构建
```

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/health | 健康检查 |
| GET | /api/projects | 项目列表 |
| GET | /api/projects/{pid} | 项目详情（基本信息/进度/风险） |
| GET | /api/projects/{pid}/node-plans | 节点计划总览（KPI/工序卡片/时间轴） |
| GET | /api/projects/{pid}/nodes/{process_name} | 某工序节点（四分组） |
| POST | /api/projects/{pid}/nodes/{process_name}/save | 按分组保存节点进度（互不覆盖） |
| POST | /api/projects/{pid}/import-schedule | 上传排产 Excel 解析入库 |
| GET | /api/projects/{pid}/alerts | 节点预警列表 |

## 业务逻辑保真说明（1:1）

后端 `services` 直接复用原 `utils/business_logic.py` / `utils/schedule_import.py` 与 `database.py`
（同一份实现，零迁移偏差），关键行为：

- `judge_node_status` 状态机（含未来节点「🟢 提前完成」/「🔵 提前进行中」语义）
- 前序工序数量联动（今日待填报校验；逾期/未来/已完成自由填报）
- 按分组独立保存（只写当前分组，互不覆盖）
- Excel 解析聚合 `(process_name, plan_date) -> plan_qty`

> 注意：原 `database.py` 的只读函数带 `@st.cache_data`（Streamlit 缓存），后端通过
> `__wrapped__` 绕过（见 `backend/app/core/db.py`），保证写后读一致性。

## 后续阶段（可选增强）

- 阶段 3：Excel 导入前端上传对接（后端接口已就绪）
- 阶段 4：WebSocket 实时进度推送（`/ws/progress/{pid}` 占位）+ APScheduler 定时预警
- 甘特看板：可接入 dhtmlx-gantt / frappe-gantt
