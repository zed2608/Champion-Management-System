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
| 5 | ABC thresholds | A=top 20% items, B=30%, C=50% (Ch. 1-3); Ch. 5 says "top 70%" | cumulative usage share A<=70%, B<=90% (`reports.py:262,1453`) | **Change code**: A = top 20% of tools by usage, B = next 30%, C = last 50% **(you)**. **Manuscript**: the Ch. 5 "top 70%" is a typo | Phase 2 (`report_service`) | done (see A7) |
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
| 23 | Tagging module (Fig. 118 "Tagging Module (Staff)"; User Manual and Admin Quick Start send users to it) | a Tagging module exists | `views/tagging.py` was orphaned (no sidebar entry, no route) and committed with unresolved merge conflicts | **Decided (you)**: its own sidebar entry for **Admin and Staff**; the print-tag button also stays in the Inventory item panel. **Staff can generate and print tags but cannot change a tool's tag ID once assigned; only Admin can relink or unlink.** Syntax repaired (done); route + the tag-ID permission: step 2g | superseded: Tagging removed, folded into Inventory (see A8 row 80) |
| 24 | "Cancel Project" on a running project | not described in the workflow lists | Admin can cancel an Ongoing project (only when no tool is deployed) | **Keep** (removing it would remove a feature); allowed as `Ongoing -> Cancelled` in `project_transitions`. **Manuscript**: add the edge to the workflow | done in schema |
| 25 | Time zone | not stated | cloud DB stored UTC and the screens added 8 h; the local server stores Manila time | **Change code**: session time zone +08:00, hacks removed (done). **Manuscript**: state "server time, Asia/Manila". **Data**: shift imported Aiven timestamps +8 h once | done (code); your data move |
| 26 | "Declined" | a status in the workflow | stored as `Cancelled`, displayed "Declined" | **Change code**: `Declined` exists in `project_transitions`; old rows stay `Cancelled` (cannot tell which were declines). Screens now use it (2e) | done |

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

## A5. Project lifecycle (Phase 2e)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 47 | Approval of an Admin-created project | created as Approved (kept) | **Kept, and now stated as a rule: a project created by an Admin is auto-approved, so there is no separate "approve" step.** This is the manuscript's "remove double validation" recommendation. An existing Pending project (from the old Staff drafts) can still be approved by an Admin | state the single-step creation in the Project Management chapter and the flowchart |
| 48 | Workflow | four different lists in the documents | Pending > Approved > Ongoing > Completed, plus Declined and Cancelled, then Archived. `Ongoing > Cancelled` (Admin "Cancel Project" on a running project) is kept | use this one list everywhere |
| 49 | "Declined" | stored as `Cancelled` and shown as "Declined" | a real status: only from Pending. `Cancelled` is only Approved/Ongoing projects that were cancelled. Projects declined in the old system remain `Cancelled` (cannot be told apart) | note it for imported data |
| 50 | Editing a project | any Pending/Approved project, delete-and-reinsert of all requirement lines (wiped the Fulfilled flags) | only Pending/Approved; lines are diffed (unchanged lines keep their Fulfilled flag); once ANY tool has been issued only name/client/head/location/description can change | add to the manual |
| 51 | Stale screens | last save won | a change made from a screen that shows an out-of-date status is refused ("changed by someone else, reload") | none |
| 52 | Cancel / Complete | tool-deployed check on the screen only | checked in the service under lock | none |
| 53 | Restoring an archived project | always set to Approved (re-opening Completed/Cancelled projects for issuance) | back to the status it had before archiving | revise Maintenance > Archived Projects |
| 54 | Workers on a project | free text, matched by `LIKE` | each ID must belong to an Active employee; stored in `project_workers` (exact match) | none |
| 55 | Staff and Project Management | Staff blocked from the module, but the screen still had Staff branches | **Staff get read-only Project Management (your decision), so Staff can no longer save drafts.** `DRAFT_ROLES = ("Admin",)` in `services/project_service.py` is the single switch if drafting should return | the "Save as Draft" step in the Staff guide goes away |

