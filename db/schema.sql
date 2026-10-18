-- Champion Management System - canonical schema (MySQL 8.0, InnoDB, utf8mb4)
--
-- This file describes the TARGET shape of a database. It is applied by `python -m db.migrate`
-- (statements are separated by ';' at end of line; do not pipe it through the mysql CLI together with triggers.sql).
-- `CREATE TABLE IF NOT EXISTS` means an existing database keeps its tables; db/migrate.py then upgrades the
-- old shapes column by column (checking information_schema first) so no data is lost.
--
-- Conventions
--   * Legacy columns keep their legacy nullability so old databases and fresh ones accept the same code.
--   * History is never deleted: FKs from transaction -> tool/user are RESTRICT. Soft delete = is_archived/archived_at/status.
--   * Stock identity (service layer, see docs/DATABASE.md):
--       quantity_available = quantity_total - deployed - quantity_in_maintenance - quantity_lost
--   * tool.updated_at / inventory.updated_at (ms precision, ON UPDATE) drive the cross-terminal cache refresh.

CREATE TABLE IF NOT EXISTS `user` (
  user_id          INT AUTO_INCREMENT PRIMARY KEY,
  employee_id      VARCHAR(50)  NULL,
  full_name        VARCHAR(100) NULL,
  email            VARCHAR(100) NULL,
  role             VARCHAR(50)  NULL,
  password_hash    VARCHAR(255) NULL,
  status           VARCHAR(50)  NULL DEFAULT 'Active',
  failed_attempts  INT          NULL DEFAULT 0,
  reset_requested  TINYINT(1)   NULL DEFAULT 0,
  archived_at      DATETIME     NULL,
  UNIQUE KEY employee_id (employee_id),
  UNIQUE KEY email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS id_sequences (
  prefix    VARCHAR(10) NOT NULL,
  yr        SMALLINT    NOT NULL,
  last_seq  INT         NOT NULL DEFAULT 0,
  PRIMARY KEY (prefix, yr)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS tool (
  tool_id          INT AUTO_INCREMENT PRIMARY KEY,
  name             VARCHAR(100) NULL,
  description      TEXT         NULL,
  category         VARCHAR(100) NULL,
  supplier         VARCHAR(100) NULL,
  location         VARCHAR(100) NULL,
  item_type        VARCHAR(50)  NULL DEFAULT 'Equipment',
  unit_of_measure  VARCHAR(20)  NULL DEFAULT 'pcs',
  `condition`      VARCHAR(50)  NULL DEFAULT 'Good',
  tag_id           VARCHAR(100) NULL,
  is_archived      TINYINT(1)   NULL DEFAULT 0,
  archived_at      DATETIME     NULL,
  date_acquired    DATETIME     NULL,
  price            DECIMAL(10,2) NULL DEFAULT 0.00,
  updated_at       TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY tag_id (tag_id),
  KEY idx_tool_archived (is_archived, category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inventory (
  inventory_id             INT AUTO_INCREMENT PRIMARY KEY,
  tool_id                  INT NOT NULL,
  quantity_total           DECIMAL(10,2) NOT NULL DEFAULT 0,
  quantity_available       DECIMAL(10,2) NOT NULL DEFAULT 0,
  minimum_stock            DECIMAL(10,2) NOT NULL DEFAULT 0,
  quantity_in_maintenance  DECIMAL(10,2) NOT NULL DEFAULT 0,
  quantity_lost            DECIMAL(10,2) NOT NULL DEFAULT 0,
  updated_at               TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_inventory_tool (tool_id),
  CONSTRAINT chk_inv_total_nonneg  CHECK (quantity_total >= 0),
  CONSTRAINT chk_inv_avail_nonneg  CHECK (quantity_available >= 0),
  CONSTRAINT chk_inv_maint_nonneg  CHECK (quantity_in_maintenance >= 0),
  CONSTRAINT chk_inv_lost_nonneg   CHECK (quantity_lost >= 0),
  CONSTRAINT chk_inv_avail_le_total CHECK (quantity_available <= quantity_total),
  CONSTRAINT inventory_ibfk_1 FOREIGN KEY (tool_id) REFERENCES tool (tool_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS projects (
  project_id           INT AUTO_INCREMENT PRIMARY KEY,
  name                 VARCHAR(255) NULL,
  client               VARCHAR(255) NULL,
  location             VARCHAR(255) NULL,
  project_head         VARCHAR(255) NULL,
  start_date           DATE         NULL,
  end_date             DATE         NULL,
  description          TEXT         NULL,
  workers_assigned     TEXT         NULL,          -- LEGACY comma list; project_workers is the source of truth
  tools_needed         TEXT         NULL,
  approved_by          INT          NULL,
  manager_id           INT          NULL,
  status               VARCHAR(50)  NULL DEFAULT 'Pending',
  is_archived          TINYINT(1)   NULL DEFAULT 0, -- LEGACY; archived_at is canonical (column dropped once no code reads it)
  archived_at          TIMESTAMP    NULL,
  status_before_archive VARCHAR(50) NULL,
  KEY idx_projects_status_end (status, end_date),
  KEY idx_projects_archived (archived_at),
  CONSTRAINT chk_projects_dates CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Allowed project status transitions (data-driven so the DB trigger and project_service share one definition).
-- 'Archived' is not a status: archiving sets projects.archived_at on a Completed/Declined/Cancelled project.
CREATE TABLE IF NOT EXISTS project_transitions (
  from_status VARCHAR(50) NOT NULL,
  to_status   VARCHAR(50) NOT NULL,
  legacy      TINYINT(1)  NOT NULL DEFAULT 0,   -- 1 = tolerated until services own every project write (removed in Phase 2)
  PRIMARY KEY (from_status, to_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS project_requirements (
  req_id      INT AUTO_INCREMENT PRIMARY KEY,
  project_id  INT NOT NULL,
  tool_id     INT NOT NULL,
  quantity    DECIMAL(10,2) NULL,
  status      VARCHAR(20)   NOT NULL DEFAULT 'Pending',     -- Pending | Fulfilled
  KEY idx_req_project_tool (project_id, tool_id),
  KEY tool_id (tool_id),
  CONSTRAINT project_requirements_ibfk_1 FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE,
  CONSTRAINT project_requirements_ibfk_2 FOREIGN KEY (tool_id)    REFERENCES tool (tool_id)         ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Replaces the comma-separated projects.workers_assigned (which made LIKE '%WKR-2026-001%' match WKR-2026-0011).
CREATE TABLE IF NOT EXISTS project_workers (
  project_id  INT NOT NULL,
  user_id     INT NOT NULL,
  assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (project_id, user_id),
  KEY idx_pw_user (user_id),
  CONSTRAINT fk_pw_project FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE,
  CONSTRAINT fk_pw_user    FOREIGN KEY (user_id)    REFERENCES `user` (user_id)      ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- One row = one issuance line. The four dates of the manuscript:
--   project_start_date, due_date  -> copied from the project at issuance (history cannot be rewritten by later edits)
--   borrow_date (issuance), return_date (retrieval) -> always the SERVER clock
CREATE TABLE IF NOT EXISTS `transaction` (
  transaction_id        INT AUTO_INCREMENT PRIMARY KEY,
  tool_id               INT NOT NULL,
  user_id               INT NOT NULL,
  project_id            INT NULL,
  type                  VARCHAR(50)  NULL,
  purpose               VARCHAR(255) NULL,
  quantity              DECIMAL(10,2) NOT NULL DEFAULT 1,
  borrow_date           DATETIME NULL,
  return_date           DATETIME NULL,
  project_start_date    DATE NULL,
  due_date              DATE NULL,
  status                VARCHAR(50)  NULL DEFAULT 'Active',
  condition_at_borrow   VARCHAR(100) NULL,
  condition_at_return   VARCHAR(100) NULL,
  condition_return_notes TEXT NULL,
  issued_by             INT NULL,
  received_by           INT NULL,
  KEY tool_id (tool_id),
  KEY project_id (project_id),
  KEY idx_txn_status_tool (status, tool_id),
  KEY idx_txn_user_status (user_id, status),
  KEY idx_txn_project_tool_status (project_id, tool_id, status),
  KEY idx_txn_borrow_date (borrow_date),
  CONSTRAINT chk_txn_quantity_pos CHECK (quantity > 0),
  CONSTRAINT chk_txn_return_after_borrow CHECK (return_date IS NULL OR borrow_date IS NULL OR return_date >= borrow_date),
  CONSTRAINT transaction_ibfk_1 FOREIGN KEY (tool_id)    REFERENCES tool (tool_id)         ON DELETE RESTRICT,
  CONSTRAINT transaction_ibfk_2 FOREIGN KEY (user_id)    REFERENCES `user` (user_id)       ON DELETE RESTRICT,
  CONSTRAINT transaction_ibfk_3 FOREIGN KEY (project_id) REFERENCES projects (project_id)  ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Maintenance tickets (ERD Fig. 92 "maintenance_issue"; the table name tool_issues is kept for the existing code).
CREATE TABLE IF NOT EXISTS tool_issues (
  issue_id             INT AUTO_INCREMENT PRIMARY KEY,
  tool_id              INT NOT NULL,
  transaction_id       INT NULL,
  reported_by          VARCHAR(100) NULL,           -- LEGACY free text
  reported_by_user_id  INT NULL,
  condition_flag       VARCHAR(100) NULL,
  notes                TEXT NULL,
  quantity             DECIMAL(10,2) NOT NULL DEFAULT 1,   -- units taken out of service by this ticket
  flagged_at           TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  is_resolved          TINYINT(1) NULL DEFAULT 0,   -- LEGACY mirror of status (kept in sync by trigger)
  status               VARCHAR(20) NOT NULL DEFAULT 'Open',   -- Open | Resolved
  resolved_by          INT NULL,
  resolved_at          DATETIME NULL,
  KEY tool_id (tool_id),
  KEY idx_issue_status (status, tool_id),
  KEY idx_issue_txn (transaction_id),
  CONSTRAINT tool_issues_ibfk_1 FOREIGN KEY (tool_id)        REFERENCES tool (tool_id)             ON DELETE RESTRICT,
  CONSTRAINT fk_issue_txn       FOREIGN KEY (transaction_id) REFERENCES `transaction` (transaction_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS system_logs (
  log_id       INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT NULL,
  action_type  VARCHAR(100) NULL,
  module       VARCHAR(100) NULL,
  details      TEXT NULL,
  `timestamp`  TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_user (user_id),
  KEY idx_ts (`timestamp`),
  KEY idx_module (module)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS backup_logs (
  backup_id   INT AUTO_INCREMENT PRIMARY KEY,
  filename    VARCHAR(255) NULL,
  filepath    TEXT NULL,
  file_size   VARCHAR(50) NULL,
  note        TEXT NULL,
  created_by  INT NULL,
  created_at  TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  status      VARCHAR(50) NULL DEFAULT 'Success',
  type        VARCHAR(20) NULL DEFAULT 'Backup',
  sha256      CHAR(64) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS help_guides (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  title          VARCHAR(255) NULL,
  steps          TEXT NULL,
  is_admin_only  TINYINT(1) NULL DEFAULT 0,
  display_order  INT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS help_faqs (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  question       VARCHAR(255) NULL,
  answer         TEXT NULL,
  is_admin_only  TINYINT(1) NULL DEFAULT 0,
  display_order  INT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS system_requirements (
  id             INT AUTO_INCREMENT PRIMARY KEY,
  req_type       VARCHAR(50) NULL,
  component      VARCHAR(255) NULL,
  specification  TEXT NULL,
  display_order  INT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS help_tickets (
  ticket_id    INT AUTO_INCREMENT PRIMARY KEY,
  user_id      INT NULL,
  subject      VARCHAR(255) NULL,
  message      TEXT NULL,
  admin_reply  TEXT NULL,
  status       VARCHAR(50) NULL DEFAULT 'Open',
  created_at   TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
