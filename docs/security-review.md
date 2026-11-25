# Security review and maintenance boundaries

The initial commit included a real-looking database password in .env and comments in .env.example. Both are removed from the current branch. Treat the credential as exposed: the database owner must revoke/rotate it and inspect logs. Git history and external copies are unaffected. No connection to the original database was made. Keep the repository private until authorized to publish. Existing account passwords are not modified; first-admin initialization is opt-in.

The base schema is not a verified full migration chain. Legacy db_patch*, db_upgrade, fix_db and migration scripts remain unchanged; they can alter schemas or copy records, so do not run them on production. The desktop application currently performs some schema checks during startup, and role enforcement depends on client behavior. Test with a disposable database before using real inventory. Review permissions, transaction boundaries, concurrent stock updates, PDF/QR workflows and audit retention separately.

TLS verification is required for non-loopback database hosts. Provide a CA bundle matching the intended MySQL server and connect using a certificate-matching hostname. This may require LAN server configuration. No live service was contacted.
