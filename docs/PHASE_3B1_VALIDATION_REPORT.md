# Phase 3B.1 live CamoFox validation

Date: **2026-09-08, Asia/Karachi**. Branch: `lead-engine-v1`.
Baseline: `19578e2` (Phase 3B). Scope: real browser validation, five unique
manually selected business websites, and fixes discovered during validation.
No Phase 3C work, discovery expansion, dependency changes, or outreach.

**Live discovery pilot skipped due to missing configured provider credentials.**

## Runtime and installation

| Item | Observed result |
| --- | --- |
| Official service | `jo-inc/camofox-browser`, package 1.14.0 |
| Exact service revision | `e5a36f5cd0332fde6597de474329a308a53a0716` |
| Browser installed by official `camoufox-js` | Camoufox 152.0.4 beta.30 |
| Platform | Windows 11, x64; Python 3.12.10 |
| Validated toolchain | Portable Node 22.23.2; isolated npm 11.6.3 / node-gyp 12.1.0 |
| Service URL / listener | `http://127.0.0.1:9377`, IPv4 loopback only |
| Key mode | No access key; supported loopback-only development mode |
| Health | Real HTTP 200; normalized `available`; actual tab creation also passed |
| Browser mode | Headless; interactive mode off |
| Crash reporting | `CAMOFOX_CRASH_REPORT_ENABLED=false` |
| Persistence / YouTube / VNC plugins | All disabled in the external checkout configuration |
| Proxy / imported state | No proxy configuration, imported cookies, authenticated profiles or traces |
| Idle expiry | Session and tab inactivity each configured to 120 seconds |

The service checkout, Node/npm tools, browser cache, test databases, logs and
screenshots were outside LeadPro. No global Node/npm configuration was changed.
The service source and lockfile stayed pinned; only its documented runtime
configuration was edited.

