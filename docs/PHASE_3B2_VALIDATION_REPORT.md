# Phase 3B.2 validation report

Validation date: 2026-09-08, Asia/Karachi. Stored timestamps are UTC.

## Branch, commit and push scope

Local repository: `F:/Website Project/leadprofork/LeadPro-4`.
Branch: `lead-engine-v1`; starting commit `821ac07` verified before edits.
Origin: `https://github.com/Shaheyar544/LeadPro-4.git`.
Upstream: `https://github.com/CodePhantom-1/LeadPro-4.git`.

This report is delivered with `phase 3b2: improve camofox audit reliability`;
the final delivery identifies the exact commit and verified origin branch push.
No upstream write or force push. The five supplied Codex instruction files remain
untracked and excluded, along with all runtime artifacts and secrets.

## Runtime and validation scope

The existing external official `jo-inc/camofox-browser` checkout was reused:
REST service 1.14.0 at `e5a36f5cd0332fde6597de474329a308a53a0716`,
Camoufox 152.0.4 beta.30, portable Node 22.23.2. No official service source was
patched or vendored. Loopback 127.0.0.1:9377, production mode, no imported cookies,
proxy configuration, authenticated profiles, tracing, interactive mode or VNC.
Crash reporting and the persistence/YouTube plugins remained disabled.

Exactly the original five business sites were retested before application edits,
then after reliability changes. No new business sites were added; the optional
second set was skipped. Example.com was used separately for integration/lifecycle
controls. Pilot inputs use `manual_validation_fixture` provenance, with rating,
review count and provider phone absent. No discovery API request was made.
The existing internal test injection seam exercised the real persistent worker,
owner-scoped API, SQLite, scoring and local UI; no public discovery bypass was added.

| Code | Business | Start URL | Observed final page scope |
| --- | --- | --- | --- |
| H | Holden Roofing - Dallas | https://holdenroofing.com/ | /, /contact-us/, /about-us/ |
| A | Accent Roofing and Construction | https://accentroofing.com/ | /, /contact-us/, /about-us/ |
| R | Arrington Roofing | https://arringtonroofing.com/ | /, /contact, /about-us |
| L | Legends Roofing | https://www.legendsroofing.com/ | Homepage navigation failed |
| Y | Reilly Roofing and Gutters - Dallas | https://reillyroofing.com/ | /, /about/ |

Identity/source URLs remain those in Phase 3B.1: Holden /locations/dallas/,
Accent /contact-us/, Arrington homepage, Legends /contact/, and Reilly
/roofing-company-in-dallas-tx/. Crawl selection uses observed visible same-domain
links, never guessed contact paths. Reilly supplied no separate contact link in
that scope, so its crawl used two pages. Local harnesses, SQLite databases,
screenshots and normalized observations remain outside Git under
`C:/tmp/leadpro-phase3b2-baseline` and `C:/tmp/leadpro-phase3b2-validation`.

## Reproduction before implementation

| Outcome | Phase 3B.1 final | 3B.2 baseline before edits | 3B.2 final |
| --- | ---: | ---: | ---: |
| Attempted | 5 | 5 | 5 |
| Completed | 2 | 3 | 4 |
| Partial | 1 | 1 | 0 |
| Failed | 2 | 1 | 1 |
| Blocked | 0 | 0 | 0 |

| Weak case | Baseline diagnosis | DOM/title/links/snapshot/evaluation | Health | Elapsed/retries |
| --- | --- | --- | --- | --- |
| Legends | Combined create/navigation; HTTP 500; private service diagnostic NS_ERROR_NET_RESET | Not obtained; no final public page | Available | 4.391 s / 0 |
| Arrington contact | Render settle; interactive, incomplete | All available; useful partial content | Available | 3.063 s / 0 |
| Reilly homepage | Earlier 3B.1: tab creation timed out after 30000 ms; baseline now loads | All available; initially interactive, subsequently complete | Available | 9.938 s / 0 |

The baseline wrapper added one read-only extraction/snapshot, so these are
diagnostic timings, not a controlled performance comparison. Reilly recovered
before edits: its old timeout was intermittent, and code alone cannot be credited
for the recovery. Arrington's contact page remained partial; Legends repeated its
reset. Raw service stacks stayed local. Production REST redacts some errors, so
the application does not infer NS_ERROR_NET_RESET from an unexplained HTTP 500.
No alternate domain, TLS disablement, proxy, challenge solving or substitute site
was used.

