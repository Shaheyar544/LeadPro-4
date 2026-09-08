# PHASE 4A.2 COMPLETE

Validated on 2026-09-08 against the local Linux Docker stack on Windows.
All 31 local acceptance criteria passed. This report describes observed tests,
including their limits; it does not authorize or claim a public deployment.

## Branch

`lead-engine-v1` throughout. Starting commit: `17fd58820eb43b77e6138bfdc6ee0e079ad0b44c`.
The required prior Phase 4A/4A.1 commits were present. No other branch was modified.

## Commits

- `94cb68cac84d68d5f1871dea5068bedc3960381e` — `phase 4a2: validate local production stack`.
- `3cded64ff3f057890264c793b79d59702d49c3c7` — `ci: update deprecated action runtimes`.
- This report is recorded separately by `docs: record phase 4a2 local integration results`; its hash is available in this file's Git history and the completion response.

The integration commit replaces incomplete production entrypoints and migration
stubs with exercised PostgreSQL repositories, cookie routes, durable workers,
v2 scoring, private browser configuration, and reproducible validation tooling.
Legacy Phase 3 behavior remains covered; its production import boundary is closed.

## Push

Code commits were pushed using only `git push origin lead-engine-v1` to
`https://github.com/Shaheyar544/LeadPro-4.git`. The report follows on the same
branch. Nothing was pushed to `upstream` or any other branch. No force push.

## Docker

| Component | Tested version/result |
| --- | --- |
| Docker Desktop | 4.89.0.238018 |
| Docker Engine / CLI | 29.7.2 |
| Docker Compose | v5.5.0 |
| Runtime | Linux containers, WSL 2, kernel 6.18.33.2-microsoft-standard-WSL2 |
| Resources visible to Docker | 24 CPUs; 15.49 GiB RAM |
| Production Python | 3.12.14 |
| Production image | Build PASS; non-root UID 10001; separate test target |
| Runtime startup | All six services healthy, including after the final rebuild |

Docker installation and daemon availability were checked first. The sandbox
initially denied the Docker named pipe; an approved daemon check succeeded.
Docker was already installed, and no installation or runtime replacement was needed.

## Compose services

| Service | Tested behavior |
| --- | --- |
| Caddy 2.8.4 | Local HTTPS with internal CA; API reverse proxy; healthy |
| API | Cookie/CSRF routes and PostgreSQL reads/writes; external worker only; healthy |
| Worker | PostgreSQL claims, Redis coordination, browser preflight/audits/cleanup; healthy |
| PostgreSQL 16.15 | Durable named volume, real migrations and transactions; healthy |
| Redis 7.4.11 | Ephemeral coordination and rate limiting; restart recovery; healthy |
| CamoFox REST 1.14.0 | Pinned derived private container, non-root/headless; healthy |

API/worker have read-only roots, /tmp tmpfs, dropped capabilities and
no-new-privileges. CamoFox has no profile volume or Docker socket mount.
The API never runs discovery, a browser audit, or an in-process job worker.

## Port exposure

Only `127.0.0.1:8443 -> Caddy:443` was published. API 8000, PostgreSQL 5432,
Redis 6379 and CamoFox 9377 had **no host mappings**. The edge, internal data,
and browser networks separate service access. Caddy exposes no CamoFox route.
No public certificate, domain, firewall opening or external listener was added.

## PostgreSQL

- PostgreSQL **16.15**, psycopg **3.3.5**, SQLAlchemy **2.0.52**, Alembic **1.19.2**.
- `alembic upgrade head` succeeded on the initially empty application database and a separate empty regression database. Current revision: `0002_production_core`.
- Migration 0002 explicitly creates 13 application tables, indexes, foreign keys and uniqueness constraints. The version table brings the public table count to 14. `alembic check` and metadata comparison reported no drift.
- Rollback and foreign-key rejection were exercised against real PostgreSQL. No `Base.metadata.create_all()` startup shortcut remains.
- Both actual production containers imported without `sqlite3`, `database`, `engine_store`, legacy `config`, or `app`. API and worker use the PostgreSQL pool, with role-specific application names.
- Production rejects SQLite/missing database URLs. No SQLite DB, legacy JWT secret, or local .env file was present in the application image. Existing development data was not imported, overwritten or deleted.
- Pools use pre-ping, bounded connections and reconnect behavior; API errors omit SQL parameters.

## Authentication