Initial `npm ci` failed building `better-sqlite3@13.0.1`. Node 25.2.1/npm 11.6.2
(node-gyp 11.4.2), then Node 22.23.2/npm 10.9.8 (node-gyp 11.5.0), could not
recognize the existing Visual Studio 2026 installation. Its C++ workload was
present. Isolated npm 11.6.3 supplies node-gyp 12.1.0, whose
[official release adds Visual Studio 2026 support](https://github.com/nodejs/node-gyp/releases/tag/v12.1.0).
Installation then succeeded without changing CamoFox versions or dependencies.
The [official Node 22.23.2 ZIP](https://nodejs.org/en/download/archive/v22.23.2)
was checked against the published SHA-256. See [setup instructions](CAMOFOX_SETUP.md).

Health does not certify that every destination loads. CamoFox returned HTTP 200
while two destinations failed navigation; the diagnostic failure counter rose
from 2 to 4 during the corrected pass. Those failures were retained in the app.
After the final passing integration test, health again showed HTTP 200 and zero
sessions/tabs. The owned validation service was then stopped; zero Camoufox
processes remained. It is installed but is not left running in the background.

## Real integration and lifecycle

The opt-in test was explicitly enabled and passed, not skipped:

```powershell
$env:RUN_CAMOFOX_INTEGRATION_TESTS = '1'
python -m unittest tests.test_camofox_provider.LiveCamoFoxTests -v
```

Its first execution reported `Ran 1 test in 3.184s` and `OK`. It visited only
`https://example.com/` through the real `CamoFoxProvider`. The full suite also ran
this test against the live service. The separate final execution after the other
regression checks reported `Ran 1 test in 3.241s` and `OK`, with zero skips.

Five additional real `example.com` cycles exercised every implemented provider
operation: health, session/page creation, explicit navigation, title and rendered
fact evaluation, link parsing, text snapshot parsing, 390px viewport control,
PNG screenshot parsing, tab deletion and session deletion. All five passed with
zero sessions/tabs after each cycle. Browser process count was 6 before and 6
after, with the shared browser intentionally warm. All five cycles were repeated
successfully after the cancellation fix. Post-fix cycles took 3.266–3.344 seconds.
No challenge site or business directory was used for these checks.

## Credentials and permitted test path

| Provider | Configuration |
| --- | --- |
| SERPER_API_KEY | Not configured |
| GOOGLE_PLACES_API_KEY | Not configured |
| YELP_API_KEY | Not configured |

The existing `tests.engine_fixtures.FixtureSource`, `PersistentWorker` injection,
real `AuditEngine`, and real `EngineStore` provided the intentional internal test
path. An external validation harness injected five manually verified records into
that source and exercised the authenticated FastAPI search/result endpoints.
Records were explicitly labeled **`manual_public_website`**, not an API provider.
No destination validator was mocked or replaced. No product bypass was added.
Temporary admin credentials and JWT secrets were generated in memory for isolated
test databases; no values are included here.

All records used Roofing / Dallas / TX. Ratings and review counts stayed unknown;
the harness did not reuse the fixture helper's example ratings or contact data.
Only five unique businesses were visited. The same five were rerun once after
the detector fixes; manual review revisited only the same bounded pages. This
was not a second discovery search, another city, or an expanded sample.

Authoritative website checks used each company's public site and Dallas/location
information:

| ID | Business | Authoritative source |
| --- | --- | --- |
| H | Holden Roofing — Dallas | [Dallas location](https://holdenroofing.com/locations/dallas/) |
| A | Accent Roofing and Construction | [Contact page](https://accentroofing.com/contact-us/) |
| R | Arrington Roofing | [Company website](https://arringtonroofing.com/) |
| L | Legends Roofing | [Contact page](https://www.legendsroofing.com/contact/) |
| Y | Reilly Roofing and Gutters — Dallas | [Dallas location](https://reillyroofing.com/roofing-company-in-dallas-tx/) |

Location verification does not imply successful browser access or independent
verification of marketing/reputation claims.

## Five-business results

Corrected pass: **02:04:33.752–02:05:15.155 PKT** (database job timestamps).

| Metric | Result |
| --- | --- |
| Requested maximum | 5 |
| Live API discovery | Skipped; 0 API-discovered records |
| Manually supplied records / verified websites | 5 / 5 |
| Fully successful audits | 2 |
| Partial audits with useful rendered evidence | 1 |
| Businesses with at least one successfully inspected page | 3 |
| Blocked audits | 0 classified blocked |
| Failed audits | 2 |
| No authoritative website | 0 |
| Contact pages successfully inspected | 3 |
| Pages attempted / completed | 11 / 9 |
| Unique public emails / phone numbers | 1 / 10 |
| Audit sessions created / closed | 5 / 5 |
| Cleanup failures / pending cleanup markers | 0 / 0 |
| Total harness wall time | 43.734 seconds, including startup/API/poll overhead |
| Database job duration | 41.403 seconds |

| Business | Audit | Pages completed | Duration | Email count | Phone count |
| --- | --- | ---: | ---: | ---: | ---: |
| H | Completed | 3 | 11.257s | 0 | 7 |
| A | Completed | 3 | 13.768s | 0 | 2 |
| R | Partial: `audit_incomplete` | 3 | 9.474s | 1 | 1 |
| L | Failed: `browser_navigation_failed` | 0 | 4.675s | 0 | 0 |
| Y | Failed: `browser_navigation_failed` | 0 | 30.025s | 0 | 0 |

Legends encountered Firefox `NS_ERROR_NET_RESET`; Reilly hit the service's bounded
30-second tab-creation timeout. Both outcomes repeated in the corrected pass.
No access challenge was solved, TLS verification disabled, proxy added, or
alternate browser used to obtain a success. These sites were not silently
replaced with other businesses.

Arrington's homepage/contact document remained `interactive` at observation time;
the about page reached `complete`. A read-only diagnostic found 255/143/153 text
nodes and 112/29/49 visible links respectively, below the existing limits. The
partial status came from readiness, not a reason to raise crawl/text limits.
Known positive evidence was retained and unconfirmed negatives stayed unknown.

The initial pass had the same 2 completed / 1 partial / 2 failed distribution.
Its persisted results exposed the detector issues below. The final pass's timing
and resource metrics are reported here; no missing initial resource measurements
were reconstructed or invented.

## Manual validation method and accuracy

Manual truth was assigned from real CamoFox screenshots of the homepage,
contact form and footer, plus independent read-only inspection of visible
links/fields, metadata and rendered resource URLs. It was not copied from the
detector output. Social URLs were inspected on the authoritative website;
social platforms were not visited. “Correct social profile” means a company-
attributed profile/channel link, not authenticated proof of account ownership.

The unit of detector comparison is one business/feature over the three-page
scope. “Absent” in manual review means not observed in that rendered scope, not
a guarantee about every conditional widget or every page. A booking **form** can
request a service appointment; it does not prove a completed booking or a live
calendar integration. Holden's generic inspection request is ambiguous on that
distinction and is marked unclear. Neither that form nor any other form was
submitted. Standalone booking widgets were evaluated separately.

**5-business pilot metrics; a small manually selected sample, not a production
accuracy estimate:**

- Matrix: 90 business/feature rows (18 features × 5). There were 54 directly
  assessable rows across the three rendered sites and 36 unavailable rows for
  the two failed sites. Including one ambiguous form, manual truth was unclear
  on 37 rows.
- Correct determinate findings: **47 / 53 = 88.68%**. The six remaining determinate
  rows had conservative system `unknown` results; they are included in the
  denominator, not hidden by the accuracy calculation.
- Binary false positives: **0**; binary false negatives (`absent` vs manual
  `present`): **0** after fixes. Unknown answers are reported separately rather
  than called correct negatives.
- Matrix system statuses: **6 unknown, 0 blocked, 36 failed**. Across all 31
  aggregate detectors × 5 businesses: **12 unknown, 0 blocked, 62 failed**.
- Public email precision: **1/1 = 100%**. Public business phone precision:
  **10/10 = 100%**. Counts deduplicate values across pages. These are public
  company numbers; Holden/Accent also publish other branch numbers. They are
  not all Dallas-only direct lines. Arrington uses a dynamically substituted
  business call-tracking number, which can differ across sessions.
- Form classification precision: **5/5 = 100%** business/type positives: three
  contact forms and two explicit scheduling request forms. No positive quote
  form was reported. No actual booking was performed.
- Social profile/channel precision: **12/12 = 100%** after filtering video URLs.
  The initial pass included one extra YouTube video URL, which is not a profile.
- Primary/contact CTA precision: **6/6 = 100%**. Booking-form precision: **2/2**;
  booking-widget precision: not measurable (no positive). Chat precision: **1/1**;
  two other chat findings remained unknown despite no visible chat in the review.

### Validation matrix

P = present, A = absent, U = unknown (system), ? = unclear (manual), F = failed.
“No: unknown” counts against determinate accuracy. “Excluded” is manual unclear.

| Business | Detector | System | Manual | Correct? | Notes |
| --- | --- | --- | --- | --- | --- |
| H | email | A | A | Yes | No visible public email in the inspected pages |
| H | phone | P | P | Yes | Visible company telephone links; branch/call-tracking caveat above |
| H | contact_page | P | P | Yes | Selected contact page opened |
| H | contact_form | P | P | Yes | Visible business enquiry form |
| H | quote_form | A | A | Yes | No explicit quote/estimate form observed |
| H | booking_form | A | ? | Excluded | Generic inspection request; booking distinction unclear |
| H | booking_widget | U | A | No: unknown | No calendar/provider widget observed |
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
| A | booking_widget | U | A | No: unknown | No calendar/provider widget observed |
| A | chat_widget | U | A | No: unknown | No visible chat in inspected scope |
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
| R | quote_form | U | A | No: unknown | No explicit quote/estimate form observed |
| R | booking_form | P | P | Yes | Explicit scheduling request; no submission |
| R | booking_widget | U | A | No: unknown | No calendar/provider widget observed |
| R | chat_widget | U | A | No: unknown | No visible chat in inspected scope |
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
| Y | email | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | phone | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | contact_page | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | contact_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | quote_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | booking_form | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | booking_widget | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | chat_widget | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | primary_cta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | contact_cta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | facebook | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | instagram | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | linkedin | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | youtube | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | cms | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | https | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | viewport_meta | F | ? | Excluded | Navigation failed; no rendered manual truth |
| Y | mobile_layout | F | ? | Excluded | Navigation failed; no rendered manual truth |

## Evidence quality and page choice

The corrected database contained 350 evidence rows: 215 present, 42 absent,
31 unknown and 62 failed. All **215 positive rows** had a source URL, timestamp,
detector version, and a nonempty excerpt or locator. There were no pending
cleanup markers. Maximum stored excerpt/locator/value lengths were
240 / 36 / 112 characters. No complete HTML, DOM or accessibility snapshots were
persisted by the engine. Screenshots and bounded manual diagnostics stayed local
outside the repository.

There were 33 contact provenance rows across pages (3 email and 30 phone rows),
representing the 1 email and 10 unique numbers above. Public visible contact
values were manually checked; placeholders and script-only values were not
accepted. Existing and added regressions cover hidden/script contacts, example
addresses, tracking IDs, newsletter/login forms, and personal LinkedIn links.

H and A selected `/contact-us/` and `/about-us/`; R selected `/contact` and
`/about-us`. Each also inspected its homepage. No duplicate URL, privacy page,
unrelated external page, or booking-provider crawl was selected. L and Y failed
on the homepage, so no further page was crawled. The default three-page budget
and the existing maximum were unchanged.

Arrington's Framer/React page and visible call-tracking replacement, and Holden's
injected Birdeye chat iframe, naturally exercised JavaScript-rendered signals.
The engine saw the rendered form/contact information and the fixed detector saw
the chat iframe. This does not establish broad SPA/conditional-widget coverage;
Arrington's incomplete readiness remains a limitation. No new anti-bot target
was sought for validation.

## Scoring review

| Business | Digital Gap | Business Strength | Opportunity | Evidence confidence | Contact confidence | Manual direction |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| H | 11.76 | Unknown | 11.76 | 81.67 | 98 | Reasonable low gap; contact action now recognized |
| A | 10.53 | Unknown | 10.53 | 82.50 | 98 | Reasonable low gap with contact and scheduling forms |
| R | 0.00 | Unknown | 0.00 | 73.50 | 98 | Reasonable only for observed checks; partial, not a perfect-site claim |
| L | Unknown | Unknown | Unknown | 0 | 0 | Correct: failed access gives no opportunity estimate |
| Y | Unknown | Unknown | Unknown | 0 | 0 | Correct: failed access gives no opportunity estimate |

No scoring weights, applicability rules, thresholds or formulas changed.
`website_conversion_v1` remains the scoring profile; detection changes are
explicitly versioned **`rendered_dom_v1.1`**. Holden's prior 29.41 gap fell to 11.76
because the phone-only contact CTA is now observed, removing a false missing-
feature penalty. This is an input-evidence correction, not weight tuning.
Business strength remains unknown without verified rating/review inputs;
opportunity uses the existing gap-only fallback. Unknown PageSpeed/other checks
do not add missing-feature penalties.

## Persistence, offline behavior and cancellation

- **Browser offline: passed.** The owned service was stopped before a one-item
  `example.com` fixture job. FastAPI `/health` remained HTTP 200. The job and run
  persisted `browser_unavailable`; all findings were failed, not absent, and the
  gap/opportunity remained unknown. A real localhost dashboard showed the
  unavailable message and unknown scores with zero absent badges.
- **App restart: passed after fix.** A three-item real-browser fixture job was
  stopped through FastAPI lifespan shutdown after one completion, then restarted
  using the same SQLite database. It moved through queued recovery to three
  completed items. The first run's evidence count and score ID were unchanged;
  there were zero duplicate scores per run. Histories were 1/2/1 runs: the
  interrupted attempt was retained and only unfinished work was retried.
  This validates controlled graceful restart; it is not a live OS-crash test.
- **Cancellation: passed.** A three-item real-browser fixture job ended with one
  completed and two cancelled items. The persistent flag remained set; pending
  work stopped and sessions/tabs returned to zero. Two SSE reconnects returned
  the terminal cancelled state. The Windows UI smoke test additionally refreshed
  and reopened cancelled job history, verified the disabled cancel button, and
  verified no new search request was sent.
- **Browser restart: passed.** During a harmless example page operation, stopping
  the owned service returned `browser_unavailable`. After restarting it, use of
  the old tab returned `browser_session_lost`. A later real audit completed.
  Retries stayed bounded; no POST was replayed.
- **Persisted dashboard: passed.** A separate real localhost FastAPI process read
  the five saved pilot records. All five details opened, source labels and
  unknown scores were visible, and reload preserved all five rows.

## Defects and fixes

1. **Cancellation/context recreation race.** Real shutdown during `POST /tabs`
   let DELETE run before creation finished. CamoFox recreated the context and
   later page creation became unresponsive. Creation now settles within the
   existing request timeout before cancellation propagates to cleanup; repeated
   cancellation is tolerated. Two mock REST regressions cover late allocation
   and errors after cancellation. The first regression failed before the fix,
   then passed, and the live restart/lifecycle checks passed afterward.
2. **Phone-only contact CTA missed.** A visible numeric telephone link was counted
   as click-to-call but not a contact CTA, inflating Holden's gap. Valid `tel:` and
   `mailto:` actions now qualify even without the words “call” or “contact”.
   A score-level regression confirms zero missing-contact points for this case.
3. **YouTube video treated as profile.** Social evidence now keeps channel/handle
   URL forms and excludes videos, shorts and short video links. Regression tests
   preserve company LinkedIn restrictions and validate YouTube URL types.
4. **Incomplete positive provenance.** Location/readiness/contact-link/social
   evidence now has useful locators; form evidence retains the matching heading
   or field description; CMS evidence includes the matched resource or generator.
   Scheduling was correctly classified in the inspected form, but its previous
   excerpt did not explain why. No form-classification rule was changed.
5. **Observed widget/CMS omissions.** Added the observed Birdeye webchat resource
   signature and explicit `Framer` generator recognition, with regressions for
   lookalike domains and unrelated resource names. No generic “chat” text match
   or broad CMS guess was introduced.

The Windows build-tool incompatibility was an environment defect, resolved
outside LeadPro and documented in setup instructions. External harness issues
(an incorrect counter name, expecting a provider literal in a failed audit's UI,
and a void manual-scroll expression) were corrected in that harness; they are
not represented as product defects or passing assertions.

## Resource observations

- Average completed pages/business: **1.8**; average attempted pages: **2.2**.
  The three sites with rendered evidence each completed 3 pages.
- Mean audit duration: **13.840 seconds** across all five, including failed runs;
  **11.500 seconds** across the three with rendered evidence.
- Browser processes: **6 baseline → 8 sampled peak → 6 after**.
  Combined browser working set: **625.5 → 1061.4 peak → 679.4 MiB**.
- CamoFox Node RSS: **125 → 130 peak → 128 MB** as reported by `/health`.
  These are approximate periodic observations, not a benchmark or leak proof.
- Peak active sessions/tabs: **2 / 2**. Final: **0 / 0**. All five business
  contexts closed; no cleanup failure or growing process count was observed
  after the fix. Some warm browser memory remained allocated.

## Regression checks

Full suite executed with `RUN_CAMOFOX_INTEGRATION_TESTS=1`:

```text
python -m unittest discover -s tests -v
Ran 108 tests in 11.047s
OK
```

**108 passed, 0 failed, 0 skipped**, including the real `example.com` test.
The six added unit regressions cover the actual cancellation/detector defects.
The extended Windows browser smoke test also passed: login, stored progress,
refresh/reconnect, cancellation after reload, blocked/offline evidence, scores,
CSV, XSS fixtures, mobile layout, settings and logout; no retired API calls or
JavaScript errors. Its browser provider remains deliberately mocked; it does not
replace the separate real CamoFox tests or manual website checks above.

Additional checks passed:

```text
python -m compileall -q .
python -m pip check                     # No broken requirements found.
node --check foundation.js
node --check audit_engine/extract.js
python tests/browser_smoke.py --artifact-dir <external validation directory>
```

## Security and remaining limitations

Public URL/DNS checks, TLS verification, same-domain navigation policy, ownership
checks, JWT protections, sanitized errors, evidence bounds, concurrency limits,
and disabled outreach were preserved. No guessed email, person enrichment,
authentication-profile import, form submission or outbound message was used.
Unknown/blocked/failed states remained distinct in the database, API, UI and
scoring. Failed sites were not assigned inflated Digital Gap scores.

The previously documented REST-provider network boundary remains: Python cannot
intercept every browser subresource or intermediate redirect before it happens.
This phase did not claim or implement a production egress sandbox. Runtime
browser logs and profiles are not repository artifacts.

### Recommendation: NEEDS PHASE 3B.2 FIXES

The real integration and lifecycle now pass, and the discovered product defects
were fixed. However, two of five sites repeatedly failed to navigate and one
remained partially loaded. Six determinate manual checks still received unknown
answers. Live provider discovery and reputation-backed scoring could not be
validated without configured credentials. A further bounded validation/fix phase
should resolve or characterize those reliability/coverage limits before treating
this sample as readiness for scaling. Do not bypass protection or enlarge the
sample to hide failures. No Phase 3C work was started.

## Git scope

Only the browser adapter, rendered detectors, targeted regressions, UI smoke
validation and these setup/report documents belong to this change. No secrets,
runtime data, screenshots, browser cache, CamoFox checkout, dependencies or user
instruction Markdown files are included. Four pre-existing Codex phase
instruction files remain untracked and must not be described as a fully clean
working tree. Commit/push verification is reported separately for the final
`origin/lead-engine-v1` revision; upstream is never a push target.
