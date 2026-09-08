# Local Business Lead Intelligence Engine

This fork of [CodePhantom-1/LeadPro-4](https://github.com/CodePhantom-1/LeadPro-4)
is becoming a Local Business Lead Intelligence Engine. Phase 3B adds a persistent
SQLite evidence worker to the hardened FastAPI and plain HTML/JS foundation.

**Local prototype, not production-ready.** The primary browser provider is the
separate official CamoFox REST service, behind a replaceable Python interface.
No full Playwright browser worker or Phase 3C features are implemented.

## Current V0.1 scope

- Dashboard, Lead Generation, Leads and Settings.
- U.S. category/city/state search, target 1–100, **Website Conversion Improvement**.
- Bounded Serper Maps, Google Places and Yelp discovery, with explicit shortfalls.
- Persistent jobs, restart recovery, owner-scoped progress and cancellation.
- Isolated browser audits: homepage, one contact/quote page, one about or services page.
- Rendered public business contacts and versioned evidence with source URLs.
- Five separate scores: opportunity, digital gap, business strength, evidence
  confidence and contact confidence. Unknown/blocked checks do not become gaps.
- Evidence details and formula-safe CSV export from normalized records.

Outreach, public sending, owner enrichment, billing and messaging remain disabled.
Retired routers are unmounted. Historical legacy leads remain preserved in their
original tables; active results and exports use the new evidence tables.

Read the [product contract](docs/V0_1_PRODUCT_CONTRACT.md),
[security foundation](docs/SECURITY_FOUNDATION.md),
[CamoFox setup](docs/CAMOFOX_SETUP.md) and
[Phase 3B architecture/scoring](docs/PHASE_3B_ARCHITECTURE.md).

## Run locally — LIVE

1. Start Docker Desktop.
2. Double-click `START_LOCAL.bat`.
3. Browser opens.
4. Run a real search.
5. Double-click `STOP_LOCAL.bat` when finished.

LIVE uses Google Places API (New), real private CamoFox, PostgreSQL and Redis.
It never silently falls back to fixtures. Missing configuration stops startup;
provider authorization/network errors fail the search visibly. Worker/browser
readiness is checked before discovery. Use `STATUS_LOCAL.bat` for service status.

The launchers load the existing ignored `.env` discovery key, then
`.local-integration/stack.env` production secrets (which take precedence).
`GOOGLE_PLACES_NEW_API_KEY` is preferred; the existing `GOOGLE_PLACES_API_KEY`
is accepted as the key for the **New** endpoint. This does not enable Legacy.
Mode selection is fixed by the launcher and Compose files, regardless of old
`DISCOVERY_MODE=offline` values in those environment files.

LIVE opens `https://localhost:8443`, reuses the existing PostgreSQL volume and
accounts, and runs Alembic before starting the API/worker. Sign in as `admin`
with the existing account password. Editing the bootstrap password does not
reset an existing account; use Settings > Change password while signed in.
Caddy's local CA may need browser trust; the launcher does not alter Windows
trust settings. See [Docker setup](docs/DEPLOYMENT_DOCKER.md).

`START_OFFLINE_TEST.bat` is only for fixture/regression testing. It uses a
separate project, PostgreSQL volume and `https://localhost:8444`, with an obvious
**OFFLINE TEST MODE — fixture data** banner and no paid discovery keys.
Stop it with `STOP_OFFLINE_TEST.bat`. Both STOP helpers preserve volumes.

`CLEAN_FIXTURE_DATA.bat` first displays counts, then requires `DELETE FIXTURES`
to remove positively identified fixtures and their related records in one
transaction. It preserves real data, users, sessions and security events.
Unclassified older history is retained and hidden from LIVE, never guessed to
be disposable. A private backup is recommended before maintenance.

## Legacy development setup (Windows PowerShell)

Python 3.11+ is required. Windows startup no longer depends on Unix file locking.
Run from the repository directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.template .env
```

Edit `.env` privately. Set INITIAL_ADMIN_PASSWORD to a unique password of at
least 12 characters (at most 72 UTF-8 bytes). Do not paste secrets into chat or
commit them. The first startup creates the `admin` account without printing the
password. Remove the bootstrap password from `.env` afterward. Without it, an
empty database starts with login unavailable until configured and restarted.

JWT_SECRET is optional; when blank a random persistent `.jwt_secret` is published
atomically. Protect that file and `.env` with your Windows account ACL. Explicit
JWT_SECRET values need at least 32 bytes. No default secret is hard-coded.

```powershell
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8000` and sign in. Startup needs no live API keys and makes
no external requests for a fresh idle database. Previously queued work resumes
automatically. Add a discovery key in `.env` or administrator Settings,
then restart before searching. Configure the separate browser service using
[CAMOFOX_SETUP.md](docs/CAMOFOX_SETUP.md). The app boots while the service is down;
browser-dependent items report browser_unavailable with unknown opportunity. PageSpeed is optional; OpenRouter is not required
for the active workflow. Review provider terms before using/storing results.

Use **one process, no reload**. `python app.py` binds loopback port 8000. For a
custom local port use `python -m uvicorn app:app --host 127.0.0.1 --port 8001`
from the activated environment; do not add multiple workers. Do not expose this
prototype publicly.

## Safe defaults

| Setting | Default / behavior |
| --- | --- |
| OUTREACH_ENABLED | false; true fails startup in this reduced release |
| PUBLIC_AUDIT_ENABLED | false; true fails startup |
| SCHEDULER_ENABLED | false; no active scheduled jobs even if changed |
| Active jobs | 1; persistent queue bounded to ten active requests per owner |
| CAMOFOX_MAX_BROWSER_CONCURRENCY | 2; hard cap 2 |
| CAMOFOX_MAX_PAGES_PER_BUSINESS | 3; configuration hard cap 4, current crawl uses at most 3 |
| CAMOFOX_REQUEST_TIMEOUT_SEC | 35; bounded 1–60 |
| CAMOFOX_PAGE_SETTLE_MS | 1200; bounded 0–3000 |
| AUDIT_SCREENSHOTS_ENABLED | false; ignored local artifacts only when enabled |
| DISCOVERY_MAX_PAGES_PER_PROVIDER | 3; bounded 1–5, with provider-specific lower caps |
| VERIFY_SSL | true; false fails startup |

Jobs are durable but not distributed. Closing a page does not cancel work; use
Cancel job. Server restarts recover unfinished items after lease expiry, preserving
completed items and audit history. JWTs still use localStorage and lack
password-change revocation. CamoFox is Firefox-based; production browser network
isolation and Chromium verification are not implemented.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall .
```

Tests use mocks and temporary fixtures; no email, mailbox access, messaging or
live discovery is required. Do not run retained legacy scripts as an alternative
entry point. Provider and worker tests use mocks; the live CamoFox test is skipped unless
RUN_CAMOFOX_INTEGRATION_TESTS=1. Local DOM fixture tests use installed Microsoft
Edge when available, otherwise skip. They do not visit external sites or replace
the CamoFox worker. No browser download is required for the mock tests.

An optional localhost-only UI smoke check uses an already installed Microsoft
Edge: `python tests/browser_smoke.py --artifact-dir <temporary-folder>`.
It starts an isolated test server/database, uses fixture data and checks desktop,
mobile, login, XSS rendering, CSV and form errors. It is not a crawler.

## Attribution and license

Based on LeadPro by CodePhantom-1. The original MIT grant and copyright notice
are preserved in [LICENSE](LICENSE): Copyright (c) 2025 LeadPro.
Third-party dependencies retain their own licenses. Phase 2/3A/3B instruction files
are local task inputs and are intentionally excluded from implementation commits.