## Reliability fixes and navigation model

- Allocate a blank tab before initial navigation, retaining a cleanup ID even
  after a failed navigation. Only the internal allocation response may contain
  about:blank; it is never an auditable website. A known tab may be observed once
  after navigation failure to preserve usable partial content without POST replay.
- Replace fixed-delay readiness with bounded, read-only DOM samples. Default
  budget 4 seconds, clamped to 0.5-5 seconds, maximum eight samples separated by
  up to 400 ms. Require a body with at least 40 visible characters, complete
  readyState, valid untruncated inputs, and two samples with unchanged link count
  and text-length change at most max(20 characters, 2%). No network-idle wait.
- Interactive/unstable content or a later failed observation is partial when
  useful facts exist. Missing detector inputs remain unknown. No usable facts
  means failed. A later snapshot, viewport or screenshot failure preserves
  valid positive evidence and suppresses incomplete negative findings.
- Persist per-page navigation attempts before browser requests. Additive SQLite
  migration 51 retains counts even when interrupted; prior evidence/history stays
  intact. Job-item attempts still count whole-run recovery, separately.
- Recover a session only after old-context cleanup succeeds, and persist fresh
  ephemeral identifiers before allocating browser state. Stale page IDs are never
  reused; unresolved cleanup prevents replacement.

Phases include session_create, tab_create, initial_navigation,
redirect_validation, dom_ready, render_settle, link_extract, evaluate, snapshot,
page_select, viewport, cleanup and service connect. Diagnostics retain normalized
code/phase, surfaced HTTP status, duration, operation availability, bounded
readiness samples and observed URL endpoints. API results exclude internal
session identifiers and raw service errors. Links/snapshot diagnostics have
three-second deadlines; full snapshots are never persisted.

A completed audit requires every selected page and requested observation
operation to finish sufficiently ready. Useful evidence plus an unavailable
page/operation is partial. Access restrictions are blocked. Conservative
maintenance/hosting, parked-domain and JavaScript/cookie-wall signatures receive
explicit non-success reasons, never ordinary business success. Readiness is a
heuristic for observed DOM, not proof that every conditional/lazy component loaded.

All public destinations and DNS are checked before candidate navigation and after
observed final URLs, including extraction/snapshot/screenshot. www aliases and
scheme canonicalization retain domain scope; arbitrary cross-domain aliases stop
as external_redirect. Start/final endpoints are recorded with
redirect_chain_complete=false. This REST contract cannot intercept every browser
subresource/intermediate redirect or pin Firefox DNS. Independent egress isolation
remains required before untrusted production deployment; protections were not weakened.

## Retry policy and failure taxonomy

At most two navigation attempts per logical page, with 300 ms backoff. Only
explicit transient navigation timeout/reset, early session loss or retryable
protocol failure before useful DOM is eligible. Retry additionally requires
healthy service, confirmed cleanup, fresh persisted identifiers and no cancellation.
Repeated failure stops at two. Individual POST operations are never blindly
replayed; GET/DELETE retains one bounded idempotent transport retry.

No new attempt for CAPTCHA/access restrictions, 403/429, unsafe URL/redirect,
target TLS trust failure, unexplained generic 500, ambiguous tab-creation timeout,
or repeated deterministic failure. Blank creation waits at least 35 seconds
(maximum 60), covering the pinned service's 30-second deadline and retaining the
Phase 3B.1 cancellation shield. Tighter readiness/diagnostic/cleanup bounds apply.

| Condition | Stable application code |
| --- | --- |
| Service connect timeout | browser_connect_timeout |
| Blank tab timeout | browser_tab_timeout |
| Navigation timeout | browser_navigation_timeout |
| No usable DOM | browser_dom_timeout |
| Render never settles | browser_render_timeout |
| JavaScript read timeout | browser_evaluate_timeout |
| Snapshot/screenshot timeout | browser_snapshot_timeout |
| Cleanup timeout | browser_cleanup_timeout |
| Known reset / lost session | browser_connection_reset / browser_session_lost |
| Certificate failure | browser_tls_error |
| Access restriction | browser_blocked |
| Unverified domain change | external_redirect |
| Maintenance, parking, JS/cookie wall | browser_maintenance / browser_parking / browser_javascript_required |
| Unexplained redacted navigation error | browser_navigation_failed plus phase and HTTP status |

