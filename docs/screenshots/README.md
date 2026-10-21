# Screenshots

* `before/` : every screen and tab of the program on branch `refactor/industrial-hardening` (before the polish), 1366 x 768, demo data, Admin and Staff.
* `after/`  : the same set on branch `ui/defense-polish`, captured right after step 7 (dashboard tidy). Two small things changed after that capture and are NOT in the pictures:
  the wrap width of the text in the dashboard's Recommendations card (it was clipped on the right) and test-only changes. An attempt to re-capture on the final commit
  produced black pictures because the PC screen was locked, so those were thrown away rather than shipped.

Both sets were made by `python scripts/capture_screens.py <folder>` (it builds a throwaway database `test_shots`, drops it afterwards and never touches champion_db).
The login picture shows the "remembered" employee ID from `remember_config.json`, nothing secret.
