# Changelog by quality attribute (ISO/IEC 25010)

Purpose: so Chapters 4 and 5 can be revised against what the system now actually does. Every change on branch `refactor/industrial-hardening`
(Phase 0 to the overnight session) is listed once under the attribute it mainly improves; a change that helps several is cross-referenced.
Short commit hashes are in brackets. "Automatic test" means a test in `tests/` against a throwaway database; **no change here has been hand-tested
by a person yet** unless `KNOWN_ISSUES.md` says so (see `HAND_TEST_CHECKLIST.md`).

ISO/IEC 25010 product-quality characteristics: Reliability, Security, Functional suitability, Performance efficiency, Usability, Maintainability,
Compatibility, Portability. Reliability is first because it scored lowest in the manuscript.

---

## 1. Reliability (maturity, availability, fault tolerance, recoverability)

**Maturity (the system does not fail under normal use)**
- Issuance and retrieval are each ONE locked database transaction: stock rows locked in a fixed order, everything re-checked from the locked rows, one
  retry on deadlock, full rollback on any failure. The last unit can no longer be issued twice by two terminals. [c92863b; Phase 1.5a 7f4528c]
- The "restock" double count (a returned damaged unit added to both total and available stock) is gone; a separate "in maintenance" counter replaces it. [2a39afb]
- Database triggers enforce the project state machine, the locked requirement list and the 4-date rules, so a bug in a screen cannot bypass them. [32c7643]
- Foreign keys are RESTRICT, not CASCADE: deleting a tool or user can no longer wipe its history. [f4eb733]
- Workers on a project are rows in a junction table, not a comma-separated text (`WKR-2026-0011` no longer matches `WKR-2026-001`). [73c11da / Phase 1.3 schema]
- Quantities are DECIMAL and counted per transaction (consumables can be fractional, equipment is whole units). [181060a]
- Tag ids can no longer be shared by two tools (Inventory Update and Save Tag both refuse in plain words and change nothing). Automatic test added in the
  overnight session; the code already did this. [overnight, tests/test_tag_duplicates.py]
- Inventory showed `2.00/5.00` instead of `2/5` (and the same in Projects, Maintenance and the issuance requirement list): fixed by one shared formatter. Found by
  the overnight issuance/return test. [overnight]
- Fixed: Inventory Update failed for every row ("KeyError '1'"); Inventory panel dates showing the format text; profile loading forever on a NULL email;
  merge-conflict markers committed in tagging.py. [4ebfa87, 2707245, ed0b315, 02bf7a7]
- Scanner: one shared scanner service with a worker thread and a queue (the screen never freezes on the camera), camera probing, reconnect after unplug,
  a 2-second repeat filter, glare retries. [ac03f5d]
- Thread and timer hygiene: worker results go through a queue polled on the Tk thread; every `after()` job is cancelled when a screen closes; charts are closed. [60120ae]
- Connection pool leaks fixed (the Profile screen held a connection forever; a dirty connection could poison the pool). [c3e04bb, c1307c0]

**Availability**
- Thread-safe connection pool with transaction helpers; `localhost` is mapped to `127.0.0.1` (2 s per connection on Windows). [d5aeda4, 0dbece5, 6763311]
- Offline banner: when MySQL is unreachable the program says so, retries by itself and saves nothing. [c3e04bb]
- Server-side paging on every table (25/50/100 rows), recycled row widgets: a large history no longer loads at once. [8a3b01e]

**Fault tolerance**
- Every database error shown to a person goes through one translator: plain words, no SQL, no host names; unexpected errors get a code and a line in `logs\app.log`. [5357f05, 4ebfa87]
- PDF export writes to a side file and renames it into place; a full disk or a locked folder shows a plain message and leaves no half-written file
  (and never destroys an older good file). Missing PDF viewer is reported as "saved, but no program could open it". [overnight, tests/test_pdf_export.py]
- Migrations are re-runnable, backup-gated, refuse to run against the cloud database, and pre-check constraints. [73c11da, 3aea4b0]

**Recoverability**
- Backup/restore rebuilt: credentials never on the command line, `.part` file renamed only after a complete-dump check, disk-space check, SHA-256, restore
  validated first (rejects cut-short, junk and wrong-database files), automatic safety backup before every restore, backup history survives a restore. [e3b4d00]
- Round trip (backup, change, restore, refused cut file, refused wrong-database file) proven by an automatic test with the real `mysqldump`/`mysql`. [overnight, tests/test_restore_roundtrip.py]
- Audit history is never deleted any more: old rows move to an archive table and the hash chain runs through it. [4575cfb]
- Archived tools, employees and projects are restorable; a restored project returns to the status it had. [67189df, 2a39afb]
- Admin dashboard warns in red when the last backup is older than 7 days. [76c7495]

