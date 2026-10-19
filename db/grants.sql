-- Champion Management System - MySQL accounts (defense in depth for server-side RBAC)
--
-- TEMPLATE. Apply with:  python -m db.apply_grants     (run as a MySQL admin such as root)
-- Placeholders {{...}} are filled from the environment by db/apply_grants.py, so no password lives in git:
--   STAFF_DB_PASS, ADMIN_DB_PASS            required
--   STAFF_DB_USER (default champion_staff), ADMIN_DB_USER (default champion_admin), GRANT_HOST (default %)
--
-- Why two accounts: the services re-check the role from the `user` table on every privileged call, but if a
-- terminal's code or memory is tampered with, MySQL itself still refuses what the account is not allowed to do.
-- Each terminal's .env carries ONE of these accounts (DB_USER / DB_PASS):
--   cashier-style Staff terminals -> champion_staff        Admin workstation -> champion_admin
-- Statements are separated by ';' at end of line.

CREATE USER IF NOT EXISTS '{{STAFF_USER}}'@'{{HOST}}' IDENTIFIED BY '{{STAFF_PASSWORD}}';
CREATE USER IF NOT EXISTS '{{ADMIN_USER}}'@'{{HOST}}' IDENTIFIED BY '{{ADMIN_PASSWORD}}';
ALTER USER '{{STAFF_USER}}'@'{{HOST}}' IDENTIFIED BY '{{STAFF_PASSWORD}}';
ALTER USER '{{ADMIN_USER}}'@'{{HOST}}' IDENTIFIED BY '{{ADMIN_PASSWORD}}';

-- Start clean so re-running tightens, never accumulates.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{{STAFF_USER}}'@'{{HOST}}';
REVOKE ALL PRIVILEGES, GRANT OPTION FROM '{{ADMIN_USER}}'@'{{HOST}}';

-- ===== ADMIN: everything inside the application database (needed for restore = DROP/CREATE, and for user management).
-- No global privileges, no GRANT OPTION, nothing on other databases.
GRANT ALL PRIVILEGES ON `{{DB}}`.* TO '{{ADMIN_USER}}'@'{{HOST}}';

-- ===== STAFF: issue / retrieve, print tags, read inventory, own history, own profile, tickets.
-- Read everything the screens need ... except the audit log.
GRANT SELECT ON `{{DB}}`.`user`                 TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`tool`                 TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`inventory`            TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`projects`             TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`project_requirements` TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`project_workers`      TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`project_transitions`  TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`transaction`          TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`tool_issues`          TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`help_guides`          TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`help_faqs`            TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`system_requirements`  TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`help_tickets`         TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`schema_migrations`    TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT SELECT ON `{{DB}}`.`v_activity_feed`      TO '{{STAFF_USER}}'@'{{HOST}}';   -- dashboard feed (project events only)
GRANT SELECT ON `{{DB}}`.`schema_meta`          TO '{{STAFF_USER}}'@'{{HOST}}';

-- Issuance / retrieval and maintenance tickets.
GRANT INSERT, UPDATE ON `{{DB}}`.`transaction` TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT UPDATE (quantity_available, quantity_in_maintenance, quantity_lost) ON `{{DB}}`.`inventory` TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT UPDATE (`condition`, tag_id)    ON `{{DB}}`.`tool`                 TO '{{STAFF_USER}}'@'{{HOST}}';   -- tag printing + condition set by retrieval
GRANT UPDATE (status)                 ON `{{DB}}`.`projects`             TO '{{STAFF_USER}}'@'{{HOST}}';   -- Approved -> Ongoing on first issuance
GRANT UPDATE (status)                 ON `{{DB}}`.`project_requirements` TO '{{STAFF_USER}}'@'{{HOST}}';   -- mark Fulfilled
GRANT INSERT                          ON `{{DB}}`.`tool_issues`          TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT INSERT                          ON `{{DB}}`.`help_tickets`         TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT INSERT                          ON `{{DB}}`.`issuance_attempts`    TO '{{STAFF_USER}}'@'{{HOST}}';   -- refused issuances are counted

-- Own profile + login bookkeeping. role, employee_id and archived_at are NOT updatable: no self-promotion.
GRANT UPDATE (full_name, email, password_hash, failed_attempts, reset_requested, status) ON `{{DB}}`.`user` TO '{{STAFF_USER}}'@'{{HOST}}';

-- Audit log: Staff may only APPEND, and only through the chained stored procedure (no direct INSERT, SELECT, UPDATE or DELETE on the table).
GRANT EXECUTE ON PROCEDURE `{{DB}}`.`sp_log_action` TO '{{STAFF_USER}}'@'{{HOST}}';
GRANT EXECUTE ON PROCEDURE `{{DB}}`.`sp_archive_audit` TO '{{STAFF_USER}}'@'{{HOST}}';

-- Deliberately NOT granted to Staff: DELETE anywhere, INSERT/UPDATE on tool/inventory rows beyond the columns above,
-- INSERT/UPDATE on projects (Project Management is read-only for Staff), any DDL, id_sequences, backup_logs.
