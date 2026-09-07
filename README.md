# Local Business Lead Intelligence Engine

This fork of [CodePhantom-1/LeadPro-4](https://github.com/CodePhantom-1/LeadPro-4)
is becoming a Local Business Lead Intelligence Engine. Phase 3A reduces and
hardens the original FastAPI, SQLite and plain HTML/JS application.

**Not production-ready. Playwright website analysis is not implemented yet.**
Phase 3B will add the isolated browser worker, rendered evidence, bounded
contact/about crawling, persistent jobs, scoring rewrite and discovery pagination.

## Current V0.1 scope

- Dashboard, Lead Generation, Leads and Settings.
- U.S. category/city/state search, 1-100 target results, with the
  **Website Conversion Improvement** opportunity profile.
- Existing Serper Maps, Google Places and Yelp discovery adapters.
- Bounded public HTTP HTML checks with SSRF/redirect protection.
- Observed website or explicit provider business emails; no guessed emails,
  Hunter/Clearbit enrichment or owner inference in active searches.
- Authenticated, owner-scoped in-process jobs and formula-safe CSV export.

Outreach and public sending are disabled by default and unavailable in this
release. Retained legacy routes are not mounted. No mail, mailbox, SMS, WhatsApp,
LinkedIn, campaign, proposal or public audit funnel is part of the active product.
Historical lead data is not rewritten; it can contain contacts from older code.
Current scoring and HTML findings are preliminary, not rendered DOM evidence.
Provider pagination remains limited, so searches may return fewer results than requested.

See the [product contract](docs/V0_1_PRODUCT_CONTRACT.md) and
[security foundation](docs/SECURITY_FOUNDATION.md) for exact policies and limitations.

## Local setup (Windows PowerShell)

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
no external requests. Add a discovery key in `.env` or administrator Settings,
then restart before searching. PageSpeed is optional; OpenRouter is not required
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
| MAX_CONCURRENT_TASKS | 1; concurrent excess returns retryable 429 |
| SCRAPE_THREADS | 2; bounded website checks per job |
| VERIFY_SSL | true; false fails startup |

Jobs are not durable or distributed. Closing a page does not cancel them;
server restarts lose progress and possibly buffered results. JWTs still use
localStorage and lack password-change revocation. These limits must be addressed
before production use.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall .
```

Tests use mocks and temporary fixtures; no email, mailbox access, messaging or
live discovery is required. Do not run retained legacy scripts as an alternative
entry point. Playwright remains a dependency for Phase 3B; no browser installation
is required for the current HTTP audit or the unittest suite.

An optional localhost-only UI smoke check uses an already installed Microsoft
Edge: `python tests/browser_smoke.py --artifact-dir <temporary-folder>`.
It starts an isolated test server/database, uses fixture data and checks desktop,
mobile, login, XSS rendering, CSV and form errors. It is not a crawler.

## Attribution and license

Based on LeadPro by CodePhantom-1. The original MIT grant and copyright notice
are preserved in [LICENSE](LICENSE): Copyright (c) 2025 LeadPro.
Third-party dependencies retain their own licenses. Phase 2/3A instruction files
are local task inputs and are intentionally excluded from implementation commits.
