# Demo setup for the defense

A separate database called **champion_demo** is filled with realistic data. Your real database (`champion_db`) is never read or changed by any of this:
the scripts refuse to use it (and refuse any Aiven host).

## What you get
| | |
|---|---|
| People | 1 Admin (Rhea Santos, `ADM-<year>-001`), 1 Staff (Miguel Ramos, `STF-<year>-001`), 6 Workers (`WKR-<year>-001` to `006`). The passwords are the ones **you** choose in step 2. |
| Tools | 40 items in 7 categories (Power Tools, Hand Tools, Measuring, Welding, Safety, Machining, Consumables). Includes: a tool with exactly 1 unit (Bench Grinder, Laser Distance Meter), consumables with fractional stock (Welding Rod 60.5 kg, Cutting Oil 18.5 L, Bearing Grease 7.5 kg), two **untagged** tools (Hard Hat, Bolt Cutter 24in) and the rest **tagged** (`TAG-###-XXX`). |
| Projects | **Warehouse Roof Retrofit Phase 1** (Completed), **Riverside Plant Shutdown Maintenance** (Ongoing, **2 days past its end date**), **Cavite Fabrication Bay Installation** (Approved, starts in 5 days, ends in 40). |
| History | About 3 weeks of issues and returns, with Damaged returns (open repair tickets), a Lost return, one repaired-and-resolved ticket, and **9 issuance lines still out and overdue**. |
| Refused issuances | 9 recorded blocked attempts (the Angle Grinder was asked for 7 times with none in stock). |
| Admin cards | A backup 3 days old, an intact audit chain, a wear forecast with tools past their service interval, recommendations, and the savings card. |

All dates are relative to the day you run the seeder, so **run it again on the morning of the demo** to make the history look fresh.

## 1. Create `.env.demo`
Copy `.env.demo.example` to `.env.demo` and set `DB_USER` / `DB_PASS` to a MySQL account that may create databases (root is fine on your own PC).
Leave `DB_NAME=champion_demo`. This file is git-ignored; your real `.env` is not touched.

## 2. Build the demo database
PowerShell, in the project folder (choose your own passwords; they need 8+ characters with a number, an uppercase letter and a special character):

```powershell
$env:DEMO_ADMIN_PASSWORD = "Choose-An-Admin-Password1!"
$env:DEMO_STAFF_PASSWORD = "Choose-A-Staff-Password1!"
python scripts/seed_demo_data.py --qr-folder demo_qr
```
(If you leave the two variables out, the script asks for the passwords, hidden.) It drops and re-creates **only** `champion_demo`, runs the normal migration, fills the data and writes the Workers' QR badges to `demo_qr\` for the webcam demo.
It prints `Done. Database champion_demo is ready.`

## 3. Start the program against the demo
```powershell
python scripts/run_demo.py
```
This reads `.env.demo`, refuses to start if it does not point at a `champion_demo` database, and opens the normal login window. Log in as `ADM-<year>-001` (Admin) or `STF-<year>-001` (Staff).
To go back to your real data just start it the usual way (`python main.py`); nothing else changed.

## 4. Reset the demo
Run step 2 again. It rebuilds `champion_demo` from scratch (everything you did during a rehearsal disappears). To remove the demo completely:
`DROP DATABASE champion_demo;` in MySQL (never `champion_db`).

