"""
config.py — 系统全局配置

包含：
- 工序标准参数
- UI 颜色主题
- Streamlit 页面配置

Author: Senior Developer
Date: 2026-08-03
"""

import os

# ============================================================
# UI 颜色主题（工业制造风格）
# ============================================================

COLORS = {
    # 主色调
    "primary": "#1a365d",        # 深蓝色（主色）
    "primary_light": "#2b6cb0",  # 中蓝色
    "primary_dark": "#0f2440",   # 深蓝暗色

    # 风险状态色
    "normal": "#38a169",         # 正常 - 绿色
    "normal_bg": "#f0fff4",      # 正常背景
    "warning": "#d69e2e",        # 预警 - 黄色
    "warning_bg": "#fffff0",     # 预警背景
    "delayed": "#e53e3e",        # 延期 - 红色
    "delayed_bg": "#fff5f5",     # 延期背景

    # 功能色
    "success": "#38a169",
    "info": "#3182ce",
    "muted": "#718096",
    "border": "#e2e8f0",
    "background": "#f7fafc",
    "card_bg": "#ffffff",
    "text": "#2d3748",
    "text_light": "#718096",
    "text_white": "#ffffff",

    # 甘特图颜色
    "gantt_not_started": "#cbd5e0",  # 灰色
    "gantt_in_progress": "#4299e1",  # 蓝色
    "gantt_completed": "#48bb78",    # 绿色
    "gantt_delayed": "#fc8181",      # 红色
}

# ============================================================
# Streamlit 页面配置
# ============================================================

PAGE_CONFIG = {
    "page_title": "塔筒生产进度管控系统",
    "page_icon": "🏭",
    "layout": "wide",
    "initial_sidebar_state": "expanded",
}

# ============================================================
# 工序参数
# ============================================================

PROCESS_NAMES = [
    "下料", "坡口", "卷板", "纵缝", "组对", "环缝",
    "焊接小件", "门框", "黑塔报检", "打砂", "防腐", "内装"
]

PROCESS_DAYS = [2, 2, 1, 2, 2, 3, 1, 4, 1, 2, 3, 2]
TOTAL_DAYS = 25

# ============================================================
# 排产工序顺序（工序节点计划，v4.0 新增）
# 独立于 processes 表 12 道制造工序，用于排产矩阵 Excel 导入
# 与节点计划管控/预警（process_node_plans 表 process_name 独立存储）
# ============================================================

SCHEDULE_PROCESS_NAMES = [
    "钢板到货", "法兰到货", "下料", "卷制", "组对",
    "黑塔", "防腐", "附件安装", "具备验收"
]

# ============================================================
# 异常责任分类选项
# ============================================================

RESPONSIBILITY_OPTIONS = [
    "设备故障", "人员不足", "物料短缺",
    "设计变更", "天气影响", "质量问题",
    "外部协调", "其他"
]

# ============================================================
# 自定义 CSS
# ============================================================

