# Audit Report (Phase 0) - branch `refactor/industrial-hardening`

Scope note: `docs/AUDIT_FINDINGS.md` is referenced in the brief but **does not exist in the repo** (there was no `docs/` folder).
Every item below was therefore verified directly against the code.
"Confirmed" means I read the cited lines. "Brief-only" means it comes from the brief and is not yet verified.
Line numbers are from the current tree and differ slightly from the brief in places.

## 1. Database and concurrency
| # | Sev | Finding | Evidence | Status | Fix (phase) |
|---|-----|---------|----------|--------|-------------|
| 1.1 | Critical | Issuance has no lock or transaction. `FOR UPDATE`, `START TRANSACTION` and `rollback` appear **nowhere** in the codebase | `views/borrowing.py:1094` (`execute_borrow`); grep over views, dashboard, main, database | Confirmed | ACID txn, ordered `FOR UPDATE`, retry on 1213/1205 (P1/P2) |
| 1.2 | Critical | Same for return, resolve-issue, inventory update, project save | `borrowing.py:1345`, `maintenance.py:513`, `inventory.py:1047` | Confirmed (no locks); bodies not yet fully read | Transaction helper (P1) |
| 1.3 | High | Resolving a damaged unit adds to **both** `quantity_total` and `quantity_available` (stock inflation) | `maintenance.py:532` | Confirmed | `quantity_in_maintenance` model (P1) |
| 1.4 | High | `ProfileView` holds a pooled connection for its lifetime and never returns it. The pool is 10, so repeated visits exhaust it | `views/profile.py:17`, used at 280/294/377/387 | Confirmed | `db.read()` / `db.transaction()` (P1) |
| 1.5 | High | Pool errors only `print()`; the app shows a generic "Database connection failed." | `database.py:31-33`, `main.py:225-228` | Confirmed | `db/pool.py` + offline banner (P1) |
| 1.6 | High | Cascade deletes from tool and user to `transaction` would wipe history | `create_tables.py:96-97` (also `:56`, `:109-110`) | Confirmed | `ON DELETE RESTRICT` (P1) |
| 1.7 | High | Workers matched by `LIKE` on a comma-separated string (`WKR-2026-0011` matches `WKR-2026-001`) | `borrowing.py:898`; `workers_assigned` used in 8 places | Confirmed | `project_workers` junction table (P1) |
| 1.8 | High | Schema drift: the base schema lacks `projects.archived_at`, `user.archived_at`, `transaction.condition_return_notes`, `tool_issues`, `system_logs`. Runtime DDL patches it from inside views | `create_tables.py` vs `projects.py:42`, `maintenance.py:36,44,260,343,1219,1238`, `borrowing.py:1368`, `main.py:147-150`, `help.py:214-232` | Confirmed (observed live: a fresh DB had 6 of 8 tables) | `db/schema.sql` + `db/migrate.py`; remove runtime DDL (P1) |
| 1.9 | Medium | `help.py` runs `DROP TABLE` at runtime | `views/help.py:214` | Confirmed | Remove (P1) |
| 1.10 | Medium | Hard-coded `DATE_ADD(.., INTERVAL 8 HOUR)` in 5 places instead of a session time zone | `views/borrowing.py` (5 matches) | Confirmed | Pool `time_zone='+08:00'`, server `NOW()` (P1) |
| 1.11 | Medium | Employee ID is MAX+1 formatted `:03d` (race between two admins; breaks past 999) | `role_management.py:~238-262` | Confirmed | `id_sequences ... FOR UPDATE` (P1) |
| 1.12 | Medium | A single damaged return blocks all units; fractional consumables create one row per unit | brief | Brief-only | Per-unit model; `transaction.quantity` (P1) |
| 1.13 | Medium | No hot-path indexes or CHECK constraints | brief + `create_tables.py` | Partly confirmed | Indexes + CHECK (P1) |
| 1.14 | Medium | The "hash-table cache" described in the docs does not exist | no cache module in repo | Confirmed | `services/tool_cache.py` (P1) |
| 1.15 | Low | Environment mismatch: the brief says Python 3.11 but the venv runs **3.14**; two venvs exist (`venv/`, `.venv/`); `requirements.txt` pulls PyQt5 and PyQt6 (unused) | tracebacks; repo root | Confirmed | Clean requirements (P6); decide target Python (open question) |