## Final original five-site rerun

| Business | Status | Pages ready/attempted | Audit duration (s) | Final reason |
| --- | --- | ---: | ---: | --- |
| H | completed | 3/3 | 11.099 | None |
| A | completed | 3/3 | 12.962 | None |
| R | completed | 3/3 | 12.569 | None |
| L | failed | 0/1 | 3.485 | browser_navigation_failed, initial_navigation, HTTP 500 |
| Y | completed | 2/2 | 17.002 | None |

The preceding first implementation rerun also produced 4 completed, 0 partial,
1 failed, 0 blocked. Arrington's homepage/contact samples progressed from
interactive to complete with stable visible content. Reilly completed both
observed pages. Legends again produced a service-side NS_ERROR_NET_RESET; no
useful business DOM, title, links or snapshot was obtained. Health stayed available
and the known blank tab/context closed. No speculative retry was made.

## Performance and resource observations

- Average audit duration: 11.423 seconds; median: 12.569 seconds.
- Total harness time: 33.219 seconds; concurrency two businesses.
- p95 omitted: five audits do not meaningfully establish a tail distribution.
- Ready pages: 11/12 (91.67%); 12 navigation attempts, zero navigation retries,
  zero live retry successes, zero pilot session losses.
- Sessions created/closed: 5/5; peak tabs/sessions 2/2; final 0/0;
  teardown failures zero; pending cleanup markers zero.
- Browser process baseline/peak/end: 6 / 8 / 6.
- Browser working set baseline/peak/end: 408.0 / 1324.1 / 661.5 MiB.
- CamoFox Node-reported RSS baseline/peak/end: 97 / 139 / 139 MB.
- At 148 seconds after the pilot (including the separate example.com test),
  browser working set was 583.1 MiB, Node RSS 98 MB, with six processes and zero
  tabs/sessions. Memory declined but remained above the initial browser baseline.

Sampling was about every 1.4 seconds and may miss peaks. No session/process leak
was observed; this is not a long-duration memory-leak proof. Phase 3B.1's average
was 13.840 seconds, but availability/network variability and changed diagnostics
prevent attributing the difference solely to implementation.

## Evidence completeness and scoring

The final database contains 382 evidence rows: 245 present, 76 absent, 30 unknown,
31 failed. All 245 positive rows have source URL, timestamp, detector version and
nonempty excerpt or locator. Maximum excerpt/locator/value lengths: 240/36/112
characters. Final detector provenance is rendered_dom_v1.2; older rows retain their
original versions. No full DOM, HTML, snapshot or profile was stored by the engine.
Screenshots remain local and excluded. Contacts represent two public emails and
fourteen unique public business numbers with per-page provenance.

All six earlier conservative unknowns were reviewed individually. H booking widget,
A booking widget, A chat widget, R booking widget and R chat widget lack universal
negative proof and remain unknown. R quote form was unknown due to partial render;
it is now scoped absent when all three pages become ready. No selector or precision
threshold was broadened to remove unknowns. Reilly adds two widget unknowns.
Existing numeric tel CTA, YouTube profile filtering, positive provenance, Birdeye,
Framer and cancellation-race regressions remain covered.

Evidence confidence now uses render_coverage_v2: completed page=1, partial=0.5,
failed/blocked=0, divided by attempted logical pages. This multiplies existing
assessed/applicable weight and weighted detector confidence. Opportunity and
contact confidence remain separate. website_conversion_v1 weights and
0.70 DigitalGap + 0.30 BusinessStrength are unchanged. Missing ratings/reviews
leave strength unknown and retain the gap-only fallback; no data was invented.

| Business | Gap / opportunity | Evidence confidence | Contact confidence | Strength |
| --- | ---: | ---: | ---: | --- |
| H | 11.76 | 81.67 | 98 | Unknown |
| A | 10.53 | 82.50 | 98 | Unknown |
| R | 10.53 | 82.50 | 98 | Unknown |
| L | Unknown | 0 | 0 | Unknown |
| Y | 41.18 | 81.67 | 98 | Unknown |

Arrington's former gap 0 becomes 10.53 when a scoped absence becomes assessable;
weights were not tuned. Reilly's result describes inspected visible pages, not
proof that hidden/interaction-only forms do not exist. Legends receives no
inflated opportunity score. Navigation duration never substitutes for PageSpeed.

