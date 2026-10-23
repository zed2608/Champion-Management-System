# Project, inventory, and tool movement rules

These are the rules users should see in the Help Guide and the service layer enforces when saving. Use a test database for the examples in the hand-test checklist.

| Action | Requirement | If it fails |
| --- | --- | --- |
| Create a project | Admin; unique active name and client with letters; at least one required tool. Names such as `Phase 2` are valid. | The project is not saved. |
| Set project dates | Enter both dates as `YYYY-MM-DD` or neither. End must be the same day as, or later than, start. | The project is not saved. |
| Assign a worker | Employee ID must identify an active user; duplicate IDs are removed. | The project is not saved. |
| Request tools | Tool must be active. Equipment quantities are positive whole units; consumables may use up to two decimal places. A request can exceed available stock, but the actual issue must wait for stock. | The invalid line or issue is refused. |
| Issue a tool | The worker belongs to an approved or ongoing project whose end date has not passed. The tool has a linked tag, appears on that project's requirement list, has available stock and stays within the approved quantity currently out. A displayed condition can reflect another unit under repair; available units can still be issued. | No transaction or stock change is saved. |
| Return a tool | Returner holds an active transaction and quantity cannot exceed what is out. Good units go back to available stock. Damaged and repair units go to maintenance; lost units leave total stock. A non-Good condition needs details and creates an issue in the same database transaction. | No partial changes are saved. |
| Issue a replacement | Returning a tool frees its project's issued quota. The project must still be eligible and the stock must be available and usable. | The replacement is refused until the conditions are met. |
| Print a tool tag | A Tag ID must be assigned. Print selects tagged rows only; Select all applies to the current page. | An untagged row says `Tag first`; no label is printed. |
| Register or edit a person | A person's name uses letters, spaces and normal name punctuation, with no digits. A tool name, client or project name may include a number but must include letters. | Saving shows a field message. |

When changing a project's schedule, workers or tool requirements, keep in mind that those fields are locked after issuance starts. Archiving preserves movement history.
