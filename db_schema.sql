-- ============================================================
-- 塔筒生产进度管控与预警系统 — 数据库表结构设计
-- 数据库：SQLite
-- 版本：v2.0 — 新增月度指标+日产量管控
-- 日期：2026-08-06
-- ============================================================

PRAGMA foreign_keys = ON;

-- ============================================================
-- 表1：projects（项目基础信息表）
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_name    TEXT    NOT NULL,
    factory_name    TEXT    NOT NULL,
    last_month_output INTEGER DEFAULT 0,
    monthly_plan    INTEGER NOT NULL DEFAULT 0,
    monthly_total_plan INTEGER DEFAULT 0,       -- v2.0: 月度总计划出品数（段）
    delivery_person TEXT    NOT NULL,
    plan_start_date TEXT,
    plan_end_date   TEXT,
    actual_start_date TEXT,
    actual_end_date   TEXT,
    risk_level      TEXT    DEFAULT 'normal',
    status          TEXT    DEFAULT 'in_progress',
    machine_type    TEXT    DEFAULT '',           -- v3.0: 机型（参与四字段组合查重）
    remarks         TEXT,
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    created_by      TEXT    DEFAULT 'system',
    updated_by      TEXT    DEFAULT 'system',

    UNIQUE(project_name, factory_name, delivery_person, machine_type),
    CHECK(risk_level IN ('normal', 'warning', 'delayed')),
    CHECK(status IN ('in_progress', 'completed'))
);

-- 迁移：兼容已存在的 projects 表，补充 missing column
ALTER TABLE projects ADD COLUMN monthly_total_plan INTEGER DEFAULT 0;

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_projects_name ON projects(project_name);
CREATE INDEX IF NOT EXISTS idx_projects_person ON projects(delivery_person);
CREATE INDEX IF NOT EXISTS idx_projects_risk ON projects(risk_level);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);


-- ============================================================
-- 表2：processes（工序进度明细表）
-- 每个项目固定12道工序，项目创建时自动初始化
-- ============================================================
CREATE TABLE IF NOT EXISTS processes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    process_order   INTEGER NOT NULL,
    process_name    TEXT    NOT NULL,
    standard_days   INTEGER NOT NULL,
    plan_start_date TEXT,
    plan_end_date   TEXT,
    actual_start_date TEXT,
    actual_end_date   TEXT,
    status          TEXT    DEFAULT 'not_started',
    lag_days        INTEGER DEFAULT 0,
    completion_pct  REAL    DEFAULT 0.0,
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_by      TEXT    DEFAULT 'system',

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, process_order),
    CHECK(status IN ('not_started', 'in_progress', 'completed', 'delayed'))
);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_processes_project ON processes(project_id);
CREATE INDEX IF NOT EXISTS idx_processes_status ON processes(status);
CREATE INDEX IF NOT EXISTS idx_processes_plan_end ON processes(plan_end_date);


-- ============================================================
-- 表3：anomalies（异常处理记录表）
-- ============================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    process_id      INTEGER NOT NULL,
    process_name    TEXT    NOT NULL,
    anomaly_reason  TEXT    NOT NULL,
    responsibility  TEXT    NOT NULL,
    estimated_resolve_date TEXT,
    actual_resolve_date    TEXT,
    measures        TEXT,
    handler         TEXT,
    status          TEXT    DEFAULT 'open',
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    created_by      TEXT    DEFAULT 'system',
    updated_by      TEXT    DEFAULT 'system',

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
    CHECK(responsibility IN ('设备故障', '人员不足', '物料短缺', '设计变更', '天气影响', '质量问题', '外部协调', '其他')),
    CHECK(status IN ('open', 'in_progress', 'closed'))
);

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_anomalies_project ON anomalies(project_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_process ON anomalies(process_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);


-- ============================================================
-- 表4：milestones（里程碑节点表）
-- ============================================================
CREATE TABLE IF NOT EXISTS milestones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    milestone_name  TEXT    NOT NULL,
    milestone_type  TEXT    DEFAULT 'key_node',
    target_date     TEXT    NOT NULL,
    actual_date     TEXT,
    status          TEXT    DEFAULT 'pending',
    remarks         TEXT,
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_by      TEXT    DEFAULT 'system',

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CHECK(milestone_type IN ('key_node', 'delivery', 'inspection')),
    CHECK(status IN ('pending', 'achieved', 'overdue'))
);

