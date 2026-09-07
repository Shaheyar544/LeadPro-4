# Security foundation: Phase 3A and Phase 3B

**Not production-ready.** Run locally with one Uvicorn process. These are
implemented boundaries and remaining limitations, not a security certification.

## Retired features

Defaults: OUTREACH_ENABLED=false, PUBLIC_AUDIT_ENABLED=false,
SCHEDULER_ENABLED=false. Legacy endpoints belong to an unmounted router and
return 404: outreach, follow-ups, replies, warm-up, WhatsApp, proposals,
SMTP/Brevo/accounts, tracking, public audit pages/submission, capture webhooks,
Slack/Discord notifications, campaigns, intelligence, email previews, sales
summaries/recommendations and outreach analytics. They are absent from OpenAPI.

Setting outreach/public flags true explicitly fails startup; these flags cannot
opt into unreviewed legacy behavior. No scheduler is started by the app.
Scheduler entry points and sending callbacks also check the outreach flag.
Startup creates no outreach/AI/proposal client and performs no FX requests.
An idle database needs no network; persisted queued searches resume automatically. Retained old modules are unsupported as standalone programs.

The active auditor does not call guessed-email, Hunter, Clearbit or owner
inference helpers. Personal LinkedIn/owner search routes are unmounted. Existing
database contents are preserved, including any historical enriched contacts.

## Website fetching / SSRF

Retained HTTP compatibility checks use `url_safety.safe_fetch_html` and the
compatibility `_fetch_website` helper. Provider credentials are never reused for
website requests. The following pinned-HTTP guarantees apply to that client; the
active Phase 3B browser boundary is described separately below.

- Absolute HTTP/HTTPS only, maximum 2,048 characters. Reject whitespace/control
  characters, backslashes, credentials, invalid hostnames and IPv6 scope IDs.
- Allow **80 for HTTP and 443 for HTTPS** only; normalize explicit default ports.
- Require a public IP or valid DNS hostname. Block single-label/local names,
  localhost aliases and `.local`, `.internal`, `.home`, `.lan`, `.localdomain`.
- Every DNS answer must be globally routable. Reject private, loopback,
  link-local/metadata, multicast, unspecified, reserved and shared/non-global
  IPv4/IPv6 ranges. Mixed public/private DNS results fail closed. Mapped IPv6,
  common translation and tunnel forms are conservatively rejected.
- Pin connections to validated addresses, retain hostname TLS checks, disable
  environment proxies and cookies, and require certificate verification.
  There are no HTTP downgrades or user-agent evasion retries.
- Automatic redirects are disabled. Normalize and revalidate each destination
  before connecting; at most three redirects.
- A 20-second total deadline includes DNS, all redirects and reading. DNS and
  connect timeouts are five seconds; socket read timeout is ten seconds.
- HTML/XHTML only; at most 2 MiB, checked by Content-Length and each streamed
  chunk. Request identity encoding and reject compressed content to avoid
  decompression expansion. No unbounded body loading.

Optional PageSpeed submissions validate the business URL first; Google's own
infrastructure performs that analysis. Fixed discovery/PageSpeed API endpoints
use separate provider sessions. Review provider permissions, retention and
attribution terms before discovery.

**Application validation alone does not fully solve DNS rebinding.** Pinning
closes the obvious second DNS lookup race in this client, but network routing,
translation mechanisms and future browser/subresource requests need protection
too. Production must isolate workers and enforce network-level egress
rules against private/local/metadata destinations for every request, without
application credentials or access to internal services.

Outcomes: ok, blocked, rate_limited, not_found, timeout, tls_error, unsafe_url,
network_error, http_error, redirect_limit, body_too_large, unsupported_content.
403/429 and other failed checks do not prove a dead website. The legacy schema
stores this classification as a preliminary finding. Structured audit status
and evidence now live in the separate Phase 3B tables.

## Phase 3B browser boundary

