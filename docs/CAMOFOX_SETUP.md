# Official CamoFox REST service

The application uses [jo-inc/camofox-browser](https://github.com/jo-inc/camofox-browser)
as a separate service. No Node server code, checkout or browser profile is vendored
in Lead Engine. The primary adapter is `browser/camofox.py`; test injection uses
`MockBrowserProvider`. A future Chromium adapter can implement the same interface.

## Verified baseline

- Official package version: **1.14.0**, Node **>=22**. Phase 3B.1 validated the
  real service on Windows using **Node 22.23.2**, **npm 11.6.3** and the existing
  Visual Studio 2026 C++ Build Tools. No global Node/npm installation was changed.
- Exact source contract pin: **e5a36f5cd0332fde6597de474329a308a53a0716**.
  This is a source revision whose package declares 1.14.0, later than the v1.14.0
  tag. Use this exact revision: do not substitute a moving branch, `latest`, or
  assume the npm tarball has the same post-release REST behavior.
- Contract verified from the pinned source and exercised against the real service
  on **2026-09-08 (Asia/Karachi)**. The official `camoufox-js` installer fetched
  Camoufox **152.0.4 beta.30**. This browser binary version is separate from the
  pinned REST service version. See [the validation report](PHASE_3B1_VALIDATION_REPORT.md)
  for the bounded live results and remaining limitations.

| Capability | Actual pinned REST contract |
| --- | --- |
| Health | `GET /health`; `{ok: true}` also permits intentionally idle browser |
| Session/open tab | `POST /tabs`, JSON `userId`, `sessionKey`, `url`, `trace: false`; response `tabId`, `url` |
| Navigate | `POST /tabs/{id}/navigate`, JSON `userId`, `url` |
| Rendered facts | `POST /tabs/{id}/evaluate`, JSON `userId`, `expression`; response `ok`, `result` |
| Snapshot | `GET /tabs/{id}/snapshot?userId=...&format=text&includeScreenshot=false` |
| Links | `GET /tabs/{id}/links?userId=...&limit=250`; actual items have **url**, text; adapter normalizes to href |
| Viewport | `POST /tabs/{id}/viewport`, JSON `userId`, width, height; 100–4000 bounds upstream |
| Screenshot | `GET /tabs/{id}/screenshot?userId=...`; actual response is **image/png bytes**, not the JSON advertised in OpenAPI |
| Close tab | `DELETE /tabs/{id}?userId=...` |
| Destroy context | `DELETE /sessions/{userId}`; idempotent for missing sessions |

The engine evaluates a fixed read-only extraction expression. It never invokes
click, type, press, cookie import, storage export, trace, VNC, upload or macro
endpoints. It never submits a form. Snapshots are an interface capability, not
stored evidence; the active engine uses structured DOM facts instead.

## Windows setup in a separate development directory

Use a separate terminal and directory outside LeadPro-4. Keep application JWT,
discovery keys and other application credentials out of this service environment.
Install Git and Node >=22 first. These steps download/install the official service
and its browser; they are not performed by Python application startup.

```powershell
git clone https://github.com/jo-inc/camofox-browser.git
Set-Location camofox-browser
git checkout --detach e5a36f5cd0332fde6597de474329a308a53a0716
npm ci
```

On the validated Windows machine, `npm ci` initially failed building
`better-sqlite3@13.0.1`: Node 25.2.1/npm 11.6.2 used node-gyp 11.4.2, and portable
Node 22.23.2/npm 10.9.8 used node-gyp 11.5.0. Both reported an unrecognized Visual
Studio 18 installation. The installed C++ workload was present. The fix was
**build tooling only**, using isolated npm 11.6.3 (node-gyp 12.1.0), which adds
[official Visual Studio 2026 support](https://github.com/nodejs/node-gyp/releases/tag/v12.1.0).
With Node 22.23.2 first on that terminal's PATH, install the tool outside LeadPro
and invoke its CLI against the unmodified CamoFox lockfile:

```powershell
npm install --prefix C:\tmp\leadpro-camofox-build-tools --no-audit --no-fund npm@11.6.3
node C:\tmp\leadpro-camofox-build-tools\node_modules\npm\bin\npm-cli.js ci --no-audit --no-fund
```

The portable Node ZIP was downloaded from the [official Node archive](https://nodejs.org/en/download/archive/v22.23.2)
and checked against its published SHA-256. Do not disable certificate checks or
change CamoFox's pinned dependencies to work around installation errors.

Before the first launch, edit the service checkout's `camofox.config.json` to use:

```json
{
  "id": "camofox-browser",
  "name": "Camofox Browser",
  "version": "1.14.0",
  "newPageTimeoutMs": 10000,
  "interactive": { "mode": "off" },
  "plugins": {
    "youtube": { "enabled": false },
    "persistence": { "enabled": false },
    "vnc": { "enabled": false }
  }
}
```

**Persistence is on by default upstream.** Disabling the persistence plugin in
the actual checkout configuration is the supported mechanism. There is no
invented persistence-disable environment variable. `lib/plugins.js` reads this
file relative to the service package, not the caller's working directory.

Launch with private defaults:

```powershell
$env:CAMOFOX_BIND_HOST = '127.0.0.1'
$env:CAMOFOX_PORT = '9377'
$env:CAMOFOX_INTERACTIVE = 'off'
$env:CAMOFOX_CRASH_REPORT_ENABLED = 'false'
$env:ENABLE_VNC = 'false'
$env:NODE_ENV = 'production'
$env:SESSION_TIMEOUT_MS = '120000'
$env:TAB_INACTIVITY_MS = '120000'
npm start
```

Use an environment without `PROXY_*` configuration; this phase does not use proxy
rotation. `CAMOFOX_INTERACTIVE=off` is the official noninteractive setting. On
Windows it selects headless Firefox; on Linux upstream may use a virtual display.
No interactive desktop or VNC session is part of this workflow. Stop the foreground
service using **Ctrl+C in its terminal**.

## Access key and application connection

`CAMOFOX_ACCESS_KEY` is the global bearer guard. Configure the same secret privately
in the service environment and the application's ignored `.env` if using it.
Never put the value in a URL, script, Git commit, log or chat. The service's
`CAMOFOX_API_KEY` is a different cookie-import key and is not used by this adapter.

The default app URL is `http://127.0.0.1:9377`. A non-loopback URL without an access
key fails application configuration validation. The URL is environment-only;
search requests and the Settings API cannot change it. Keep this prototype on
loopback even when a key is set. Remote production deployment requires transport
security, network restrictions and additional browser isolation.

Check the local service without a browser navigation:

```powershell
Invoke-RestMethod http://127.0.0.1:9377/health
```

The application's authenticated `GET /api/browser/health` and Settings **Check
browser service** button return normalized availability without secrets or raw
server diagnostics. Health is exempt from upstream global auth; an available
health response does not prove the supplied key authorizes tab creation. Denied
operations report `browser_unavailable`, never echoing provider response bodies.
The app boots with CamoFox offline. Browser-dependent items persist a clear failure
and unknown scores; discovery identity/provenance is retained.

## Isolation, teardown and retention

Every business audit attempt gets independent random `userId` and `sessionKey`.
The worker persists those opaque IDs before its first tab request. It closes each
page in `finally` and deletes the session after success, failure, timeout and
cancellation. If teardown fails, the database retains a cleanup marker; subsequent
worker passes retry after service health recovers. Stale runs retain their history
and their IDs for orphan cleanup. The service's two-minute idle expiry is a final
fallback. Network failures cannot guarantee immediate remote destruction.

Phase 3B.1 fixed a real shutdown race: cancellation now waits for the in-flight
tab-creation POST to finish within its bounded request timeout before deleting
the context. It tolerates repeated cancellation and never replays the POST. An
early DELETE previously triggered CamoFox's own context recreation, leaving a
stale session and disrupting later page creation. Graceful shutdown can therefore
wait for the remaining request timeout plus bounded session cleanup. Abrupt
process termination still relies on persisted recovery/cleanup and service expiry.

No cookies, localStorage or authenticated browser state are imported/reused across
businesses. Tracing stays off. Crash reporting is explicitly disabled at service
launch; the Python adapter cannot attest to a separately configured service's
telemetry or plugin settings. Verify that launch configuration before using it.

Screenshots are off by default. If enabled, at most the homepage and one contact
page are captured, to random `.png` filenames under ignored `audit_artifacts/`.
The database stores filename/byte-count metadata, not image data. Screenshots are
not served by a public route or exported. Retain only as long as locally needed;
review and remove expired files manually under your retention policy (suggested
maximum seven days). No automatic deletion is introduced by this phase. Full
HTML, full visible text, full accessibility snapshots, cookies and traces are not
stored by the engine. Keep the service's own logs private and short-lived.

## Security boundary and optional integration test

The adapter validates public schemes, hosts, ports and DNS before every candidate
navigation and validates returned/rendered destinations. Unsafe destinations
stop the audit and trigger teardown. This REST contract does **not** allow the
Python caller to intercept every redirect or subresource before Firefox requests
it, and it cannot pin Firefox's DNS lookup. A public site could redirect or load
private resources before post-navigation checks run. Production needs a separate
browser account/container and network egress rules denying local, private and
metadata destinations for every request. This remains a documented limitation,
not a security guarantee provided by CamoFox.

Live integration is skipped by default. After intentionally configuring the service:

```powershell
$env:RUN_CAMOFOX_INTEGRATION_TESTS = '1'
python -m unittest tests.test_camofox_provider.LiveCamoFoxTests -v
```

The opt-in test visits only `https://example.com/`, reads its title and closes the
tab/session. It does not search Google, Yelp or LinkedIn. Live discovery requires
configured discovery credentials. Phase 3B.1 used the existing internal fixture
source injection to supply five manually verified public websites; it did not add
a product route that bypasses discovery or destination validation.


## Phase 3B.2 navigation and readiness

The adapter allocates a blank tab (`POST /tabs`, without a destination), then uses
`POST /tabs/{id}/navigate` for the validated public URL. Only the internal blank
allocation response may contain `about:blank`; it is never an auditable website.
This separates tab creation from navigation and retains a cleanup ID when the
website times out. A failed navigation may be inspected once on that known tab;
usable DOM is partial evidence, never proof of absence. No POST is automatically
replayed by the HTTP adapter. Blank creation waits at least 35 seconds (at most
60) before timeout so cancellation does not race the pinned service's 30-second
creation deadline. The existing cancellation shielding remains in place.

`CAMOFOX_READINESS_TIMEOUT_MS` defaults to 4000, clamped to 500–5000 ms. Within
that observation budget, at most eight read-only DOM samples are taken, separated
by up to 400 ms. Ready requires usable body text (at least 40 characters), complete
readyState, valid bounded detector inputs, and two samples with unchanged link
count and text length changing by at most max(20 characters, 2%). Interactive DOM,
changing DOM, extraction limits, or a later failed observation produces partial
when usable facts exist. No usable facts produces failed. This is a heuristic for
the observed DOM, not proof every lazy/conditional component has loaded.

The old settle setting is retained for compatibility and the bounded mobile
viewport check; it no longer establishes desktop readiness. Links and transient
snapshot diagnostics have three-second deadlines. Snapshot/viewport/screenshot
failures preserve prior positive evidence and make the page partial. Snapshots
are never persisted. Each page's bounded attempts, phases, elapsed times,
readiness samples and normalized errors are retained in SQLite and owner-scoped
business detail. Start and observed final URLs are recorded; intermediate HTTP
redirects are not available from this REST contract and the chain is explicitly
marked incomplete. Only www aliases and scheme upgrades preserve domain scope;
unverified cross-domain aliases stop as `external_redirect`.

The worker permits at most two navigation attempts per logical page, with a
300 ms backoff, only for explicitly classified transient navigation timeout,
connection reset, session loss, or retryable protocol error before usable DOM.
Retry requires service health and successful cleanup of the old context, then
persists fresh ephemeral identifiers before allocation. Cancellation suppresses
retry. Denial/challenge/403/429, unsafe destinations, TLS trust errors, generic
500s, ambiguous tab-creation timeouts and repeated failures do not trigger a new
attempt. A production service may redact NS_ERROR details to a generic 500;
classification retains the phase and status, without guessing its cause.

Timeout codes distinguish connect, tab creation, navigation, DOM readiness,
render settle, evaluate, snapshot and cleanup. Soft challenge/access restrictions
are blocked. Conservative maintenance/hosting, domain parking, and JavaScript or
cookie requirement signatures are explicit non-success reasons. These checks do
not submit forms or solve challenges. See the Phase 3B.2 report for measured limits.

## Discovery configuration and opt-in smoke tests

Authenticated `GET /api/discovery/readiness` performs no network request. It
returns only configured/enabled flags, pagination and page bounds, configuration
status and unknown quota status. Configured does not imply valid credentials or
available quota. Configure keys privately in the existing operator environment
and restart; never paste them into chat or source files.

The following flags intentionally enable tiny live smoke requests. Each uses an
ordinary Roofing/Dallas query and parses at most one record: Serper and Yelp one
search request, Google Legacy Text Search one search plus at most one Details
request. Cursor types are checked without requesting another page. Missing keys
skip cleanly. No raw response or contact list is persisted by these tests.

```powershell
$env:RUN_SERPER_INTEGRATION_TESTS = '1'
$env:RUN_GOOGLE_PLACES_INTEGRATION_TESTS = '1'
$env:RUN_YELP_INTEGRATION_TESTS = '1'
python -m unittest tests.test_provider_readiness.ProviderIntegrationTests -v
```

Serper stays one-page: no verified pagination contract has been added. Google
uses its existing Legacy API and needs credentials eligible for that API; new
account/API enablement must be verified during the opt-in smoke. Yelp exposes
listing provenance and public phone, not an authoritative business website; no
website is guessed. Worker tests cover page bounds, deduplication, target stopping,
Google token activation and Yelp offsets. Live availability is not established
without successful credentialed tests.