CREATE INDEX IF NOT EXISTS idx_milestones_project ON milestones(project_id);


-- ============================================================
-- 表5：system_config（系统配置表）
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    config_key      TEXT    NOT NULL UNIQUE,
    config_value    TEXT    NOT NULL,
    config_type     TEXT    DEFAULT 'string',
    description     TEXT,
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_by      TEXT    DEFAULT 'system',
    CHECK(config_type IN ('string', 'integer', 'float', 'json', 'date_list'))
);

-- 初始化默认配置
INSERT OR IGNORE INTO system_config (config_key, config_value, config_type, description) VALUES
    ('warning_threshold_days', '1', 'integer', '预警触发阈值：滞后天数'),
    ('delay_threshold_days', '2', 'integer', '延期触发阈值：滞后天数'),
    ('workday_exclude_weekends', 'true', 'string', '是否排除周末'),
    ('custom_holidays', '[]', 'json', '自定义节假日列表'),
    ('standard_process_count', '12', 'integer', '标准工序总数'),
    ('standard_total_days', '25', 'integer', '标准总工期'),
    ('system_version', '1.0.0', 'string', '系统版本号');


-- ============================================================
-- 表6：import_logs（导入日志表）
-- ============================================================
CREATE TABLE IF NOT EXISTS import_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name       TEXT    NOT NULL,                       -- 导入文件名
    total_rows      INTEGER DEFAULT 0,                     -- 总行数
    success_rows    INTEGER DEFAULT 0,                     -- 成功导入行数
    error_rows      INTEGER DEFAULT 0,                     -- 失败行数
    error_details   TEXT,                                   -- 错误详情（JSON）
    imported_at     TEXT    DEFAULT (datetime('now', 'localtime')),
    imported_by     TEXT    DEFAULT 'system'
);

-- ============================================================
-- 表关联关系说明
-- ============================================================
-- 
-- projects (1) ──── (N) processes      项目与工序：一对多
-- projects (1) ──── (N) anomalies      项目与异常：一对多
-- projects (1) ──── (N) milestones     项目与里程碑：一对多
-- processes (1) ──── (N) anomalies     工序与异常：一对多
--
-- 删除级联：删除项目时，自动删除关联的工序、异常、里程碑记录


-- ============================================================
-- 常用查询 SQL 示例
-- ============================================================

-- 【查询1】项目列表带风险状态
/*
SELECT 
    p.id,
    p.project_name,
    p.factory_name,
    p.last_month_output,
    p.monthly_plan,
    p.delivery_person,
    COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) AS completed_count,
    ROUND(COUNT(CASE WHEN pr.status = 'completed' THEN 1 END) * 100.0 / 12, 1) AS progress_pct,
    p.risk_level,
    p.status
FROM projects p
LEFT JOIN processes pr ON p.id = pr.project_id
WHERE p.status = 'in_progress'
GROUP BY p.id
ORDER BY 
    CASE p.risk_level 
        WHEN 'delayed' THEN 1 
        WHEN 'warning' THEN 2 
        WHEN 'normal' THEN 3 
    END;
*/

-- 【查询2】单项目工序详情
/*
SELECT 
    process_order,
    process_name,
    standard_days,
    plan_start_date,
    plan_end_date,
    actual_start_date,
    actual_end_date,
    status,
    lag_days,
    completion_pct
FROM processes
WHERE project_id = ?
ORDER BY process_order;
*/

-- 【查询3】异常记录统计（按项目和责任分类）
/*
SELECT 
    p.project_name,
    a.responsibility,
    COUNT(*) AS anomaly_count,
    COUNT(CASE WHEN a.status = 'closed' THEN 1 END) AS closed_count,
    COUNT(CASE WHEN a.status = 'open' THEN 1 END) AS open_count
FROM anomalies a
JOIN projects p ON a.project_id = p.id
GROUP BY p.project_name, a.responsibility
ORDER BY p.project_name, anomaly_count DESC;
*/

-- 【查询4】按负责人统计预警/延期项目数
/*
SELECT 
    delivery_person,
    COUNT(*) AS total_projects,
    COUNT(CASE WHEN risk_level = 'warning' THEN 1 END) AS warning_count,
    COUNT(CASE WHEN risk_level = 'delayed' THEN 1 END) AS delayed_count
FROM projects
WHERE status = 'in_progress'
GROUP BY delivery_person;
*/