## 2. Security (confidentiality, integrity, non-repudiation, accountability, authenticity)

- Role checks happen in the services and are re-read from MySQL on every privileged call (`@require_role`), not only by hiding buttons; a sweep test fails the build
  if a new service function is unguarded, and the overnight session added a test that the sweep really detects an unguarded function and extended it to the Phase 4 modules. [61ea0d1, overnight]
- Two MySQL accounts (`champion_staff`, `champion_admin`) with least-privilege grants, applied by a script that never stores passwords in git. [3f4f0cd]
- Login: only Active non-Worker accounts; 3 failed attempts lock the account, counted under a row lock; passwords over bcrypt's limit are "invalid", not a crash;
  "Forgot username" no longer reveals who exists; workers have no password hash. [61ea0d1]
- Tamper-evident audit log: every row is hash-chained (SHA-256 over the previous hash and the row, including the session id); MySQL refuses UPDATE/DELETE on it;
  two terminals cannot fork the chain; Admin-only **Verify Audit Chain** names the first broken row or a removed tail; the verdict and head hash print on the audit PDF. [4575cfb]
- A session id per login is stored with every action. [4575cfb]
- No hard-coded passwords; `seed_admin.py` asks for one; `.env` no longer tracked (overnight, Part C). [8dabdd6, overnight]
- Input validation in one module (lengths, formats, control characters, ids that arrive as text). [7f4528c]

## 3. Functional suitability (correctness, completeness, appropriateness)

- Reports count quantities, not rows; ABC analysis is 20/30/50 by rank, never-issued tools are always C, archived tools stay in the historical total. [9d835d3]
- Issuing to a project whose end date passed is refused; issue/return times are the SERVER clock (+08:00) on the receipt and in history, not the PC clock; the +8 hour hacks are removed. [43596a2, c92863b]
- Project lifecycle (Pending > Approved > Ongoing > Completed > Archived) is a real state machine; edits are diffed, not delete-and-reinsert. [67189df]
- Tagging became part of Inventory (Staff may tag only untagged tools). [c1307c0, 0bfb7a0]
- New (Phase 4): wear and maintenance forecast per tool (hours out, service interval, "due in N days"), anomaly and bottleneck detector with peso-ranked recommendations
  and the numbers behind each, monthly savings card against the P10,000 baseline, blocked issuance attempts recorded. [e049616, 3a2398b, ab3a49a]
- Reports gained Wear and Anomalies tabs and PDF export for them. [5ff36dd]
- Every one of the 7 report PDFs (plus Wear and Anomalies) is produced and read back by an automatic test. [overnight]

## 4. Performance efficiency

- Pool opened up front, `localhost` fix (start-up 20-30 s faster), O(1) tool lookup cache refreshed across terminals by `updated_at` polling, hot-path indexes, paging. [6763311, 955dab1, 3aea4b0, 8a3b01e]
- Admin dashboard insight cards load in a worker thread; the dashboard never waits for them. [76c7495]

## 5. Usability (user error protection, operability, learnability)

- Plain-language messages everywhere (see Fault tolerance); a damaged/lost return needs a written description; one success box instead of two. [c92863b, 5357f05]
- Password-strength checklist on registration; 15-minute inactivity logout with a 30-second warning and "Stay Logged In". [064697b]
- Paged tables with recycled rows; Staff see a read-only Projects screen and only the controls they may use. [8a3b01e, 61ea0d1]
- Help editor and support tickets moved to a guarded service. [224b0f5]

## 6. Maintainability (modularity, analysability, modifiability, testability)

- Business rules moved out of 12 screens into `services/` (no screen writes SQL any more); schema in one `schema.sql` with a re-runnable `migrate.py`; runtime DDL removed. [43596a2, c92863b to 224b0f5]
- 395 automatic tests at the end of Phase 3; the overnight session added the tests listed in `OVERNIGHT_LOG.md`. Generated database diagram `docs/DATABASE.md`. [32b93b7]
- Dead code removed (`spy.py`, `_test.py`, `scripts/fix_thread_dates.py`), legacy schema scripts retired to `db/legacy`. [8dabdd6, overnight]

## 7. Compatibility
- Target is Python 3.11; PyQt removed from requirements; requirements pinned. [50fb651, overnight]

## 8. Portability (installability)
- `README.md` describes the offline LAN setup (server PC, client PCs, grants, `.env` per terminal, backups, VC++ runtime, `mysqldump` on PATH). A PyInstaller spec exists
  but is **untested**. [overnight]

---

## What is NOT claimed
- No screen, the webcam, backup/restore buttons, printing or PDF export has been verified by a person. Automatic tests drive the same functions the buttons call
  but do not click.
- The audit chain makes tampering detectable, not impossible: someone with full MySQL administrator rights can drop the triggers or the table.
