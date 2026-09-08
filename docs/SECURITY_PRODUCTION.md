# Production security boundaries validated locally

The Phase 4A.2 Compose topology is restricted to local HTTPS on 127.0.0.1:8443.
No public deployment, VPS, domain, firewall change or public certificate exists.

## Authentication and CSRF

Opaque random sessions are stored in PostgreSQL by SHA-256 fingerprint, with an
8-hour expiry. The browser receives a __Host-leadpro_session cookie with Secure,
HttpOnly, SameSite=Strict and Path=/. The session is never exposed as a bearer JWT.
CSRF tokens are derived with HMAC from the session and secret, returned through
same-origin JSON, retained only in page memory and checked on state changes.
Missing, invalid, cross-session and foreign-origin requests fail before mutation.
Read-only GETs need no CSRF token. Logout deletes the session; password change
locks the user, updates its bcrypt hash and revokes all prior sessions.

The existing frontend uses this cookie path in production, including after
reload. Development compatibility is explicitly enabled by the legacy server's
mode route and retains its JWT in memory only. No localStorage/sessionStorage
auth or job state is written. The legacy server refuses production mode.

Redis limits login attempts to five per client per 60-second fixed window.
The sixth returns 429; the actual window expiry was tested. Correct credentials
do not bypass an active window. Caddy overwrites a dedicated client-IP header;
Uvicorn proxy-header processing is disabled, and the API trusts this header only
from Caddy's resolved network peer. Spoofed X-Forwarded-For and client-supplied
dedicated headers did not bypass the limit.

## Configuration and service isolation

Production refuses non-Postgres/missing DB URLs, missing Redis, weak/default
session secrets, insecure cookies, wildcard CORS, debug/reload, in-process
workers, outreach/scheduler, missing CamoFox access keys, unsafe browser URLs,
interactive/VNC/persistence/telemetry settings and unsupported discovery policy.
The Phase 4A origin is deliberately fixed to https://localhost:8443.

API and worker run as UID 10001 with read-only roots, temporary /tmp, dropped
capabilities and no-new-privileges. CamoFox runs as the node user, with no profile
or Docker-socket mount. CamoFox and the data services have separate networks.
No database, Redis, browser or API port is published directly.

CamoFox's pinned official REST image is derived locally: plugin config disables
persistence, YouTube and VNC; telemetry is explicitly disabled; Firefox headless
launch is asserted and forced at build time. Its logger accepts only static
source event names and numeric/boolean metrics, excluding raw URL/error/session
fields. Build-time assertions fail if the pinned contract changes.

## Logging and policy

API/worker emit structured allowlisted events and use centralized secret
redaction. Database exceptions produce a generic 503 without SQL parameters.
Security events store action, optional user/subject ID and timestamp only.
Caddy runtime proxy errors originally exposed a CSRF header during testing.
The global log filter now removes the entire request object, including headers
and URI. A repeated API restart/outage test and all-container log scan passed.
Affected test sessions were revoked through the password-revocation test.

Synthetic provider values are scanned across all PostgreSQL tables, CSV output
and container logs. No real provider/customer data is used. CI runs policy and
security regressions and a redacted Gitleaks scan of the candidate source tree.

## Exact residual browser-egress risk

Application URL validation rejects deliberate local/private/link-local/metadata,
internal service, unsafe port and file/socket targets before tab creation and
rechecks the final destination. Tests exercised these rejections inside the
worker. CamoFox cannot resolve the separate data-network service aliases, has no
Docker socket, and no Caddy browser proxy route exists.

These checks do **not** intercept Firefox's every subresource, intermediate
redirect or DNS rebinding. A hostile public page may still attempt private,
Docker-host or cloud-metadata requests through the browser network's egress.
Docker network separation alone is not a complete SSRF firewall. Per-request
browser egress enforcement denying private/link-local/host/service destinations
must be established before later public/untrusted staging use. No claim of
complete browser egress isolation is made by this local gate.

Capacity-one coordination, short leases and one local resource sample do not
establish production scaling, availability, browser security-patch currency,
key rotation, backup retention or disaster-recovery targets. The official
container ships Camoufox 135.0.1 beta.24; review/update and revalidate the browser
binary before public use. Live discovery and wider deployment are separate work.