## 2. Logic, validation, RBAC
| # | Sev | Finding | Evidence | Status | Fix |
|---|-----|---------|----------|--------|-----|
| 2.1 | Critical | RBAC is UI-only: one `show_frame` check; nothing below it checks the role | `dashboard.py:397-405` | Confirmed | `services/` + `@require_role` re-reading the role from the DB; `db/grants.sql` (P2) |
| 2.2 | High | Only `status == "Locked"` blocks login, so Archived and Inactive users can log in | `main.py:249` | Confirmed | Block all non-Active (P2) |
| 2.3 | High | Workers are stored with the bcrypt hash of a shared constant | `role_management.py:189,259` | Confirmed | `password_hash NULL` (P2) |
| 2.4 | High | "Forgot Username" reveals name and employee ID to anyone who types an email, and distinguishes found from not found | `main.py:~356-375` | Confirmed | Uniform response + admin request (P2) |
| 2.5 | High | Project edit is delete-and-reinsert of requirements, even for running projects | `projects.py:716` | Confirmed | State machine + trigger (P2) |
| 2.6 | High | Restoring an archived project always sets `Approved` | `maintenance.py:981` | Confirmed | `status_before_archive` (P2) |
| 2.7 | Medium | The duplicate-name check blocks real people who share a name | `role_management.py:205-206` | Confirmed | Warn and allow (P2) |
| 2.8 | Medium | No server-side input limits; QR payload parsing is copy-pasted in 3 views | brief | Brief-only (copies not yet diffed) | `services/validators.py` (P1/P2) |
| 2.9 | Medium | Staff is blocked from Project Management, Reports, Maintenance and Role Management; the docs show Staff access to Projects | `dashboard.py:399-400` | Confirmed (code); docs not in repo | Staff gets read-only Projects (P2) |
| 2.10 | Medium | Passwords are not length-checked before bcrypt (72-byte limit) | brief | Brief-only | validators (P2) |

## 3. Unhappy paths and fault tolerance
| # | Sev | Finding | Evidence | Status | Fix |
|---|-----|---------|----------|--------|-----|
| 3.1 | Critical | **Profile page spun forever.** The seeded admin had `email = NULL`; `.get('email','')` returns `None`; Tk `insert(0, None)` raised `TclError`; `show_frame` had no try/finally, so the spinner overlay was never removed | `profile.py:235`, `dashboard.py:419-467` | **Fixed in ed0b315** (the overlay fix covers every view) | Done |
| 3.2 | High | Scanner is a blocking `while True` + `cv2.imshow` loop, **copy-pasted 3 times** | `borrowing.py:844/868`, `tagging.py:367/391`, `inventory.py:387/408` (+ the login scanner in `main.py`) | Confirmed | `services/scanner.py` + in-window HUD (P3/P5) |
| 3.3 | High | Backup passes the password on the command line | `maintenance.py:1300` (restore: `1483`) | Confirmed | `--defaults-extra-file` (P3) |
| 3.4 | High | A non-zero `mysqldump` exit counts as success if the file is at least 512 bytes | `maintenance.py:1310-1316` | Confirmed | Strict exit code, trailer check, SHA-256 (P3) |
| 3.5 | High | Inventory is silently capped at `LIMIT 100`, so most of 2,000 tools are invisible | `inventory.py:546` | Confirmed | `widgets/paged_table.py` (P3) |
| 3.6 | High | Matplotlib figures are created with `plt.subplots` on every dashboard visit and never closed | `dashboard.py:916, 1223` | Confirmed | `Figure` reuse / `plt.close` (P3/P5) |
| 3.7 | Medium | `confirm_logout` cancels the clock, refresh and inactivity timers **before** asking, so answering "No" permanently disables auto-logout | `dashboard.py:253-262` | Confirmed | Cancel only on "Yes" (P3) |
| 3.8 | Medium | Inactivity timeout is 5 min; the docs say 15 | `dashboard.py:277` | Confirmed | 15 min + 30 s warning (P3) |
| 3.9 | Medium | Worker threads read Tk variables (`start_date.get()`) off the main thread | `reports.py:129,220,434,654` (threads started at 363, 499) | Partly confirmed; thread bodies need a closer read | Read on the main thread first (P3) |
| 3.10 | Medium | `show_toast` is **never defined**. Callers guard with `hasattr(dashboard, "show_toast")`, so success toasts silently never appear (not a crash; this corrects the brief) | `inventory.py:1162`, `projects.py:1082`, `role_management.py:440` | Confirmed | `ui/toast.py` (P5) |
| 3.11 | Medium | The audit tab has no LIMIT; no pagination anywhere | brief | Brief-only | `paged_table` (P3) |

