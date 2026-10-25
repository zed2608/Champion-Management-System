# Hand-test checklist (everything only a person can verify)

**Read this first**
- The earlier lists (Phase 2 issuance steps, the 24-step list, the Phase 3 list) were chat messages, not files in the repository.
  This list was **rebuilt** from `docs/DOC_SYNC.md`, `docs/KNOWN_ISSUES.md` and the screens' own button texts, and merged into one order.
  If an old step you remember is missing, add it at the bottom and tell me.
- Button names below were copied from the code, but nobody has clicked this list yet. If a name differs on your screen, that is a finding.
- **Use a copy of the data, not your real database.** Steps 43-46 (backup / restore) REPLACE the whole database. Easiest: restore the newest file in
  `backups\` into a second database (e.g. `champion_handtest`) and point `.env` `DB_NAME` at it for the session; put `DB_NAME=champion_db` back afterwards.
  The automatic tests use their own throwaway databases and never touched `champion_db`.
- Accounts needed: one **Admin**, one **Staff**, one **Worker** (a Worker has an Employee ID and a QR badge but no password).
  Examples used below: Admin `ADM-2026-001`, Staff `STF-2026-001`, Worker `WKR-2026-901`.
- ★ = one of the **10 riskiest steps**. If you only have 20 minutes, do just the ★ steps (they are copied again at the end as the short list).
- The order is deliberate: read-only first, then things that add data, then things that change data, then the destructive ones last.
  Do not skip ahead; a later step may use data an earlier step created.

Legend: **Do** = exact clicks. **Expect** = what you must see. Write PASS or FAIL and a note next to each number.

---

## A. Start-up and login (read-only)

1. **Start the program** (`python main.py`).
   *Expect:* the login window opens within a few seconds; no error box; no red "Database offline" banner.
2. **Wrong password.** Use a SPARE Staff account (this step locks it), password `wrong`, **Login**.
   *Expect:* "Invalid Credentials. 2 attempt(s) left." (plain text, no technical words). Twice more: "Account Locked: Maximum attempts reached ..." (3 strikes).
   A correct password now still says the account is locked. Unlock it afterwards in Role Management (**Edit** the user, then set the status/password as the screen allows).
3. **Worker cannot log in.** Employee ID `WKR-2026-901`, any password.
   *Expect:* refused with a plain message (Workers have no login).
4. **Staff login.** Log in as Staff.
   *Expect:* the sidebar shows exactly: Dashboard, Project Management, Inventory, Issuance & Retrieval, Tracking & Accountability, Help.
   It does **not** show Reports, Maintenance, Role Management, or the Admin-only System status panel.
5. **Staff screens open** (click each sidebar item once): Dashboard, Project Management, Inventory, Issuance & Retrieval, Tracking & Accountability, Help.
   *Expect:* each opens, shows data (or a plain "No ... found"), no error box. Project Management has **no** "+ Add Project" button.
   Tracking shows only "My Deployment History" (no Audit / Activity tabs, no Verify button).
6. **Log out, then log in as Admin.**
   *Expect:* the sidebar also shows Reports, Maintenance, Role Management. The Dashboard shows a short **System status** line (it may say "Checking…" briefly); **Show details** opens the extra status cards.
7. **Admin screens open** (click each once, and click through every tab inside Reports, Maintenance, Tracking).
   *Expect:* no error box on any tab; tables show pages (25/50/100 per page) with Prev / Next.

## B. Inventory (adds data)

8. **Add an item.** Inventory > **+ Add New Item**. Name `Test Hammer`, Item Type `Equipment`, a Category, a Supplier, Quantity `5`, Price `250`. **Save Item**.
   *Expect:* success message; the table shows `Test Hammer` with quantity **5/5** (not `5.00/5.00`), tag "Unassigned" in red.
9. **Fractional equipment refused.** Add New Item again, Equipment, Quantity `2.5`.
   *Expect:* a plain message that equipment is counted in whole units; nothing saved.
10. **Duplicate name refused.** Add `Test Hammer` again.
    *Expect:* "already exists" message; nothing saved.
11. ★ **Inventory Update on "nails".** Click the row of an existing item named "nails" (or `Test Hammer` if you have no "nails") > change the **Price** > **Update** > Yes.
    *Expect:* the dialog closes, the table refreshes, the new price shows. No "KeyError", no error code box. (This was the Inventory ID bug.)
12. **Duplicate tag refused (Update).** Open `Test Hammer`. In **Tag ID** type the tag of ANOTHER tool, also change the name to `Test Hammer 2`. **Update** > Yes.
    *Expect:* a message saying the tag is already used by another tool; after closing it, reopen the item: the name is still `Test Hammer` and the tag is unchanged.
13. **Duplicate tag refused (Save Tag Link).** Same item, type the other tool's tag, click **Save Tag Link**.
    *Expect:* "Tag not saved ... already used by another tool"; no "successfully linked" message.
14. **Give a tag.** Click **↻ Auto-Gen** (or type `TST-001`) > **Save Tag Link**.
    *Expect:* "Tag successfully linked"; the table now shows the tag; the QR preview shows the tag text.
15. **Print a tag.** **⎙ Generate Print File**.
    *Expect:* a PDF with the QR code and the tag text opens (needs a PDF viewer). Close it.
16. **Staff may tag only an untagged tool** (log in as Staff in a second window or after logging out). Open an untagged item.
    *Expect:* Staff sees **Save Tag Link** only for items with no tag; for a tagged item the tag box is locked and there is no Unlink button.
17. **Search.** Type part of a name in the search box.
    *Expect:* the table narrows; clearing it restores all rows.

## C. Projects

18. **Admin adds a project.** Project Management > **+ Add Project**. Name `Test Project`, a client, a location, Start = today, End = 30 days ahead, add a worker `WKR-2026-901`,
    **Browse Inventory Catalog** and add `Test Hammer` x `4`, then **Save**.
    *Expect:* the project appears as **Ready for Deployment / Approved** (an Admin's project is approved at once).
19. **Dates.** Edit the project and set End earlier than Start.
    *Expect:* refused with a plain message.

## D. Issuance and Retrieval (changes stock)

20. ★ **Issue tools.** Issuance & Retrieval > **📤 Issue Tools**. Employee ID `WKR-2026-901` + Enter. Pick `Test Project`. Scan/type the hammer's tag `TST-001` + Enter **four times**.
    A fifth time must be refused ("Limit Reached"). **Issue Tools & Print Receipt**.
    *Expect:* exactly **one** success box; a receipt image/print window; the history table shows an **Issue** row, quantity 4; Inventory shows the hammer **1/5**.
21. ★ **Receipt time.** Look at the "Date & Time" on the receipt and compare with the clock on the wall.
    *Expect:* the same minute, Philippine time. Then close the program, change the PC clock by -2 hours, reopen the program, **reprint** the same receipt from the history row:
    *Expect:* it still shows the ORIGINAL issue time (server time), not the changed PC clock. Put the PC clock back.
22. **Return one Good.** **📥 Retrieve Tools**. Employee `WKR-2026-901` + Enter, tag `TST-001` + Enter. Condition `Good`, quantity `1`, **Confirm Retrieval & Restock**.
    *Expect:* one success box; Inventory shows **2/5**.
23. ★ **Return one Damaged, empty details** (with 24 this is one of the 10). Retrieve again: condition `Damaged`, quantity `1`, leave **Condition Details** empty, Confirm.
    *Expect:* a warning that you must describe what is wrong; nothing changes (Inventory still **2/5**).
24. ★ **Return one Damaged, with details.** Type `Handle cracked` in Condition Details > Confirm.
    *Expect:* one success box that names a ticket number; Inventory shows **2/5** (2 on the shelf, 2 still out, 1 in maintenance). Maintenance > Issues shows an **Open** ticket for the hammer with that number.
25. **Return the last two Good.** Retrieve quantity `2`, `Good`.
    *Expect:* Inventory shows **4/5** (the 5th unit is in maintenance); the history shows the rows as Retrieved.
26. **Refusals.** Try to issue to `WKR-2026-901` a project that has ended / a tool with no stock left.
    *Expect:* plain refusal messages, nothing saved. (Each refusal is silently counted for the Anomalies report in step 37.)

## E. Maintenance (Admin)

27. **Flag an issue.** Maintenance > **🚩 Flag a Tool Issue**: Tool `TST-001`, Reported By `STF-2026-001`, Condition `Needs Repair`, Units `1`, notes, **Submit Flag**.
    *Expect:* success; the unit count in maintenance rises; a new Open ticket.
28. **Resolve the ticket as Good.** Select the open ticket > Final condition `Good` > **✓ Mark Resolved & Update Inventory**.
    *Expect:* the unit returns to stock (Inventory total available rises by 1); the ticket shows Resolved.
29. **Archive refused while deployed.** Try to archive a tool that still has a unit out or in maintenance.
    *Expect:* a plain refusal saying how many units are deployed / in maintenance.
30. **Wear Forecast tab.** Maintenance > Wear & Maintenance Forecast.
    *Expect:* equipment listed with hours, % of interval, "due in N days" or "not used lately"; the editable category default and per-tool interval save without error; **Mark serviced now** resets the hours.

## F. Reports and PDF (Admin)

31. **Open every report tab** (Usage, Activity, Allocation, Damage, Low stock, Overdue). Wear is under Maintenance.
    *Expect:* each shows data or a plain "none found"; charts draw; no error box.
32. ★ **Export all PDFs.** On each tab click **⎙ Export PDF** > **⎙ Export Now**.
    *Expect:* a PDF opens for each (6 in all), titled correctly, with the company header and a "Records: N" line under each table. No error box.
33. **PDF problems (partly automatic).** A full disk and a locked folder are simulated by the automatic tests; do NOT try them by hand.
    By hand, only check this: if the PC has no PDF viewer, export once. *Expect:* "The report was saved but no program could open it" plus the file path, not an "Export Error".
    Skip if your PC has a PDF viewer.
34. **Date filter.** Set From/To dates (YYYY-MM-DD, or the 📅 picker) on Usage > Apply; export.
    *Expect:* the PDF's header shows the same period. An invalid date such as `2026-13-40` is refused with a plain message.

## G. Tracking and the audit chain (Admin)

35. ★ **Verify Audit Chain.** Tracking > ⚙️ Activity Log > **🔐 Verify Audit Chain**.
    *Expect:* "Recomputing every hash…", then an **INTACT** verdict with the number of entries and the chain head (a long hex code). Not red.
36. **Audit Report PDF.** Click **⎙ Audit Report PDF**.
    *Expect:* a PDF whose first table says Result: INTACT and prints the same head hash as step 35, followed by the newest entries.
37. **Report search.** Search a worker, item, project or status in each relevant report, press Enter, and export the PDF.
    *Expect:* the PDF rows match the filtered screen. Low Stock has no date filter. The optional PDF note does not filter rows.
38. **Dashboard cards.** Dashboard (Admin) > **Show details** > **↻ Refresh** on System status.
    *Expect:* last backup (red if none or older than 7 days), audit chain status, top 5 wear forecasts, top 5 recommendations, and the monthly savings card. The page never freezes while they load.

## L. Defense UI and workflow checks

49. **Print controls with no tag.** Inventory > **Needs Tag**. *Expect:* rows say **Tag first** in the Print column; the page's **Select all** checkbox is absent and **Batch Print Tags** is disabled. Assign one Tag ID, switch to **Already Tagged**, click both its small checkbox and the surrounding Print cell on separate tries. *Expect:* each click changes selection, the count follows it, and Batch Print enables only while something is selected. Change page size and repeat.
50. **Sidebar hover.** Move the pointer quickly across Dashboard, Inventory and Help without clicking. *Expect:* only the item under the pointer and the currently open section are highlighted. Move outside the window and back; no old hover remains.
51. **Dashboard overview.** Log in as Admin and Staff. *Expect:* four short cards for each role. Click each card; it opens the corresponding section. With no recent tool activity, the chart says so rather than showing a false trend. Admin details stay collapsed until requested.
52. **Field rules.** Try a name `Worker 123` in Role Management and `123` as a project or tool name. *Expect:* refused in plain language. Try `10 mm drill` as a tool and `Phase 2` as a project. *Expect:* accepted. Enter only one project date, then an end date before the start date. *Expect:* both refused; equal dates are accepted.
53. **Replacement after return.** On a test project whose full tool quantity is currently issued, verify that it no longer offers further issuance. Return one Good unit, verify the assigned worker can select the project again, and issue that unit once. *Expect:* no more than the approved active quantity is deployed, and stock decreases by one. A damaged return opens a maintenance issue and does not increase available stock.
54. **Help content.** Open Help Guide and FAQs after updating an existing database. *Expect:* the printing, project dates, issuance and return instructions match these screens. If an Admin edited a built-in guide or FAQ earlier, that custom text remains.
55. **Sample data (only if wanted).** From PowerShell, preview with `python scripts/add_mock_data.py` and confirm it names the database you intend to use. Then run `python scripts/add_mock_data.py --apply`, restart the app and look for Demo tools, three projects and two Workers. Rerun the command; it should add zero records the second time. Existing records must be unchanged.

## H. People (Admin)

39. **Register users.** Role Management > **+ Register New User**: a Staff with a weak password (`abc`).
    *Expect:* the four checks (8 characters, number, uppercase, special) stay grey/✗ and **Register** is refused; with `Abcdef1!` they turn green ✓ and it saves. Choosing Worker hides the password boxes.
40. **Badge.** On a user row click **🔖 Badge**.
    *Expect:* a QR badge opens/prints.
41. **Archive a user.** Archive the test user; Maintenance > Archived Employees lists it.
    *Expect:* it disappears from Registered Users and appears under Archived Employees.

## I. Camera (needs the real webcam and a printed QR)

42. ★ **Scan a real sticker.** Inventory > **📷 Scan & Test QR**, hold the printed `TST-001` label (from step 15) in front of the camera in normal room light.
    *Expect:* "Starting camera…" then the tool opens within about 2 seconds. Then try: very bright light on the sticker (glare), the sticker upside down, and unplugging the webcam while the window is open.
    *Expect:* a read in all but extreme glare; unplugging gives a plain message and reconnecting works; holding the same sticker still does NOT open it twice in under 2 seconds. Repeat once from Login (**📷 Scan**) and from Issuance (**📷 Scan**).

## J. Backup and restore (changes or replaces the database: do these LAST)

43. ★ **Create a backup** (with 44 this is one of the 10). Maintenance > Database Backup & Restore > pick a folder with **Browse**, optional name, **💾 Create Backup** (or **⬇ Run Backup Now**).
    *Expect:* success with file name and size; the file exists; Backup History lists it. No `.part` file left in the folder.
44. ★ **Restore round trip.** Add one more test item (so the data differs), then **⬆ Restore from Backup** with the file from step 43, confirm.
    *Expect:* success; the extra item is gone; a "before_restore_…" safety file appears in the program's `backups` folder; Backup History still lists the earlier backups plus a Restore row; the audit chain still verifies INTACT (repeat step 35).
45. ★ **Bad restore files.** Restore (a) a copy of the backup you cut in half with a file editor, then (b) any other `.sql` file or a Word file renamed `.sql`.
    *Expect:* both refused with a plain message ("incomplete" / "not a backup"); data unchanged; no safety backup created for them.
46. **Restore a backup of a different database** (if you have one).
    *Expect:* refused: "made from a different database".

## K. Time-based (slow: do last)

47. ★ **15-minute inactivity.** Log in as any user and leave the mouse and keyboard alone for 15 minutes.
    *Expect:* after about 14 min 30 s a "Session Inactivity" warning with **Stay Logged In**; clicking it keeps you logged in and restarts the timer. Leave it again and do not click:
    after 30 more seconds you are logged out and the login window returns. Also: click Exit/Logout and answer **No**: the timers must keep working (you are still logged out after 15 idle minutes).
48. **Database offline banner.** With the app open, stop the MySQL service (Windows Services > MySQL80 > Stop).
    *Expect:* a banner "Database offline – retrying… Nothing is being saved."; actions give a plain message, not a crash. Start the service again: the banner disappears by itself.
    (Do this only if nobody else is using the database.)

---

## Short list: the 10 riskiest steps (about 20 minutes, plus 15 for the timer)

| # | Step | Expect |
|---|---|---|
| 11 | Inventory Update on "nails" | saves, table refreshes, no error |
| 20 | Issue 4 tools; a 5th is refused | one success box, receipt, Inventory 1/5 |
| 21 | Receipt time / PC clock changed | original server time, Philippine time |
| 23 + 24 | Damaged return, empty then filled details | refused, then accepted with a ticket number; Inventory 2/5 |
| 32 | Export all 9 PDFs | all open, titled correctly |
| 35 | Verify Audit Chain | INTACT + head hash; same hash on the PDF (36) |
| 42 | Real webcam scan (+ unplug) | reads sticker, no double open, plain message on unplug |
| 43 + 44 | Backup, then restore it | extra item gone, history kept, safety file made |
| 45 | Cut-off and junk restore files | refused, nothing changed |
| 47 | 15-minute idle logout | warning at ~14:30, logout 30 s later, "Stay Logged In" works |

(10 rows; 23 + 24 and 43 + 44 are each one test in two clicks.)

---

## Polish branch checks (`ui/defense-polish`): only your eyes can judge these

Do these on the polish branch with the **demo database** (see `docs/DEMO_SETUP.md`), not your real data. Each takes under a minute.

P1. **Splash.** Start with `python scripts/run_demo.py`. *Expect:* a borderless green splash with a thin yellow progress line that fills in about 1.5 seconds, then the intro (first launch) or the login window. It must not flash a white window first.
P2. **Intro.** On the first start: four slides; **Next ▶**, **◀ Back**, **Skip**, the arrow keys and **Esc** all work; four dots show where you are; the last button says **Done ✓**. Tick **Don't show again**, finish, restart. *Expect:* no intro. Then Help > **ℹ About** > **▶ Replay the intro** shows it again, and **Show it again at next start** brings it back on the next launch. Reading all four slides takes under 20 seconds.
P3. **Welcome toast.** After login a small card "Welcome back, <your name>" appears at the top right, shrinks its thin timer bar and disappears by itself after about 3 seconds. *Expect:* it never covers the green **+ Add ...** button of the page and never needs a click.
P4. **Toasts after actions.** Archive and restore a tool, update your profile, restore an archived employee. *Expect:* a green toast (not a pop-up you must click). A **destructive** action (archive, restore database, delete) still asks "Are you sure?" first.
P5. **Hover and click feel.** Move the mouse over buttons, sidebar items, the Low Stock and Action Items cards and table rows. *Expect:* each fades smoothly (about a tenth of a second), the pointer turns into a hand, a button darkens briefly while pressed. Nothing flickers when you slide across a row or card. Leave the mouse over a sidebar item you just clicked: it stays highlighted as the active page.
P6. **Reduced motion.** Put `CHAMPION_REDUCE_MOTION=1` in `.env`, restart. *Expect:* no fades, no count-up, no pulsing placeholders, a shorter still splash; everything still works. Remove the line to get the animations back.
P7. **Loading placeholders.** Open Inventory, Issuance & Retrieval, Tracking. *Expect:* grey bars (gently pulsing) instead of an empty white frame for a moment, then the rows.
P8. **KPI cards.** Admin and Staff dashboards show four number cards with short labels and coloured stripes. Low Stock turns pink when something is below its minimum. Staff has no ADMIN INSIGHTS panel; Admin can open the detailed insights.
P9. **Readable from 2 metres.** Stand 2 m from the screen at the resolution you will present at. *Expect:* sidebar, card numbers, table text and the green headers are readable; grey hint text is the faintest thing and is still legible. If something is too small, note the screen and tell me.
P10. **Every screen still reachable.** Click every sidebar item and every tab: Dashboard, Project Management, Inventory, Issuance & Retrieval (2 tabs), Tracking (3 tabs), Reports (6 tabs), Maintenance (6 tabs), Role Management, Help (5 tabs), Profile (click your name top right). *Expect:* each opens with a title and no overlapping or cut-off text at 1366 x 768.
P11. **One full issue/return still works.** Issuance & Retrieval > **📤 Issue Tools** to a demo worker, then **📥 Retrieve Tools** with one **Damaged** (empty details refused, then accepted). *Expect:* the same results as before the polish (one success box, a receipt, a ticket number, quantities right in Inventory).
P12. **Colours.** Buttons come in four looks only: green (main action), grey (secondary), text-only (quiet) and red (danger). Statuses are readable on white (no pale green or yellow text).
P13. **Dark/light switch.** Not built (see `docs/POLISH_SUMMARY.md`): there is nothing to check.

## Defense UI checks (`ui/tour-dashboard`, 23 October 2026)

Use `champion_demo` from `docs/DEMO_SETUP.md`. These checks still need a person at an unlocked screen; automated Tk event checks do not judge visual appearance.

T1. **Tagged print selection.** Inventory: click the checkbox and the surrounding Print cell for a tagged tool such as Masking Tape. *Expect:* one click ticks it, the count becomes `1 selected`, and **Print Selected Tags** enables beside it. Untick it: count returns to zero and the button disables. Change page, set Rows per page to 50, search another tagged tool, then clear the search and click a row that was reused. *Expect:* the visible tick matches the selected tool IDs, not whichever tool used that row before.
T2. **Untagged print selection.** Search `Hard Hat` or `Bolt Cutter 24in`. *Expect:* its Print cell says **Tag first** and clicking it does nothing. Clear the search, click the **Select** label or checkbox on a tagged row. *Expect:* the count and Print Selected Tags state update. Tick **Select tagged tools on this page**. *Expect:* only tagged rows on the current page are selected. Untick it to clear that page's tagged rows.
T3. **All six Reports tabs.** At 1366×768 and 1920×1080, open Usage, Employee Activity, Project Allocation, Damage and Loss, Low Stock, and Overdue. *Expect:* headers, search, filters and scrolling work; the table starts promptly below the description and any chart with data. Export after searching and check the PDF rows. Low Stock has no date picker. Check real charts and one PDF export if a viewer is installed.
T4. **Dashboard and sidebar.** Log in as Admin, then Staff. *Expect:* four readable KPI cards with short notes; Staff sees only permitted pages and no Admin Insights. Move the mouse across sidebar pages without clicking; every unselected hover highlight clears when the pointer leaves. Check the opening and post-login loading screens have the same style.
T5. **Issue and return.** On demo data, issue one tagged tool to a demo Worker on a valid project, then return it. *Expect:* one receipt, correct Inventory quantity, and a completed history row. If returning Damaged, empty details are refused and filled details create a ticket. This branch did not change the service workflow.

Earlier `scripts/check_tour_inventory.py` passed Tk press/release checks on `champion_demo`. Re-run the updated checks on Windows because this revision changed quantity, confirmations, and reports; screenshot capture was unavailable in the earlier run.

## Quantity, confirmation and search checks (current branch)

1. Create a Rotary Hammer (Equipment, pcs) and try `0.5` as stock, project requirement, issue, return and maintenance quantity. Each must be refused without saving. Repeat with Consumable, pcs.
2. Create a Consumable, kg with `2.5`. Request and issue `0.5`, return `0.25` as Good. Inventory available, deployed quantity, project requirement and history must agree. Try `0.001` and check that it is refused. A duplicate project cart addition must never exceed total owned stock.
3. Cancel each confirmation for new Inventory item, new/edited Project, Issue, Return, Maintenance flag and issue resolution. Reload the relevant screen: no stock or record should have changed. Confirm each action once and check one success message.
4. Search all Maintenance data lists (issues, archived tools, employees, projects, wear, backup history). Search a term that appears only on a later page and check the result is found. Search each Reports tab, export, and compare the PDF rows to the screen.
5. Check the six Reports tabs, Inventory selection row and sidebar at 1366×768 and 1920×1080 on Windows. Check keyboard Enter in quantity and report search fields and test the mouse hover after opening and closing dialogs.
6. Edit a project with several required items, close it, then open Add Project. The new item list and workers must be empty. Return to Edit Project and remove one item with the red X. Cancel once, then confirm once. No `IndexError` should appear in the terminal and only the selected item should disappear.
7. In the project catalog, click + Add. Both **Confirm** and **Cancel** must stay visible along the bottom of the question window at Windows display scale. Cancel must leave the list unchanged; Confirm must add one item. Repeat with a long shortage warning and with the camera quantity prompt.
8. At the presentation screen size, check the compact right-aligned 200-pixel search boxes, grouped actions, section menus, and a table with several pages in Inventory, Issuance & Retrieval, Projects, Tracking, Reports, Maintenance, Role Management and Help. Rows per page, First, Prev, Next and Last must stay on one line and no control should extend outside the window.
