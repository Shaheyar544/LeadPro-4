# Local production-like Docker validation

Phase 4A.2 is local only. Use branch `lead-engine-v1`. No VPS, public domain,
public certificate, billing or Phase 4B deployment is configured.

## Prerequisites and tested versions

Windows Docker Desktop 4.89.0.238018, Linux/WSL 2 backend, Docker Engine/CLI
29.7.2, Compose v5.5.0. Tested services: PostgreSQL 16.15, Redis 7.4.11,
Caddy 2.8.4, CamoFox REST 1.14.0, Node 22.23.2, Camoufox 135.0.1 beta.24.
The CamoFox image digest is pinned in `docker/camofox/Dockerfile`; this
container browser binary differs from the prior Windows Phase 3 browser.

Run `docker --version`, `docker compose version`, `docker info` first.
If Docker is unavailable, stop and start/install Docker Desktop normally.
Do not use Windows containers.

## Local configuration and launch modes

Keep the existing private `.local-integration/stack.env` with POSTGRES_PASSWORD,
SESSION_SECRET, INITIAL_ADMIN_PASSWORD and CAMOFOX_ACCESS_KEY. For a new setup,
generate four independent random values (32 random bytes encoded as hex works).
Never print or commit them. Keep the Google key in the existing ignored `.env`:
`GOOGLE_PLACES_NEW_API_KEY` is preferred, with `GOOGLE_PLACES_API_KEY` accepted
for compatibility at the New endpoint only. The launchers load `.env` first,
then the production secret file. There is no default account password.

| Mode | Compose files | Project | PostgreSQL volume | URL |
| --- | --- | --- | --- | --- |
| LIVE | compose.production.yaml | leadpro-live | leadpro-phase4a2_pgdata (existing external volume) | https://localhost:8443 |
| OFFLINE TEST | compose.production.yaml + compose.test.yaml | leadpro-offline-test | leadpro-offline-test_pgdata | https://localhost:8444 |

Compose fixes LOCAL_RUN_MODE and discovery settings. LIVE uses Google New and
real CamoFox; OFFLINE TEST uses explicitly tagged fixtures and receives no Google
key. Existing offline flags in stack.env cannot change the LIVE launcher.
The live project adopts the existing PostgreSQL and Caddy volumes without
copying or deleting data. On a new machine, the launcher creates these named
volumes. Offline uses distinct database/CA volumes and session-cookie names.

## Startup

Start Docker Desktop, then `START_LOCAL.bat` for LIVE or
`START_OFFLINE_TEST.bat` for fixtures. They build the existing production image,
start PostgreSQL/Redis, run Alembic, bootstrap an absent admin, start all six
services, verify health and the Caddy CA, then open the default browser.
PowerShell 7 is preferred with Windows PowerShell 5.1 fallback. Compose 2.24.4+
is required for the offline port override; tested with v5.5.0.

The administrator bootstrap never resets an existing password. Use Settings
> Change password with the current password. API startup never creates tables
or runs migrations itself; the launcher runs the explicit maintenance command.
`STATUS_LOCAL.bat` shows the exact live project, files, volume and services.

Only `https://localhost:8443` is published, bound to 127.0.0.1. Caddy uses its
internal CA; no public certificate is requested. PostgreSQL 5432, Redis 6379,
CamoFox 9377 and API 8000 have no host port mapping. Browser and data networks
are separate; the worker connects to both. Caddy/API connect through the edge
network. API/worker use UID 10001, read-only roots and /tmp tmpfs. CamoFox uses
the non-root node account, no profile volume, disabled plugins/telemetry/VNC,
and explicitly forced headless Firefox. Its official image still starts Xvfb;
the Firefox process itself has `-headless`.

The launcher exports only the public local CA into the ignored integration
directory. To run the restart fixture regression harness, start
**OFFLINE TEST only**, then:

```text
python scripts/validate_local_stack.py
python scripts/validate_local_stack.py --ui
python scripts/validate_local_stack.py --extras
python scripts/validate_local_stack.py --coordination
python scripts/validate_local_stack.py --secret-scan
```

The harness is pinned to the offline project/port and checks mode before
submitting jobs. Do not redirect it at LIVE. Reports use offline-validation.json.

Use the repository virtualenv on Windows. The UI smoke requires installed Edge
and Playwright, runs headless, and trusts the local certificate only within its
test context. It does not change the OS trust store. The HTTPX suite verifies
the actual Caddy CA and hostname.

The harness restarts local services, tests revocation, restores the original
test password, and leaves additional synthetic records for inspection.
`--extras` runs backup/restore into a new database and the harmless example.com
browser smoke. It never calls a live discovery provider.
`--coordination` temporarily runs two workers, tests Redis restart with global
capacity one, and returns to one worker. `--secret-scan` scans candidate source
files with the pinned Gitleaks image; pull that image first if it is not cached.

## Regression image

```text
docker build --target test -t leadpro-phase4a2:test .
docker compose -p leadpro-offline-test --env-file .local-integration/stack.env -f compose.production.yaml -f compose.test.yaml exec -T postgres createdb -U leadpro phase4a2_tests
docker compose -p leadpro-offline-test --env-file .local-integration/stack.env -f compose.production.yaml -f compose.test.yaml run --rm integration alembic upgrade head
docker compose -p leadpro-offline-test --env-file .local-integration/stack.env -f compose.production.yaml -f compose.test.yaml run --rm integration
```

The database creation intentionally fails if the name already exists; reuse
only this known test database or choose another explicitly empty test DB.
The normal image excludes test dependencies; the named test target adds them.

## Maintenance and shutdown

`CLEAN_FIXTURE_DATA.bat` targets LIVE. It runs a dry run with counts only, then
requires exact `DELETE FIXTURES` confirmation. The transaction rechecks the
reviewed plan under short database locks and refuses active jobs/pending browser
cleanup or changed records. Mixed/unclassified history and all account/security
records are preserved. Use `-DryRun` to inspect without a prompt.

Before applying schema/data maintenance, make a private backup:

```text
python scripts/backup_restore.py backup .local-integration/before-maintenance.dump
python scripts/backup_restore.py restore .local-integration/before-maintenance.dump --database phase4a2_restore_review
```

Restore always creates a new database and refuses to overwrite an existing one.
These commands explicitly target the live Compose project. Restore verification
in the offline harness explicitly targets the offline project instead.

`STOP_LOCAL.bat` stops LIVE; `STOP_OFFLINE_TEST.bat` stops OFFLINE TEST. Both
preserve every named volume. Never use volume deletion or pruning as fixture
cleanup. Logs, credentials, dumps, profiles, screenshots and instruction files
remain ignored/untracked. No public deployment or other phase is included.