## Manual validation matrix

Fresh CamoFox read-only observations, form/footer/mobile screenshots and small
source excerpts were reviewed. No form or CAPTCHA was activated/submitted.
Truth is scoped to bounded visible pages. Holden's generic inspection form remains
unclear for booking. Legends supplies no rendered manual truth. Reilly's visible
search form and empty quote heading were distinguished from contact/quote inputs;
hidden controls were not activated. Social destinations were read, not visited.

P=present, A=absent, U=unknown, F=failed, ?=unclear manual truth.

| Site | Detector | System | Manual truth | Correct? | Notes |
| --- | --- | --- | --- | --- | --- |
| H | email | A | A | Yes | No visible public email in the inspected pages |
| H | phone | P | P | Yes | Visible company telephone links; branch/call-tracking caveat above |
| H | contact_page | P | P | Yes | Selected contact page opened |
| H | contact_form | P | P | Yes | Visible business enquiry form |
| H | quote_form | A | A | Yes | No explicit quote/estimate form observed |
| H | booking_form | A | ? | Excluded | Generic inspection request; booking distinction unclear |
| H | booking_widget | U | A | No: conservative unknown | No calendar/provider widget observed |
| H | chat_widget | P | P | Yes | Visible chat bubble and Birdeye iframe |
| H | primary_cta | P | P | Yes | Visible call/contact/schedule action |
| H | contact_cta | P | P | Yes | Visible phone/contact action |
| H | facebook | P | P | Yes | Company-attributed profile link |
| H | instagram | P | P | Yes | Company-attributed profile link |
| H | linkedin | P | P | Yes | Company path; no personal profile |
| H | youtube | P | P | Yes | Company-attributed channel; video URL excluded |
| H | cms | P | P | Yes | Matched rendered resource or explicit generator |
| H | https | P | P | Yes | Actual final HTTPS URL |
| H | viewport_meta | P | P | Yes | Responsive viewport metadata inspected |
| H | mobile_layout | P | P | Yes | 390px screenshot and 390px document width |
| A | email | A | A | Yes | No visible public email in the inspected pages |
| A | phone | P | P | Yes | Visible company telephone links; branch/call-tracking caveat above |
| A | contact_page | P | P | Yes | Selected contact page opened |
| A | contact_form | P | P | Yes | Visible business enquiry form |
| A | quote_form | A | A | Yes | No explicit quote/estimate form observed |
| A | booking_form | P | P | Yes | Explicit scheduling request; no submission |
| A | booking_widget | U | A | No: conservative unknown | No calendar/provider widget observed |
| A | chat_widget | U | A | No: conservative unknown | No visible chat in inspected scope |
| A | primary_cta | P | P | Yes | Visible call/contact/schedule action |
| A | contact_cta | P | P | Yes | Visible phone/contact action |
| A | facebook | P | P | Yes | Company-attributed profile link |
| A | instagram | P | P | Yes | Company-attributed profile link |
| A | linkedin | P | P | Yes | Company path; no personal profile |
| A | youtube | P | P | Yes | Company-attributed channel; video URL excluded |
| A | cms | P | P | Yes | Matched rendered resource or explicit generator |
| A | https | P | P | Yes | Actual final HTTPS URL |
| A | viewport_meta | P | P | Yes | Responsive viewport metadata inspected |
| A | mobile_layout | P | P | Yes | 390px screenshot and 390px document width |
| R | email | P | P | Yes | Visible public text; input placeholders excluded |
| R | phone | P | P | Yes | Visible company telephone links; branch/call-tracking caveat above |
| R | contact_page | P | P | Yes | Selected contact page opened |
| R | contact_form | P | P | Yes | Visible business enquiry form |
| R | quote_form | A | A | Yes | All selected pages now ready; no explicit quote/estimate form observed |
| R | booking_form | P | P | Yes | Explicit scheduling request; no submission |
| R | booking_widget | U | A | No: conservative unknown | No calendar/provider widget observed |
| R | chat_widget | U | A | No: conservative unknown | No visible chat in inspected scope |
| R | primary_cta | P | P | Yes | Visible call/contact/schedule action |
| R | contact_cta | P | P | Yes | Visible phone/contact action |
| R | facebook | P | P | Yes | Company-attributed profile link |
| R | instagram | P | P | Yes | Company-attributed profile link |
| R | linkedin | P | P | Yes | Company path; no personal profile |
| R | youtube | P | P | Yes | Company-attributed channel; video URL excluded |
| R | cms | P | P | Yes | Matched rendered resource or explicit generator |
| R | https | P | P | Yes | Actual final HTTPS URL |
| R | viewport_meta | P | P | Yes | Responsive viewport metadata inspected |
| R | mobile_layout | P | P | Yes | 390px screenshot and 390px document width |
| L | email | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | phone | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | contact_page | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | contact_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | quote_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | booking_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | booking_widget | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | chat_widget | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | primary_cta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | contact_cta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | facebook | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | instagram | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | linkedin | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | youtube | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | cms | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | https | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | viewport_meta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| L | mobile_layout | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | email | P | P | Yes | Visible public company mailto link |
| Y | phone | P | P | Yes | Four published branch numbers; location context reviewed |
| Y | contact_page | A | A | Yes | No separate contact link in visible homepage/about scope |
| Y | contact_form | A | A | Yes | Only search form visible; hidden controls not activated |
| Y | quote_form | A | A | Yes | Quote heading but no visible quote inputs in observed DOM |
| Y | booking_form | A | A | Yes | No visible scheduling form in observed DOM |
| Y | booking_widget | U | A | No: conservative unknown | No vendor observed; conservative unknown |
| Y | chat_widget | U | A | No: conservative unknown | No vendor observed; conservative unknown |
| Y | primary_cta | P | P | Yes | Visible call/email action |
| Y | contact_cta | P | P | Yes | Visible tel/mailto action |
| Y | facebook | P | P | Yes | Company-attributed Facebook profile |
| Y | instagram | A | A | Yes | No profile in inspected visible links |
| Y | linkedin | A | A | Yes | No profile in inspected visible links |
| Y | youtube | A | A | Yes | No channel in inspected visible links |
| Y | cms | P | P | Yes | Rendered WordPress resources |
| Y | https | P | P | Yes | Validated final HTTPS URL |
| Y | viewport_meta | P | P | Yes | Rendered viewport metadata |
| Y | mobile_layout | P | P | Yes | 390 px viewport and document width; screenshot inspected |


