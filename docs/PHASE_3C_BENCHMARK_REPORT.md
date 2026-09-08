# Phase 3C Live Discovery + 25→50 Benchmark Report

Date: 2026-09-08 (Asia/Karachi)
Branch: `lead-engine-v1`
Base commit: `256e660` (`phase 3b2: improve camofox audit reliability`)

## 1. Environment

- Windows PowerShell, Python 3.12.10, isolated `.venv` created from the declared requirements.
- SQLite runtime databases were temporary files outside the repository; no runtime database was committed.
- Discovery-key readiness was checked as presence-only. `SERPER_API_KEY`, `GOOGLE_PLACES_API_KEY`, and `YELP_API_KEY` were all configured locally; no values were printed or copied here.
- Search jobs were run one at a time. Browser concurrency remained 2 and pages per business remained 3.
- The CamoFox health endpoint at `http://127.0.0.1:9377/health` was unavailable during the benchmark.

## 2. CamoFox version

No live CamoFox service was running, so no live service version could be measured. The repository’s pinned target remains official `jo-inc/camofox-browser` source revision `e5a36f5cd0332fde6597de474329a308a53a0716`, package version 1.14.0, as documented in `docs/CAMOFOX_SETUP.md`.

## 3. Discovery provider

Primary provider: **Google Places (Legacy)**.

All three configured adapters passed their opt-in one-request smoke tests. Google was selected because it supplies stable place IDs, an authoritative website field through Place Details, and documented token pagination; Yelp’s active path does not provide an authoritative business website, and Serper is intentionally one-page in this adapter.

## 4. Provider API/contract used

- Text Search (Legacy): `GET https://maps.googleapis.com/maps/api/place/textsearch/json`.
- Place Details (Legacy): `GET https://maps.googleapis.com/maps/api/place/details/json` with fields for name, address, phone, website, rating, review count and Maps URL.
- Search pages return up to 20 records; the adapter follows up to three `next_page_token` pages and performs the bounded activation retry required by the Legacy contract.
- Google’s current documentation confirms up to 60 results over three pages and a short token activation delay: <https://developers.google.com/maps/documentation/places/web-service/legacy/search-text>.
- The benchmark’s second-page sequence returned a normalized `provider_unavailable`; no raw provider body or credential was retained.

## 5. Benchmark niche/location

- Category: Roofing
- City: Dallas
- State: Texas (`TX`)
- Opportunity profile: `website_conversion`

## 6. Stage A — 25-run

- Requested: 25
- Raw provider records returned: 20
- Unique provider records persisted: 20
- Duplicate records removed: 0 within the isolated Google run
- Businesses persisted: 20
- Businesses in requested city/state: provider query was Dallas/TX; no out-of-area count was observed in the persisted metadata review
- Businesses with authoritative provider website: 20
- Businesses without verified website: 0 at discovery time
- Invalid provider websites: 0
- Audits attempted: 20
- Completed audits: 0
- Partial audits: 0
- Failed audits: 20 (`browser_unavailable`)
- Blocked audits: 0
- Job result: **partial**, 20/25 discovered
- Discovery exhaustion reason: normalized `provider_unavailable` after the first Google page plus Place Details sequence; the job did not fabricate the missing five records.
- Runtime: approximately 118 seconds from job creation to terminal state.

## 7. Stage A manual validation

Ten provider records were reviewed for name, provider ID, Maps provenance URL, city/state metadata and website-field provenance. All ten had provider IDs and provider-supplied website fields; no domain was constructed or guessed. Because CamoFox was unavailable, ownership of each website and live city/site relationship could not be confirmed, so those live checks are **unclear**, not positive.

| Classification | Count |
| --- | ---: |
| Correctly confirmed live | 0 |
| Wrong website | 0 observed, live confirmation unavailable |
| Wrong business | 0 observed in provider metadata, live confirmation unavailable |
| Ambiguous | 10 for live website ownership |
| Duplicate | 0 |

- Website precision: not measurable from this run; live verification was unavailable.
- Business identity precision: not measurable from this run; provider metadata was internally consistent.
- Duplicate rate: 0/20 in the isolated persisted sample.
- Email precision: not measurable; no audited public emails were produced.
- Phone precision: not measurable; provider phone fields were present, but no live page audit or manual call verification was performed.

Detector truth labels and positive precision for forms, social, CTA, booking, chat and public contact were not measurable because all browser audits failed before rendered evidence collection. No detector strictness was changed.

## 8. Stage A gate decision

**FAIL**.

The provider did not reach 25 because its next-page request failed. More significantly, CamoFox was unavailable, producing a 100% browser failure rate and no live detector or scoring validation. The persistent job remained bounded and represented failures as failures/unknowns rather than gaps.

## 9. Stage B — 50-run

Not run. The Phase 3C gate failed, so the specification prohibits starting Stage B.

## 10. Stage B manual validation

Not applicable; no Stage B job was created.

## 11. Discovery quality

The isolated Google run produced 20 unique records with provider IDs and provider website fields. It did not meet the 25 target because pagination/provider availability failed after the first page. A preliminary run with all keys enabled also confirmed that the current product architecture cycles all configured sources; that run was not used as the isolated benchmark dataset.

## 12. Website precision

No wrong or guessed website was observed in stored discovery records. Website ownership precision remains unvalidated because CamoFox was offline. This is a validation gap, not a positive precision claim.

