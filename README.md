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
# 2. 安装依赖
pip install -r requirements.txt
# 3. 启动系统
python -m streamlit run app.py
# 或双击 run_mysql.bat（Windows，内置 MySQL 连接变量）
# 说明：MySQL 连接通过环境变量 MYSQL_HOST/USER/PASSWORD/DATABASE/PORT 配置，见 config.py

#清除缓存
Get-ChildItem -Path . -Filter "*.pyc" -Recurse -File | Remove-Item -Force
Get-ChildItem -Path . -Filter "__pycache__" -Recurse -Directory | Remove-Item -Recurse -Force

#检查缓存
Get-ChildItem -Path . -Filter "*.pyc" -Recurse -File
Get-ChildItem -Path . -Filter "__pycache__" -Recurse -Directory
```
启动后浏览器自动打开 `http://localhost:8501`

### 首次使用

1. 点击「导入月度调度令」上传 Excel 文件
2. 在表头映射界面匹配字段
3. 导入成功后在主界面查看项目列表
4. 点击「查看详情」进入单项目管控页
5. 在详情页更新工序进度、提报异常
6. 使用里程碑倒排工具规划交付节点

---

## 项目结构

```
tower_production_system/
├── app.py                      # 主入口（项目总览看板）
├── config.py                   # 全局配置（颜色/工序参数）
├── database.py                 # 数据库操作（MySQL CRUD）
├── requirements.txt            # Python 依赖
├── run.bat                     # Windows 启动脚本
├── db_schema.sql               # 数据库建表脚本
├── db_schema_mysql.sql         # MySQL 建表脚本
├── db_upgrade_v2_mysql.sql     # MySQL 表结构升级脚本
├── utils/
│   ├── __init__.py
│   ├── business_logic.py       # 核心业务逻辑
│   ├── excel_parser.py         # Excel 解析器
│   └── workday_calendar.py     # 工作日历工具
├── pages/
│   └── 2_项目详情.py            # 项目详情页
└── 需求说明书与技术方案.md      # 完整需求文档
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