The active worker uses the official CamoFox REST provider. `normalize_url` and
`resolve_public` run before top-level/candidate navigation. Returned URLs, rendered
location and viewport/capture locations are checked again. Candidate pages are
same-host (www alias allowed); unsafe redirects terminate the audit and trigger
session teardown. No HTTP TLS downgrade, authentication, form submission, CAPTCHA
solving, login automation, social interactions or proxy rotation is implemented.

**These REST checks cannot intercept intermediate redirects/subresources or pin
Firefox DNS.** The remote browser may contact a private resource before Python
observes a redirect. No production egress sandbox is delivered in Phase 3B. Run
locally with a separate service account/environment; production requires browser
container/network isolation blocking private/local/metadata access for every
request, plus prevention of access to application files and credentials.

CamoFox's base URL is operator environment configuration, never a request field.
Non-loopback configuration requires CAMOFOX_ACCESS_KEY. Bearer authorization is
centralized, raw provider errors are discarded, and no access key is returned
by health/config. The upstream health route is unauthenticated, so health alone
does not verify key authorization. CAMOFOX_API_KEY (cookie import) is not used.
The setup guide disables crash reports, persistence and VNC using official
supported settings; the app cannot attest to an externally launched service's
configuration. See [CamoFox setup](CAMOFOX_SETUP.md) for the pinned source contract.

Each audit has independent random context IDs. Tab and session cleanup runs in
finally; timed-out or interrupted cleanup is durably marked and retried after
recovery. No browser storage state is imported or shared. Service-side idle expiry
is an additional fallback. An unavailable service cannot guarantee immediate
remote deletion. Screenshots are opt-in, generated filenames in an ignored local
folder; only metadata goes in SQLite. No public artifact endpoint exists.

Full HTML, full visible text, cookie jars, localStorage, traces and raw snapshots
are not persisted. DOM extraction returns bounded facts and small contact/evidence
excerpts. Structured worker logs contain IDs, phase/provider, normalized error
code and duration, never page content, email lists, URL queries, keys or raw
exceptions. Retain browser service logs privately according to local policy.

## Auth, secrets and configuration

Bcrypt hashing and 24-hour HS256 JWTs remain. Expiration is required; users are
rechecked in SQLite on authenticated access. Administrator authority comes
from the current DB role, never from an old token claim. Only bearer headers
are accepted; query-string JWTs are rejected.

Environment JWT_SECRET takes precedence and must contain at least 32 bytes.
Otherwise Python secrets generates a persistent key in `.jwt_secret`. A
same-directory temporary file is flushed/fsynced, then atomically hard-linked
to the destination without overwriting a concurrent winner. Other starters read
the same complete file. No Unix locking module or insecure/ephemeral fallback
is used. Invalid/unreadable files and unsupported filesystems fail closed.
POSIX permissions are 0600. NTFS supports this publication method; secure the
directory with Windows user-only ACLs, since chmod does not secure a Windows ACL.
Secrets are never printed.

The first admin is created only from INITIAL_ADMIN_PASSWORD: 12+ characters,
at most 72 UTF-8 bytes. Without it, an empty DB can start but login remains
unavailable, with a non-secret setup warning. Remove the bootstrap value after
initial setup. Settings show configured/not-configured booleans. Only a current
administrator can write provider API keys, with bounded/control-free values
safely quoted into `.env`. Restart is required; signing secrets, feature flags
and database paths cannot be changed through the API.

JWTs still live in localStorage. Secure HttpOnly sessions, token revocation on
password change and production rate limiting/proxy configuration remain future
work. Logout clears the current browser token; issued JWTs expire normally.
This is one shared workspace, not multi-tenancy.

## UI and export

Untrusted values use DOM creation, textContent and explicit properties. No
dynamic HTML interpolation, inline event code or remote JavaScript remains.
A same-origin CSP blocks inline script and framing. External website links
accept only HTTP/HTTPS without credentials and use noopener/noreferrer; invalid
values remain text. No legacy UI action calls a disabled API.