## Accuracy and precision

- 90 matrix rows: 71 determinate, 64 correct (90.14%), zero binary false positives,
  zero binary false negatives, seven conservative unknowns counted as incorrect,
  and 19 unclear rows excluded (18 Legends and one Holden booking).
- Comparable H/A/R subset: 48/53 correct, versus 47/53 in Phase 3B.1. The one
  resolved finding is Arrington quote-form absence. The combined comparison now
  includes observable Reilly and is not an independent generalization benchmark.
- Public email precision 2/2; public phone precision 14/14.
- Form-positive precision 5/5 (three contact and two booking findings).
- Social profile/channel precision 13/13; primary/contact CTA precision 8/8.
- Booking-form precision 2/2; chat-positive precision 1/1 (Birdeye).

These are observed sample ratios, not population estimates. Holden's seven,
Accent's two and Reilly's four numbers are legitimate company branch contacts.
Arrington's one visible CallRail replacement changes between sessions and is not
asserted to be a permanent main line. Its final stored number was checked against
rendered telephone evidence. Public company emails were observed; placeholders,
hidden/script-only contacts, guessed emails and personal enrichment were excluded.
No appointments, phone calls, email or outreach occurred.

## Persistent jobs and live controls

Real-service controls used example.com and isolated SQLite databases:

- Graceful app shutdown/restart preserved the first completed audit's evidence
  count and score ID, recovered unfinished work and completed all three items.
  Histories were 1/2/1, preserving the interrupted run; duplicate scores zero.
- Cancellation left one completed and two cancelled items. The durable flag
  survived two SSE reconnects and all sessions closed.
- Stopping CamoFox produced browser_connection_reset on an existing connection.
  After restart its stale tab produced browser_session_lost; a later audit completed.
- Initially offline CamoFox produced browser_unavailable, persisted failed evidence
  and unknown gap, while the local UI stayed usable and displayed no false absence.
- All five pilot rows/evidence details survived a real local UI reload.
- Offline regressions cover successful fresh-ID retry, repeated timeout/reset
  capped at two, cancellation during backoff, durable pre-request counts, recovery
  without duplicate scores, and cleanup failure preventing session replacement.