## A6. Access control, login and Role Management (Phase 2f)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 56 | Who can do what | enforced only by hiding sidebar entries | **every service function** re-reads the caller's role and status from MySQL (`@require_role`); a tampered or stale session cannot escalate; refusals are written to the audit log; Workers never have a session. A test fails the build if a service function lacks a guard. Matching MySQL accounts (`champion_staff`, `champion_admin`) are the second layer | revise the "UI-only RBAC" weakness in Ch. 5 |
| 57 | Staff and Project Management | Staff blocked from the module | **Staff see a read-only Project Management** (list and details; no Add, Edit, status or archive actions) **(your decision)** | update Fig. 116 |
| 58 | Staff dashboard feed | the dashboard read the audit log directly | Staff read a database view (`v_activity_feed`) that exposes project-creation events only, so Staff need no access to the audit log | none |
| 59 | Login for non-active accounts | only `Locked` was refused | `Locked`, `Archived` and `Inactive` are refused; Workers cannot log in; failed attempts of non-active accounts are not counted | add to the login section |
| 60 | Passwords | trimmed at login and registration | **never trimmed**; a password over 72 bytes is "invalid", not an error | none |
| 61 | Workers' password | the bcrypt hash of one shared constant on every Worker | no password hash at all (migration clears the old ones) | none |
| 62 | Forgot Username | showed the employee id to anyone who knew an email, and said "not found" otherwise | identical reply either way; **the id is never shown**; a match creates a support ticket ("Username request") for an Admin, who contacts the person | revise Fig. 3 and the FAQ |
| 63 | Forgot Password | reply differed for unknown ids | identical reply; known accounts are flagged for an Admin | none |
| 64 | Same full name | registration was blocked | **warns and allows** (real employees share names); the e-mail address stays unique; also applies to the Profile screen | add to Role Management |
| 65 | Employee ids | `MAX + 1` with no lock; padded to 3 digits | issued from a locked sequence (two Admins cannot get the same id); numbers past 999 work | none |
| 66 | Blank e-mail on registration | stored as an empty string, so a second blank e-mail broke the unique key | stored as NULL | none |
| 67 | Editing a user | saving re-activated the account unconditionally | an archived account cannot be edited (restore it first); saving a Locked account still unlocks it | none |
| 68 | Last Admin | could be archived or demoted | **the last active Admin cannot be archived or demoted, and nobody can archive their own account** (race-safe) | add to Role Management |
| 69 | Dashboard numbers | counted rows | sums of quantity: a consumable of 2.5 kg counts 2.5; total physical = shelf + deployed + in maintenance; "maintenance items" = open tickets; archived employees and tools are excluded | none |
| 70 | Help editor, backup log, Tagging writes | direct SQL in the screens | **still direct SQL** (Help editor and tickets, backup log: scheduled; Tagging: step g) | n/a |

