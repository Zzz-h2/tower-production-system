# -*- coding: utf-8 -*-
"""后端核心配置：数据库连接 + 业务常量。

业务常量与「现有 config.py」保持同源（SCHEDULE_PROCESS_NAMES 九工序顺序等），
保证后端行为与 Streamlit 版 1:1 一致。
"""
import os
import sys
from pathlib import Path

# 允许 import 原项目根目录的 utils / database（业务逻辑 1:1 复用，避免迁移偏差）
PROJECT_ROOT = Path(__file__).resolve().parents[3]  # backend/app/core -> 项目根
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------- MySQL 配置（与 config.py MYSQL_CONFIG 一致；可用环境变量覆盖） ----------
MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "tower_production"),
    "charset": "utf8mb4",
}

# ---------- 业务常量（与 config.py 同源） ----------
try:
    from config import SCHEDULE_PROCESS_NAMES as _S
    SCHEDULE_PROCESS_NAMES = list(_S)  # 九工序顺序（前序联动依据）
except Exception:  # pragma: no cover - 兜底常量
    SCHEDULE_PROCESS_NAMES = [
        "钢板到货", "法兰到货", "下料", "卷制", "组对", "黑塔",
        "防腐", "附件安装", "具备验收",
    ]

# 状态语义色（前端渲染与后端响应统一）
STATUS_COLORS = {
    "done": "#38a169",
    "pending": "#718096",
    "in_progress": "#3182ce",
    "warning": "#d69e2e",
    "overdue": "#e53e3e",
}
STATUS_EMOJI = {
    "done": "🟢", "pending": "⚪", "in_progress": "🔵",
    "warning": "🟡", "overdue": "🔴",
}

# 分组名（填报弹窗互斥手风琴）
GROUP_LABELS = {
    "today": "今日待填报",
    "overdue": "逾期未完成",
    "future": "未来计划",
    "done": "已完成",
}
