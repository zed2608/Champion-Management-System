# Doc <-> System Sync

Source: `docs/AUDIT_FINDINGS.md` §6 (checked by you against the manuscript, User Manual and ERD Fig. 92), plus items found in the code audit.
Decisions marked **(you)** were set by your defaults; the rest are mine, applying the rule "never remove a feature". Status: `todo` = not yet done, `done` = committed.

## A. Rows from AUDIT_FINDINGS §6
| # | Topic | Docs say | System does | Decision | Where | Status |
|---|---|---|---|---|---|---|
| 1 | Deployment | Strictly offline LAN | Aiven cloud MySQL via `.env` | **Change ops**: run on local/LAN MySQL (you are migrating the data). `db/migrate.py` never targets Aiven. Manuscript wording stays correct once migrated **(you)** | Phase 1 + your data move | in progress |
| 2 | Python version | 3.11 | venv built on 3.14, `.pyc` committed | **Change code/env**: target 3.11 **(you)**; untrack `__pycache__` | Phase 1 / 6 | in progress |
| 3 | Requirements | CTk, OpenCV, pyzbar, bcrypt, Pillow, Matplotlib, NumPy | also PyQt5/PyQt6; `python-dotenv`, `qrcode` unpinned | **Change code**: remove PyQt, pin both, add pytest **(you)** | Phase 1 | todo |
| 4 | Inactivity logout | 15 min | 5 min | **Change code**: 15 min + 30 s warning, configurable **(you)** | Phase 3 | todo |
| 5 | ABC thresholds | A=top 20% items, B=30%, C=50% (Ch. 1-3); Ch. 5 says "top 70%" | cumulative usage share A<=70%, B<=90% (`reports.py:262,1453`) | **Change code**: A = top 20% of tools by usage, B = next 30%, C = last 50% **(you)**. **Manuscript**: the Ch. 5 "top 70%" is a typo | Phase 2 (`report_service`) | todo |
| 6 | The 7 reports | brief listed "Inventory Summary" | ABC, Usage, Employee Activity, Project Allocation, Damage/Loss, Low Stock, Overdue | **No change**: the manuscript list is correct; "Inventory Summary" is not a report. Keep all 7 | n/a | done (noted) |
| 7 | Project workflow | four different lists | Pending > Approved > Ongoing > Completed, Cancelled ("Declined" stored as Cancelled); Ongoing auto-set by issuance | **Change code** to Pending > Approved > Ongoing > Completed, plus Declined and Cancelled, then Archived **(you)**. **Manuscript revised** to this one list. Old rows keep `Cancelled` (cannot tell which were declines) | Phase 1 (enum/trigger) + 2 (state machine) | todo |
| 8 | Requirement lock | locked once Ongoing / tools deployed | editable while Approved even with tools out; restore sets Approved | **Change code**: trigger + service lock; restore uses `status_before_archive` | Phase 1/2 | todo |
| 9 | Worker login | Manual p.8 / Fig. 136: "Worker Identification via QR... logs you in" | Workers hard-blocked from login | **Keep code (blocked)** **(you)**. **Manuscript/manual revised**: QR identifies a Worker for issuance, it does not log them in | n/a | manuscript |
| 10 | Manual entry | FAQ: "manual typing is disabled" | Employee ID fields accept typed input + Enter | **Keep code**: typed ID stays as camera fallback **(you)**. **Manuscript/FAQ revised** | n/a (validated in Phase 1/2) | manuscript |
| 11 | Retrieve flow | Manual Guide B: scan the tool | Code needs Employee ID first | **Keep code**: removes nothing; scanning the tool first is also supported in kiosk mode. **Manual revised** | Phase 5 | manuscript |
| 12 | Damaged routing | automatically creates an actionable ticket in Maintenance | only sets `tool.condition`; ticket appears on the next auto-sync | **Change code**: ticket is inserted inside the retrieval transaction | Phase 1/2 | todo |
| 13 | Audit trail | unalterable, undeletable, session IDs | pruned at 10k, no session IDs | **Change code**: remove pruning, hash chain, triggers, session IDs | Phase 4 | todo |
| 14 | Hash table | O(1) cache used for QR scanning | scanning hits the DB; cache only in the Inventory modal | **Change code**: `services/tool_cache.py` used by all scan paths | Phase 1 | todo |
| 15 | Tagging | "QR/RFID" (Fig. 97) | QR only | **Manuscript revised**: QR only (no RFID hardware in scope) | n/a | manuscript |
| 16 | Registration | Fig. 5 collects security questions | none | **Manuscript revised**: recovery is Admin-mediated (reset request), no security questions. Adding them would be a new feature | n/a | manuscript |
| 17 | Restore flowchart | Fig. 8 text is a copy of Backup | n/a | **Manuscript**: correct Fig. 8 (the new restore adds the safety backup + checksum steps) | Phase 3 | manuscript |
| 18 | Manual section names | "Inactive Archived Projects" describes deactivated users | tab is "Archived Employees" | **Manuscript**: rename | n/a | manuscript |
| 19 | Figure refs | algorithm text cites Figs. 93/95/96 | actual figures 129-132 | **Manuscript**: fix references | n/a | manuscript |
| 20 | Min hardware | Ch. 1/CBA: Core i7, 8 GB | Manual: i5 or i7 | **Manuscript**: make consistent (suggest "i5 or better, 8 GB") | n/a | manuscript |
| 21 | Search module | standalone global Search (DFD Fig. 54) | per-table search boxes | **Manuscript**: DFD to show per-module search (debounced, capped at 64 chars). A global search is a new feature | Phase 3 | manuscript |
| 22 | Staff dashboard / PM | Fig. 116 Project Management (Staff) | Staff cannot open it | **Change code**: Staff gets **read-only** Project Management **(you)**. Reports, Maintenance, Role Management stay Admin-only | Phase 2 | todo |

