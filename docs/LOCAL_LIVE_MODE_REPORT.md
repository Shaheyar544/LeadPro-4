# Local live mode repair

## Root cause recorded before application changes

At commit `303bf4c`, START_LOCAL called the shared helper with production Compose,
project `leadpro-phase4a2`, and `.local-integration/stack.env`. That existing
validation environment selected `DISCOVERY_MODE=offline` and enabled local
integration fixtures. The worker consequently used OfflineGoogle and a mock
browser despite a healthy real CamoFox container.

OfflineGoogle identified its records as `google_places_new:phase4a2-place-1`
through `-5`. The repository persisted the mock browser's independently observed
name and fixture-business.test URL without durable run-mode metadata. Leads,
CSV and job projections filtered ownership but did not distinguish test data.

Read-only inspection of the existing PostgreSQL volume found five businesses,
all five with those exact fixture references and fixture observations; 20 jobs,
53 items/audits, 1,590 evidence rows, 106 contacts, 53 scores and 56 cleanup
intents (none pending). Even the recent HVAC/Phoenix search had used fixtures.
There was one user, two sessions and 87 security events. No live discovery was
performed during diagnosis.

The repair preserves this existing volume and accounts for LIVE, creates a
separate offline project/volume, and classifies only positively identified old
fixtures for deletion. Unclassified historical records are retained and hidden
until explicitly reviewed; they are never assumed safe to delete.

## Completed validation — 2026-09-08

Branch: `lead-engine-v1`. Implementation: `daf7d33`
(`dev: separate live and offline local launch modes`). This report is a separate
documentation commit. Delivery target is exclusively `origin/lead-engine-v1`
on the user's fork; the final response records both pushed commit IDs.

### Compose modes

| | LIVE | OFFLINE TEST |
| --- | --- | --- |
| Files | compose.production.yaml | compose.production.yaml + compose.test.yaml |
| Project | leadpro-live | leadpro-offline-test |
| PostgreSQL volume | leadpro-phase4a2_pgdata (existing external volume) | leadpro-offline-test_pgdata |
| URL | https://localhost:8443 | https://localhost:8444 |
| Discovery | Google Places API (New) | Explicit fixture provider |
| Audits | Real private CamoFox REST | Mock browser fixtures |
| Runtime mode | live | offline_test |

Both retain Caddy/API/Worker/PostgreSQL/Redis/CamoFox. PostgreSQL and Caddy
volumes are separate; Redis is ephemeral and project-local. The offline port
override replaces the published port. Only Caddy publishes a loopback port.
CamoFox remains private, headless, non-root, without persistence, telemetry,
VNC or cookie import; cleanup remains enforced.

### One-click files

- START_LOCAL.bat: fixed LIVE selection, production Compose only.
- STOP_LOCAL.bat: stops LIVE, preserves volumes.
- STATUS_LOCAL.bat: exact LIVE project/configuration/status.
- START_OFFLINE_TEST.bat: isolated fixture stack and visible banner.
- STOP_OFFLINE_TEST.bat: stops offline services, preserves volumes.
- CLEAN_FIXTURE_DATA.bat: dry run, exact confirmation, transactional cleanup.
- Shared scripts/local_stack.ps1, start_stack.ps1 and stop_stack.ps1, with
  mode-specific start/stop/status/cleanup wrappers under scripts/.

START validates Docker/Compose/Linux containers and configuration, builds,
starts PostgreSQL/Redis, runs Alembic and the idempotent admin bootstrap, starts
the stack, checks six healthy services plus CA-verified HTTPS 200, then opens
the default browser. Actual launches passed with PowerShell 7 and Windows
PowerShell 5.1 fallback. STOP/STATUS passed running and stopped checks.

### Fixture isolation

Alembic `0003` adds indexed, constrained run modes to jobs/businesses. New jobs
derive mode from runtime, never request fields. Known old fixtures become
offline; uncertain history becomes `legacy`, retained but hidden from LIVE.
Lists, details, CSV, statistics, job access/counts, worker claims and persistence
enforce mode boundaries. Job results select the requested job's audit/context.
New offline records use provider `fixture`. LIVE rejects fixture references,
navigation and browser output before persistence. Separate cookie names prevent
localhost ports from overwriting each other's sessions.

### Existing fixture cleanup

A private PostgreSQL backup preceded migration/cleanup. The tool dry-ran,
then accepted the exact `DELETE FIXTURES` confirmation authorized by this task:

| Table | Dry run | Deleted |
| --- | ---: | ---: |
| businesses | 5 | 5 |
| search_jobs | 17 | 17 |
| search_job_items | 53 | 53 |
| audit_runs | 53 | 53 |
| audit_pages | 53 | 53 |
| audit_evidence | 1,590 | 1,590 |
| business_contacts | 106 | 106 |
| lead_scores | 53 | 53 |
| provider_refs | 5 | 5 |
| browser_cleanup | 56 | 56 |

Candidate counts became zero. Three unclassified cancelled jobs remained.
User/session/security-event checksums were identical across cleanup. No real
businesses existed in the original database. Isolated PostgreSQL tests proved
preservation of mixed real/fixture data, fixture-looking live rows and unrelated
history. After the fresh search, another dry run selected zero rows and retained
all five real businesses.

Cleanup requires explicit offline provenance, reviewed-plan equality and a
single transaction with short locks. Active jobs, pending cleanup, changed plans
and mixed cross-mode relationships are refused or retained. Errors roll back;
users, sessions and security events are never deletion targets. No volumes were
deleted and no database was wiped.

### LIVE configuration and preflight

