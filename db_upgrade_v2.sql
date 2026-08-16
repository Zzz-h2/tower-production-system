-- ============================================================
-- 塔筒生产进度管控系统 数据库升级 v2.0
-- 新增: daily_progress 表 + monthly_total_plan 字段
-- 兼容: 已存在的 projects 表用 ALTER TABLE 补充字段
-- ============================================================

-- 表7: 每日进度填报
CREATE TABLE IF NOT EXISTS daily_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL,
    process_id      INTEGER NOT NULL,
    process_name    TEXT    NOT NULL,
    report_date     TEXT    NOT NULL,
    plan_qty        REAL    DEFAULT 0,
    actual_qty      REAL    DEFAULT 0,
    cumulative_plan REAL    DEFAULT 0,
    cumulative_actual REAL  DEFAULT 0,
    daily_status    TEXT    DEFAULT 'in_progress',
    remarks         TEXT,
    created_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_by      TEXT    DEFAULT 'system',
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
    UNIQUE(process_id, report_date),
    CHECK(daily_status IN ('completed', 'in_progress'))
);

CREATE INDEX IF NOT EXISTS idx_dp_project ON daily_progress(project_id);
CREATE INDEX IF NOT EXISTS idx_dp_process ON daily_progress(process_id);
CREATE INDEX IF NOT EXISTS idx_dp_date ON daily_progress(report_date);

-- 迁移: projects 表补充 monthly_total_plan 字段(idempotent)
INSERT OR IGNORE INTO system_config (config_key, config_value, config_type, description)
VALUES ('system_version', '2.0.0', 'string', '系统版本号');