## 4. Panel-Awe features and audit integrity
| # | Sev | Finding | Evidence | Status |
|---|-----|---------|----------|--------|
| 4.1 | High | `log_action` **deletes** all but the latest 10,000 log rows, contradicting "unalterable" logs | `database.py:52-59` | Confirmed |
| 4.2 | Medium | No session ID in logs (the manuscript claims cross-referencing by session) | `log_action(user_id, action_type, module, details)` signature | Confirmed |
| 4.3 | n/a | Wear forecast, anomaly detector and audit chain do not exist | repo | To build in P4 |

## 5. UI/UX
| # | Sev | Finding | Evidence |
|---|-----|---------|----------|
| 5.1 | Medium | Light-only, small-font theme (Inter 10-12), colour-only status | `profile.py`, `dashboard.py` |
| 5.2 | Medium | The scanner opens a separate OpenCV window | see 3.2 |
| 5.3 | Medium | No toast system | see 3.10 |

## 6. Repo hygiene
| # | Sev | Finding | Evidence |
|---|-----|---------|----------|
| 6.1 | High | `.env` **is tracked by git** although `.gitignore` lists it (ignore rules do not untrack files). Its history contains the Aiven password; `.env.example` also contains it in a comment | `git ls-files` |
| 6.2 | Medium | Tracked junk: `__pycache__/*.pyc`, `remember_config.json`, `spy.py`, `_test.py` | `git ls-files` |
| 6.3 | Medium | `create_tables.py` and `seed_admin.py` print emoji and crash on a Windows cp1252 console; `seed_admin` creates the admin with no email (the cause of 3.1) | observed |

## Not yet verified (to be read before editing)
Bodies of `execute_borrow` and `execute_return`, `tracking.py`, the `reports.py` ABC SQL (archived-tool joins), `help.py` beyond the cited lines, `scripts/*.py`.

---

# Phase 1 addendum - new findings and status

