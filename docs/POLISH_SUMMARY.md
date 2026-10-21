# Polish summary (branch `ui/defense-polish`)

Written for reading in the morning. Nothing was merged or pushed. No behaviour was changed: no service, database rule, schema, trigger, grant, role check or report query was edited.

## 1. What was done, step by step
| Step | Result | Commit |
|---|---|---|
| (prep) Demo data seeder, screenshot script, "before" screenshots | done | c49357d |
| 1. Design tokens (`ui/theme.py`) and a contrast checker | done: colours (light and dark), Segoe UI + Consolas, 12/14/16/20/28/40 scale, 4 px spacing, radii, 120/200/320 ms; 72 text/background pairs all reach 4.5:1 (34 reach 7:1) | edba823 |
| 2. Tokens applied everywhere | done: no screen writes a hex colour or a font any more; a test fails if one does | b112996 |
| 3. Uniform components | done: cards, four buttons (primary, secondary, ghost, danger), form fields, page header (title, subtitle, primary action on the right) on every screen, "More" menu component (no screen needs it yet), stock mint widgets recoloured, pagers restyled | 6f530a0 |
| 4. Hover and click transitions | done: about 120 ms fades on buttons, sidebar items, clickable cards and table rows; short press effect; pointer cursor; `CHAMPION_REDUCE_MOTION=1` turns it all off; cancelled when a screen closes | 1a8f992 |
| 5. Loading, toasts, welcome | done: grey skeleton rows while tables load, stacked toasts with a thin timer bar at the top right (clear of the primary button), "Welcome back, <name>" after login; confirmation dialogs untouched | 65d2fcb |
| 6. Splash and intro | done: about 1.5 s splash, 4-slide first-launch intro (Next/Back/Skip, dots, arrow keys, "Don't show again"), replay and reset in Help > About | 65d2fcb (steps 5 and 6 share one commit) |
| 7. Dashboard tidy | done: five (Admin) or four (Staff) identical KPI cards, count-up, one Matplotlib style from the tokens, figures closed, every Phase 4 card kept, Staff still see no Admin card | 7487ec4 |
| 8. Dark/light switch | **skipped on purpose** (would look broken; see DOC_SYNC section R) | none |
| 9. Demo data and setup guide | done: `scripts/seed_demo_data.py` (champion_demo only), `scripts/run_demo.py`, `docs/DEMO_SETUP.md` with a 12-minute walkthrough | c49357d (seeder), c5bfed1 (guide and launcher) |
| Docs | DOC_SYNC section R, KNOWN_ISSUES, hand-test checklist, this file | last commits on the branch |

## 2. Screenshots
`docs/screenshots/before/` (42 pictures) and `docs/screenshots/after/` (43 pictures), 1366 x 768, same demo data, Admin and Staff, every screen and tab. The "after" set was taken right after step 7; a re-capture on the last commit failed (PC screen locked, black pictures, discarded). Details in `docs/screenshots/README.md`.

## 3. Tests
**559 passed, exit code 0**, last full SERIAL run (11 min 47 s) on exactly the tree of commits 7487ec4 and c5bfed1. Commits after that only add documentation and screenshots. Every step above was committed after a full serial run of its own tree (515, 515, 524, 541, 559 tests). No test was deleted or skipped. See `docs/POLISH_LOG.md`.

## 4. What only you can check by eye (full list: "Polish branch checks" in `docs/HAND_TEST_CHECKLIST.md`)
1. Start `python scripts/run_demo.py` (after building the demo, see `docs/DEMO_SETUP.md`). *Expect:* a green splash with a yellow progress line for about 1.5 s, then the 4-slide intro, then login.
2. Finish the intro with "Don't show again" ticked, restart. *Expect:* no intro; Help > ℹ About > Replay brings it back.
3. Log in. *Expect:* a "Welcome back, <name>" toast at the top right that disappears after about 3 s and never covers the green "+ Add" button.
4. Move the mouse over buttons, sidebar items, the two clickable dashboard cards and table rows. *Expect:* smooth fades, hand cursor, no flicker.
5. Dashboard as Admin: five identical cards, numbers count up, Low Stock pink; as Staff: four cards, no ADMIN INSIGHTS.
6. Click through every screen and tab at 1366 x 768. *Expect:* title, subtitle and primary action on every page, nothing cut off.
7. Stand 2 m away. *Expect:* all main text readable.
8. Issue and return one tool (one unit Damaged). *Expect:* the same results as before the polish.
9. Set `CHAMPION_REDUCE_MOTION=1` in `.env`. *Expect:* no animation anywhere, everything still works.

## 5. Merging, or throwing it away
Nothing has been merged. To look at it: `git checkout ui/defense-polish`.

To keep it:
```
git checkout refactor/industrial-hardening
git merge --no-ff ui/defense-polish
```
To keep only the demo tooling (seeder, launcher, guide) and nothing visual: `git checkout refactor/industrial-hardening`, then `git cherry-pick c49357d c5bfed1`.

To throw it away: `git checkout refactor/industrial-hardening`, then `git branch -D ui/defense-polish`. Nothing else is affected (the commits stay recoverable through `git reflog` for a while). Your `.env`, your database and `refactor/industrial-hardening` are never touched by the polish branch.

## 6. Decisions I made on my own (all in `docs/DOC_SYNC.md` section R)
Steps 5 and 6 in one commit; step 8 not built; the font family changed from the uninstalled "Inter" to Segoe UI and the smallest text became 12 pt; darker status text and a slightly darker solid green so every pair reaches 4.5:1; yellow/blue/purple buttons became primary or secondary; the page header carries the primary action only on Inventory, Projects and Role Management, tab screens keep their tabs on the right; search boxes got an inside hint (CustomTkinter hides placeholders when a text variable is used); a stale "auto-pruned to 10,000 entries" label was corrected; a handful of success pop-ups became toasts (profile saved, user updated, ticket sent, restores from the archive) while issuance, return and registration confirmations stay as dialogs; the team list in the intro has names only, marked "(roles to be added)"; the demo uses its own database `champion_demo` and its own `.env.demo`.

## 7. Reverted or skipped, and why
Nothing was reverted. Skipped: the dark/light switch (see above). Not fully done: the last "after" screenshots (screen lock). The "More" menu exists but no screen has more than three secondary buttons, so it is not in use yet. Rare test flakes are listed in `docs/KNOWN_ISSUES.md`.
