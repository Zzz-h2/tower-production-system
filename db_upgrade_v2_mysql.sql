-- ============================================================
-- 塔筒生产进度管控系统 数据库升级 v2.0（MySQL 版）
-- 新增: daily_progress 表
--
-- 说明:
--   1. monthly_total_plan 字段已包含在 db_schema_mysql.sql 的
--      projects 建表语句中，这里不再执行 ALTER TABLE ADD COLUMN。
--   2. 全新库由 init_database() 直接读取 db_schema_mysql.sql 全量建表，
--      本脚本仅用于「已存在旧 MySQL 库」时的手工补充升级。
-- ============================================================

-- 表7: 每日进度填报
CREATE TABLE IF NOT EXISTS daily_progress (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_id          INT NOT NULL,
    process_id          INT NOT NULL,
    process_name        VARCHAR(255) NOT NULL,
    report_date         VARCHAR(20) NOT NULL,
    plan_qty            DOUBLE DEFAULT 0,
    actual_qty          DOUBLE DEFAULT 0,
    cumulative_plan     DOUBLE DEFAULT 0,
    cumulative_actual   DOUBLE DEFAULT 0,
    daily_status        VARCHAR(20) DEFAULT 'in_progress',
    remarks             TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by          VARCHAR(255) DEFAULT 'system',

    UNIQUE KEY uk_daily_progress (process_id, report_date),
    CONSTRAINT fk_daily_progress_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_daily_progress_process FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
    CONSTRAINT chk_daily_progress_status CHECK (daily_status IN ('completed', 'in_progress'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_dp_project ON daily_progress(project_id);
CREATE INDEX idx_dp_process ON daily_progress(process_id);
CREATE INDEX idx_dp_date ON daily_progress(report_date);

-- 版本号更新
INSERT IGNORE INTO system_config (config_key, config_value, config_type, description)
VALUES ('system_version', '2.0.0', 'string', '系统版本号');
