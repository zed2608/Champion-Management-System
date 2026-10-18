# Known issues and things only a person can verify

Last updated at the end of Phase 3. Nothing here is hidden: if it is listed, it was not done or not verified.

## Not verified by automated tests (needs a person at a real computer)
1. **A real webcam.** The scanner is tested with a fake camera and fake pictures (reading a code, 2-second repeat filter, unplug and
   reconnect, "no camera", "camera in use", glare retries, releasing the camera). Nobody has yet scanned a printed sticker with a real
   camera under real light. See the hand-test list in the final summary.
2. **Backup and restore buttons.** The service is tested against a throwaway database with the real `mysqldump` and `mysql` programs
   (good file, cut-short file, junk file, wrong database, failing program, restore round trip). The Browse dialogs and the pop-ups were
   not clicked by a test.
3. **The 15-minute inactivity logout** is tested with a fake clock (14:59 no warning, 15:01 warning, 30 seconds later logout, "Stay logged
   in", "No" on the logout question). A real 15-minute wait was not done.
4. **Look and feel of the paged tables** (spacing, how the page buttons look on your screen size).

## Decisions and limits worth knowing
- **Reports are paged on screen only.** A report must be computed over ALL rows (the ABC ranking, the totals, the charts and the PDF
  need the whole set), so the database is asked once for the whole result and the screen shows 25/50/100 rows at a time.
  Every other table (Inventory, Issuance history, Tracking logs/audit/activity/my history, the four Maintenance tables, backup
  history) asks the database for one page at a time (`LIMIT`/`OFFSET` plus a total count).
- **Row widgets are recycled** in every paged table. Rows are not re-created on page change; only text and colours change.
- **Help text already stored in your database** (the guide that says "inactivity for 5 minutes") was seeded from the old built-in text
  and is not rewritten automatically. Edit that guide once in Help > Guide (Admin), or delete it and the new built-in text is
  re-seeded on the next start when the table is empty.
- **`remember_config.json`** is tracked by git and changes whenever someone ticks "remember me" on the login screen. It was left alone.
- **Restore needs every other computer logged out.** The screen says so, but nothing forces it; MySQL is replaced under their feet.
- **`.env`** shows as modified in git. That is yours and was never staged.
- **SQL in screens.** No screen writes to the database any more (no INSERT/UPDATE/DELETE/commit in `views/`, `dashboard.py` or
  `main.py`). Read-only SELECTs that feed the paged tables (Inventory, Issuance history, Tracking, the Maintenance tables, a few lookups in
  Projects/Profile/Role Management) still live in the screens and go through the shared `services.paging.fetch_page` helper; moving those
  reads into services is a clean-up, not a safety issue.

## Reverted or skipped steps
None. Every Phase 3 step (B1 to B6) was completed and committed.
