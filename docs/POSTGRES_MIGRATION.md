# PostgreSQL migration and production boundary

Production uses SQLAlchemy 2 with psycopg 3 and a cached pool per process
(pool_size=5, max_overflow=2, pre-ping enabled, recycle=300s, connect timeout=3s).
API and worker set distinct PostgreSQL application names. Transactions are short;
no discovery or browser operation runs inside a database transaction.

`DATABASE_URL` must use PostgreSQL. There is no SQLite URL fallback in
`production_db.py`. The legacy `app.py` refuses APP_ENV=production before it
imports legacy configuration/storage. Pure browser helpers were separated into
`engine_utils.py` so production imports do not load SQLite at all.

## Explicit Alembic history

The historical `0001` scaffold remains a no-op; `0002_production_core.py`
contains explicit create-table/index/foreign-key/unique-constraint operations.
`alembic/env.py` uses Alembic's transaction and migration context. There is
no `Base.metadata.create_all()` production path.

Run the commands in [DEPLOYMENT_DOCKER.md](DEPLOYMENT_DOCKER.md). Empty-database
upgrade was executed against real PostgreSQL for both the application and
separate regression databases. `alembic check` returned no drift.

The schema contains users, sessions, security_events, search_jobs,
search_job_items, businesses, provider_refs, audit_runs, audit_pages,
audit_evidence, business_contacts, lead_scores and browser_cleanup, plus the
Alembic version table. Timestamps are timezone-aware. Foreign keys and lookup
indexes link the core records; unique constraints protect usernames, owner/provider
references, job/business items, item/audit runs, audit/scores and audit contacts.
Provider references have no arbitrary JSON payload column.

Readiness compares the database revision with the current Alembic script head.
An old/missing schema returns HTTP 503. API/worker startup refuses an old schema;
neither process migrates implicitly. The integration suite changes only the
version marker temporarily, verifies readiness/startup refusal, and restores it.

## Claims and recovery

Claims use `FOR UPDATE SKIP LOCKED`, then persist a random lease token,
12-second expiry, heartbeat and attempt count. Every durable completion checks
the current unexpired token while locking the job. Stale owners cannot commit.
Heartbeat renews once per second during browser work. Audit/score writes and
item completion commit together. Completed items are skipped on recovery.

Redis provides wakeup and renewable capacity-one job/browser semaphores.
Two PostgreSQL advisory locks also guard global capacity so a Redis restart
cannot grant overlapping capacity while an older worker still owns work.
Redis contains no authoritative jobs, sessions, contacts, evidence or scores.
This conservative local configuration intentionally permits one job/browser
at a time; it is not a throughput sizing claim.

Browser cleanup intent is stored before opening a remote tab. Worker recovery
retries pending cleanup before new discovery. Abrupt worker termination releases
its advisory connections; the durable job lease then expires and is reclaimed.
The SIGKILL integration test retained completed audit IDs and produced no
duplicate audit or score rows.

No Phase 3 SQLite records were copied into PostgreSQL.
