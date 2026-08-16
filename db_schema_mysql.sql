-- ============================================================
-- 塔筒生产进度管控与预警系统 — 数据库表结构设计（MySQL 版）
-- 数据库：MySQL 8.0（InnoDB / utf8mb4）
-- 版本：v4.0 — 含机型四字段唯一约束 + 月度指标 + 日产量管控 + 工序节点计划管控
-- 日期：2026-08-XX
-- 说明：由 db_schema.sql + db_upgrade_v2.sql 转换而来；
--       init_database() 读取本文件建表（表已存在则跳过）。
--
-- 转换规则：
--   INTEGER PRIMARY KEY AUTOINCREMENT → INT PRIMARY KEY AUTO_INCREMENT
--   TEXT → VARCHAR(255)（备注/长文本用 TEXT）
--   日期列 → VARCHAR(20)
--   DEFAULT (datetime('now','localtime')) → DATETIME DEFAULT CURRENT_TIMESTAMP
--   INSERT OR IGNORE → INSERT IGNORE
--   每表末尾 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
--   旧库 ALTER TABLE ADD COLUMN 迁移语句已删除（新库全量建表）
--
-- 注意：projects 四字段唯一索引参与列使用 VARCHAR(191)，
--       utf8mb4 下 4×191×4=3056B < InnoDB 3072B 索引上限；
--       若用 VARCHAR(255) 则 4080B 超限，建表会失败。
-- ============================================================