The existing frontend uses an opaque `__Host-leadpro_session` cookie with
**Secure, HttpOnly, SameSite=Strict, Path=/** and an eight-hour expiry.
PostgreSQL stores its SHA-256 fingerprint, never the raw session identifier.
The HTTPS integration client verified the exported local Caddy CA and hostname.

Login, authenticated reads, reload, job creation and CSV export passed through
the production routes. Browser checks found empty localStorage/sessionStorage,
no readable session cookie and no bearer authorization on production requests.
Legacy development compatibility uses a memory-only token selected by its
explicit development mode endpoint.

Logout invalidated the previous cookie. Password change revoked every prior
session, including a second active login; the synthetic test password was restored.
Sessions survived API and Redis restarts because PostgreSQL owns session state.

## CSRF

Missing, invalid, cross-session and foreign-origin mutation requests were
rejected. Valid session-bound HMAC tokens permitted job creation, cancellation,
logout and password change. Safe GET requests worked without CSRF headers.
Tokens remain in page memory. Provider settings also enforce authentication and
CSRF, then return 403 because production settings are environment-only.

## Redis

Redis supplies token-owned job/browser capacity leases, wakeups and a fixed
login-attempt window. PostgreSQL supplies authoritative jobs, sessions and results.
Redis loss cannot erase those records. PostgreSQL advisory locks preserve the
capacity-one constraint while Redis keys disappear and are reacquired.

A real Redis restart during an active job preserved its single claim and eventual
completion. A separate test ran **two worker containers**, restarted Redis with
both coordination keys present, and observed at most one active job. Both
five-item jobs finished with one claim each. The stack was returned to one worker.

Five login failures were followed by 429 despite spoofed X-Forwarded-For and
client-IP headers. A successful login after the actual 60-second expiry proved
recovery. Caddy overwrites the trusted client header; Uvicorn proxy parsing is off.

## Jobs

Claims use `FOR UPDATE SKIP LOCKED`, bounded leases, heartbeat renewal and
token checks before writes. A real second PostgreSQL connection skipped a locked
job; an expired lease was reclaimed and the stale worker's write was rejected.

SIGKILL during a five-item job caused lease recovery after worker replacement.
Already completed audit IDs remained unchanged; no duplicate audit runs or
scores appeared. Unique constraints and completed-item checks protect retries.
API restart left the worker running and durable progress reconnectable.
Cancellation and recoverable browser cleanup intents also survived the exercised paths.

## CamoFox

- REST **1.14.0**, Node **22.23.2**, bundled Camoufox **135.0.1 beta.24**.
- Upstream image pinned to `sha256:86c79eed8a6b3a78859f73bc70d6003c5566b85e969354ec454524b28197ffce`.
- Derived image forces headless launch and asserts the pinned source contract. Actual Firefox `-headless`, non-root execution and disabled interactive/VNC/persistence/telemetry settings were inspected. Upstream still starts Xvfb.
- A real worker-side open/evaluate/close of `https://example.com` passed. Final service counters were **0 active tabs, 0 active sessions**.
- Direct private/loopback/link-local/metadata/internal-service/file/socket targets were rejected. Data/API service aliases did not resolve from the browser network. No published browser port or Caddy browser proxy was found.
- Stopping CamoFox made the worker unready and left queued jobs unclaimed, with zero discovery attempts. API readiness remained available; queued cancellation worked. Browser restart resumed work.
- Log hardening excludes raw navigation URLs, errors and session identifiers while retaining static diagnostic events. The complete egress limitation is documented below.

## Provider policy

Only the allowlisted Google provider identifier and place ID are durable provider
data. Search category/location remain user-supplied job context. Display name,
address, website hint, phone, rating, review count, type and status are transient.
Only a navigation hint reaches AuditEngine; successful browser observations have
their own provenance. Failed-navigation hints are excluded from durable page data.

Eight distinguishable synthetic restricted fields traversed the production
discovery/worker boundary. Scans of **all 14 PostgreSQL tables**, exported CSV,
all six container logs, and the restored database found **zero sentinel values**.
CSV retained independently observed URL/phone/email, evidence, v2 score and
confidence, provider ID, and user search context; formula-like cells were escaped.
No live Google credentials or customer data were involved.

Structured-log fixtures also tested fake provider, database, Redis, browser,
password, cookie and CSRF secrets. A real Caddy upstream error initially revealed
a CSRF header; removing the complete request object from global Caddy logging
fixed it. A forced 502 retained the connection diagnostic while excluding the
query secret, cookie and CSRF token. Affected test sessions were revoked.
Security events covered login success/failure, logout, password change, job
creation and cancellation without secret/request payloads.

## Scoring

Production writes **website_conversion_v2** from allowlisted browser findings.
Changing all Google transient fields leaves the score unchanged. Unknown or
blocked evidence is not counted as absence; insufficient evidence yields an
unscored result with explicit confidence. Historical v1 scoring remains separate.

## Offline E2E

The explicit local integration mode uses deterministic Google-shaped responses
and independently defined browser facts; no request can override fixture URLs.
Cookie login -> CSRF-protected job -> external worker -> PostgreSQL browser
evidence/contacts/v2 -> job results/detail -> CSV -> logout passed.
This exercises the real API, Redis, PostgreSQL, worker and AuditEngine; the
offline BrowserProvider is a fixture. Real CamoFox was tested separately above.

Headless Edge verified desktop 1280x900 and mobile width 390, reload/session
restoration, job progress, evidence, CSV download and logout with zero JavaScript
errors. The scoped browser test accepted the local certificate only in its test
context; it did not alter the OS trust store or relax the application's CSP.

## Optional live smoke

Live Google discovery was deliberately **SKIPPED**. No paid provider request or
50-business run occurred. The separate harmless example.com browser smoke passed.

## Backup/restore

`pg_dump` custom format produced a **125,148-byte** private backup. Binary-safe
pipes and the container's environment kept database passwords out of command
arguments and Git. Restore used `pg_restore --exit-on-error` into a newly created,
separate empty database; no existing database was replaced.

| Restored table | Rows at backup |
| --- | ---: |
| users | 1 |
| sessions | 1 |
| search_jobs | 19 |
| businesses | 5 |
| audit_runs | 48 |
| audit_pages | 48 |
| audit_evidence | 1440 |
| business_contacts | 96 |
| lead_scores | 48 |
| provider_refs | 5 |
| security_events | 72 |

Counts and canonical row checksums matched the source snapshot, schema revision
remained 0002, and the entire restored database contained no restricted provider
sentinels. Subsequent tests may add synthetic records to the source database.

## Health/readiness

Liveness stayed 200 during dependency failure. API readiness returned 503 for
stopped PostgreSQL, stopped Redis and an intentional migration mismatch; normal
readiness returned after recovery. Actual DB-dependent requests and login during
Redis loss returned generic 503 responses. Schema mismatch also prevented API
startup. Worker readiness checked PostgreSQL, Redis and CamoFox separately.

## Production config validation

Nineteen unsafe configurations were rejected in tests and actual containers:
missing/non-PostgreSQL storage, absent Redis, weak/default secrets, insecure
cookies, wildcard CORS, debug/reload, in-process workers, scheduler/outreach,
missing/unsafe browser configuration, interactive/VNC/persistence/telemetry, and
unsupported discovery policy. Offline mode requires an explicit local opt-in.
This phase fixes the allowed application origin to `https://localhost:8443`.

## CI

[Integration CI run 34237971973](https://github.com/Shaheyar544/LeadPro-4/actions/runs/34237971973)
passed on commit 94cb68c: PostgreSQL/Redis services, empty-DB migration, Alembic
drift check, compilation, dependency check, JavaScript syntax, pytest, production
Docker build and redacted Gitleaks scan. Result: **177 passed, 9 skipped,
1 warning, 143 subtests passed**, in 25.14 seconds.

Action runtime deprecations discovered in that run were addressed using the
official [checkout](https://github.com/actions/checkout),
[setup-python](https://github.com/actions/setup-python) and
[setup-node](https://github.com/actions/setup-node) v7 actions. Checkout does not
persist credentials; unused package-manager caching is disabled. The follow-up
[CI run 34238672833](https://github.com/Shaheyar544/LeadPro-4/actions/runs/34238672833)
also **passed** on commit 3cded64: 177 passed, 9 skipped, 1 warning and 143
subtests in 24.22 seconds. Node runtime and punycode warnings were absent;
the documented upstream Starlette warning remained. Gitleaks found no leaks.

CI uses only disposable service credentials/configuration, read-only repository
permissions, and no production secrets. PostgreSQL trust authentication is limited
to the fresh isolated CI service, never the local production Compose service.

## Tests

| Validation | Result |
| --- | --- |
| Windows pytest | 177 passed, 9 skipped, 1 warning, 143 subtests; 36.02 s |
| Linux test image with real PostgreSQL | 177 passed, 9 skipped, 1 warning, 143 subtests; 21.54 s |
| Dedicated real PostgreSQL regression suite | 4 passed |
| New configuration/scoring/redaction tests | 21 passed |
| Full compileall; local/container pip check; JS syntax | PASS |
| Empty migrations; Alembic check; metadata/FK/rollback | PASS |
| Production Docker build; Compose startup/health | PASS |
| HTTPS auth/session/revocation; CSRF; rate limit | PASS |
| Offline API/worker/evidence/CSV and browser UI | PASS |
| Provider DB/CSV/log/restore scans | PASS |
| Redis/API/worker restart; two-worker coordination | PASS |
| Real CamoFox/private exposure/cleanup/outage | PASS |
| Security regressions and Gitleaks | PASS; no secrets found |
| Existing Phase 3 detector, browser, evidence and policy suites | PASS |

Skip counts are platform/opt-in differences: Windows omits the four real-PG
tests, Linux omits four Windows Edge DOM tests; five optional live tests are
skipped in both. The separate production Edge smoke passed on Windows. Counts
must not be summed as independent tests across environments.

The remaining pytest warning was inspected: current Starlette 1.6.0's test
client imports AnyIO 4.15.1's deprecated BlockingPortal alias. It is an upstream
test-client import, not an application failure, and was not blindly suppressed.
Container build-time root-pip notices do not describe runtime privileges.
Ephemeral CI service notices include trust authentication and Redis host memory
overcommit; no host-wide sysctl change was made for this local task.

## Resource observations

One `docker stats --no-stream` sample during an offline job:

| Service | Memory | CPU |
| --- | ---: | ---: |
| Caddy | 15.68 MiB | 1.62% |
| API | 81 MiB | 0.09% |
| Worker | 120.4 MiB | 65.23% |
| PostgreSQL | 52.4 MiB | 2.83% |
| Redis | 6.625 MiB | 0.29% |
| CamoFox | 317.8 MiB | 1.55% |

Later memory observations were API 79.01 MiB, worker 63.65 MiB and CamoFox
218 MiB. These are local snapshots, not a live-browser load benchmark or a
production sizing/availability guarantee. Global job/browser concurrency is one.

## Phase 4A.2 gate

| # | Criterion | Result |
| ---: | --- | --- |
| 1 | Docker installed/running | PASS |
| 2 | Production Docker image builds | PASS |
| 3 | Compose stack starts | PASS |
| 4 | PostgreSQL healthy | PASS |
| 5 | Redis healthy | PASS |
| 6 | CamoFox healthy/private | PASS |
| 7 | Alembic empty-DB upgrade works | PASS |
| 8 | Production API uses PostgreSQL only | PASS |
| 9 | Production worker uses PostgreSQL only | PASS |
| 10 | No production SQLite connection | PASS |
| 11 | API/worker separation proven | PASS |
| 12 | Distributed job claim/recovery works | PASS |
| 13 | Redis restart preserves authoritative job data | PASS |
| 14 | Cookie-session auth integrated | PASS |
| 15 | No production localStorage JWT | PASS |
| 16 | CSRF integrated | PASS |
| 17 | Login rate limiting works | PASS |
| 18 | Provider policy enforced end-to-end | PASS |
| 19 | Restricted Google fields excluded from tested DB/CSV/log paths | PASS |
| 20 | website_conversion_v2 is production score | PASS |
| 21 | CamoFox cleanup passes | PASS |
| 22 | CamoFox outage safely pauses browser work | PASS |
| 23 | API restart safe | PASS |
| 24 | Worker restart safe | PASS |
| 25 | Backup passes | PASS |
| 26 | Restore passes | PASS |
| 27 | Readiness/liveness works | PASS |
| 28 | Production config fail-fast works | PASS |
| 29 | CI production checks present | PASS |
| 30 | Security regressions pass | PASS |
| 31 | Existing Phase 3 evidence behavior remains covered | PASS |

## Known remaining limitations

1. Application URL checks and network separation do not intercept every browser subresource, intermediate redirect or DNS rebinding. A hostile public page could attempt private, Docker-host or metadata access through browser egress. Per-request egress enforcement is required before public/untrusted staging. Section 23 permits explicit documentation of this residual risk; complete SSRF isolation is not claimed.
2. The pinned official container bundles Camoufox 135.0.1 beta.24, different from the prior Windows browser. Its security-patch currency must be reviewed and the browser updated/revalidated before public use.
3. Live Google quota behavior, paid credentials, public TLS, VPS operation, load/HA, key rotation, off-host backup retention and recovery-time objectives were not validated.
4. Capacity is intentionally one. Production provider settings are environment-only. No billing, multi-tenancy, scheduler or outreach was introduced.
5. The upstream Starlette test-client deprecation remains visible. Local generated credentials, screenshots, logs, CA and backups are intentionally private and ignored by Git.

## Git status

All code and supporting documentation changes are committed to the requested
branch. The 14 pre-existing untracked `CODEX_PHASE*.md` instruction files remain
untouched and excluded. No runtime secrets, database files, profiles or backups
are staged. The completion response records final report-commit synchronization.

## Recommendation

**READY FOR PHASE 4B — STAGING/VPS DEPLOYMENT**

All 31 Phase 4A.2 local gates passed. The explicit limitations above must inform
any separately requested staging work; this recommendation starts no deployment.

## Stop

Compose was cleanly stopped with `down` (without `-v`); a subsequent `compose ps`
returned no containers. Named database/CA volumes and ignored local backups
remain available for review. No public deployment, VPS/domain configuration,
billing or Phase 4B work was performed. Stop here.
