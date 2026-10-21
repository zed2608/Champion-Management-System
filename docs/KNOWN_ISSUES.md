# Known issues and things only a person can verify

Last updated after the overnight session (Phase 4 and Part C). Nothing here is hidden: if it is listed, it was not done or not verified.

## Not verified by a person (automatic tests only)
The full step-by-step list is `docs/HAND_TEST_CHECKLIST.md`. In short, nobody has yet:
1. clicked through the screens (tests call the same functions the buttons call and build every screen for Staff and Admin, but do not click and cannot judge looks);
2. scanned a printed sticker with a real webcam (tested with a fake camera);
3. pressed the Backup / Restore buttons or used the Browse dialogs (the service is tested with the real `mysqldump` / `mysql` on throwaway databases);
4. waited out the 15-minute inactivity logout (tested with a fake clock);
5. opened a PDF in a viewer or printed anything (PDFs are written and read back by tests; `os.startfile` is replaced in tests);
6. watched the Admin dashboard cards, the Verify Audit Chain button or the Anomalies tab on real data. Anomalies in particular need weeks of real use to say anything.

## Decisions and limits worth knowing
- **A full disk and a locked folder during PDF export are simulated** (the write is made to fail after bytes are on disk); they were not reproduced on a real disk.
- **PDFs go to the Windows temp folder** and are opened; there is no "choose a folder" dialog.
- **Audit chain:** makes tampering detectable, not impossible. Someone with full MySQL administrator rights can drop the triggers or the table.
- **Reports are paged on screen only** (a report must be computed over all rows). Every other table asks the database for one page at a time.
- **Help text already stored in your database** (the guide that says "inactivity for 5 minutes") is not rewritten automatically. Edit the guide once in Help > Guide (Admin).
- **Restore needs every other computer logged out.** The screen says so; nothing forces it.
- **Helper scripts in `scripts/`** (`check_db.py`, `debug_dates.py`, `import_test.py`, `migrate_db_to_lan.py`, `seed admin.py`) were not reviewed or deleted. They may connect to whatever `.env` points at; do not run them casually.
- **SQL in screens:** screens no longer write to the database. Read-only SELECTs that feed paged tables still live in the screens (a clean-up, not a safety issue).
- **Tests take about 10 minutes and must run serially.** The migration holds a server-wide lock; running the suite (or two copies of it) in parallel makes tests fail with "Another migration is running".
- **The PyInstaller spec (`ChampionManagement.spec`) has never been run.**

## Secrets: action needed from you
- `.env` and `remember_config.json` are no longer tracked (they stay on your disk). **They are still in git history**, and the old `.env.example` contained the previous cloud
  database's host and password in a comment. Rotate that password and scrub history yourself, as you said you would. History was not rewritten.

## Reverted or skipped steps
None. Part B (Phase 4) was already committed before the overnight session; it was audited, not rebuilt. `requirements.txt` already met the brief and needed no change.