Google New, CamoFox, PostgreSQL, Redis and session secret: configured; no values
printed. Existing ignored `.env` supplies discovery credentials; the existing
ignored `.local-integration/stack.env` production secrets take precedence.
The generic existing Google key is accepted at the New endpoint only.
Legacy/Yelp/Serper were not used. Compose fixes mode independently of stale
offline flags in environment files.

API checks configuration, PostgreSQL/Redis and fresh worker/browser readiness
before queueing. Worker checks actual browser health immediately before
discovery. Google authorization is verified by the first requested page before
audits, avoiding another quota-consuming probe. Missing/unauthorized/disabled/
unreachable Google fails visibly, with terminal provider errors and no fixture
fallback. The New request now uses the requested page size: five here.

### Exactly one fresh five-business LIVE search

Roofing, Dallas, TX; website conversion; target five.
Job `20260908160005230868b48caef398f64b59b9a8e032b31a1bb4`.
Created 16:00:05 UTC; final audit persisted 16:01:11 UTC.
One provider page, one job claim, five requested/discovered/processed businesses.
Zero fixture/mock records. No additional discovery was submitted.

All five websites were independently opened and reviewed:

| Business/website | Audit | Pages | Evidence | Contacts | V2 score |
| --- | --- | ---: | ---: | ---: | ---: |
| [New View Roofing](https://newviewroofing.com/) | completed | 3 | 88 | 2 | 33.33 |
| [Priority Roofing, Dallas](https://priorityroofs.com/location/dallas/) | partial | 3 | 163 | 77 | 0 |
| [Arrington Roofing](https://arringtonroofing.com/) | partial | 1 | 30 | 2 | unknown |
| [T Rock Roofing](https://dallasroofer.com/) | partial | 3 | 90 | 4 | 0 |
| [Blue Hammer Roofing, Dallas](https://bluehammerroofing.com/areas-served/dallas/) | completed | 3 | 89 | 4 | 50 |

Requested 5; discovered 5; real 5; fixtures 0; audited 5; completed 2; partial 3;
failed 0; blocked 0. Four are assessable leads with observed websites, contacts,
evidence and numeric scores. This does not imply high commercial opportunity:
two have zero measured gap.

Arrington's secondary navigation failed; two assessed checks were below the v2
minimum of three, so its score remains unknown. Priority's contact page was
incomplete; T Rock's homepage hit the rendering deadline. Successful observations
remain, and failed/unknown checks are not represented as missing features.
Priority's 77 contacts come from its company-wide
[branch contact page](https://priorityroofs.com/contact-us), not just Dallas.

### Evidence, policy and Leads UI

Persisted: five Google New place references, five real CamoFox audits, 13 observed
pages, 460 browser evidence rows, 89 source-backed contact rows, and five
`website_conversion_v2` records (four numeric, one unknown). Contacts use observed
tel/mailto/visible-text evidence; zero guessed contacts. Excerpts/locators
supported 88 values; direct source-page inspection confirmed the remaining mailto.

Five cleanup intents completed: 100%, zero pending, zero active sessions/tabs.
Provider phone/name/address/rating never enter AuditEngine. Provider responses
remain transient; only independently observed browser facts become durable.
Offline sentinel regressions scanned all 14 public PostgreSQL tables,
API/detail/CSV and logs without leakage. Live logs contained no full configured
secrets or synthetic provider values. Both production entrypoints excluded
SQLite/legacy imports and database files.

LIVE Leads and CSV show exactly the fresh five businesses; job counts/results
match. Desktop/mobile checks passed with working evidence dialogs/CSV and zero
JavaScript errors. The offline banner is visible only in OFFLINE TEST. Screenshots
and detailed evidence remain in the ignored integration directory.

### Tests and recovery

- Windows pytest: 194 passed, 13 skipped; 143 subtests passed.
- Docker pytest with real PostgreSQL: 198 passed, 9 skipped; 143 subtests passed.
- Added 21 cases covering mode/provider/launcher/banner boundaries, job isolation
  and transactional mixed-data cleanup. Defaults never call live providers.
- Skips cover optional live tests and platform-specific Edge/PostgreSQL checks;
  PostgreSQL ran in Docker and Edge DOM fixtures ran on Windows.
- One existing Starlette/AnyIO deprecation warning; no test failures.
- Compileall, pip check, JavaScript syntax and PowerShell parsing passed.
- Both Compose modes built/validated and real one-click launch/stop/status passed.
- Offline cookie sessions, CSRF, password/logout revocation, proxy-aware rate
  limits, API/Redis restart and worker SIGKILL recovery passed without duplicate
  audits/scores. Browser downtime returned 503 before discovery/job creation.
- LIVE invalid CSRF/offline-origin requests created no jobs; five failed logins
  triggered 429 despite spoofed forwarding. Actual 60-second Redis expiry passed.
- Real private CamoFox open/evaluate/close and direct SSRF rejection passed.
- Offline backup restored into a new database: all 11 checked table counts and
  canonical row checksums matched, without provider sentinels.
- LIVE STOP/START preserved checksums across 11 tables, including all five live
  businesses/accounts/sessions, with zero additional provider calls.
- Gitleaks found no leaks. Secrets, dumps, profiles, logs, screenshots and existing
  CODEX instruction files were excluded from commits.

### Final state and user workflow

LIVE remains running with six healthy services; OFFLINE TEST is stopped. The
original PostgreSQL volume and accounts are preserved. Existing untracked CODEX
instruction files remain untouched. No public deployment, larger benchmark or
other development phase was started.

```text
Start Docker Desktop
→ Double-click START_LOCAL.bat
→ Browser opens
→ Run real search
→ Double-click STOP_LOCAL.bat
```
