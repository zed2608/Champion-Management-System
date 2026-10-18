-- A database as it looked BEFORE the refactor (create_tables.py era + some runtime patches), with awkward data.
-- Used by tests/test_migrate.py to prove the migration upgrades real-world shapes without losing rows.

CREATE TABLE `user` (
  user_id int NOT NULL AUTO_INCREMENT, employee_id varchar(50) DEFAULT NULL, full_name varchar(100) DEFAULT NULL,
  email varchar(100) DEFAULT NULL, role varchar(50) DEFAULT NULL, password_hash varchar(255) DEFAULT NULL,
  status varchar(50) DEFAULT 'Active', failed_attempts int DEFAULT 0, reset_requested tinyint(1) DEFAULT 0,
  PRIMARY KEY (user_id), UNIQUE KEY employee_id (employee_id), UNIQUE KEY email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE tool (
  tool_id int NOT NULL AUTO_INCREMENT, name varchar(100) DEFAULT NULL, description text, category varchar(100) DEFAULT NULL,
  supplier varchar(100) DEFAULT NULL, location varchar(100) DEFAULT NULL, item_type varchar(50) DEFAULT 'Equipment',
  unit_of_measure varchar(20) DEFAULT 'pcs', `condition` varchar(50) DEFAULT 'Good', tag_id varchar(100) DEFAULT NULL,
  is_archived tinyint(1) DEFAULT 0, archived_at datetime DEFAULT NULL, date_acquired datetime DEFAULT NULL,
  price decimal(10,2) DEFAULT 0.00, PRIMARY KEY (tool_id), UNIQUE KEY tag_id (tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE inventory (
  inventory_id int NOT NULL AUTO_INCREMENT, tool_id int DEFAULT NULL, quantity_total float DEFAULT NULL,
  quantity_available float DEFAULT NULL, minimum_stock float DEFAULT NULL, PRIMARY KEY (inventory_id), KEY tool_id (tool_id),
  CONSTRAINT inventory_ibfk_1 FOREIGN KEY (tool_id) REFERENCES tool (tool_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE projects (
  project_id int NOT NULL AUTO_INCREMENT, name varchar(255) DEFAULT NULL, client varchar(255) DEFAULT NULL,
  location varchar(255) DEFAULT NULL, project_head varchar(255) DEFAULT NULL, start_date date DEFAULT NULL,
  end_date date DEFAULT NULL, description text, workers_assigned text, tools_needed text, approved_by int DEFAULT NULL,
  manager_id int DEFAULT NULL, status varchar(50) DEFAULT 'Pending', is_archived tinyint(1) DEFAULT 0,
  PRIMARY KEY (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE project_requirements (
  requirement_id int NOT NULL AUTO_INCREMENT, project_id int DEFAULT NULL, tool_id int DEFAULT NULL,
  quantity decimal(10,2) DEFAULT NULL, PRIMARY KEY (requirement_id), KEY project_id (project_id), KEY tool_id (tool_id),
  CONSTRAINT project_requirements_ibfk_1 FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE CASCADE,
  CONSTRAINT project_requirements_ibfk_2 FOREIGN KEY (tool_id) REFERENCES tool (tool_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE `transaction` (
  transaction_id int NOT NULL AUTO_INCREMENT, tool_id int DEFAULT NULL, user_id int DEFAULT NULL, project_id int DEFAULT NULL,
  type varchar(50) DEFAULT NULL, purpose varchar(255) DEFAULT NULL, borrow_date datetime DEFAULT NULL,
  return_date datetime DEFAULT NULL, status varchar(50) DEFAULT 'Active', condition_at_borrow varchar(100) DEFAULT NULL,
  condition_at_return varchar(100) DEFAULT NULL, issued_by int DEFAULT NULL, received_by int DEFAULT NULL,
  PRIMARY KEY (transaction_id), KEY tool_id (tool_id), KEY user_id (user_id), KEY project_id (project_id),
  CONSTRAINT transaction_ibfk_1 FOREIGN KEY (tool_id) REFERENCES tool (tool_id) ON DELETE CASCADE,
  CONSTRAINT transaction_ibfk_2 FOREIGN KEY (user_id) REFERENCES `user` (user_id) ON DELETE CASCADE,
  CONSTRAINT transaction_ibfk_3 FOREIGN KEY (project_id) REFERENCES projects (project_id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE tool_issues (
  issue_id int NOT NULL AUTO_INCREMENT, tool_id int NOT NULL, reported_by varchar(100) DEFAULT NULL,
  condition_flag varchar(100) DEFAULT NULL, notes text, flagged_at timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  is_resolved tinyint(1) DEFAULT 0, PRIMARY KEY (issue_id), KEY tool_id (tool_id),
  CONSTRAINT tool_issues_ibfk_1 FOREIGN KEY (tool_id) REFERENCES tool (tool_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE system_logs (
  log_id int NOT NULL AUTO_INCREMENT, user_id int DEFAULT NULL, action_type varchar(100) DEFAULT NULL,
  module varchar(100) DEFAULT NULL, details text, `timestamp` timestamp NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (log_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---- data ---------------------------------------------------------------------------------------------------------
INSERT INTO `user` (user_id, employee_id, full_name, email, role, password_hash, status) VALUES
  (1, 'ADM-2026-001', 'System Admin',  'admin@example.com', 'Admin',  '$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234', 'Active'),
  (2, 'STF-2026-014', 'Stacy Staff',   'stacy@example.com', 'Staff',  '$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234', 'Active'),
  (3, 'WKR-2026-001', 'Wally Worker',  NULL, 'Worker', '$2b$12$sharedconstanthashsharedconstanthashsharedconstanthashsha', 'Active'),
  (4, 'WKR-2026-0011','Willa Worker',  NULL, 'Worker', '$2b$12$sharedconstanthashsharedconstanthashsharedconstanthashsha', 'Active'),
  (5, 'WKR-2025-099', 'Old Worker',    NULL, 'Worker', NULL, 'Archived');

INSERT INTO tool (tool_id, name, category, item_type, unit_of_measure, `condition`, tag_id, price) VALUES
  (1, 'Digital Caliper', 'Measuring', 'Equipment',  'pcs', 'Good',    'CAL-001',  4500.00),
  (2, 'Cordless Drill',  'Power',     'Equipment',  'pcs', 'Damaged', 'DRL-001',  6200.00),
  (3, 'Machine Grease',  'Supplies',  'Consumable', 'kg',  'Good',    'GRS-001',   350.00);

-- floats and a NULL on purpose
INSERT INTO inventory (tool_id, quantity_total, quantity_available, minimum_stock) VALUES
  (1, 10, 7, 2), (2, 5, 3, NULL), (3, 2.5, 2.5, 1);

INSERT INTO projects (project_id, name, client, start_date, end_date, workers_assigned, status, is_archived) VALUES
  (1, 'Alpha Line Retool', 'ACME', '2026-01-01', '2026-12-31', 'WKR-2026-001, WKR-2026-0011, Juan Dela Cruz', 'Approved', 0),
  (2, 'Beta Overhaul',     'Globex', '2025-01-01', '2025-06-30', 'WKR-2025-099', 'Completed', 1),
  (3, 'Gamma Draft',       'Initech', '2026-03-01', '2026-02-01', NULL, 'Pending', 0);   -- start AFTER end: violates the new date CHECK

INSERT INTO project_requirements (project_id, tool_id, quantity) VALUES (1, 1, 2), (1, 3, 1.5);

INSERT INTO `transaction` (tool_id, user_id, project_id, type, borrow_date, return_date, status) VALUES
  (1, 3, 1, 'Issue',     '2026-02-01 08:00:00', NULL, 'Active'),
  (1, 3, 1, 'Issue',     '2026-02-01 08:00:00', NULL, 'Active'),
  (1, 4, 1, 'Issue',     '2026-02-02 09:00:00', NULL, 'Active'),
  (2, 4, 1, 'Issue',     '2026-02-02 09:00:00', NULL, 'Active'),
  (1, 3, 1, 'Retrieval', '2026-01-10 08:00:00', '2026-01-10 17:00:00', 'Returned');

INSERT INTO tool_issues (tool_id, reported_by, condition_flag, notes, is_resolved) VALUES
  (2, 'Stacy Staff', 'Damaged', 'Chuck is cracked', 0),
  (1, 'Stacy Staff', 'Needs Repair', 'Old and fixed', 1);

INSERT INTO system_logs (user_id, action_type, module, details) VALUES (1, 'Login', 'Authentication', 'fixture');
