# PHASE 3C.1 COMPLETE — Benchmark Report

Date: 2026-09-08 (Asia/Karachi)
Branch: `lead-engine-v1`
Base: `e9114e2` (`phase 3c: validate live lead benchmark`)

## Previous failure root cause

- **CamoFox:** the Phase 3C run had no browser service listening, so all audits became `browser_unavailable` after discovery had already spent quota.
- **Google pagination:** Legacy Text Search page 1 returned 20 records and a token, but every page-token request returned `INVALID_REQUEST`, previously normalized incorrectly as `provider_unavailable`.

## CamoFox preflight

- Official checkout: `jo-inc/camofox-browser`, pinned revision `e5a36f5cd0332fde6597de474329a308a53a0716`, package 1.14.0.
- Node 22.23.2 and npm 11.6.3 were used outside the repository after official SHA-256 verification.
- Service configuration used loopback, headless mode, crash reporting off, persistence off, VNC off and YouTube off.
- Health: passed.
- Real integration (`RUN_CAMOFOX_INTEGRATION_TESTS=1` against `https://example.com`): passed.
- Application preflight: passed harmless open/evaluate/close before the benchmark request.
- Cleanup: preflight and all 20 benchmark audit runs ended with zero remaining tabs/sessions and zero cleanup-pending rows.

The live start route now fails with `PHASE 3C.1 BLOCKED — CAMOFOX PREFLIGHT FAILED` before creating a job or resolving live discovery sources when the production browser provider is unavailable. Test-injected offline providers retain their isolated test path.

## Discovery provider

- Selected provider: Google Places Legacy Text Search + Legacy Place Details.
- Google was selected because the prior page returned 20 real provider IDs with authoritative website fields and the API documents three token pages.
- Google smoke: passed.
- Serper smoke: passed.
- Yelp smoke: passed.
- No API key value was printed, logged, committed or copied into this report.

## Google pagination fix

- Pagination now tracks the token issued by the immediately preceding successful response; stale arbitrary cursors do not receive token-readiness treatment.
- A fresh token receives an initial two-second wait, then at most three additional two-second waits (four token requests total, approximately eight seconds elapsed).
- `OK` and `ZERO_RESULTS` stop immediately. `OVER_QUERY_LIMIT`, `REQUEST_DENIED`, `UNKNOWN_ERROR`, malformed responses, transport timeout and HTTP transport errors have distinct normalized paths.
- Page state records page number, token-attempt count, readiness wait duration, observed statuses and token presence without storing the token itself.
- Regression scenarios cover successful delayed tokens, bounded invalid-token exhaustion, quota, denial, zero results, stale tokens and target counts that do not require a second page.

## Stage A — 25

- Requested: 25
- Page 1: 20 results
- Page 2: no usable results; four `INVALID_REQUEST` token attempts, then `page_token_not_ready_timeout`
- Page 3: not reached
- Raw/unique/persisted: 20/20/20
- Authoritative provider websites: 20
- Completed audits: 11
- Partial audits: 7
- Failed audits: 2
- Blocked audits: 0
- Discovery target: partial (20/25)
- CamoFox concurrency: 2
- Pages per business: 3
- Runtime: approximately 200 seconds

## Stage A quality

A manual review of ten records checked business name, provider ID, Maps provenance, provider website, city/state relationship and duplicate identity. Eight were confirmed correct from provider and rendered evidence; two remained ambiguous because the site evidence was incomplete. No wrong website, wrong business or duplicate was observed, and no domain was guessed.

- Sample: 10
- Correct: 8
- Wrong website: 0
- Wrong business: 0
- Ambiguous: 2
- Duplicates: 0
- Public email-bearing businesses: 9; reviewed reported emails were source-backed, with no inferred addresses.
- Public phone-bearing businesses: 20; representative phone evidence was observed from provider or public `tel:` links.
- Email/phone precision: not independently population-validated beyond this bounded sample.
- Detector precision: not independently calculable without a separate external truth label; offline detector tests passed.

## Stage A gate

**FAIL**.