## New findings (not in the brief or `AUDIT_FINDINGS.md`)
| # | Sev | Finding | Evidence | Status |
|---|-----|---------|----------|--------|
| N1 | Critical | **`views/tagging.py` was committed with three unresolved merge-conflict blocks** (`<<<<<<< HEAD` ... `>>>>>>> 0b6201e`), so it could not even be imported. It is also **not imported or routed anywhere**: the sidebar has no Tagging entry and `show_frame` has no Tagging branch (the "TAGGING MODULE" placeholder would show). The documented Tagging module is unreachable | `views/tagging.py:256,293,329,339,342,346,592,638,685`; `dashboard.py` nav list | **Syntax fixed** (took the `HEAD` side: fixed 450x300 label, bold font, long-name truncation, 300 dpi, over the older variable-size layout). **Still to do**: route it (see DOC_SYNC #23) |
| N2 | Critical | `InventoryView.__init__` ran `ALTER TABLE inventory MODIFY ... FLOAT` on every visit. It would have silently reverted the DECIMAL(10,2) stock columns the new schema relies on | `views/inventory.py:36-62` | **Removed** with all other runtime DDL |
| N3 | High | Connecting to the name `localhost` costs ~2 s per connection on this Windows machine (IPv6 first). The old pool opened 10 connections at the first call, so login stalled 20+ s | measured: 2.07 s vs 0.00 s for `127.0.0.1` | **Fixed** in `db/pool.py` (`localhost` -> `127.0.0.1`); test suite 111 s -> 10 s |
| N4 | High | My own first pool draft set `conn.autocommit = ...` on a pooled-connection **proxy**, which never reaches the session; a bookkeeping `INSERT` was silently rolled back. Caught by the migration re-run test | `db/pool.py` | **Fixed** (set in SQL); covered by tests |
| N5 | Medium | Plain `pytest` collected the legacy `_test.py` in the repo root, which connects to the configured database at import time | `_test.py` | `pytest.ini` restricts collection to `tests/`; file is deleted in Phase 6 |
| N6 | Medium | MySQL cannot drop and re-add a foreign key of the same name in one `ALTER`; the first CASCADE->RESTRICT attempt failed silently. Caught by test | `db/migrate.py` | **Fixed** |
| N7 | Low | The Maintenance tab "auto-sync" inserts an open ticket for every tool whose `condition` is Damaged/Needs Repair/Lost (the documented "automatic ticket" is really this query) | `views/maintenance.py` (`_fetch`) | Replaced in Phase 2 by a ticket created inside the retrieval transaction |

## Status of Area 1 (database) after Phase 1
| Brief item | Status |
|---|---|
| 1.1/1.2 ACID issuance + transaction helper, retry 1213/1205 | **Mechanism done and tested** (`db/pool.py`, `services/stock_ledger.py`, `tests/test_stock_concurrency.py`). **Not yet wired**: `execute_borrow`/`execute_return`/maintenance/inventory/projects still use the old code paths until Phase 2 |
| 1.3 Pool, leak in profile, offline banner | **Done**: `db/pool.py`; `ProfileView` no longer holds a connection (40 views opened against a pool of 16); banner verified in the real `DashboardApp` |
| 1.4 O(1) cache | **Done** (`services/tool_cache.py`, 7 tests). **Not yet wired** into the scan screens (Phase 2/3) |
| 1.5 Canonical schema + idempotent migrate + remove runtime DDL | **Done**; legacy scripts moved to `db/legacy/`; no `CREATE/ALTER/DROP TABLE` remains in app code (grep clean) |
| 1.6 Schema drift (`req_id`, `status`, archive columns, `tool_issues`) | **Done** |
| 1.7 `project_workers` junction | **Done** (table, backfill, trigger sync). Old screens still write the text column; the trigger mirrors it |
| 1.8 Snapshot 4 dates | **Done** (columns, backfill, trigger copies from the project on insert) |
| 1.9 `tool_issues` columns per ERD | **Done**. Creating the ticket inside the retrieval transaction: Phase 2 |
| 1.10 Per-unit condition | **Schema + ledger done** (`quantity_in_maintenance`, `quantity_lost`). Screens still use the old per-tool `condition` until Phase 2 |
| 1.11 Fractional consumables (`transaction.quantity`) | Column + CHECK done; screens still create one row per unit until Phase 2 |
| 1.12 FKs RESTRICT, CHECKs, unify archive flags | **Done** (archive: `archived_at` canonical, `is_archived` kept in sync by trigger; column dropped in Phase 2) |
| 1.13 Indexes | **Done** (all nine listed, plus `updated_at`) |
| 1.14 Remove `DATE_ADD(.. 8 HOUR)` | **Done** (5 places). **Data note:** old Aiven timestamps are UTC, see `docs/DATABASE.md` |
| 1.15 Employee ID sequences | Table + backfill done; `role_management.py` still uses MAX+1 until Phase 2 |

## Verification actually run (Phase 1)
* `pytest`: **107 passed** with `TEST_DB_*` set (local MySQL 8.0.46); **30 passed, 77 skipped** without it (DB tests skip cleanly).
* Migration of a legacy-shaped database with awkward data (FLOAT/NULL stock, `requirement_id`, colliding worker ids, archive flag only, a project that violates the new date CHECK): all rows kept, shape identical to a fresh install, re-run is a no-op.
* Migration run for real on the local `champion_db` (verified backup written to `backups/` first, which is git-ignored).
* Headless build of all 10 screens (Profile, Projects, Inventory, Issuance, Tracking, Reports, Maintenance, Role Management, Help, Tagging) under a real Tk main loop for 2.5 s each with background threads: no exceptions. **This is a load check, not a click-through of every button.**
* **Not run:** the GUI by hand, camera/QR scanning, PDF export, backup/restore buttons, and any Aiven access (by design).
