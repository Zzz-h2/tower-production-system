# 🏭 塔筒生产工序进度管控与风险预警系统

## 系统简介

面向陆基风电塔筒制造企业的轻量化生产进度管控系统，实现从月度调度令导入到工序级追踪、自动预警、异常闭环的全流程数字化管理。

### 核心功能

| 模块 | 功能 |
|------|------|
| 📁 数据导入 | Excel 排产计划上传（工序/日期/套数解析）、调度令批量建项目、自动去重 |
| 📊 项目总览 | 指标卡（总数/预警/延期/月计划）+ 项目列表 + 进度条（附件安装口径）+ 实时风险三级标识 |
| 📋 项目详情 | 头部信息卡（附件安装整体进度 + 实时风险）+ 节点计划 / 节点预警 / 里程碑倒排 三 Tab |
| 🗂️ 节点计划 | 工序节点时间轴（ECharts，今日红线）+ 工序卡片（主状态 + 已提前/部分完成 附加标签）+ 填报弹窗 |
| ⚠️ 节点预警 | 当前预警 + 历史异常记录 双模块；异常「管理」可编辑 / 行内「关闭」 |
| 📝 异常提报 | 详情弹窗「异常提报」Tab（责任分类/原因/处理人/计划关闭/措施）→ 预警联动 → 闭环归档 |
| 📅 里程碑倒排 | 输入交付日 → 自动倒排各工序最晚完成时间（预留） |

### 技术栈

- **前端**: Vue3 + Vite + Element Plus + ECharts + Pinia
- **后端**: Python FastAPI（前后端分离式单体）
- **数据库**: MySQL 8.0 (pymysql)
- **图表**: ECharts（工序节点时间轴）
- **数据处理**: Pandas + openpyxl（Excel 解析）

---

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 安装运行

```bash
# 1. 进入项目目录
cd tower_production_system
# 2. 安装依赖（后端）
cd backend && pip install -r requirements.txt
# 3. 启动系统（Windows 直接双击 run.bat 或 start_app.bat）
# 后端：cd backend && uvicorn app.main:app --port 8000
# 前端：cd frontend && npm run dev   → http://localhost:5173
# 说明：MySQL 连接通过环境变量 MYSQL_HOST/USER/PASSWORD/DATABASE/PORT 配置，见 backend/app/core/config.py
```
启动后浏览器访问 `http://localhost:5173`（前端 Vite 开发服务器代理 /api → 后端 :8000）

### 首次使用

1. 主页面左侧切换到「排产计划总览」或进项目详情「节点计划」Tab 导入排产计划 Excel
2. 项目详情「节点计划」Tab 查看工序时间轴、填报各节点实际进度
3. 填报后「节点预警」Tab 自动生成当前预警；可提报/编辑/关闭异常
4. 使用「里程碑倒排」输入交付截止日自动倒排
5. 主页面可筛选/搜索/编辑/删除项目

---

## 项目结构

```
tower_production_system/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 入口 / CORS / 路由
│   │   ├── core/                # config / db（数据库访问）
│   │   ├── routers/             # projects / nodes / dashboard / exceptions 等
│   │   ├── schemas/             # Pydantic 模型
│   │   └── services/            # 业务逻辑（状态机/倒排/Excel 解析，自包含）
│   └── requirements.txt
├── frontend/
│   ├── src/                     # Vue3 前端（views/components/store/api）
│   └── package.json
├── database.py                  # 数据库操作（MySQL CRUD，被 backend 复用）
├── db_schema_mysql.sql          # MySQL 建表脚本（node_plans/node_actuals/node_exceptions 等）
├── run.bat / run_mysql.bat      # Windows 一键启动（后端+前端）
├── start_app.bat                # 幂等启动（检测端口空闲再拉起）
└── README.md / 启动指南.md      # 文档
```

---

## 业务规则

### 工序标准参数

| 序号 | 工序 | 工期(天) |
|------|------|:------:|
| 1 | 下料 | 2 |
| 2 | 坡口 | 2 |
| 3 | 卷板 | 1 |
| 4 | 纵缝 | 2 |
| 5 | 组对 | 2 |
| 6 | 环缝 | 3 |
| 7 | 焊接小件 | 1 |
| 8 | 门框 | 4 |
| 9 | 黑塔报检 | 1 |
| 10 | 打砂 | 2 |
| 11 | 防腐 | 3 |
| 12 | 内装 | 2 |

**总工期：25天（串行执行）**

### 预警规则（实时计算，基于 node_plans + node_actuals，弃用 processes 表）

- **延期** 🔴：存在历史逾期节点（`plan_date < 今日` 且 `actual_qty < plan_qty`）
- **预警** 🟡：存在今日节点未完成（`plan_date == 今日` 且 `actual_qty < plan_qty`；未来提前进行中**不算**预警）
- **正常** 🟢：其余情况（今日计划已完成 / 未来节点 / 历史已完成）

> 首页总览、项目列表、详情页头部卡、节点预警四处风险口径完全一致（同一实时判定）。
> 整体进度 = 「附件安装」工序进度；工序卡片主状态 + 附加标签（已提前/部分完成）实时判定。

工作日计算自动排除周六、周日及自定义节假日。

---

## 测试

```bash
# 工作日历测试
python -m utils.workday_calendar

# 核心业务逻辑测试
python -m utils.business_logic

# Excel 解析测试（生成示例文件）
python -m utils.excel_parser
```

---

## 版本

v1.1 - 2026-08-17（重构 Vue3 + FastAPI；风险/进度实时口径；异常提报与预警双模块）

## 开发

Senior Developer (高级开发工程师)
