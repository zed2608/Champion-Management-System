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
