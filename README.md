# 🏭 塔筒生产工序进度管控与风险预警系统

## 系统简介

面向陆基风电塔筒制造企业的轻量化生产进度管控系统，实现从月度调度令导入到工序级追踪、自动预警、异常闭环的全流程数字化管理。

### 核心功能

| 模块 | 功能 |
|------|------|
| 📁 数据导入 | Excel调度令上传、表头智能映射、自动去重更新 |
| 📊 项目总览 | 指标卡片 + 项目列表 + 进度条 + 风险等级三级标识 |
| 📋 工序甘特图 | Plotly交互式甘特图，计划/实际对比，今日线标注 |
| ⚠️ 风险预警 | 自动判定工序滞后(黄/红)，项目级风险汇总 |
| 📝 异常闭环 | 异常提报 → 处理跟踪 → 闭环归档 |
| 📅 里程碑倒排 | 输入交付日 → 自动倒排12道工序最晚完成时间 |

### 技术栈

- **前端**: Streamlit (Python Web 框架)
- **数据库**: MySQL 8.0 (pymysql)
- **图表**: Plotly (交互式甘特图)
- **数据处理**: Pandas + openpyxl

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

### 预警规则

- **正常** 🟢：所有工序按时或提前
- **预警** 🟡：某工序滞后 1 个工作日
- **延期** 🔴：某工序滞后 ≥ 2 个工作日

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

v1.0 - 2026-08-03

## 开发

Senior Developer (高级开发工程师)
