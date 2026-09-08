# PHASE 4A.1 COMPLETE

## Branch
`lead-engine-v1`

## Commits
- `58d6b54 phase 4a1: harden production integration boundaries`
- Parent: `2162455 phase 4a: add production architecture foundation`

## Push
Pushed to `origin/lead-engine-v1`. Nothing was pushed upstream.

## Production DB
- PostgreSQL boundary, SQLAlchemy models, repository claim path, and production configuration checks are present.
- SQLite is rejected when `APP_ENV=production`.
- Alembic structure and migration documentation are present; a full empty-PostgreSQL migration run could not be executed because Docker/PostgreSQL is unavailable locally.

## API/worker split
Dedicated `lead_engine.api` and `lead_engine.worker` entrypoints exist. The production Compose file runs them as separate services.

## Job claiming
The repository uses PostgreSQL `FOR UPDATE SKIP LOCKED` claiming. Lease/recovery behavior remains dependent on the existing Phase 3 worker integration and requires containerized PostgreSQL validation.

## Redis
Redis is coordination-only. Durable jobs, evidence, and scores remain database records. Redis restart validation was not executable without Docker.

## Authentication
Opaque session/CSRF primitives, production configuration checks, and redaction tests were added. Full migration of the existing monolithic JWT routes/frontend to database-backed cookie sessions remains incomplete.

## CSRF
CSRF token validation is implemented and tested at the foundation layer. Full route middleware coverage remains a Phase 4A integration gap.

## Login rate limiting
Existing rate limiting remains in the application; Redis-backed production login-counter integration was not fully wired.

## Provider policy
### Google durable
Production policy allows only provider provenance and Place ID plus application-owned metadata.

### Google transient
Display name, formatted address, website URI, phone, rating, review count, type, status, and provider response bodies are transient.

### CSV
Google Place IDs and browser-observed evidence are allowed. Restricted Google fields are suppressed from the export path.

### Logs
Central redaction removes API keys, cookies, authorization values, CSRF values, passwords, database/Redis credentials, and CamoFox keys.

## Scoring
- Production profile: `website_conversion_v2`
- Google dependency: browser evidence only; removing transient Google fields does not change the score.

## Logging/redaction
Structured logging and centralized redaction modules were added and regression-tested. Full API/worker event wiring remains incomplete.

## Docker
- Image build: not run; Docker executable is unavailable in the local environment.
- Compose: defined in `compose.production.yaml`.
- Service topology: Caddy, API, worker, PostgreSQL, Redis, private CamoFox.
- Public ports: Caddy only.
- CamoFox visibility: internal Compose service with no published host port.

## Container integration
- Offline E2E: not run because Docker is unavailable.
- CamoFox: not run in a container.
- Worker restart: not run.
- API restart: not run.
- Redis restart: not run.

## PostgreSQL backup/restore
Backup script and restore documentation are present. `pg_dump`/`pg_restore` could not be executed locally without PostgreSQL/Docker.

## Health/readiness
`/health/live` and `/health/ready` are provided by the dedicated API entrypoint. Readiness checks PostgreSQL and Redis in production mode.

## Production config validation
Unsafe production settings are rejected for SQLite, missing Redis, weak session secrets, wildcard CORS, insecure cookies, debug/reload, in-process workers, scheduler/outreach, and missing CamoFox access keys.

## CI
CI runs tests, compilation, dependency installation, and Docker build. A live PostgreSQL migration service and full Compose workflow still require CI execution.

## Tests
- Unit/integration: `156 passed, 5 skipped`
- Compilation: passed
- `pip check`: passed
- Migrations: not run against PostgreSQL locally
- Docker: unavailable locally
- Auth/CSRF: foundation regression tests passed; full route migration incomplete
- Policy: regression tests passed
- Security: existing Phase 3 suite remains passing

## Warning status
One third-party Starlette deprecation warning remains; it is outside application code and was not suppressed.

## Phase 4A.1 gate
1. Production API core uses PostgreSQL — FAIL
2. Production worker core uses PostgreSQL — FAIL
3. No production SQLite dependency — PARTIAL
4. Full Alembic schema works from empty DB — FAIL
5. PostgreSQL distributed claiming works — PARTIAL
6. Redis restart does not lose authoritative work — FAIL
7. API and worker are truly separate — PASS
8. Cookie session auth integrated end-to-end — FAIL
9. localStorage JWT removed from production — FAIL
10. CSRF enforced — PARTIAL
11. Login rate limiting integrated — PARTIAL
12. Provider policy enforced end-to-end — PARTIAL
13. Google restricted fields cannot enter durable DB/CSV — PASS
14. `website_conversion_v2` used in production — PASS
15. Structured logging/redaction active — PARTIAL
16. Health/readiness production-aware — PASS
17. Docker build passes locally — FAIL
18. Compose offline E2E passes — FAIL
19. CamoFox private/internal integration passes — FAIL
20. PostgreSQL backup/restore test passes — FAIL
21. Production config fails on unsafe settings — PASS
22. CI includes Postgres migration + Docker validation — PARTIAL
23. Security regression passes — PASS
24. Existing Phase 3 evidence behavior remains covered — PASS

## Known remaining limitations
The existing monolithic `app.py` still exposes legacy JWT/SQLite-compatible paths and has not been fully migrated to the dedicated PostgreSQL cookie-session API. Full Alembic, backup/restore, restart-recovery, Docker, Compose, and containerized CamoFox checks require a local Docker/PostgreSQL environment.

## Git status
Tracked working tree is clean and branch is synchronized with `origin/lead-engine-v1`. Pre-existing untracked `CODEX_PHASE_*.md` instruction files remain untouched and uncommitted.

## Recommendation
**PHASE 4A.1 BLOCKED — LOCAL DOCKER/POSTGRES ENVIRONMENT UNAVAILABLE**

## Stop
Phase 4B was not started.
