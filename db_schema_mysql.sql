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
    contract_count      INT NULL COMMENT '合同总数（调度令「合同数量」导入；独立工序累计完成/累计发运的参考计划数）',
    delivery_person     VARCHAR(191) NOT NULL,
    big_area_person     VARCHAR(191) DEFAULT '',
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

    -- 唯一键提醒：machine_type 默认 ''。若某次导入未提供机型列，则所有同(名称+厂家+负责人)
    -- 的记录都会落到 machine_type='' 而互相判重（upsert 覆盖 / 手动添加 409）。
    -- 导入前请确保机型列有值，或明确该(名称+厂家+负责人)组合本身唯一。
    UNIQUE KEY uk_projects_4fields (project_name, factory_name, delivery_person, machine_type),
    CONSTRAINT chk_projects_risk CHECK (risk_level IN ('normal', 'warning', 'delayed')),
    CONSTRAINT chk_projects_status CHECK (status IN ('in_progress', 'completed'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 查询索引
CREATE INDEX idx_projects_name ON projects(project_name);
CREATE INDEX idx_projects_person ON projects(delivery_person);
CREATE INDEX idx_projects_risk ON projects(risk_level);
CREATE INDEX idx_projects_status ON projects(status);
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
CREATE TABLE IF NOT EXISTS process_node_plans (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    process_name    VARCHAR(64) NOT NULL,
    process_order   INT NOT NULL DEFAULT 0,
    plan_date       DATE NULL,
    plan_qty        INT NOT NULL DEFAULT 1,
    manager         VARCHAR(64) NULL COMMENT '归属负责人（多负责人项目按 / 拆分后逐位导入；NULL=历史/未拆分数据，仅汇总视图可见）',
    plan_month      CHAR(7) NULL COMMENT '排产归属月 YYYY-MM（仅排产导入的工序行有值；NULL=独立工序 90/91、手动完成占位行 99、或 v7.2 迁移前的历史行）',
    UNIQUE KEY uk_proj_proc_date_mgr (project_id, process_name, plan_date, manager),
    KEY idx_pnp_month (project_id, plan_month),
    CONSTRAINT fk_pnp_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
    manager         VARCHAR(64) NULL COMMENT '归属负责人（与对应 node_plan 行一致；NULL=历史/未拆分数据）',
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_proj_node (project_id, node_plan_id),
    CONSTRAINT fk_nap_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
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
  INDEX idx_status (status),
  CONSTRAINT fk_nex_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表10：users（系统用户表，v5.0 大区行级数据隔离新增）
-- username = 大区名（与 Excel 严格一致）；admin 的 big_area_name 为空
-- 初始账号由 backend/scripts/seed_users.py upsert（不在此处插入）
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    username            VARCHAR(64) NOT NULL,
    password_hash       VARCHAR(255) NOT NULL,
    role                VARCHAR(20) DEFAULT 'big_area',
    big_area_name       VARCHAR(191) DEFAULT '',
    status              VARCHAR(20) DEFAULT 'active',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_users_username (username),
    KEY idx_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表11：project_manager_plans（多负责人月度计划表，v6.0 多负责人管理新增）
-- 记录「每位负责人 对 某项目」各自申报的本月计划数。
-- 设计要点：
--   - projects.monthly_plan 保持不动，仍为项目整体计划数（项目列表原样展示用）；
--   - 本表的 monthly_plan 为各负责人独立申报值，【不强制】求和 = projects.monthly_plan（方案P）；
--   - 汇总视图用 projects.monthly_plan 判定；单人视图用本表对应值判定；
--   - delivery_person 原样保存（如「张三/李四」），拆分逻辑在应用层按 / 切分。
-- ============================================================
CREATE TABLE IF NOT EXISTS project_manager_plans (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    project_id      INT NOT NULL,
    manager         VARCHAR(64) NOT NULL COMMENT '负责人姓名（delivery_person 按 / 拆分后的单个姓名）',
    monthly_plan    INT NOT NULL DEFAULT 0 COMMENT '该负责人对本项目的本月计划数（独立申报）',
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_pid_mgr (project_id, manager),
    CONSTRAINT fk_pmp_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表12：node_segment_progress（按段填报进度表，v7.1 行级化）
-- 记录「某套（计划行）」的分段进度（一套细分为多段的工序，如组对/门框焊接）。
-- 设计要点：
--   - 段数挂在计划行（node_plan_id）上，唯一键 uk_node_seg 保证一套一条；
--   - 排产重导删除计划行时段数级联清理（重导=重排，可接受）；
--   - 负责人维度不单独存——计划行 process_node_plans 自带 manager；
--   - 段数独立记录，不折算、不写 actual_qty（联动校验/出品排名/进度百分比零影响）。
-- ============================================================
CREATE TABLE IF NOT EXISTS node_segment_progress (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    project_id    INT NOT NULL,
    node_plan_id  INT NOT NULL,
    segment_total INT NOT NULL,
    segment_done  INT NOT NULL DEFAULT 0,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_node_seg (node_plan_id),
    CONSTRAINT fk_nsp_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_nsp_node   FOREIGN KEY (node_plan_id) REFERENCES process_node_plans(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表9：dispatch_records（月度调度令快照表）
-- ============================================================
-- 语义：一次月度调度令导入 = 一批「项目 × 归属月」快照。
--   项目主表 projects 与月份无关（四字段唯一键跨月复用同一行，重复导入走 UPDATE）；
--   本表负责记录「该项目在本月调度令中的计划口径」，使同一项目可同时出现在多个月份
--   列表，且各月 monthly_plan / last_month_output 互不覆盖（历史月份可回溯）。
--
-- 列表/KPI 的月份口径：created_at 年月 ∪ 本表 plan_month（app/core/db.get_projects_filtered）。
-- is_approx=1 表示历史回填时该月原值已被后续导入覆盖，只能沿用最新值近似留档。
-- ============================================================
CREATE TABLE IF NOT EXISTS dispatch_records (
    id                  INT PRIMARY KEY AUTO_INCREMENT,
    project_id          INT NOT NULL,
    plan_month          CHAR(7) NOT NULL COMMENT '调度令归属月 YYYY-MM',
    monthly_plan        INT NOT NULL DEFAULT 0 COMMENT '本月计划出品（该月口径）',
    last_month_output   INT NOT NULL DEFAULT 0 COMMENT '截止上月出品（该月口径）',
    monthly_total_plan  INT NULL,
    contract_count      INT NULL,
    delivery_person     VARCHAR(191) NULL,
    big_area_person     VARCHAR(191) NULL,
    factory_name        VARCHAR(191) NULL,
    machine_type        VARCHAR(191) NULL,
    source_file         VARCHAR(255) NULL COMMENT '来源调度令文件名',
    is_approx           TINYINT(1) NOT NULL DEFAULT 0 COMMENT '1=历史回填近似值（原值已被覆盖）',
    imported_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_pid_month (project_id, plan_month),
    KEY idx_dispatch_month (plan_month),
    CONSTRAINT fk_dispatch_records_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表10：schedule_imports（排产计划上传台账，v7.2 新增）
-- ============================================================
-- 语义：一次「排产 Excel 导入成功」= 一条「项目 × 归属月 × 负责人」台账。
--   存在的理由：排产导入是覆盖式重排（process_node_plans 只保留最后一次上传的行），
--   系统原本无处记录「哪个月传过排产」，导致列表页只能靠「有没有工序行」推测——
--   而「手动完成」占位行（process_order=99）与调度令自动创建的独立工序（90/91）
--   都不是排产上传的证据，于是出现「没上传却显示已上传」的假阳性。
--
-- 判定口径（app/core/db.get_projects_filtered）：
--   has_schedule_plan（本月）= 本表命中 plan_month ∪ process_node_plans.plan_month 命中；
--   schedule_upload_month     = 该项目 MAX(plan_month)，供前端展示「上次上传：X月」。
-- ============================================================
CREATE TABLE IF NOT EXISTS schedule_imports (
    id              INT PRIMARY KEY AUTO_INCREMENT,
    project_id      INT NOT NULL,
    plan_month      CHAR(7) NOT NULL COMMENT '排产归属月 YYYY-MM',
    manager         VARCHAR(64) NOT NULL DEFAULT '' COMMENT '本次导入归属负责人；空串=未区分负责人',
    row_count       INT NOT NULL DEFAULT 0 COMMENT '本次导入实际写入的计划行数',
    source_file     VARCHAR(255) NULL COMMENT '来源排产文件名',
    imported_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_pid_month_mgr (project_id, plan_month, manager),
    KEY idx_schedule_month (plan_month),
    CONSTRAINT fk_schedule_imports_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表11：process_node_plans_history（排产明细归档表，v7.2 新增）
-- ============================================================
-- 语义：覆盖式重排前，把即将被 DELETE 的排产工序行原样归档一份，做到「替换而非销毁」。
--   主表 process_node_plans 保持「每个项目只有一份最新排产」的单月语义（读路径零改动，
--   规避跨月行共存导致的 plan_qty 翻倍风险）；历史月份明细在本表可按
--   (project_id, plan_month) 回溯，必要时用 backend/scripts/restore_schedule_month.py 恢复。
--
-- 行级字段与主表一致；id 保留原主表 id（同一行多次被归档会出现多条，历史是追加式的）。
-- 「已完成」回填出的实际进度（node_actual_progress）不在此表，恢复后代数为空。
-- 与其余表一致带 projects 外键 ON DELETE CASCADE：项目删除后归档无恢复价值（无项目可回挂），
-- 带外键可杜绝孤儿行；delete_project 亦显式删除本表（兼容未带外键的存量库）。
-- ============================================================
CREATE TABLE IF NOT EXISTS process_node_plans_history (
    hist_id         INT PRIMARY KEY AUTO_INCREMENT,
    id              INT NOT NULL COMMENT '归档时原 process_node_plans.id',
    project_id      INT NOT NULL,
    process_name    VARCHAR(64) NOT NULL,
    process_order   INT NOT NULL DEFAULT 0,
    plan_date       DATE NULL,
    plan_qty        INT NOT NULL DEFAULT 1,
    manager         VARCHAR(64) NULL,
    plan_month      CHAR(7) NULL,
    archived_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    archived_reason VARCHAR(64) NULL COMMENT '归档原因：schedule_reimport / manual',

    KEY idx_hist_pid (project_id),
    KEY idx_hist_pid_month (project_id, plan_month),
    CONSTRAINT fk_pnp_history_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;


-- ============================================================
-- 表关联关系说明
-- ============================================================
--
-- projects (1) ──── (N) milestones     项目与里程碑：一对多
--
-- 删除级联：删除项目时，自动删除关联的工序、异常、里程碑、日报记录


-- ============================================================
-- 性能索引：列表页批量查询（消除 N+1 后的 IN 查询 / DISTINCT 全扫描）
-- ============================================================
CREATE INDEX idx_pnp_project ON process_node_plans(project_id);
CREATE INDEX idx_nap_project ON node_actual_progress(project_id);
