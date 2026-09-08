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

## Local configuration

Generate four independent random values (at least 32 random bytes encoded as
hex is suitable) for POSTGRES_PASSWORD, SESSION_SECRET, INITIAL_ADMIN_PASSWORD
and CAMOFOX_ACCESS_KEY. Put them in the ignored `.local-integration/stack.env`.
Never print or commit that file. Add the following nonsecret local settings:

```dotenv
DISCOVERY_MODE=offline
LOCAL_INTEGRATION_TEST=true
OFFLINE_ITEM_DELAY=2
```

The offline Google response and independent browser facts are built-in,
deterministic fixtures. Request bodies cannot select or override fixture URLs.
Leave the live Google key unset. The regular default is discovery disabled.

## Startup

Run from the repository root (PowerShell or a POSIX shell):

```text
docker compose --env-file .local-integration/stack.env -f compose.production.yaml build
docker compose --env-file .local-integration/stack.env -f compose.production.yaml up -d postgres redis
docker compose --env-file .local-integration/stack.env -f compose.production.yaml run --rm --no-deps api alembic upgrade head
docker compose --env-file .local-integration/stack.env -f compose.production.yaml run --rm --no-deps api alembic check
docker compose --env-file .local-integration/stack.env -f compose.production.yaml run --rm --no-deps api python -m lead_engine.admin
docker compose --env-file .local-integration/stack.env -f compose.production.yaml up -d --wait
docker compose --env-file .local-integration/stack.env -f compose.production.yaml ps
```

The explicit administrator bootstrap creates `admin` only if absent. It does
not reset an existing password. API startup never creates tables or runs migrations.

Only `https://localhost:8443` is published, bound to 127.0.0.1. Caddy uses its
internal CA; no public certificate is requested. PostgreSQL 5432, Redis 6379,
CamoFox 9377 and API 8000 have no host port mapping. Browser and data networks
are separate; the worker connects to both. Caddy/API connect through the edge
network. API/worker use UID 10001, read-only roots and /tmp tmpfs. CamoFox uses
the non-root node account, no profile volume, disabled plugins/telemetry/VNC,
and explicitly forced headless Firefox. Its official image still starts Xvfb;
the Firefox process itself has `-headless`.

Export the local CA for the strict HTTPS integration client:

```text
docker compose --env-file .local-integration/stack.env -f compose.production.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt .local-integration/caddy-root.crt
python scripts/validate_local_stack.py
python scripts/validate_local_stack.py --ui
python scripts/validate_local_stack.py --extras
python scripts/validate_local_stack.py --coordination
python scripts/validate_local_stack.py --secret-scan
```

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
docker compose --env-file .local-integration/stack.env -f compose.production.yaml exec -T postgres createdb -U leadpro phase4a2_tests
docker compose --env-file .local-integration/stack.env -f compose.production.yaml -f compose.test.yaml run --rm integration alembic upgrade head
docker compose --env-file .local-integration/stack.env -f compose.production.yaml -f compose.test.yaml run --rm integration
```

The database creation intentionally fails if the name already exists; reuse
only this known test database or choose another explicitly empty test DB.
The normal image excludes test dependencies; the named test target adds them.

## Shutdown

```text
docker compose --env-file .local-integration/stack.env -f compose.production.yaml down
```

This stops/removes the task's containers/networks and retains named database/CA
volumes. Do not use `down -v` unless deliberately deleting this test data.
Backups, logs, screenshots, runtime configuration and instruction files stay out
of Git and the production build context. See the integration report for results
and security limitations before any later deployment work.
