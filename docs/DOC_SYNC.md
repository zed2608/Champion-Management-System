# Doc <-> System Sync (Phase 0)

**The manuscript, the ERD figures and `docs/AUDIT_FINDINGS.md` are not in the repository.**
Each row comes from the brief, and I checked the code side only. Confirm the "Docs say" column against the actual manuscript before it goes into Chapter 4/5.

| # | Docs say (per brief) | Code does (verified) | Decision |
|---|---|---|---|
| 1 | Staff can access Project Management (Fig. 116) | Staff is blocked from Projects, Reports, Maintenance and Role Management (`dashboard.py:399`) | **Change code**: Staff gets read-only Project Management. Reports, Maintenance and Roles stay Admin-only, so the **manuscript must say so** |
| 2 | O(1) hash-table tool cache | No cache exists | **Change code**: `services/tool_cache.py` (P1) |
| 3 | Audit log is unalterable | `log_action` deletes rows beyond 10,000 (`database.py:52`) | **Change code**: remove pruning, add hash chain and triggers (P4) |
| 4 | Actions are cross-referenced by user session ID | No session ID is recorded | **Change code**: add a session ID (P4) |
| 5 | Inactivity logout after 15 min | 5 min (`dashboard.py:277`) | **Change code**: 15 min + warning (P3) |
| 6 | Weekly off-site backup policy | Nothing enforces or even reports backup age | **Change code**: dashboard warning at more than 7 days. **Manuscript**: describe it as policy enforced by a warning, not as automatic |
| 7 | 3-tier architecture (UI / logic / data) | Views contain SQL; there is no logic tier | **Change code**: `services/` (P2) |
| 8 | ERD Fig. 92 `maintenance_issue` (transaction link, reporter, resolver, status) | `tool_issues` lacks those columns and is created at runtime | **Change code** (P1). **Manuscript**: rename the entity or note that `tool_issues` is its implementation |
| 9 | Four project dates (start, end, issuance, retrieval) | Dates are read live from `projects`, so edits rewrite history | **Change code**: snapshot on `transaction` (P1). **Manuscript**: state that *Issuance <= End* is enforced and *Issuance < Start is allowed as early staging* (a literal Issuance <= Start rule would block every top-up issuance) |
| 10 | Workers have no login | Worker rows store a bcrypt hash of a shared constant | **Change code**: `password_hash NULL` (P2) |
| 11 | RBAC enforced by role | UI-only | **Change code** (P2) + `db/grants.sql`. **Manuscript**: remove the Ch. 5 "UI-only RBAC" weakness once done |
| 12 | Environment: Python 3.11 (per brief) | The venv runs Python 3.14 | **Decide**: pin 3.11 for the exe build, or **revise the manuscript** |
| 13 | Inventory lists all tools | Rows beyond 100 are hidden (`inventory.py:546`) | **Change code**: pagination (P3) |
| 14 | Toast notifications are part of the UI | `show_toast` is undefined; calls are silently skipped | **Change code** (P5) |