-- ============================================================
-- 表1：projects（项目基础信息表）
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_name        VARCHAR(191) NOT NULL,
    factory_name        VARCHAR(191) NOT NULL,
    last_month_output   INT DEFAULT 0,
    monthly_plan        INT NOT NULL DEFAULT 0,
    monthly_total_plan  INT DEFAULT 0,
    delivery_person     VARCHAR(191) NOT NULL,
    plan_start_date     VARCHAR(20),
    plan_end_date       VARCHAR(20),
    actual_start_date   VARCHAR(20),
    actual_end_date     VARCHAR(20),
    risk_level          VARCHAR(20) DEFAULT 'normal',
    status              VARCHAR(20) DEFAULT 'in_progress',
    machine_type        VARCHAR(191) DEFAULT '',
    remarks             TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(255) DEFAULT 'system',
    updated_by          VARCHAR(255) DEFAULT 'system',

    UNIQUE KEY uk_projects_4fields (project_name, factory_name, delivery_person, machine_type),
    CONSTRAINT chk_projects_risk CHECK (risk_level IN ('normal', 'warning', 'delayed')),
    CONSTRAINT chk_projects_status CHECK (status IN ('in_progress', 'completed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 查询索引
CREATE INDEX idx_projects_name ON projects(project_name);
CREATE INDEX idx_projects_person ON projects(delivery_person);
CREATE INDEX idx_projects_risk ON projects(risk_level);
CREATE INDEX idx_projects_status ON projects(status);


-- ============================================================
-- 表2：processes（工序进度明细表）
-- 每个项目固定12道工序，项目创建时自动初始化
-- ============================================================
CREATE TABLE IF NOT EXISTS processes (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_id          INT NOT NULL,
    process_order       INT NOT NULL,
    process_name        VARCHAR(255) NOT NULL,
    standard_days       INT NOT NULL,
    plan_start_date     VARCHAR(20),
    plan_end_date       VARCHAR(20),
    actual_start_date   VARCHAR(20),
    actual_end_date     VARCHAR(20),
    status              VARCHAR(20) DEFAULT 'not_started',
    lag_days            INT DEFAULT 0,
    completion_pct      DOUBLE DEFAULT 0.0,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by          VARCHAR(255) DEFAULT 'system',

    UNIQUE KEY uk_processes_project_order (project_id, process_order),
    CONSTRAINT fk_processes_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT chk_processes_status CHECK (status IN ('not_started', 'in_progress', 'completed', 'delayed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 查询索引
CREATE INDEX idx_processes_project ON processes(project_id);
CREATE INDEX idx_processes_status ON processes(status);
CREATE INDEX idx_processes_plan_end ON processes(plan_end_date);


-- ============================================================
-- 表3：anomalies（异常处理记录表）
-- ============================================================
CREATE TABLE IF NOT EXISTS anomalies (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_id          INT NOT NULL,
    process_id          INT NOT NULL,
    process_name        VARCHAR(255) NOT NULL,
    anomaly_reason      TEXT NOT NULL,
    responsibility      VARCHAR(50) NOT NULL,
    estimated_resolve_date VARCHAR(20),
    actual_resolve_date    VARCHAR(20),
    measures            TEXT,
    handler             VARCHAR(255),
    status              VARCHAR(20) DEFAULT 'open',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    created_by          VARCHAR(255) DEFAULT 'system',
    updated_by          VARCHAR(255) DEFAULT 'system',

    CONSTRAINT fk_anomalies_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_anomalies_process FOREIGN KEY (process_id) REFERENCES processes(id) ON DELETE CASCADE,
    CONSTRAINT chk_anomalies_responsibility CHECK (responsibility IN ('设备故障', '人员不足', '物料短缺', '设计变更', '天气影响', '质量问题', '外部协调', '其他')),
    CONSTRAINT chk_anomalies_status CHECK (status IN ('open', 'in_progress', 'closed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 查询索引
CREATE INDEX idx_anomalies_project ON anomalies(project_id);
CREATE INDEX idx_anomalies_process ON anomalies(process_id);
CREATE INDEX idx_anomalies_status ON anomalies(status);


-- ============================================================
-- 表4：milestones（里程碑节点表）
-- ============================================================
CREATE TABLE IF NOT EXISTS milestones (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_id          INT NOT NULL,
    milestone_name      VARCHAR(255) NOT NULL,
    milestone_type      VARCHAR(20) DEFAULT 'key_node',
    target_date         VARCHAR(20) NOT NULL,
    actual_date         VARCHAR(20),
    status              VARCHAR(20) DEFAULT 'pending',
    remarks             TEXT,
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by          VARCHAR(255) DEFAULT 'system',

    CONSTRAINT fk_milestones_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT chk_milestones_type CHECK (milestone_type IN ('key_node', 'delivery', 'inspection')),
    CONSTRAINT chk_milestones_status CHECK (status IN ('pending', 'achieved', 'overdue'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_milestones_project ON milestones(project_id);


-- ============================================================
-- 表5：system_config（系统配置表）
-- ============================================================
CREATE TABLE IF NOT EXISTS system_config (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    config_key          VARCHAR(255) NOT NULL UNIQUE,
    config_value        VARCHAR(255) NOT NULL,
    config_type         VARCHAR(20) DEFAULT 'string',
    description         TEXT,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_by          VARCHAR(255) DEFAULT 'system',

    CONSTRAINT chk_config_type CHECK (config_type IN ('string', 'integer', 'float', 'json', 'date_list'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 初始化默认配置
INSERT IGNORE INTO system_config (config_key, config_value, config_type, description) VALUES
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
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    file_name           VARCHAR(255) NOT NULL,
    total_rows          INT DEFAULT 0,
    success_rows        INT DEFAULT 0,
    error_rows          INT DEFAULT 0,
    error_details       TEXT,
    imported_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    imported_by         VARCHAR(255) DEFAULT 'system'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表7：daily_progress（每日进度填报表，v2.0 新增）
-- ============================================================
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


-- ============================================================
-- 表8：process_node_plans（工序节点计划表，v4.0 新增）
-- 排产 Excel 导入：多套塔筒 × 9 道排产工序 × 计划完成日期矩阵
-- 排产工序独立于 processes 表 12 道制造工序，process_name 独立存储
-- ============================================================
CREATE TABLE IF NOT EXISTS process_node_plans (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    process_name    VARCHAR(64) NOT NULL,
    process_order   INT NOT NULL DEFAULT 0,
    plan_date       DATE NOT NULL,
    plan_qty        INT NOT NULL DEFAULT 1,
    UNIQUE KEY uk_proj_proc_date (project_id, process_name, plan_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表9：node_actual_progress（节点实际进度表，v4.0 新增）
-- 记录各工序节点实际完成套数（填报日期锁定当天）
-- ============================================================
CREATE TABLE IF NOT EXISTS node_actual_progress (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    node_plan_id    INT NOT NULL,
    process_name    VARCHAR(64) NOT NULL,
    actual_qty      INT NOT NULL DEFAULT 0,
    report_date     DATE NOT NULL,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_proj_node (project_id, node_plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 节点异常提报表
-- ============================================================
CREATE TABLE IF NOT EXISTS node_exceptions (
  id INT AUTO_INCREMENT PRIMARY KEY,
  project_id INT NOT NULL COMMENT '项目ID',
  node_id INT NOT NULL COMMENT '关联 node_plans.id',
  process_name VARCHAR(64) NOT NULL COMMENT '工序名称',
  plan_date DATE NOT NULL COMMENT '计划日期',
  responsibility_category VARCHAR(32) NOT NULL COMMENT '责任分类',
  reason_detail TEXT NOT NULL COMMENT '异常原因详情',
  handler VARCHAR(64) DEFAULT NULL COMMENT '处理人',
  planned_close_date DATE DEFAULT NULL COMMENT '计划关闭日期',
  measures TEXT DEFAULT NULL COMMENT '处理措施',
  status VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '状态：pending/处理中processing/已关闭closed',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  closed_at DATETIME DEFAULT NULL,
  INDEX idx_project_id (project_id),
  INDEX idx_node_id (node_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表关联关系说明
-- ============================================================
--
-- projects (1) ──── (N) processes      项目与工序：一对多
-- projects (1) ──── (N) anomalies      项目与异常：一对多
-- projects (1) ──── (N) milestones     项目与里程碑：一对多
-- processes (1) ──── (N) anomalies     工序与异常：一对多
-- processes (1) ──── (N) daily_progress 工序与日报：一对多
--
-- 删除级联：删除项目时，自动删除关联的工序、异常、里程碑、日报记录