The required target was not met because Google Legacy pagination remained unavailable after bounded token retries. CamoFox was healthy and cleanup was stable, but the provider shortfall alone prevents the Stage A gate from passing.

## Stage B — 50

Not run. The specification requires stopping after a failed Stage A gate.

## Score distribution

Of 20 discovered businesses, 18 had numeric opportunity scores and 2 remained unknown because their audits failed.

- Unknown: 2
- 0–19: 0
- 20–39: 13
- 40–59: 5
- 60–79: 0
- 80–100: 0
- Mean numeric score: 37.76
- Median numeric score: 36.55
- Min/max numeric score: 27.40 / 57.98
- Evidence confidence: 11 high (≥70), 3 medium (40–69.99), 6 low/unknown (<40)

Failed/unknown sites did not receive a confidently high opportunity score. These internal bands are not purchase-intent or conversion-likelihood estimates.

## Commercially usable candidates

0 under the Phase 3C definition (verified business + verified website + available opportunity score + medium/high evidence confidence + at least one public contact path). This is not a purchase-intent claim.

## Browser performance

- Audit attempts: 20
- Average duration: 17.41 seconds
- Median duration: 15.18 seconds
- Completed/partial/failed: 11/7/2
- Browser process baseline: approximately 73 MB working set after service start
- Peak observed service RSS: approximately 151 MB
- End observed service RSS: approximately 149 MB working set; service health reported 142 MB RSS
- Sessions created/closed: 20/20 at the application level
- Remaining tabs/sessions after job: 0/0
- Cleanup failures: 0
- Bounded idle observation: service checked after completion; zero active tabs/sessions, with no queued application cleanup.

## Persistent jobs

- Job and item state persisted across the complete run.
- No controlled FastAPI restart was performed during this paid partial run; offline restart/cancellation tests passed.
- Duplicate scores/items: none observed.
- SQLite lock, busy-timeout and write errors: none observed.
- Cleanup-pending reconciliation: the benchmark database ended with zero pending cleanup rows; the repository runtime database had no prior pending rows to reconcile.

## Provider smoke tests

- Serper: configured, pass.
- Google Places Legacy: configured, pass for one search plus bounded Details parsing.
- Yelp: configured, pass.

## Tests

- Full regression: **148 passed, 4 skipped**.
- `python -m compileall -q .`: passed.
- `python -m pip check`: passed.
- `node --check foundation.js`: passed.
- `node --check audit_engine/extract.js`: passed.
- Real CamoFox integration: passed, not skipped.
- Provider integrations: all three passed, not skipped.

## Security regression

Verified by the full suite and code review: SSRF and redirect enforcement; owner-scoped persistent jobs; no guessed email or personal enrichment; no cookies, login automation or form submission; no CAPTCHA bypass or proxy circumvention; blocked/failed/partial/unknown semantics; safe CSV and DOM rendering; retired outreach routes; and CamoFox access-key redaction. No new infrastructure was added.

## Bugs discovered

- Google Legacy page-token responses remain `INVALID_REQUEST` beyond the bounded readiness window for this configured project/query.
- The prior generic `provider_unavailable` classification was insufficiently specific.

## Fixes made

- Added mandatory real-browser preflight before production live discovery.
- Added owner-capacity check so preflight does not mask the existing bounded 429 response.
- Hardened Google Legacy token readiness, fresh-token tracking, status taxonomy and diagnostics.
- Added offline regression coverage for all specified token/status scenarios.

## Recommendation

### PHASE 3C.1 BLOCKED — GOOGLE PROVIDER FAILURE

CamoFox preflight and live integration now pass, but Google Legacy pagination still cannot obtain page 2 within the conservative, billable-request retry bound. Stage A therefore remains partial at 20/25 and the 50-lead benchmark is correctly prohibited. Resolve the Google project/API pagination issue, then repeat Stage A before Phase 4.

## Git status

Only application code, regression tests and this report are staged for this phase. `.env`, runtime databases, CamoFox checkout, profiles, logs and instruction Markdown files are excluded from the commit.