## 13. Duplicate rate

0 duplicates removed in the isolated 20-record Google job. The preliminary multi-source run contained cross-provider physical branches; it was excluded from this rate.

## 14. Browser reliability

| Metric | Result |
| --- | ---: |
| Audits attempted | 20 |
| Completed | 0 |
| Partial | 0 |
| Failed | 20 |
| Blocked | 0 |
| Average/median duration | Not reported separately; service-unavailable attempts were bounded |
| Sessions created/closed | 20 attempts; remote session closure could not be confirmed while service was down |
| Teardown failures | 20 cleanup markers persisted (`cleanup_pending=1`) |
| Browser process baseline/peak/end | No local CamoFox process observed |
| Browser memory baseline/peak/end | Not available |

The application preserved evidence rows and wrote unknown opportunity scores for failed audits; failed sites did not receive a high opportunity score.

## 15. Contact precision

The discovery records carried provider phone fields for 20 businesses. No public emails were produced by the failed browser audits. Email and phone precision therefore remain unmeasured.

## 16. Detector precision

Not measurable in Stage A because no rendered DOM was obtained. Offline detector regression tests passed; no live false-positive pattern was inferred.

## 17. Score distribution

All 20 persisted score rows had `opportunity_score = unknown`/null, `evidence_confidence = 0`, and no digital-gap score. Distribution: unknown 20; 0–19: 0; 20–39: 0; 40–59: 0; 60–79: 0; 80–100: 0. Mean, median, min and max are not applicable to the numeric subset.

## 18. Commercial usefulness counts

0 commercially usable candidates under the required definition (verified business + verified website + available opportunity score + medium/high evidence confidence + at least one public contact path). The run did not establish purchase intent.

## 19. Resource measurements

- FastAPI/Python CPU and memory: not instrumented for this bounded run.
- CamoFox process/memory: unavailable; no service process was listening.
- SQLite: temporary benchmark DB grew from 4 KiB initialization to approximately 733 KiB; no lock, busy-timeout or write-failure was observed.
- The job completed without duplicate claims. Browser cleanup markers remained because the remote service was unavailable; no live process leak could be assessed.

## 20. Error taxonomy

Stage A job/audit errors:

| Code | Count | Share of 20 persisted audits |
| --- | ---: | ---: |
| `browser_unavailable` | 20 | 100% |

Job-level discovery error: `provider_unavailable` after 20/25 records. No unsafe redirect, guessed website, CAPTCHA bypass, proxy circumvention or authentication automation occurred.

## 21. Persistence/restart behavior

The benchmark job used persistent search-job, item, audit, evidence and score tables. Terminal state, all 20 item records, 20 audit histories, cleanup markers and unknown scores remained queryable after completion. A controlled FastAPI restart was not performed because this run already had a provider shortfall and no available CamoFox service; the existing offline restart/cancellation regression suite passed.

## 22. CSV validation

Stage B CSV validation was not applicable. Existing offline CSV tests passed, including job scoping, formula neutralization and preservation of status/unknown semantics.

## 23. Security regression

The full offline suite confirmed SSRF and redirect validation, no guessed emails, no personal enrichment, no login/cookie/form automation, no CAPTCHA bypass, no proxy circumvention, blocked/failed/partial semantics, owner-scoped jobs, safe CSV/rendering, retired outreach 404 behavior and CamoFox access-key redaction. No secret value was printed, committed or written into this report.

## 24. Bugs found/fixed

No application defect was fixed. The benchmark exposed two environmental/provider readiness limitations: CamoFox was not running, and the Google second-page sequence returned `provider_unavailable` after a successful first page. Neither was changed in this phase; no regression code was added.

## 25. Remaining product risks

- CamoFox must be running and authorized before any live website evidence or browser reliability claim can be made.
- Google pagination/detail availability must be investigated with provider-side diagnostics that do not expose credentials before another 25-run.
- Website ownership, detector precision, contact precision, scoring direction, CSV job isolation and resource behavior over 50 businesses remain unvalidated.
- The current worker uses every configured discovery source; a future benchmark should isolate a selected provider through supported configuration or an explicit product change.
- Provider retention/attribution and production architecture decisions remain unresolved.

## 26. Recommendation

### NEEDS PHASE 3C.1 PRODUCT QUALITY FIXES

Stage A failed its required gate: it returned only 20/25 after a provider-unavailable pagination failure, and all browser audits failed because CamoFox was unavailable. Stage B was correctly not started. Phase 3C.1 should first establish a healthy CamoFox service and diagnose the bounded Google pagination failure, then repeat Stage A before any 50-lead benchmark or Phase 4 design.

## Tests

- Full offline regression: **141 passed, 4 skipped**, after installing `requirements-dev.txt` into `.venv`.
- `python -m compileall -q .`: passed.
- `python -m pip check`: passed.
- `node --check foundation.js`: passed.
- `node --check audit_engine/extract.js`: passed.
- Serper, Google Places and Yelp opt-in provider smoke tests: passed (one request each; no raw payload persisted).
- Real CamoFox opt-in integration: attempted and failed with normalized `browser_unavailable` because the service was not listening; this is reported as an environment blocker.

## Git status

The only tracked change from this phase is this report. Existing untracked `CODEX_PHASE_*.md` instruction files were left untouched and are not included in the commit.
