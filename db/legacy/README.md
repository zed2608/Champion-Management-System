# Retired schema scripts (history only - do not run)

These scripts built and patched the database before there was one canonical schema. Each one fixed a different gap, so
no single script produced a working database, and the views added more `CREATE/ALTER/DROP TABLE` at runtime.

| Script | What it did | Replaced by |
|---|---|---|
| `create_tables.py` | Base tables (but with `requirement_id`, no `status`, no archive columns, no `tool_issues`/`system_logs`) | `db/schema.sql` |
| `db_patch.py`, `db_patch_2.py`, `db_patch_3.py` | Added project/tool/transaction columns, `system_logs`, `tool_issues` | `db/schema.sql` + `db/migrate.py` (step 3 adds any missing column) |
| `db_upgrade.py` | More columns, `projects`, `project_requirements`, `issues_log` | same |
| `fix_db.py` | Added `transaction.project_id` and its FK | same |

## What to run instead

```
python -m db.migrate --status            # what is pending (changes nothing)
python -m db.migrate --dry-run           # same, listing the steps
python -m db.migrate --make-backup       # take a verified mysqldump, then upgrade (re-runnable; no-op when up to date)
python seed_admin.py                     # first Admin account on an empty database
```

`db.migrate` upgrades **any** of the old shapes in place without deleting rows, refuses to run without a fresh verified
backup, and never touches an Aiven host.

They are kept (not deleted) so the history is visible in `git log` and so a reviewer can compare what each patch did with
what `db/schema.sql` now declares. They import `database.get_connection` and will not run from this folder.
