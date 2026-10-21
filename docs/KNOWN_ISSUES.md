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

## Polish branch (`ui/defense-polish`)
- **Not verified by a person:** how it looks and feels (hover fades, press effect, toast position and timing, splash and intro, count-up, skeleton placeholders, text size from 2 metres). The automated tests check colours, sizes, positions and behaviour, not taste. See "Polish branch checks" in `docs/HAND_TEST_CHECKLIST.md`.
- **Dark/light switch not built.** Screens pass single colour strings to CustomTkinter, the PDF/receipt code and Matplotlib, so a switch would leave half the window light. The dark palette exists in `ui/theme.py` and passes the contrast check; wiring it in is a follow-up.
- **"After" screenshots are from right after step 7**, not from the very last commit (the PC screen locked when I tried to re-capture; the black pictures were discarded). The only visual difference is the wrap width of the Recommendations card text. See `docs/screenshots/README.md`.
- **Test flakes seen, not caused by the polish:** one full run exited silently with code 127 at 58% (passed on rerun, cause unknown); a test that compares today's date fails if a run crosses midnight (it did once; it passes alone); `test_after_jobs_are_cancelled_when_the_screen_is_destroyed` is timing-sensitive on a busy PC; and a rare Windows process crash (0x80000003) happens when Python frees a closed window's objects on a background thread. The last one is mitigated by collecting garbage on the main thread after every test (`tests/conftest.py`) and by waiting for loader threads in the screen tests; the program itself only meets this situation while closing a window mid-load.
- **Fonts:** the old code asked for "Inter", which is not installed, so Windows used a default. Segoe UI ships with Windows, so nothing needs installing.
- **`champion_demo` data is dated relative to the day it was built.** Rebuild it on the morning of the demo (docs/DEMO_SETUP.md, step 2).
