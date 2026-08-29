-- ============================================================
-- 塔筒生产进度管控系统 — 数据库完整重建脚本（v4.0 真实 schema）
-- 用途：覆盖之前照简化版误建的 7 张表（列名/结构不一致导致代码报错）
-- 前提：当前库内无业务数据（total:0），可安全 DROP + 重建
-- 执行方式：CloudBase SQL 编辑器不支持多段 SQL，请逐条执行下列语句
-- ============================================================

-- ---------- 第 1 步：DROP 旧表（先子后父，避免 FK 约束报错）----------
DROP TABLE IF EXISTS milestones;
DROP TABLE IF EXISTS node_exceptions;
DROP TABLE IF EXISTS node_actual_progress;
DROP TABLE IF EXISTS process_node_plans;
DROP TABLE IF EXISTS import_logs;
DROP TABLE IF EXISTS system_config;
DROP TABLE IF EXISTS projects;

-- ---------- 第 2 步：CREATE 新表（按真实 v4.0 schema，逐个执行）----------

-- 表1：projects（项目基础信息表）
CREATE TABLE IF NOT EXISTS projects (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_name        VARCHAR(191) NOT NULL,
    factory_name        VARCHAR(191) NOT NULL,
    last_month_output   INT DEFAULT 0,
    monthly_plan        INT NOT NULL DEFAULT 0,
    monthly_total_plan  INT DEFAULT 0,
    contract_count      INT NULL COMMENT '合同总数（调度令「合同数量」导入；独立工序累计完成/累计发运的参考计划数）',
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

CREATE INDEX idx_projects_name ON projects(project_name);
CREATE INDEX idx_projects_person ON projects(delivery_person);
CREATE INDEX idx_projects_risk ON projects(risk_level);
CREATE INDEX idx_projects_status ON projects(status);

-- 表2：milestones（项目里程碑）
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

-- 表3：system_config（系统配置）
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

INSERT IGNORE INTO system_config (config_key, config_value, config_type, description) VALUES
    ('warning_threshold_days', '1', 'integer', '预警触发阈值：滞后天数'),
    ('delay_threshold_days', '2', 'integer', '延期触发阈值：滞后天数'),
    ('workday_exclude_weekends', 'true', 'string', '是否排除周末'),
    ('custom_holidays', '[]', 'json', '自定义节假日列表'),
    ('standard_process_count', '12', 'integer', '标准工序总数'),
    ('standard_total_days', '25', 'integer', '标准总工期'),
    ('system_version', '1.0.0', 'string', '系统版本号');

-- 表4：import_logs（导入日志）
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

-- 表5：process_node_plans（工序节点计划）
CREATE TABLE IF NOT EXISTS process_node_plans (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    process_name    VARCHAR(64) NOT NULL,
    process_order   INT NOT NULL DEFAULT 0,
    plan_date       DATE NULL,
    plan_qty        INT NOT NULL DEFAULT 1,
    UNIQUE KEY uk_proj_proc_date (project_id, process_name, plan_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 表6：node_actual_progress（节点实际进度）
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

-- 表7：node_exceptions（节点异常提报）
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

-- 性能索引
CREATE INDEX idx_pnp_project ON process_node_plans(project_id);
CREATE INDEX idx_nap_project ON node_actual_progress(project_id);

-- ---------- 第 3 步：验证 ----------
SHOW TABLES;