## A2. Additional rows found during Phase 1
| # | Topic | Docs say | System does | Decision | Status |
|---|---|---|---|---|---|
| 23 | Tagging module (QR tag printing; Staff "print tags") | a Tagging module exists | `views/tagging.py` is orphaned (no sidebar entry, no route) and was committed with unresolved merge conflicts. Tag printing otherwise exists inside the Inventory screen | **Change code**: syntax repaired (done); route it in the sidebar for Admin and Staff (Phase 2, so Staff can print tags as documented). **Open question for you**: confirm you want it as its own sidebar module rather than only inside Inventory | syntax done; routing todo |
| 24 | "Cancel Project" on a running project | not described in the workflow lists | Admin can cancel an Ongoing project (only when no tool is deployed) | **Keep** (removing it would remove a feature); allowed as `Ongoing -> Cancelled` in `project_transitions`. **Manuscript**: add the edge to the workflow | done in schema |
| 25 | Time zone | not stated | cloud DB stored UTC and the screens added 8 h; the local server stores Manila time | **Change code**: session time zone +08:00, hacks removed (done). **Manuscript**: state "server time, Asia/Manila". **Data**: shift imported Aiven timestamps +8 h once | done (code); your data move |
| 26 | "Declined" | a status in the workflow | stored as `Cancelled`, displayed "Declined" | **Change code**: `Declined` exists in `project_transitions`; old rows stay `Cancelled` (cannot tell which were declines). Screens switch in Phase 2 | todo |

## B. ERD (Fig. 92) vs code (AUDIT_FINDINGS 1.12)
| Item | ERD | Code | Decision |
|---|---|---|---|
| `maintenance_issue` | transaction_id, reported_by INT FK, resolved_by, resolved_at | `tool_issues` (reported_by VARCHAR, is_resolved) | **Change code**: add the columns (Phase 1), keep the table name `tool_issues`. **Manuscript**: note the name or rename in the ERD |
| transaction dates | assignee_id, issuance_date, start_date, end_date, retrieval_date | user_id, borrow_date, return_date | **Change code**: add `project_start_date`, `due_date` snapshots; keep `user_id`, `borrow_date`, `return_date`. **Manuscript**: ERD to use the real names |
| Quantities | INT | DECIMAL(10,2) | **Manuscript**: ERD shows DECIMAL |
| Missing tables | help, tickets, backup_logs, requirements | present in code | **Manuscript**: regenerate the ERD from `docs/DATABASE.md` (Phase 1) |

## C. Other items from the code audit
| Topic | Decision |
|---|---|
| Hash-chained audit log, session ID (see row 13) | code |
| `.env` tracked / public credentials | Untrack in Phase 6; you are rotating the password and will scrub history yourself |
| Worker accounts store a hashed shared constant | **Change code**: `password_hash NULL` |
