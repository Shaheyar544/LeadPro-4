# Official CamoFox REST service

The application uses [jo-inc/camofox-browser](https://github.com/jo-inc/camofox-browser)
as a separate service. No Node server code, checkout or browser profile is vendored
in Lead Engine. The primary adapter is `browser/camofox.py`; test injection uses
`MockBrowserProvider`. A future Chromium adapter can implement the same interface.

## Verified baseline

- Official package version: **1.14.0**, Node **>=22** (Node 25.2.1 was available
  during implementation; no live service was started).
- Exact source contract pin: **e5a36f5cd0332fde6597de474329a308a53a0716**.
  This is a source revision whose package declares 1.14.0, later than the v1.14.0
  tag. Use this exact revision: do not substitute a moving branch, `latest`, or
  assume the npm tarball has the same post-release REST behavior.
- Contract verified from the pinned `server.js`, `openapi.json`, `lib/config.js`,
  `lib/auth.js`, `lib/plugins.js` and package metadata. Mock HTTP tests exercise
  that contract. **This is not a claim that a live CamoFox deployment was tested.**

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
tab/session. It does not search Google, Yelp or LinkedIn. No live pilot is attempted
when discovery credentials or the local browser service are unconfigured.
