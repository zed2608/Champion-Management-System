# ABC, Physical Cycle Count, and Off-Site Backup Policy

## 1. Approved ABC definition

Champion uses a **rank-based ABC rule** for the period selected in Reports:

| Class | System rule | Physical count frequency |
|---|---|---|
| A | First `ceil(20% × N)` active items, ranked by quantity issued | Every two weeks |
| B | Next items through `ceil(50% × N)` | Every three months |
| C | Remaining active items | Twice a year |

`N` is the number of active inventory items. An item with no issuance during the selected period is always Class C. Archived items are not ranked, although their transactions remain in historical usage totals.

This project does **not** define A as the first 70% of cumulative usage. That is a different valid method. The system, Help Guide, report labels, tests, and documentation use the 20% / 30% / 50% rank rule consistently.

## 2. Physical cycle-count procedure

1. An Admin records the current ABC list before the count begins.
2. A counter identifies each item by Product ID and Tag ID, then records the location, system quantity, physical quantity, date, and counter.
3. Count deployed quantities from open issuance records and maintenance quantities from open maintenance records. Do not count them as warehouse stock.
4. Recount every difference. Check recent issuance, retrieval, maintenance, archive, and stock adjustment records.
5. Record the reason when known, such as an unrecorded return, wrong unit, damaged stock, misplaced stock, or data-entry error.
6. An Admin reviews and approves any correction. Keep the original count evidence and reason.
7. Route damaged or worn items through Retrieval or Maintenance. Do not silently change Inventory.
8. Management reviews repeated differences by item, location, and user and assigns corrective action.

The software supports the count with records and reports. It cannot physically detect theft, wear, or an item placed in the wrong location.

## 3. Encrypted off-site backups

New backups created from Maintenance use an encrypted `.cftbak` file. AES-256-GCM protects the data, and scrypt derives the encryption key from the passphrase. A changed file or incorrect passphrase is rejected before the database is overwritten. Older verified `.sql` backups remain restorable for migration, but new off-site copies must use `.cftbak`.

### Required operating procedure

1. Create a backup after important data changes and at least weekly during active use.
2. Use a unique passphrase with at least 12 characters.
3. Keep one encrypted copy away from the computer and building that host the live database.
4. Verify the file name, date, size, and SHA-256 checksum in Backup History.
5. Test a restore to a separate test database at least monthly and record the result.
6. Keep recent generations so one damaged or overwritten backup does not remove every recovery point.

### Key custody

- The system does not store or log the backup passphrase.
- The primary custodian is the authorized system administrator. A management representative is the second custodian.
- Store recovery details in an approved password manager or a sealed record held by management.
- Never place the passphrase in the file name, Backup Note, source code, `.env`, chat, email, or the same drive or folder as the backup.
- Update the controlled record when responsibility changes.
- A lost passphrase cannot be recovered. Without it, an encrypted backup cannot be restored.

The automatic safety copy created immediately before a restore remains a local SQL file for rapid rollback. Restrict that folder to the application host and do not use it as the off-site copy.
