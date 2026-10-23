# Champion Management System

Automated tool issuance, retrieval, inventory, project and maintenance management for Champion Fine Tooling Corp.
Python 3.11, CustomTkinter, MySQL 8, OpenCV (QR scanning). It runs **offline on a local network (LAN)**: one PC hosts the MySQL
database, every other PC runs the program and connects to it. No internet is needed.

```
   Client PC 1 ─┐
   Client PC 2 ─┼── LAN ──►  Server PC  (MySQL 8, the only copy of the data, backups)
   Admin PC    ─┘
```

## 1. The server PC (once)

1. Install **MySQL Server 8.0** (the MySQL installer is fine). Give the server PC a fixed address (reserve it in the router), e.g. `192.168.1.100`.
2. Allow MySQL through the Windows firewall (inbound TCP **3306**, private network only).
3. Create the database and an administrator account (as `root`):

   ```sql
   CREATE DATABASE champion_db CHARACTER SET utf8mb4;
   ```
4. In the project folder, create `.env` from `.env.example` with the **root/administrator** connection (`DB_HOST=127.0.0.1`, `DB_NAME=champion_db`), then:

   ```
   python -m db.migrate --make-backup     # creates/upgrades every table, trigger and procedure (safe to run again)
   python seed_admin.py                   # first Admin account; asks for the password (never stored in a file)
   ```
5. **Grants** (recommended): create one MySQL account for Staff terminals and one for Admin workstations, so MySQL itself refuses what a role may not do.

   ```
   set STAFF_DB_PASS=choose-a-long-password
   set ADMIN_DB_PASS=choose-another-long-password
   python -m db.apply_grants
   ```
   `champion_staff` can issue/retrieve and read; it cannot touch the audit log, other users' data or restore a database. `champion_admin` has
   everything inside `champion_db` and nothing on other databases. Re-run this command after upgrading the program (new tables add new grants).
6. Backups: on this PC keep a folder such as `D:\ChampionBackups` and take a backup from **Maintenance > Database Backup & Restore** at least weekly
   (the Admin dashboard turns red when the last backup is older than 7 days). Copy the folder to a USB drive off-site.

## 2. Each client PC

1. Install **Python 3.11** (64-bit) and the **Microsoft Visual C++ Redistributable (x64)** (OpenCV and the QR reader need it).
2. Copy the project folder, then in it:

   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
3. Create `.env` **on that PC only** (never share or commit it):

   ```
   DB_HOST=192.168.1.100
   DB_PORT=3306
   DB_USER=champion_staff          # champion_admin on an Admin workstation
   DB_PASS=the-password-from-step-5
   DB_NAME=champion_db
   ```
   `localhost` is treated as `127.0.0.1` automatically (the name is slow on Windows).
4. Start with `.venv\Scripts\python main.py`. If the server is off, the program shows an offline banner, retries by itself and saves nothing until it is back.
5. Webcam: any USB camera. Choose it in the scan window; the choice is remembered per PC (`scanner_config.json`).

**`mysqldump` and `mysql` must be on the PATH** of any PC that makes or restores backups (normally only the Admin workstation or the server). The program also
looks in `C:\Program Files\MySQL\MySQL Server 8.0\bin`. Restoring replaces the whole database, so every other PC must be logged out first.

## 3. Roles

| Role | Can do |
|---|---|
| Admin | Everything: inventory edits, projects, maintenance, reports, role management, backup/restore, audit verification |
| Staff | Issue and retrieve tools, read inventory and projects, tag untagged tools, own history |
| Worker | No login. A badge (QR) so Staff can scan them for issuance |

The 15-minute inactivity logout, the audit chain (Tracking > Activity Log > Verify Audit Chain) and the Admin insight cards (wear forecast, anomalies, backup age) are described in `docs/DOC_SYNC.md`.

## 4. Sample records and guided tour

### Add sample records to your current database

If you already run the app through `.env` (including an Aiven connection), preview the target and then add 12 sample inventory items, 3 approved projects and 2 non-login Workers:

```powershell
python scripts/add_mock_data.py
python scripts/add_mock_data.py --apply
python main.py
```

The command only adds missing records with `Demo` in their names, keeps existing records, and can be run again without duplicating the sample. It uses the same database as `python main.py`, so check the target shown in the preview first. Its projects have assigned Workers and tool requirements; ten of the items have tags for printing. The full local defense dataset and its separate database remain described in `docs/DEMO_SETUP.md`.

After login, choose **Guided tour** in the top bar or **Help > About > Start guided tour**. Use Next and Back to see the actual modules and the outlined controls. Admin sees all sections; Staff sees only sections they may open. Exit tour at any point. It does not change projects, stock or tool movements; normal page visits still appear in the activity log.

## 5. Tests

```
set TEST_DB_HOST=localhost
set TEST_DB_USER=root
set TEST_DB_PASS=...
python -m pytest -q
```
Database tests create and drop their own **throwaway databases named `test_*`** and never touch `champion_db`. Without `TEST_DB_USER` they are skipped.
Some tests open real (hidden) windows and need a Windows desktop session.

## 6. Building the .exe (UNTESTED)

`ChampionManagement.spec` is a PyInstaller recipe (`pip install pyinstaller`, then `pyinstaller ChampionManagement.spec`; output in `dist\ChampionManagement\`).
**It has never been run.** Expect to adjust hidden imports or data files on the first build, then test every screen, the camera and PDF export from the built folder.
It builds a folder, not a single file, because the program writes next to itself (`logs\`, `backups\`, `.env`, `scanner_config.json`, `assets\profiles\`).

## 7. Where to look

| | |
|---|---|
| `docs/HAND_TEST_CHECKLIST.md` | Everything only a person can verify |
| `docs/DOC_SYNC.md` | Every place the code differs from the thesis text |
| `docs/KNOWN_ISSUES.md` | What is not verified or not done |
| `docs/CHANGELOG.md` | Every change since Phase 0, by quality attribute (ISO/IEC 25010) |
| `docs/DATABASE.md` | Generated table diagram |
| `logs\app.log` | Error log (rotates at 1 MB). Send it with the error code to an administrator |

## Security notes
- `.env` and `remember_config.json` are not in git. Never commit passwords; `.env.example` holds placeholders only.
- Change the database password if it was ever committed (git history keeps old versions).