## A7. Reports, ABC and quantities (Phase 2f, continued)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 71 | ABC thresholds | cumulative usage share: A <= 70%, B <= 90%, C the rest (and the PDF used the same, over all time) | **A = top 20% of tools by rank, B = next 30%, C = last 50%** **(your decision, Ch. 1-3).** The Ch. 5 "A = top 70%" is a manuscript typo. Rule detail: with N ranked tools, A = the first ceil(20% x N), B = up to ceil(50% x N); **a tool never issued in the period is always C** (otherwise a never-used tool could be "high priority" when few tools were used) | state the rule and the never-issued exception |
| 72 | ABC and archived tools | archived tools disappeared from the totals, so every other percentage shifted when something was archived | archived tools are not ranked, but their usage stays in the **historical total**; every share is measured against that total; the screen shows the historical total, the number of ranked tools and the archived share | add to the ABC section |
| 73 | "Times Issued" | number of transaction rows | **quantity issued** (units): 3 calipers = 3, 2.5 kg of grease = 2.5. Column renamed "Qty Issued" in the screen and the PDF | rename the column in the figures |
| 74 | Usage report | "Currently out" = total - available, which also counted units waiting in maintenance | units actually deployed (sum of active issuance quantities) | none |
| 75 | Employee activity / Project allocation | row counts | quantities (issued, active, retrieved, requested vs issued) | none |
| 76 | Damage & Loss report | counted rows and valued each row at one unit's price | counts UNITS and values them as price x units; the detail list shows the units | none |
| 77 | Overdue report | compared the live project end date, using the PC date | uses the due-date snapshot stored at issuance and the server's date; shows the units held; value at risk = price x units | none |
| 78 | PDF export vs screen | the PDF always exported all-time data using its own copy of the queries (and ignored the screen's From/To dates) | the PDF uses the **same report service** and the screen's current From/To range; the criteria line states the period | revise the export description |
| 79 | Tracking | consumable records showed no amount | records of quantity other than 1 show it ("Grease x2.5") | none |

## A8. Tagging is part of Inventory (Phase 2g, revised after your hand-test)
| # | Topic | Old behaviour | New behaviour | Manuscript / manual impact |
|---|---|---|---|---|
| 80 | **Separate Tagging module** | a file existed but was never reachable (no sidebar entry) and would not even load (unresolved merge conflicts). I briefly added a sidebar entry in step g because you asked for one earlier | **Removed again (your latest instruction: tagging is integrated in Inventory).** There is no Tagging sidebar entry and `views/tagging.py` is deleted. Everything it did exists in Inventory: the *Needs Tag* / *Already Tagged* filters, the per-item tag panel (generate, assign, unlink, live QR preview, print) and **Batch Print Tags** (tick the checkboxes of tagged items) | **Delete the separate Tagging module (Fig. 118) from the manuscript and from the Admin Quick Start / User Manual; describe tagging under Inventory** |
| 81 | What Staff can do with tags | nothing (the whole item panel is read-only) | in the **Inventory item panel**: **generate and assign a tag to a tool that has none, and print**; **cannot change an assigned tag; only Admin can relink or unlink** (enforced in the service, so it holds even if the screen is bypassed) | revise the Staff guide |
| 82 | Auto-generated tag | `TAG-<id>-<CAT>-<SUP>` with whatever characters the category had (could be illegal) | same shape, with only letters/digits kept (e.g. `TAG-007-CUT-BOS`), so it always passes the tag rules | none |
| 83 | Batch-print checkboxes | the box is greyed out for a tool with no tag and nothing explained why | unchanged rule (**only tagged items can be ticked**), now explained in the hint above the table: tick tagged items, then Batch Print Tags | mention in the Inventory section |
| 84 | Missing / blank supplier and location | the panel shows a blank as 'N/A'; saving an untouched panel stored the text 'N/A' | 'N/A' is never stored as data | none |

### Manuscript spots to update for the Tagging removal (approved)
The Scope already reads "Products and Inventory Module (with integrated Tagging)", so the code now matches the Scope; these places still describe a separate module and must change:

| Where | What to change |
|---|---|
| Tagging flowcharts, **Figs. 13-16** | remove them, or redraw them as steps inside the Inventory item panel (assign / generate tag, unlink [Admin only], print tag, batch print) |
| **Fig. 97** | it says "QR/RFID" and shows a Tagging screen: replace it with the Inventory item panel's QR tag section and say **QR only** (no RFID) |
| **Fig. 118** "Tagging Module (Staff)" | remove the Tagging Module (Staff) figure; Staff tagging is now the Inventory item panel: assign a tag only to an untagged tool, always print, never change an assigned tag |
| **User Manual: the "Tagging" page** | delete the page; move its steps under Inventory (item panel > QR Tag Management; Batch Print Tags by ticking tagged rows; the *Needs Tag* and *Already Tagged* filters) |
| **Admin Quick Start** | replace "go to the Tagging module" with "open Inventory, click the item, use QR Tag Management" |
| Module count / sidebar figures | the sidebar no longer has a Tagging entry (Admin: Dashboard, Project Management, Inventory, Issuance & Retrieval, Tracking, Reports, Maintenance, Role Management, Help; Staff: the same minus Reports, Maintenance, Role Management); also adjust any "10 modules" statement and DFD / use-case diagrams that show Tagging as its own module |
| DOC_SYNC row 15 above | "QR/RFID" is resolved by this: QR only |

## A9. Other fixes from your hand-test
| # | Topic | Old behaviour | New behaviour |
|---|---|---|---|
| 85 | Date pickers | broke with 'Dependency Missing: pip install tkcalendar' in a fresh environment: **tkcalendar was never listed in requirements.txt** (it had been installed by hand) | `tkcalendar==1.6.1` (and `babel==2.18.0`) pinned; a test fails the build if any third-party import is missing from requirements.txt |
| 86 | 'No projects needing tools' | no explanation | says why for each of the worker's projects: ended on a date, still awaiting approval, all required tools already issued, or not assigned to any active project (the end-date rule itself is unchanged: tools cannot be issued to a project whose end date has passed) |
| 87 | Unexpected error dialog | 'Something went wrong...' hid the cause completely | the user still sees the safe sentence; the real traceback is printed to the console for the developer |
| 88 | Connection pool | a screen that left a query result unread made `close()` fail, silently losing a connection from the pool and poisoning the next save (the likely cause of an unexplained 'Something went wrong' on Update) | legacy screens get buffered cursors, the pool replaces a lost connection and heals a dirty one; regression tests |

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

## D. Error codes and the log file (Inventory fix)
Unexpected errors now show `(ERR-<AREA>-<4 digits>) <short reason>` and are logged with a traceback in `logs\app.log`. The User Manual's troubleshooting page should tell users to send that file and code to an administrator. Text ids from screens are converted centrally (no manuscript change).

## E. Inactivity timeout (Phase 3 B3)
Auto-logout is now **15 minutes** idle with a **30-second** warning (it was 5 minutes in code). Per-computer override in `.env`: `CHAMPION_IDLE_MINUTES` (1-240) and `CHAMPION_IDLE_WARNING_SECONDS` (5-300). Manuscript/User Manual: state 15 minutes. Answering "No" to "Log out?" no longer stops the timers.

## F. Backup and restore (Phase 3 B2)
Restore now (1) validates the file (mysqldump header for THIS database, "Dump completed" trailer), (2) saves an automatic safety backup in `backups\` named `before_restore_<db>_<time>.sql`, (3) then loads the file; the backup history is kept across a restore. Each backup stores a SHA-256 checksum. User Manual: tell Admins that other computers must log out before a restore.

## G. Scanner (Phase 3 B1)
One shared scanner window for login, issuance, retrieval and inventory. The working camera is remembered in `scanner_config.json` (per computer, not in git). A code is ignored for 2 seconds after it was read.

## H. Paging (Phase 3 B4)
Every table shows one page at a time (10/25/50/100 rows, First/Prev/Next/Last, "Showing 1-25 of N"). User Manual: add a short "Paging" note
with a screenshot. Reports are paged on screen only (see docs/KNOWN_ISSUES.md).

## I. Help and support tickets (Phase 3 B6)
Help content and tickets are now read and written by `services/help_service.py` (Admin edits, Staff read; Staff see only their own tickets).
The built-in guide text now says 15 minutes of inactivity. An existing database keeps the old stored text until an Admin edits that guide.

## J. Logs and error codes (see section D)
`logs\app.log` is created next to the program; it is git-ignored and rotates at 1 MB (5 old files kept).

## K. Audit chain (Phase 4 step 1) [PANEL-AWE]
- The manuscript says the audit log cannot be altered unnoticed. It is now true: every `system_logs` row stores `prev_hash` and `row_hash`
  (SHA-256 over prev_hash, log_id, user_id, action, module, details, timestamp, session id). Differences from the formula you gave, all on purpose:
  fields are joined with a separator character (so "ab"+"c" differs from "a"+"bc"); the timestamp is written in UTC (so the hash does not depend
  on a PC's time zone); the session id is inside the hash (otherwise it could be edited undetected).
- The old "keep only the newest 10,000 rows" deletion is gone. Rows older than the newest 20,000 are MOVED to `system_logs_archive`
  (env `CHAMPION_AUDIT_KEEP_LIVE`); the chain runs through the archive, so history is never lost. The Activity Log tab shows the live part.
- MySQL itself refuses UPDATE and DELETE on the audit log (a row can only be deleted after an identical copy is in the archive).
  The dashboard feed for Staff still works through the existing view. Staff accounts now append only through a stored procedure
  (`sp_log_action`); re-run `python -m db.apply_grants` so their account gets EXECUTE instead of INSERT.
- Limit worth stating at the defense: someone with full database-administrator rights can still drop the triggers or the whole table. The chain
  does not stop that; it makes it DETECTABLE (Verify Audit Chain reports the first broken entry, or that the newest entries were removed).
- Each login now has a session id, stored with every entry of that login.
- Tracking > Activity Log has "Verify Audit Chain" and "Audit Report PDF" (the verdict and the chain head hash are printed on the PDF).

## L. Wear and maintenance forecast (Phase 4 step 2) [PANEL-AWE]
Maintenance > "Wear Forecast" (Admin). Hours out per tool come from the transaction dates (issuance to retrieval; a tool still out counts up to now),
weighted by quantity. The service interval is the tool's own, else its category's, else the '*' default (500 h, editable on the same screen);
`tool.service_interval_hours` and `tool.last_serviced_at` are new columns (added by the migration). Marking a tool serviced, or resolving a repair
ticket as "Good", restarts its clock. "Due in N days" uses the last 30 days of use; a tool not used in 30 days shows "not used lately" instead of a made-up date.
Flags: 90% or more of the interval used; damage rate (tickets + damaged/lost returns without a ticket, per 100 hours out) more than 2 standard
deviations above the category average (needs at least 3 tools with 10+ hours). Only Equipment is forecast; consumables have no wear.