CUSTOM_CSS = """
<style>
    /* 风险标签 */
    .risk-tag-normal {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 4px;
        background: #f0fff4;
        color: #38a169;
        font-weight: 600;
        font-size: 14px;
    }
    .risk-tag-warning {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 4px;
        background: #fffff0;
        color: #d69e2e;
        font-weight: 600;
        font-size: 14px;
    }
    .risk-tag-delayed {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 4px;
        background: #fff5f5;
        color: #e53e3e;
        font-weight: 600;
        font-size: 14px;
    }

    /* 指标卡片 */
    .metric-card {
        background: white;
        border-radius: 8px;
        padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border-left: 4px solid #1a365d;
    }
    .metric-card.warning-card { border-left-color: #d69e2e; }
    .metric-card.delayed-card { border-left-color: #e53e3e; }
    .metric-card.normal-card { border-left-color: #38a169; }

    .metric-value {
        font-size: 32px;
        font-weight: 700;
        color: #2d3748;
    }
    .metric-label {
        font-size: 14px;
        color: #718096;
        margin-top: 4px;
    }

    /* 项目信息卡 */
    .project-info-card {
        background: linear-gradient(135deg, #1a365d 0%, #2b6cb0 100%);
        border-radius: 12px;
        padding: 24px;
        color: white;
        margin-bottom: 24px;
    }

    /* 异常行高亮 */
    .delayed-row {
        background-color: #fff5f5 !important;
    }
    .warning-row {
        background-color: #fffff0 !important;
    }

    /* ---- 节点计划页卡片容器 ---- */
    .node-section-box {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 28px;            /* 原 20px */
        margin-bottom: 16px;      /* 收紧：消除模块间空白条 */
    }
    /* 工序卡片网格：内边距收紧（避免模块顶部大片空白），卡片之间横向留白 */
    .node-section-box.process-card-grid {
        padding: 16px 20px;
    }

    /* ---- 工序卡片 ---- */
    .process-card {
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 16px;
        margin-bottom: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    .process-card:hover {
        border-color: #3182ce;
        box-shadow: 0 4px 12px rgba(49,130,206,0.12);
        transform: translateY(-1px);
    }
    .process-card-title {
        font-size: 18px;
        font-weight: 700;
        color: #2d3748;
        margin-bottom: 8px;
    }
    .process-card-meta {
        font-size: 13px;
        color: #718096;
    }
    .process-card-progress {
        margin-top: 10px;
        height: 8px;              /* 加高便于看清进度 */
        background: #edf2f7;      /* 浅灰轨道 */
        border-radius: 4px;
        overflow: hidden;
        max-width: none;          /* 去掉任何宽度限制 */
    }
    .process-card-progress-bar {
        height: 100%;
        border-radius: 4px;
        max-width: none;
    }

    /* ---- 弹窗内节点表格 ---- */
    .node-table-header {
        background: #f1f5f9;
        border-radius: 8px 8px 0 0;
        padding: 10px 12px;
        font-weight: 600;
        color: #475569;
        font-size: 14px;
    }
    .node-table-row {
        padding: 10px 12px;
        border-bottom: 1px solid #f1f5f9;
        font-size: 14px;
    }
    .node-table-row:nth-child(even) {
        background: #f8fafc;
    }
    .node-table-row:last-child {
        border-bottom: none;
        border-radius: 0 0 8px 8px;
    }
    .node-table-row:hover {
        background: #eff6ff;
    }

    /* ---- 右侧填报抽屉面板 ---- */
    .drawer-panel {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 3px solid #3182ce;
        border-radius: 12px;
        padding: 16px;
        min-height: 420px;
        max-height: 85vh;
        overflow-y: auto;
    }
    /* ---- 抽屉内部左侧概览卡片 ---- */
    .drawer-summary-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px;
    }
    .drawer-placeholder {
        text-align: center;
        color: #a0aec0;
        padding: 60px 10px;
        font-size: 15px;
    }
    .drawer-placeholder span { font-size: 13px; color: #cbd5e0; }

    /* ---- 分组容器背景 ---- */
    .grp-today  { background: #ebf8ff; border-radius: 8px; padding: 8px 10px; }
    .grp-overdue{ background: #fff5f5; border-radius: 8px; padding: 8px 10px; }
    .grp-future { background: #f7fafc; border-radius: 8px; padding: 8px 10px; }
    .grp-done   { background: #f0fff4; border-radius: 8px; padding: 8px 10px; }

    /* ---- 单元格级行（无背景色条，仅内边距；hover 轻微底色）---- */
    .cell-today, .cell-overdue, .cell-future, .cell-done {
        background: transparent;
        border-radius: 6px;
        padding: 6px 8px;
    }
    .cell-today:hover, .cell-overdue:hover, .cell-future:hover, .cell-done:hover {
        background: #f8fafc;
    }

    /* ---- 状态彩色胶囊 ---- */
    .status-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        line-height: 1.6;
    }

    /* ---- 抽屉底部固定保存区 ---- */
    .drawer-footer {
        position: sticky;
        bottom: 0;
        background: #f8fafc;
        padding-top: 10px;
        border-top: 1px solid #e2e8f0;
        margin-top: 10px;
    }

    /* ---- 工序卡片：直接用 st.button 渲染成卡片 ---- */
    .process-card-grid .stButton {
        width: 100%;
        margin-bottom: 18px;   /* 卡片纵向间距 */
    }
    .process-card-grid button[kind="secondary"] {
        width: 100% !important;
        min-height: 150px;
        background: #f8fafc;            /* 淡淡背景，与页面白色区分 */
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        padding: 24px;                   /* 增大内边距 */
        text-align: left;
        line-height: 1.8;                /* 行间距宽松 */
        white-space: pre-line;           /* 支持 label 中 \n 换行 */
        font-size: 16px;                 /* 整体字号加大 */
        font-weight: 500;                /* medium 字重 */
        color: #222222;                  /* 深黑文字 */
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        transition: all 0.2s ease;
    }
    .process-card-grid button[kind="secondary"]:hover {
        border-color: #3182ce;
        background: #ffffff;
        box-shadow: 0 4px 12px rgba(49,130,206,0.12);
        transform: translateY(-1px);
    }
    .process-card-grid button[kind="secondary"]:active {
        background: #f1f5f9;
    }

    /* ============================================================
       全站浅色工业风主题（追加覆盖）
       配色：页面 #f4f6f9 / 卡片白 / 边框 #e2e8f0 / 主色 #1a365d
             次文字 #64748b / 绿 #38a169 黄 #d69e2e 红 #e53e3e 灰 #94a3b8
       ============================================================ */
    /* 页面背景：浅灰蓝 */
    .stApp,
    .stApp header,
    .stMain,
    div[data-testid="stAppViewContainer"] {
        background-color: #f4f6f9 !important;
    }

    /* Streamlit border 容器统一卡片化：白底、圆角、边框、阴影 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-radius: 12px !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
        padding: 20px 24px !important;
        margin-bottom: 16px !important;   /* 收紧：消除模块间空白条 */
    }

    /* 标题统一深蓝 */
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3, .stMarkdown h4 {
        color: #1a365d !important;
    }
    /* 卡片标题行：左侧色块 + 深蓝标题（作用于 st.subheader 等 h2） */
    .stMarkdown h2 {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 0.2rem !important;
        margin-bottom: 0.6rem !important;
    }
    .stMarkdown h2::before {
        content: '';
        width: 8px;
        height: 22px;
        border-radius: 4px;
        background: #2b6cb0;
        display: inline-block;
        flex-shrink: 0;
    }

    /* metric 指标卡：白底卡片 + 深蓝数值 + 灰标签 */
    div[data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 14px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetricValue"] {
        color: #1a365d;
        font-weight: 700;
    }
    div[data-testid="stMetricLabel"] {
        color: #64748b;
    }

    /* ---- 通用工具类 ---- */
    /* 通用卡片框 */
    .block-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 20px 24px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
        margin-bottom: 20px;
    }
    /* 标题行：图标色块 + 标题 + 右侧辅助文字 */
    .block-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 14px;
    }
    .block-header .block-icon {
        width: 8px;
        height: 24px;
        border-radius: 4px;
        background: #2b6cb0;
        display: inline-block;
        flex-shrink: 0;
    }
    .block-title {
        font-size: 18px;
        font-weight: 700;
        color: #1a365d;
    }
    .block-subtitle {
        font-size: 13px;
        color: #64748b;
        margin-left: auto;
    }
    /* 卡片内次级分组：浅底、小圆角、左上小标签 */
    .sub-group {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 14px;
        margin: 10px 0;
    }
    .sub-group-label {
        font-size: 13px;
        font-weight: 600;
        color: #64748b;
        margin-bottom: 8px;
    }
    /* 彩色胶囊（规范四色：半透明底 + 同色文字） */
    .status-pill {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        line-height: 1.6;
    }
    /* 列表行卡片：左侧状态色条 + 内容 */
    .row-card {
        display: flex;
        align-items: center;
        gap: 12px;
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 8px;
    }
    .row-card .row-bar {
        width: 4px;
        align-self: stretch;
        border-radius: 2px;
        flex-shrink: 0;
    }
    /* 细圆角进度条 */
    .thin-progress {
        height: 6px;
        background: #edf2f7;
        border-radius: 3px;
        overflow: hidden;
    }
    .thin-progress-bar {
        height: 100%;
        border-radius: 3px;
    }

    /* ---- 现有类适配浅色工业风 ---- */
    .node-section-box {
        background: #ffffff !important;
    }
    .metric-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    .process-card-grid button[kind="secondary"] {
        background: #ffffff;
        border: 2px solid #e2e8f0;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }
    .process-card-grid button[kind="secondary"]:hover {
        border-color: #3182ce;
    }
    .drawer-panel {
        background: #ffffff;
    }
    .drawer-summary-box {
        background: #f8fafc;
    }
    .node-table-header {
        background: #f8fafc;
        color: #475569;
    }
    /* ---- 工序卡片：相对定位容器，透明按钮将覆盖整个区域 ---- */
    .proc-card-wrapper {
        position: relative;
        border-radius: 12px;
        overflow: hidden;
        margin-bottom: 20px;
        min-height: 150px;
        background: #ffffff;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
    }

    /* HTML 视觉卡片：白底、圆角、内边距 */
    .proc-card-html {
        border-radius: 12px;
        padding: 20px 22px;
        min-height: 150px;
    }
    .proc-card-name {
        font-size: 18px;
        font-weight: 700;
        color: #1a365d;
    }
    .proc-card-status {
        font-size: 14px;
        font-weight: 500;
        color: #64748b;
        margin-top: 4px;
    }
    .proc-card-counts {
        font-size: 16px;
        font-weight: 700;
        color: #222222;
        margin-top: 8px;
    }

    /* 动态填充进度条：轨道 8px 浅灰，填充随百分比宽度 + 状态色 */
    .proc-card-bar-wrap {
        margin-top: 12px;
        height: 8px;
        background: #edf2f7;
        border-radius: 4px;
        overflow: hidden;
    }
    .proc-card-bar-fill {
        height: 100%;
        border-radius: 4px;
        transition: width 0.4s ease;
    }

    /* 透明覆盖按钮：占满整个卡片，点击整片打开弹窗 */
    .proc-card-wrapper .stButton {
        position: absolute !important;
        top: 0 !important;
        left: 0 !important;
        width: 100% !important;
        height: 100% !important;
        z-index: 10;
    }
    .proc-card-wrapper .stButton > button {
        width: 100% !important;
        height: 100% !important;
        min-height: 150px !important;
        opacity: 0;
        border: none !important;
        background: transparent !important;
        margin: 0 !important;
        padding: 0 !important;
        cursor: pointer;
    }
    .proc-card-wrapper .stButton > button:hover,
    .proc-card-wrapper .stButton > button:active,
    .proc-card-wrapper .stButton > button:focus {
        border: none !important;
        box-shadow: none !important;
        background: transparent !important;
        outline: none !important;
    }

    /* ---- 工序卡片内容排版（process-card-inner）---- */
    .process-card-inner {
        padding: 18px 20px;      /* 内容更饱满 */
        min-height: 130px;
        display: flex;
        flex-direction: column;
    }
    /* 第一行：圆点 + 工序名 + 状态胶囊 */
    .pc-row-1 {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .pc-dot {
        font-size: 14px;
        margin-right: 2px;
        flex-shrink: 0;
    }
    .pc-title {
        font-size: 16px;
        font-weight: 700;
        color: #1a365d;
        flex-shrink: 0;
    }
    .pc-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        margin-left: auto;       /* 靠右 */
    }
    /* 第二行：完成数量 */
    .pc-row-2 {
        margin-top: 8px;
    }
    .pc-count {
        font-size: 13px;
        color: #64748b;
    }
    /* 进度条 + 百分比 */
    .pc-progress-wrap {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-top: 8px;
    }
    .pc-progress-track {
        flex: 1;
        height: 8px;
        background: #edf2f7;
        border-radius: 4px;
        overflow: hidden;
    }
    .pc-progress-bar {
        height: 100%;
        border-radius: 4px;
        transition: width 0.3s ease;
    }
    .pc-percent {
        font-size: 12px;
        color: #64748b;
        flex-shrink: 0;
        min-width: 48px;
        text-align: right;
    }
    /* 底部：查看详情提示 */
    .pc-row-footer {
        margin-top: auto;
        padding-top: 10px;
        text-align: right;
    }
    .pc-hint {
        font-size: 12px;
        color: #94a3b8;
        transition: color 0.2s ease;
    }
    .proc-card-wrapper:hover .pc-hint {
        color: #3182ce;
    }

    /* ---- 工序卡片盒（HTML 主体 + 独立查看详情按钮）---- */
    /* 模块标题行：紧贴模块顶部，标题与卡片网格间距 12-16px */
    .process-card-grid h4 {
        margin: 0 0 14px !important;
        font-weight: 700;
        color: #1a365d;
    }
    .process-card-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06);
        margin-bottom: 16px;   /* 卡片独立成框：底部间距 16px，不粘连 */
        min-height: 120px;
    }
    .pc-header {
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .pc-count {
        font-size: 13px;
        color: #64748b;
        margin-top: 8px;
    }
    .pc-progress {
        margin-top: 10px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .pc-progress-track {
        flex: 1;
        height: 8px;
        background: #edf2f7;
        border-radius: 4px;
        overflow: hidden;
    }
    .pc-progress-bar {
        height: 100%;
        border-radius: 4px;
        transition: width 0.3s ease;
    }
    .pc-percent {
        font-size: 12px;
        color: #64748b;
        min-width: 35px;
        text-align: right;
    }

    /* 查看详情按钮：紧凑 + 右对齐 */
    .process-card-grid .stButton {
        display: flex;
        justify-content: flex-end;
        margin-top: 6px;
    }
    .process-card-grid .stButton > button {
        padding: 4px 14px !important;
        font-size: 13px !important;
        border-radius: 8px !important;
        border: 1px solid #e2e8f0 !important;
        color: #1a365d !important;
        background: #ffffff !important;
        min-height: 0 !important;
        line-height: 1.4 !important;
    }
    .process-card-grid .stButton > button:hover {
        border-color: #3182ce !important;
        color: #3182ce !important;
    }

    /* ---- 填报弹窗互斥分组（手风琴）控件 ---- */
    div[data-testid="stSegmentedControl"] {
        width: 100%;
        margin-bottom: 16px;
    }
    div[data-baseweb="radio-group"] {
        display: flex;
        gap: 12px;
        margin-bottom: 16px;
    }
</style>
"""

# ============================================================
# MySQL 数据库配置（SQLite → MySQL 迁移后使用）
# 全部从环境变量读取，避免把密码硬编码进代码。
# 未设置时使用本机开发默认值（密码默认为空）。
# ============================================================

MYSQL_CONFIG = {
    "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("MYSQL_PORT", "3306")),
    "user": os.environ.get("MYSQL_USER", "root"),
    "password": os.environ.get("MYSQL_PASSWORD", ""),
    "database": os.environ.get("MYSQL_DATABASE", "tower_production"),
    "charset": os.environ.get("MYSQL_CHARSET", "utf8mb4"),
}
