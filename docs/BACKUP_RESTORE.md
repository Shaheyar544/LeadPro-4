# Local PostgreSQL backup and restore

Use `scripts/backup_restore.py` from the repository root with the running
Phase 4A.2 Compose stack. It invokes the Postgres container's pg_dump/pg_restore
over binary stdin/stdout pipes, avoiding PowerShell text corruption of custom
archives. Passwords are never passed on the command line or printed.

```text
python scripts/backup_restore.py backup .local-integration/manual.dump
python scripts/backup_restore.py restore .local-integration/manual.dump --database phase4a2_restore_manual
```

Backup uses exclusive file creation and refuses to overwrite a file. Restore
uses createdb and refuses an existing destination; names must match
`phase4a2_restore_*`. It restores with --exit-on-error, --no-owner and
--no-privileges. Do not restore into the running application database.

`python scripts/validate_local_stack.py --extras` performs a fresh backup and
restore and compares both row counts and canonical checksums for users, session
metadata, jobs, businesses, provider references, audits, pages, evidence, contacts,
scores and security events. It rescans every restored public table for restricted
synthetic Google values and verifies the Alembic head. See
[PHASE_4A2_LOCAL_INTEGRATION_REPORT.md](PHASE_4A2_LOCAL_INTEGRATION_REPORT.md)
for the observed result.

Archives live under ignored `.local-integration/`; no archive or database data
directory is committed. A dump contains sensitive user/session metadata and must
be treated as private. This local test does not establish off-host retention,
encryption, disaster recovery timing or production recovery objectives.

The POSIX helper `scripts/backup_postgres.sh` uses native PGHOST/PGPORT/PGDATABASE/
PGUSER/PGPASSFILE configuration and restrictive umask. It likewise refuses to
overwrite an existing file. Do not put a password-bearing connection URL in a
process argument. A real operational restore should revoke restored sessions
before reopening access; this validation only compared their hashed metadata.
