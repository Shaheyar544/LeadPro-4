# Phase 3A security foundation

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
Startup creates no outreach/AI/proposal client and performs no FX or external
API requests. Retained old modules are unsupported as standalone programs.

The active auditor does not call guessed-email, Hunter, Clearbit or owner
inference helpers. Personal LinkedIn/owner search routes are unmounted. Existing
database contents are preserved, including any historical enriched contacts.

## Website fetching / SSRF

All active direct business-website fetching uses `url_safety.safe_fetch_html`,
including provider URLs and the compatibility `_fetch_website` helper. The
provider session is deliberately not reused for websites.

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
too. Phase 3B/production must isolate workers and enforce network-level egress
rules against private/local/metadata destinations for every request, without
application credentials or access to internal services.

Outcomes: ok, blocked, rate_limited, not_found, timeout, tls_error, unsafe_url,
network_error, http_error, redirect_limit, body_too_large, unsupported_content.
403/429 and other failed checks do not prove a dead website. The legacy schema
stores this classification as a preliminary finding. Structured audit status
and evidence are Phase 3B work.

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

MAX_CONCURRENT_TASKS defaults to 1, clamped to 1–5. Capacity is reserved on the
single app loop before scheduling; excess work returns 429/Retry-After: 10.
There is no unbounded queue. Per-job website concurrency SCRAPE_THREADS defaults
to 2, clamped to 1–5. Input and engine enforce target_count 1–100 and prevent
batch overshoot.

Jobs use full UUID4 IDs, authenticated status/SSE and starter ownership. Missing
and other-user jobs both return 404. Reads are non-destructive and disconnects
do not cancel work. Retain at most 200 events/job and 2,000 characters/message.
Completed jobs expire after an hour and are capped at approximately 100 on
subsequent access. Shutdown requests cancellation; the UI offers no misleading
Stop control. Restart loses job state and potentially uncommitted batches.

Limits are **not distributed**: use one worker and no reload. Durable jobs,
restart recovery and cross-process claiming belong to Phase 3B. Legacy schema,
scoring heuristics, provider errors, data provenance and pagination need further
work. No Playwright crawler is implemented here.

Health returns 200/status ok on DB success and 503/status unavailable on critical
DB failure, without internal exception details.

## Dependencies and tests

Unused pandas/tqdm/timezonefinder requirements were removed after import searches.
fpdf2 and Twilio remain for retained legacy imports. Playwright stays for Phase
3B and is not imported by the product. Pydantic and test-only httpx are explicit.
python-jose now requires >=3.4.0,<4: the maintainer's
[3.4.0 release](https://github.com/mpdavis/python-jose/releases/tag/3.4.0)
documents CVE-2024-33663 and CVE-2024-33664 fixes. No sweeping upgrade or full
supply-chain assessment was performed.

Run `python -m unittest discover -s tests -v` and `python -m compileall .`.
Tests use temporary data and mocked DNS/HTTP/providers, with no live messaging,
mailboxes, discovery or scraping. A separate local UI smoke check may use an
installed browser; this is not the Phase 3B worker.