Pilot retry count was zero, so live retry success is not claimed from those five
business sites. Abrupt process death remains covered by lease/orphan fixtures;
the real app restart control was graceful, not every possible OS crash timing.
Official browser expiry remains a fallback, not immediate cleanup after service loss.
The service was stopped after validation; no validation worker was left running.

## Discovery providers

| Provider | Configuration | Adapter enabled | Pagination | Quota/config knowledge | Live smoke |
| --- | --- | --- | --- | --- | --- |
| Serper | Not configured | No | One page | Unknown quota; not configured | Skipped, key absent |
| Google Places | Not configured | No | Legacy next_page_token, max 3 pages | Unknown quota; not configured | Skipped, key absent |
| Yelp | Not configured | No | Offset, hard max 5 worker pages | Unknown quota; not configured | Skipped, key absent |

Authenticated GET /api/discovery/readiness performs no external call. Configured
means an operator value exists, not valid credentials or available quota. The
exact Windows smoke commands and flags are in CAMOFOX_SETUP.md. Each smoke parses
at most one business: one search request, with at most one Google Details request;
no next-page cursor is followed and no unnecessary raw response is persisted.
Absent keys skip cleanly. Google Legacy eligibility must be checked when keys are
supplied; no Serper pagination is invented and Yelp never guesses a business site.

Mocked API responses verify Google token forwarding/activation, page bounds,
duplicate identities and target stopping; Yelp offsets, page bounds, dedupe,
target stopping and no guessed website; and Serper's one-page behavior. These
establish readiness of the test path, not live provider coverage. Authoritative
provider/manual website provenance and SSRF checks remain audit prerequisites.
No key was requested in chat or written into the repository.

## Tests

Final suite: 141 tests. Default mode: 137 passed, zero failed, four opt-in skips.
With real CamoFox and provider flags enabled: 138 passed, zero failed, three
provider skips because keys are absent. The real example.com integration executed
and passed. There are 33 added tests relative to Phase 3B.1's 108.

Required unittest discovery, compileall, pip check, node --check foundation.js
and node --check audit_engine/extract.js passed. The standalone Windows UI smoke
passed login, persistent search/refresh, cancellation/reload, blocked/offline
semantics, score detail, stored-XSS fixtures, CSV, settings, validation, mobile
layout and logout, with no retired API calls or JavaScript errors.
New tests default to offline/mock/local rendered fixtures. Earlier numeric tel,
YouTube profile, provenance, Birdeye, Framer and creation/cancellation regression
coverage remains. No dependency was changed.

## Security regression

SSRF and private-network rejection still occur before candidate browser requests;
final destinations are revalidated, www aliases are accepted, unverified domains
stop. This retains the documented REST/subresource limitation. Tests preserve
owner-scoped jobs/results, access-key redaction, no service URL overrides, public
visible contacts only, no guessed emails/personal enrichment, profile filtering,
persistent cancellation, formula-safe CSV, XSS protections and retired outreach
404 behavior. Blocked, failed and partial evidence never become absence.
No CAPTCHA bypass, proxy circumvention, cookie reuse, authenticated browsing,
form submission, PostgreSQL, Redis, billing, outreach or Phase 3C was introduced.

## Git review and limitations

Only reliability/provider-readiness implementation, regression tests and requested
documentation are included. Instruction files, databases, screenshots, profiles,
large logs, keys and the official CamoFox checkout are excluded. After commit,
tracked changes are clean; full git status still lists the five supplied untracked
Codex instruction files. They were not deleted, hidden or committed.

One site still fails navigation; production REST may redact target error details.
Only observed redirect endpoints are available. Lazy/conditional components and
widgets cannot support universal absence claims. Dynamic numbers can change.
Live discovery and Google Legacy account eligibility remain untested without
credentials. There is no production browser network sandbox or long-duration
resource benchmark. The product is not production-ready.

## Recommendation

### READY FOR PHASE 3C

The bounded local browser reliability gate is satisfied: original weak cases
improved or were correctly classified, evidence retained provenance/precision,
failed pages did not inflate scores or corrupt jobs, restart/cancellation/cleanup
passed, no session/process leak was observed, and the provider test path is ready
for credentials. Live provider discovery remains explicitly unvalidated. This
recommendation does not assert production readiness or authorize scaling now.

## Stop

Phase 3C was not started. No second business set, scaling, PostgreSQL, Redis,
billing, outreach, proxy circumvention or CAPTCHA bypass was implemented.
