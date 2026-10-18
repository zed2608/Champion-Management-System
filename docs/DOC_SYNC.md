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
| 23 | Tagging module (Fig. 118 "Tagging Module (Staff)"; User Manual and Admin Quick Start send users to it) | a Tagging module exists | `views/tagging.py` was orphaned (no sidebar entry, no route) and committed with unresolved merge conflicts | **Decided (you)**: its own sidebar entry for **Admin and Staff**; the print-tag button also stays in the Inventory item panel. **Staff can generate and print tags but cannot change a tool's tag ID once assigned; only Admin can relink or unlink.** Syntax repaired (done); route + the tag-ID permission: step 2g | syntax done; routing + rule todo (2g) |
| 24 | "Cancel Project" on a running project | not described in the workflow lists | Admin can cancel an Ongoing project (only when no tool is deployed) | **Keep** (removing it would remove a feature); allowed as `Ongoing -> Cancelled` in `project_transitions`. **Manuscript**: add the edge to the workflow | done in schema |
| 25 | Time zone | not stated | cloud DB stored UTC and the screens added 8 h; the local server stores Manila time | **Change code**: session time zone +08:00, hacks removed (done). **Manuscript**: state "server time, Asia/Manila". **Data**: shift imported Aiven timestamps +8 h once | done (code); your data move |
| 26 | "Declined" | a status in the workflow | stored as `Cancelled`, displayed "Declined" | **Change code**: `Declined` exists in `project_transitions`; old rows stay `Cancelled` (cannot tell which were declines). Screens switch in Phase 2 | todo |

## A3. Behaviour decisions made while rebuilding Issuance & Retrieval (Phase 2a/2b)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 27 | Lost return | whole tool flagged Lost (blocked all units); total reduced | only the lost units leave the total; `quantity_lost` counts them; ticket created in the same transaction | state per-unit condition handling |
| 28 | Damaged / Needs Repair return | whole tool flagged (blocked all units); next Good return cleared the flag; message said "Restocked" | only those units are held in maintenance; other units stay issuable; flag cannot be hidden by a later Good return; message says they are held back | revise the "Retrieval" and "Damaged routing" text |
| 29 | Condition details | optional | **required** for Damaged, Needs Repair and Lost (screen + service) | add to manual Guide B |
| 30 | Maintenance ticket | appeared when the Maintenance tab next ran its auto-sync | created inside the retrieval transaction (with transaction id, reporter) | matches the docs ("automatically creates an actionable ticket") |
| 31 | Success message | shown twice on return | shown once | none |
| 32 | Borrower check | any user, any status | Active accounts only; assigned to the project by exact match (junction table) | the manual should say archived/locked accounts cannot receive tools |
| 33 | Quota | checked on screen, then updated without a lock | re-checked under lock at commit: two terminals cannot together exceed the approved quantity or the last unit | none (hardening) |
| 34 | Receipt time | time the receipt was printed, on the printing PC | time of issuance from the server clock; a reprint shows the same time | state "server time" |
| 35 | Overdue colouring | compared with the PC's date | compared with the server's date (same as the filter); uses the due date snapshot taken at issuance | none |
| 36 | `INTERVAL 8 HOUR` | shown +8 h for the UTC cloud DB | removed; session time zone +08:00 | see row 25 |
| 37 | Return after the project ended | n/a | still allowed (the end-date rule applies to issuing only) | add to manual |

## A4. Maintenance and Inventory behaviour changes (Phase 2d)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 38 | Resolving a ticket | "Restock quantity" added to total AND available while the damaged unit was still in total, so stock was inflated | Final condition **Good** returns the units to stock (total unchanged); any other condition removes them from stock; "New units to add" (replacement bought / lost unit found) is the only way the total grows | revise the Maintenance section |
| 39 | Resolved ticket's issue type | overwritten with the final condition | kept (Damaged stays Damaged); resolution and outcome appended to the notes | none |
| 40 | Manual flag | set the tool's condition (blocking every unit) | takes the stated number of units (new "Units" field, default 1) out of stock; Discrepancy/Other are records only | add the "Units" field to the screenshots |
| 41 | Maintenance auto-sync | opening the tab invented a ticket for any tool whose condition field was flagged | removed. Tickets are created by what causes them (return, manual flag); for data coming from the old system the upgrade creates them once | none |
| 42 | Condition on the Inventory item panel | editable by Admin | read-only; changes go through Maintenance (Fig. "Manage Item") | revise the Inventory section |
| 43 | Archiving a tool | allowed while units were deployed | refused while units are deployed or in maintenance (service **and** database trigger): "A tool cannot be archived while units are deployed or in maintenance." | add to the Inventory/Maintenance sections |
| 44 | Editing total quantity | "cannot go below deployed" computed from the values the panel loaded | checked against the locked, current values; also counts units in maintenance | none |
| 45 | Restoring a tool | set `is_archived = 0` only | also clears `archived_at` | none |
| 46 | Tag ID | Admin could edit it freely, no format rule | new tags must be 3-32 letters/digits/dashes; an unchanged legacy tag is kept; **Staff may assign a tag only to an untagged tool; only Admin can relink or unlink** | revise the Tagging section (Fig. 118) |

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