## 5. Print the stickers (for the webcam moment)
- Workers: `demo_qr\` already has the six badge pictures; or Role Management > a Worker > **Badge**.
- Tools: Inventory > click a tool > **⎙ Generate Print File** (the two untagged tools need a tag first: **↻ Auto-Gen**, then **Save Tag Link**).
Test the webcam in the same light as the room you will present in.

## The 12-minute walkthrough
Numbers are what the seeder produced on 21 Oct 2026; yours will differ slightly (dates move with the day you seed). Open the program fresh so the splash and intro show.

| Time | Do | Say / show |
|---|---|---|
| 0:00 | Start the program. Splash, then the 4-slide intro (arrow keys), tick **Don't show again**. | The problem: P10,000 a month in lost tools; scan, issue, return, insight. |
| 0:45 | Log in as the Admin. Welcome toast appears top right. | Server-side roles: Admin sees every module. |
| 1:15 | **Dashboard**. | Four cards: tools out, overdue projects, open tool issues and low stock. The project strip shows one overdue project. |
| 2:00 | **System status > Show details > Refresh**. | Last backup 3 days ago, audit chain status, wear forecasts, recommendations and savings. Details are hidden until requested. |
| 3:30 | **Inventory**: search "grinder", point at `2/5`-style quantities and the fractional consumables; open **Hard Hat** (untagged), **↻ Auto-Gen**, **Save Tag Link**. | Tags are unique; a duplicate is refused in plain words. |
| 5:00 | **Issuance & Retrieval > 📤 Issue Tools**: worker `WKR-<year>-001`, project *Cavite Fabrication Bay Installation*, scan/type a Welding Helmet tag, issue. Receipt shows the server time. | Four dates are kept per issuance; issuing to an ended project is refused. |
| 6:00 | Try to issue the **Angle Grinder** (none in stock). | Refused; the attempt is recorded for the anomaly detector. |
| 6:30 | **📥 Retrieve Tools**: return something **Damaged** with empty details (refused), then with details (ticket number shown). | Stock moves per unit; one broken unit does not block the others. |
| 7:30 | **Maintenance**: *Issues & Repairs* (open tickets), resolve one; *Wear Forecast*; *Backup & Restore* > **Run Backup Now**. | Backup is verified before it is accepted; restore makes a safety copy first. |
| 9:00 | **Reports**: *Inventory ABC Analysis* (Cutting Disc and Sandpaper are class A), *Overdue Transactions*, *Anomalies* (the Angle Grinder bottleneck, the damage outlier, the overdue cluster). **Export PDF** from one. | Every recommendation shows the numbers behind it. |
| 10:30 | **Tracking & Accountability > Activity Log > 🔐 Verify Audit Chain**; then **Audit Report PDF**. | INTACT, and the same hash is printed on the PDF; MySQL itself refuses edits and deletes of log rows. |
| 11:15 | Log out, log in as **Staff**. | No Reports, Maintenance or Role Management; Projects are read-only; no Admin cards on the dashboard. |
| 11:45 | **Help > About**. | Replay the intro any time; team list. |

Tips: rehearse once with a throwaway reset; keep the Angle Grinder refusal and the Damaged-return-without-details for live moments (they are the most convincing); do not run **Restore** in front of the panel unless you rehearsed it on `champion_demo` first.

## `ui/tour-dashboard` defense UI checks (23 October 2026)

Inventory now has **Select tagged tools on this page**, a live selected count, and **Batch Print Tags** enables only after a tagged tool is selected. Tagged rows have a clickable **Select** label; untagged rows say **Tag first**. Check this with a real mouse on a tagged row, after paging and searching, then on an untagged row. The automated Tk event check can be repeated with `.venv\Scripts\python.exe scripts/check_tour_inventory.py`; it forces the local `champion_demo` database and does not print.

Reports keep their data charts, but empty chart and summary regions collapse and populated charts are shorter. Open all nine tabs at 1366×768 and 1920×1080. `.venv\Scripts\python.exe scripts/capture_tour_reports.py --check-only` opens each tab at both sizes without writing screenshots. With an unlocked 1920×1080 desktop, omit `--check-only` to save captures under `docs/screenshots/tour_dashboard_after/`. Capture was blocked in the automated session (`OSError: screen grab failed`), so inspect the screen directly.

The current `fix/defense-ux` branch has a four-card dashboard for each role. See `docs/HAND_TEST_CHECKLIST.md` for the current manual checks. The older `docs/TOUR_DASHBOARD_SUMMARY.md` records the previous branch's state.