The browser downloads the backend CSV; it does not serialize cells. One reusable
helper prefixes an apostrophe for formula-leading text (=, +, -, @), including
markers behind whitespace/control prefixes. CSV quoting and bounded server
batches apply to all exported fields. Preserve escaping in downstream tools.

## Jobs and operations

Phase 3B uses additive migration 50 and SQLite WAL. One persistent job executes
at a time, with a bounded queue of ten active jobs per owner, browser concurrency
at most two and target_count 1–100. Short BEGIN IMMEDIATE transactions claim
jobs/items; a 60-second lease and ten-second heartbeat fence stale writers.
Completed items survive restart. Interrupted attempts are retained and retried
from the business start at most three times; opaque session IDs permit cleanup.
No network operation is held inside a database transaction.

Jobs, item lists, detail, results, exports and browser diagnostics require bearer
authentication. Jobs and business audit results are scoped to the starter; another
user receives 404. Cancellation is persisted, pending work is cancelled and active
sessions close at a bounded safe boundary. Disconnects do not cancel jobs. The
UI reconnects using saved server state. This does not implement multi-tenant SaaS.

Use one process and no reload. There is no distributed queue, Redis, PostgreSQL or
production worker network sandbox. Legacy scoring is not used by the new pipeline.
Provider quotas and blocks result in partial/unknown outcomes, not bypass attempts.

Health returns 200/status ok on DB success and 503/status unavailable on critical
DB failure, without internal exception details.

## Dependencies and tests

Unused pandas/tqdm/timezonefinder requirements were removed after import searches.
fpdf2 and Twilio remain for retained legacy imports. Playwright stays for local
DOM/UI tests and is not imported by the active browser provider. Pydantic and test-only httpx are explicit.
python-jose now requires >=3.4.0,<4: the maintainer's
[3.4.0 release](https://github.com/mpdavis/python-jose/releases/tag/3.4.0)
documents CVE-2024-33663 and CVE-2024-33664 fixes. No sweeping upgrade or full
supply-chain assessment was performed.

Run `python -m unittest discover -s tests -v` and `python -m compileall .`.
Tests use temporary data and mocked DNS/HTTP/providers, with no live messaging,
mailboxes, discovery or scraping. A separate local UI smoke check may use an
installed Edge browser with external requests blocked; the active business
provider remains CamoFox. Live CamoFox integration is explicitly opt-in and visits
only example.com. Live discovery/pilots require intentionally configured keys.


## Phase 3B.2 reliability boundary

Additive SQLite migration 51 stores bounded navigation diagnostics and durable
attempt counts. Each attempt is recorded before a browser request. Existing
history is retained; retries do not create duplicate scores or replay completed
job items. A replacement context is allowed only after confirmed old-context
cleanup, with new identifiers persisted before allocation. Failed teardown keeps
the existing durable orphan marker. No context identity is rotated to bypass an
access restriction. The maximum remains two concurrent businesses, three pages
by default (hard maximum four), and two navigation attempts per page.

Public URL and DNS validation remains before candidate navigation and after
observed destinations, including extraction, snapshot and screenshot checks.
Only www/scheme canonicalization is automatically trusted. Cross-domain redirects
stop unverified. This cannot intercept every subresource or intermediate browser
redirect: the existing local-only egress-isolation limitation still applies.

Only valid visible inputs contribute contacts and positive findings. Missing
inputs, partial pages, blocked pages and failed operations never become negative
feature evidence. Soft-error pages are not ordinary business pages. Credentials,
raw service errors, full DOM, snapshots, cookies and profiles are excluded from
application diagnostics. Local validation screenshots and databases remain outside
Git. Readiness requires authentication but makes no provider API request and
returns no keys or inferred quotas. API smoke tests are opt-in and skipped without
keys. Owner scoping, CSP/XSS handling, safe CSV, public-contact rules and retired
outreach 404 routes remain covered by regressions. No authenticated browsing,
form submission, CAPTCHA solving, proxies, enrichment or outreach was introduced.
