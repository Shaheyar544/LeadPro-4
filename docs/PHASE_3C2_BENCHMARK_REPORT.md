# PHASE 3C.2 COMPLETE — Benchmark Report

Date: 2026-09-08 (Asia/Karachi)  
Branch: `lead-engine-v1`  
Base: `1fda0d3`

## Why Legacy is no longer benchmark primary

Legacy remains feature-frozen for rollback and tests. Its page-token pagination repeatedly returned `INVALID_REQUEST`; the benchmark now uses Places API (New), which has a separate adapter and response schema.

## Google Places migration

- New adapter: `google_places_new`; Legacy adapter retained as `google_places`.
- Endpoint: `POST https://places.googleapis.com/v1/places:searchText`.
- Authentication: `X-Goog-Api-Key`; explicit `X-Goog-FieldMask`.
- Key source: configured New key when present, otherwise the existing configured key was tested for New authorization. No key value was printed or persisted.
- Places API (New) authorization: **passed**; a live New integration test returned a place ID and parsed fields.
- No automatic Legacy fallback is used for New benchmarks.
- Text Search New supplied the benchmark data, so no redundant per-result Place Details calls were made.

## Field mask

`places.id, places.displayName, places.formattedAddress, places.websiteUri, places.nationalPhoneNumber, places.rating, places.userRatingCount, places.primaryType, places.businessStatus, nextPageToken`.

Website, phone, rating, and review-count fields can select higher Places pricing tiers. Google-supplied sites remain candidates and pass the existing normalization, SSRF, redirect, public-network, and browser evidence checks.

## Pagination

- Page size: 20; maximum 3 pages.
- Page 1: 20 places.
- Page 2: requested successfully and supplied enough additional records to reach 25.
- Page 3: not requested.
- API requests: 2.
- Results are deduplicated by namespaced IDs (`google_places_new:<place-id>`).
- New pagination does not use Legacy token-readiness retries; HTTP/API failures are normalized explicitly and earlier pages are preserved.

## CamoFox preflight

- Health: passed.
- Real browser integration: passed.
- Harmless open/evaluate/close preflight: passed before discovery calls.
- Browser concurrency: 2; pages per business: 3.
- Sessions created/closed: 25/25; remaining tabs/sessions: 0/0; cleanup errors: 0.

## Stage A — 25

- Requested/discovered/unique/persisted: 25/25/25/25.
- Authoritative website candidates: 25.
- Businesses without `websiteUri`: 0.
- Completed audits: 14.
- Partial audits: 9.
- Failed audits: 2.
- Blocked audits: 0.
- Qualified: 23.
- Discovery target: met; provider status: successful.
- Runtime: approximately 208 seconds.

## Stage A quality

A manual review of 10 records checked identity, provider ID, Maps provenance, website ownership, Dallas/Texas relationship, duplicates, public email/phone, forms, social profiles, CTA, booking and chat evidence.

- Correct: 8.
- Wrong website: 0.
- Wrong business: 0.
- Ambiguous: 2.
- Duplicates: 0.
- Public email-bearing businesses: 9; reported emails were source-backed.
- Public phone-bearing businesses: 25; no inferred contacts.
- Detector precision: no systemic false-positive pattern observed; formal external truth labels were unavailable.
- No guessed websites, emails, personal enrichment, login, cookies, form submission, CAPTCHA bypass, or proxy circumvention.

## Stage A gate

**FAIL**. Discovery and New pagination passed, but 11 of 25 audits were partial or failed. This is a meaningful browser evidence-quality defect, so Stage B is prohibited.

## Stage B — 50

Not run. The specification requires stopping after a failed Stage A quality gate.

## Discovery quality and scores

- Numeric scores: 23; unknown scores: 2.
- 0–19: 0; 20–39: 17; 40–59: 6; 60–79: 0; 80–100: 0.
- Mean: 36.93; median: 35.27; minimum/maximum: 27.40/57.98.
- Commercially usable candidates under the existing definition: 0.
- Failed/blocked evidence did not receive confidently high opportunity scores.

## Browser performance

- Audit average: 16.34 seconds; minimum/maximum: 2.12/46.13 seconds.
- Process baseline/peak/end: approximately 73/151/149 MB working set; CamoFox health reported approximately 146 MB RSS near peak.
- Browser sessions created/closed: 25/25.
- Cleanup failures: 0; idle cooldown: zero active tabs/sessions.

## Persistent jobs

The complete job, discovery state, item statuses, audit history, scores and contacts persisted in SQLite. No lock/write errors or duplicate items were observed. The benchmark database ended with zero pending cleanup rows.

## CSV validation

The existing job-scoped export path was exercised for the authenticated owner. Formula-safe cells and status fields remained intact; Google provider provenance and browser evidence/contact source URLs remain distinguishable. No raw evidence blobs or credentials were exported.

## Provider integrations

- Serper: pass.
- Google Places Legacy: pass (rollback adapter smoke).
- Yelp: pass.
- Google Places New: pass (authorized live integration and benchmark provider).

## Google data-policy note

Google Maps Platform terms, attribution, retention and export policy remain unresolved for unrestricted production CSV use. Place IDs have distinct caching treatment, and Phase 4 must establish a compliant retention/attribution policy while keeping Google fields separate from independently observed website evidence.

## Tests

- Full regression: 151 passed, 5 skipped (opt-in integrations disabled in the default suite).
- `compileall`, `pip check`, and both Node syntax checks: passed.
- Real CamoFox integration: passed.
- Google Places New integration: passed.
- Existing configured-provider integrations: passed.

## Security regression

SSRF/private-IP and redirect enforcement, owner scoping, cancellation, persistence, cleanup, no-guessed-contact rules, XSS-safe rendering, formula-safe CSV, retired outreach behavior, and provider/CamoFox key redaction remain covered and passing. No new infrastructure was added.

## Recommendation

### NEEDS MORE PHASE 3C PRODUCT QUALITY FIXES

Places API (New) authorization, pagination and discovery target succeeded. The Stage A quality gate remains failed because browser evidence was partial or failed for 11 of 25 businesses. Fix and retest browser evidence quality before Phase 4.

## Git status

Only the migration code, tests, provider documentation and this report are included in the phase commit. `.env`, databases, browser artifacts, CamoFox checkout and instruction Markdown files are excluded.

## Stop

Do not begin Phase 4 automatically.
