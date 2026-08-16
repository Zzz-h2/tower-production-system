# 塔筒生产进度管控系统 — 交付概览

## 项目概述

为陆基风电塔筒制造企业交付岗设计的轻量化生产进度管控系统。从月度调度令导入到工序级追踪、自动预警、异常闭环的全流程数字化管理。

## 已交付模块

| 序号 | 模块 | 文件 | 状态 |
|------|------|------|:----:|
| 1 | 需求说明书与技术方案 | `需求说明书与技术方案.md` | ✅ |
| 2 | 数据库设计 + 建表SQL | `db_schema.sql` + `database.py` | ✅ |
| 3 | 核心业务逻辑 | `utils/business_logic.py` | ✅ |
| 4 | 工作日历工具 | `utils/workday_calendar.py` | ✅ |
| 5 | Excel解析器 | `utils/excel_parser.py` | ✅ |
| 6 | 主界面(项目总览) | `app.py` | ✅ |
| 7 | 项目详情页 | `pages/2_项目详情.py` | ✅ |
| 8 | 依赖配置 | `requirements.txt` | ✅ |
| 9 | 启动脚本 | `run_mysql.bat` | ✅ |
| 10 | 使用说明 | `README.md` | ✅ |

## 关键决策

- **技术栈**：Python 3.10+ / Streamlit / MySQL — 生产环境数据库
- **滞后计算**：使用日历天数（与业务规则"超过X天"保持一致）
- **数据库**：MySQL 8.0（pymysql），6张表，支持级联删除和外键约束，便于团队多人共用
- **甘特图**：Plotly 交互式图表，支持缩放和悬浮提示

## 测试结果

- 工作日历工具：7/7 测试通过
- 核心业务逻辑：7/7 测试通过
- 数据库集成：全部 CRUD 操作验证通过

## 启动方式

```bash
cd tower_production_system
pip install -r requirements.txt
streamlit run app.py
```

或双击 `run.bat`（Windows）

## 后续建议

1. 接入企业微信/钉钉消息通知，异常自动推送
2. 增加多用户角色权限（交付经理/车间主任/厂长）
3. 移动端 H5 适配，支持车间现场扫码填报进度
