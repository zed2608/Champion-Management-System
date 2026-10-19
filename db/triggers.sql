-- Champion Management System - database-side business rules (MySQL 8.0)
--
-- Applied by `python -m db.migrate` (re-applied whenever this file's hash changes; every trigger is DROPped first).
-- Statements are separated by a line containing only `-- //` (Python splits on it; the mysql CLI needs DELIMITER instead).
-- The same rules also live in the service layer (Phase 2). They are duplicated on purpose: the service gives friendly
-- messages, the trigger guarantees the rule even when SQL is run by hand or by a stale terminal.
-- All errors use SQLSTATE '45000' and start with "CHAMPION:" so the UI can show the text after the prefix.

DROP TRIGGER IF EXISTS trg_projects_bu
-- //
-- [4-DATE] [STATE-MACHINE] Project rules:
--   * status may only change along an edge listed in project_transitions
--   * archiving is only for Completed/Declined/Cancelled projects; it remembers the pre-archive status
--   * restoring from the archive puts the project back to that remembered status (never "Approved")
--   * once a project is Ongoing/Completed, or any tool was ever issued to it, dates and workers are read-only
CREATE TRIGGER trg_projects_bu BEFORE UPDATE ON projects FOR EACH ROW
BEGIN
  IF OLD.archived_at IS NOT NULL AND NEW.archived_at IS NULL THEN
    SET NEW.status = COALESCE(OLD.status_before_archive, OLD.status);
    SET NEW.status_before_archive = NULL;
    SET NEW.is_archived = 0;
  ELSE
    IF OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL THEN
      IF NEW.status NOT IN ('Completed', 'Declined', 'Cancelled') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Only Completed, Declined or Cancelled projects can be archived.';
      END IF;
      SET NEW.status_before_archive = NEW.status;
      SET NEW.is_archived = 1;
    END IF;
    IF OLD.status IS NOT NULL AND NOT (NEW.status <=> OLD.status) THEN
      IF NOT EXISTS (SELECT 1 FROM project_transitions
                     WHERE from_status = OLD.status AND to_status = NEW.status) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: That project status change is not allowed.';
      END IF;
    END IF;
  END IF;

  IF OLD.status IN ('Ongoing', 'Completed')
     OR EXISTS (SELECT 1 FROM `transaction` WHERE project_id = OLD.project_id) THEN
    IF NOT (NEW.start_date <=> OLD.start_date)
       OR NOT (NEW.end_date <=> OLD.end_date)
       OR NOT (NEW.workers_assigned <=> OLD.workers_assigned) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Dates and workers are locked once a project is Ongoing or Completed, or has issued tools.';
    END IF;
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_projects_workers_ai
-- //
-- Keeps the project_workers junction in step with the legacy comma list while old screens still write it.
-- Exact employee_id match (the old LIKE '%WKR-2026-001%' also matched WKR-2026-0011).
CREATE TRIGGER trg_projects_workers_ai AFTER INSERT ON projects FOR EACH ROW
BEGIN
  IF NEW.workers_assigned IS NOT NULL AND NEW.workers_assigned <> '' THEN
    INSERT IGNORE INTO project_workers (project_id, user_id)
    SELECT NEW.project_id, u.user_id
    FROM JSON_TABLE(CONCAT('["', REPLACE(REPLACE(NEW.workers_assigned, '"', ''), ',', '","'), '"]'),
                    '$[*]' COLUMNS (emp VARCHAR(50) PATH '$')) jt
    JOIN `user` u ON u.employee_id = TRIM(jt.emp);
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_projects_workers_au
-- //
CREATE TRIGGER trg_projects_workers_au AFTER UPDATE ON projects FOR EACH ROW
BEGIN
  IF NOT (NEW.workers_assigned <=> OLD.workers_assigned) THEN
    DELETE FROM project_workers WHERE project_id = NEW.project_id;
    IF NEW.workers_assigned IS NOT NULL AND NEW.workers_assigned <> '' THEN
      INSERT IGNORE INTO project_workers (project_id, user_id)
      SELECT NEW.project_id, u.user_id
      FROM JSON_TABLE(CONCAT('["', REPLACE(REPLACE(NEW.workers_assigned, '"', ''), ',', '","'), '"]'),
                      '$[*]' COLUMNS (emp VARCHAR(50) PATH '$')) jt
      JOIN `user` u ON u.employee_id = TRIM(jt.emp);
    END IF;
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_req_bi
-- //
-- [STATE-MACHINE] Requirements are frozen once the project is Ongoing/Completed or has issued tools.
CREATE TRIGGER trg_req_bi BEFORE INSERT ON project_requirements FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM projects WHERE project_id = NEW.project_id AND status IN ('Ongoing', 'Completed'))
     OR EXISTS (SELECT 1 FROM `transaction` WHERE project_id = NEW.project_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Requirements are locked for Ongoing/Completed projects and projects with issued tools.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_req_bu
-- //
CREATE TRIGGER trg_req_bu BEFORE UPDATE ON project_requirements FOR EACH ROW
BEGIN
  -- Marking a line Fulfilled during issuance only touches `status`; that stays allowed.
  IF NOT (NEW.project_id <=> OLD.project_id) OR NOT (NEW.tool_id <=> OLD.tool_id) OR NOT (NEW.quantity <=> OLD.quantity) THEN
    IF EXISTS (SELECT 1 FROM projects WHERE project_id = OLD.project_id AND status IN ('Ongoing', 'Completed'))
       OR EXISTS (SELECT 1 FROM `transaction` WHERE project_id = OLD.project_id) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Requirements are locked for Ongoing/Completed projects and projects with issued tools.';
    END IF;
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_req_bd
-- //
CREATE TRIGGER trg_req_bd BEFORE DELETE ON project_requirements FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM projects WHERE project_id = OLD.project_id AND status IN ('Ongoing', 'Completed'))
     OR EXISTS (SELECT 1 FROM `transaction` WHERE project_id = OLD.project_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Requirements are locked for Ongoing/Completed projects and projects with issued tools.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_txn_bi
-- //
-- [4-DATE] Issuance. The server clock is the only clock: borrow_date defaults to NOW() here.
--   * start/due dates are COPIED from the project (snapshot), so later project edits cannot rewrite history
--   * issuance must not be after the project's end date (hard rule)
--   * issuance BEFORE the project's start date is deliberately ALLOWED ("staged early"). A literal
--     "Issuance <= Start" rule would block every top-up issuance once a project has started.
CREATE TRIGGER trg_txn_bi BEFORE INSERT ON `transaction` FOR EACH ROW
BEGIN
  IF NEW.borrow_date IS NULL THEN
    SET NEW.borrow_date = NOW();
  END IF;
  IF NEW.project_id IS NOT NULL THEN
    SET NEW.project_start_date = COALESCE(NEW.project_start_date, (SELECT start_date FROM projects WHERE project_id = NEW.project_id));
    SET NEW.due_date           = COALESCE(NEW.due_date,           (SELECT end_date   FROM projects WHERE project_id = NEW.project_id));
  END IF;
  IF NEW.due_date IS NOT NULL AND DATE(NEW.borrow_date) > NEW.due_date THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: This project has ended; tools cannot be issued to it.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_txn_bu
-- //
-- [4-DATE] Retrieval: return_date >= borrow_date, and the snapshot dates never change.
CREATE TRIGGER trg_txn_bu BEFORE UPDATE ON `transaction` FOR EACH ROW
BEGIN
  IF OLD.borrow_date IS NOT NULL AND NOT (NEW.borrow_date <=> OLD.borrow_date) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The issuance date of a record cannot be changed.';
  END IF;
  IF OLD.project_start_date IS NOT NULL AND NOT (NEW.project_start_date <=> OLD.project_start_date) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The project start date snapshot cannot be changed.';
  END IF;
  IF OLD.due_date IS NOT NULL AND NOT (NEW.due_date <=> OLD.due_date) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The due date snapshot cannot be changed.';
  END IF;
  IF NEW.status = 'Returned' AND NOT (OLD.status <=> 'Returned') AND NEW.return_date IS NULL THEN
    SET NEW.return_date = NOW();
  END IF;
  IF NEW.return_date IS NOT NULL AND NEW.borrow_date IS NOT NULL AND NEW.return_date < NEW.borrow_date THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: Retrieval cannot be earlier than issuance.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_issue_bu
-- //
-- Keeps the legacy is_resolved flag and the new status/resolved_at columns consistent whichever one a screen writes.
CREATE TRIGGER trg_issue_bu BEFORE UPDATE ON tool_issues FOR EACH ROW
BEGIN
  IF NEW.is_resolved = 1 AND (OLD.is_resolved IS NULL OR OLD.is_resolved = 0) THEN
    SET NEW.status = 'Resolved';
    SET NEW.resolved_at = COALESCE(NEW.resolved_at, NOW());
  ELSEIF NEW.status = 'Resolved' AND NOT (OLD.status <=> 'Resolved') THEN
    SET NEW.is_resolved = 1;
    SET NEW.resolved_at = COALESCE(NEW.resolved_at, NOW());
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_tool_bu
-- //
-- A tool cannot be archived while units are out. Mirrors inventory_service.archive_tool so the rule holds for any SQL.
CREATE TRIGGER trg_tool_bu BEFORE UPDATE ON tool FOR EACH ROW
BEGIN
  IF (OLD.is_archived IS NULL OR OLD.is_archived = 0) AND NEW.is_archived = 1 THEN
    IF EXISTS (SELECT 1 FROM `transaction` WHERE tool_id = OLD.tool_id AND status = 'Active')
       OR EXISTS (SELECT 1 FROM inventory WHERE tool_id = OLD.tool_id AND quantity_in_maintenance > 0) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: A tool cannot be archived while units are deployed or in maintenance.';
    END IF;
  END IF;
END

-- //
-- [PANEL-AWE] AUDIT LOG IS APPEND-ONLY.
--   * a row can be filled in ONCE (the hash columns), never edited afterwards
--   * a row can be deleted only after an identical copy exists in system_logs_archive (this is how old rows are moved, never lost)
--   * the archive itself accepts neither UPDATE nor DELETE
DROP TRIGGER IF EXISTS trg_system_logs_bu
-- //
CREATE TRIGGER trg_system_logs_bu BEFORE UPDATE ON system_logs FOR EACH ROW
BEGIN
  IF OLD.row_hash IS NOT NULL OR NEW.row_hash IS NULL
     OR NOT (NEW.log_id <=> OLD.log_id AND NEW.user_id <=> OLD.user_id AND NEW.action_type <=> OLD.action_type
             AND NEW.module <=> OLD.module AND NEW.details <=> OLD.details AND NEW.`timestamp` <=> OLD.`timestamp`
             AND NEW.session_id <=> OLD.session_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The audit log is append-only; entries cannot be changed.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_system_logs_bd
-- //
CREATE TRIGGER trg_system_logs_bd BEFORE DELETE ON system_logs FOR EACH ROW
BEGIN
  IF NOT EXISTS (SELECT 1 FROM system_logs_archive a
                 WHERE a.log_id = OLD.log_id AND a.row_hash <=> OLD.row_hash AND a.prev_hash <=> OLD.prev_hash
                   AND a.details <=> OLD.details AND a.action_type <=> OLD.action_type AND a.module <=> OLD.module) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The audit log is append-only; entries cannot be deleted.';
  END IF;
END
-- //
DROP TRIGGER IF EXISTS trg_system_logs_archive_bu
-- //
CREATE TRIGGER trg_system_logs_archive_bu BEFORE UPDATE ON system_logs_archive FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The audit archive is append-only; entries cannot be changed.';
END
-- //
DROP TRIGGER IF EXISTS trg_system_logs_archive_bd
-- //
CREATE TRIGGER trg_system_logs_archive_bd BEFORE DELETE ON system_logs_archive FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'CHAMPION: The audit archive is append-only; entries cannot be deleted.';
END
-- //
-- [PANEL-AWE] The ONLY way the application writes the audit log. SQL SECURITY DEFINER lets a Staff account append without any
-- privilege on system_logs itself. The head row is locked first, so two terminals take turns and the chain can never fork.
-- The hash text is built exactly like db/audit_core.py::row_digest.
DROP PROCEDURE IF EXISTS sp_log_action
-- //
CREATE PROCEDURE sp_log_action(IN p_user INT, IN p_action VARCHAR(100), IN p_module VARCHAR(100), IN p_details TEXT, IN p_session VARCHAR(36))
SQL SECURITY DEFINER
BEGIN
  DECLARE v_prev CHAR(64);
  DECLARE v_id BIGINT;
  DECLARE v_ts TIMESTAMP;
  DECLARE v_hash CHAR(64);
  SELECT head_hash INTO v_prev FROM audit_chain_head WHERE id = 1 FOR UPDATE;
  IF v_prev IS NULL THEN
    SET v_prev = REPEAT('0', 64);
    INSERT INTO audit_chain_head (id, head_hash, last_log_id) VALUES (1, v_prev, 0);
  END IF;
  SET v_ts = NOW();
  INSERT INTO system_logs (user_id, action_type, module, details, `timestamp`, session_id, prev_hash)
  VALUES (p_user, p_action, p_module, p_details, v_ts, p_session, v_prev);
  SET v_id = LAST_INSERT_ID();
  SET v_hash = SHA2(CONCAT_WS(CHAR(31 USING utf8mb4), v_prev, v_id, IFNULL(p_user, ''), IFNULL(p_action, ''), IFNULL(p_module, ''),
                              IFNULL(p_details, ''), DATE_FORMAT(DATE_ADD('1970-01-01 00:00:00', INTERVAL UNIX_TIMESTAMP(v_ts) SECOND), '%Y-%m-%dT%H:%i:%s'), IFNULL(p_session, '')), 256);
  UPDATE system_logs SET row_hash = v_hash WHERE log_id = v_id;
  UPDATE audit_chain_head SET head_hash = v_hash, last_log_id = v_id WHERE id = 1;
END
-- //
-- [PANEL-AWE] Moves old audit rows into system_logs_archive (copy first, then delete; the delete trigger checks the copy exists).
-- Nothing is ever lost. At most 5000 rows per call; a named lock stops two terminals doing it at once.
DROP PROCEDURE IF EXISTS sp_archive_audit
-- //
CREATE PROCEDURE sp_archive_audit(IN p_keep INT)
SQL SECURITY DEFINER
BEGIN
  DECLARE v_cut BIGINT;
  DECLARE v_top BIGINT;
  IF GET_LOCK('champion_audit_archive', 0) = 1 THEN
    SELECT MAX(log_id) INTO v_top FROM system_logs;
    IF v_top IS NOT NULL AND v_top - p_keep > 0 THEN
      SET v_cut = v_top - p_keep;
      INSERT IGNORE INTO system_logs_archive (log_id, user_id, action_type, module, details, `timestamp`, session_id, prev_hash, row_hash)
        SELECT log_id, user_id, action_type, module, details, `timestamp`, session_id, prev_hash, row_hash
        FROM system_logs WHERE log_id <= v_cut ORDER BY log_id LIMIT 5000;
      DELETE s FROM system_logs s JOIN system_logs_archive a ON a.log_id = s.log_id WHERE s.log_id <= v_cut;
    END IF;
    DO RELEASE_LOCK('champion_audit_archive');
  END IF;
END
