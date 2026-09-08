# PHASE 3C.3 COMPLETE — Evidence Quality Calibration Report

Date: 2026-09-08 (Asia/Karachi)
Branch: `lead-engine-v1`
Base: `831c0a3`

## Phase 3C.2 root-cause decomposition

The prior 25-run produced 23 numeric scores but zero commercially usable candidates because the review used a narrower practical gate than the product definition: it effectively required a fully completed audit and treated partial evidence as unusable. Four partial audits nevertheless had medium evidence confidence, and 14 completed audits had high confidence. Public phone evidence was present for the businesses and website corroboration raised contact confidence, but the old review did not count phone/form/contact-page paths consistently.

The Phase 3C.2 evidence formula was `100 * detector coverage * confidence mean * page coverage` (`render_coverage_v2`). Not-applicable detectors were excluded from the denominator; unknown/failed states reduced coverage. Completed sites generally scored 81.67–82.50, while partial render/operation failures fell to 23.33–59.72. Contact confidence was high where website `tel:`/visible evidence existed, but provider-only contacts remained low.

### Commercial-usefulness gate failures (Phase 3C.2)

Counts are non-exclusive; the single dominant reason uses priority: audit failed, identity/website unresolved, evidence below threshold, no public path, opportunity unavailable, other.

| Gate/reason | Count |
|---|---:|
| Identity not verified/ambiguous | 2 sample ambiguities; no systemic failure |
| Website not verified | 0 provider candidates; failed audits had no usable verification |
| Opportunity score unavailable | 2 |
| Evidence confidence below medium | 7 |
| No public contact path | 0 among usable website audits; provider-only paths were not promoted |
| Audit failed | 2 |
| Primary dominant: audit failed | 2 |
| Primary dominant: evidence below threshold | 7 |
| Primary dominant: other/old gate excluded partial | 16 |

The old rule therefore returned 0 despite valid phone/form/contact paths and numeric scores. No contact was guessed.

### Partial audits

All nine Phase 3C.2 partial audits were classified as: render instability/timeouts 6, navigation failure after partial evidence 1, browser block 1, and incomplete bounded operation 1. The dominant pattern was secondary-page render/evaluate instability, not page-selection depth.

### Failed audits

The two failures were one `browser_tls_error` and one `browser_navigation_timeout`. Browser health was available at job level, no usable positive DOM evidence was persisted for either, and bounded retry behavior did not produce evidence. They correctly remained failed rather than being relabeled partial.

## Evidence coverage

Phase 3C.2 detector aggregation showed the largest unknown/failed totals in: booking widget (65), chat widget (65), meta pixel (43), Google Tag Manager (33), and PageSpeed (24). Widget unknowns were mostly legitimate absence of an observable widget or failed pages; they were not converted to absence. `not_applicable` remains excluded from the confidence denominator. Phone, title, reachability, HTTPS, final URL, and CTA evidence were highly assessable on completed pages.

Page selection previously allowed only one generic secondary page. The bounded refinement now ranks Contact, Quote/Estimate, Booking/Schedule, About, and Services, preserves same-origin/SSRF checks, and still caps the crawl at three pages (hard cap four).

## Contact-path analysis

The v2 public-path rule accepts a verified public business phone or `tel:`, public email or `mailto:`, visible contact/quote form, booking/scheduling action, or authoritative contact page. Provider-only data remains low confidence and cannot qualify by itself. This separates contact-path availability from email presence and from opportunity scoring.

## Evidence-confidence analysis

No opportunity weights or thresholds were lowered. `rendered_dom_v1.3` adds bounded iframe metadata (source, accessible title and nearby label) to existing rendered evidence so clearly identified booking/chat/form widgets can be observed without navigation or interaction. The confidence formula remains coverage-based and does not reward a weak site or the presence of a contact.

## Identity ambiguity analysis

The two prior ambiguous records involved incomplete visible business/location corroboration rather than duplicate IDs or guessed domains. Provider IDs, provider addresses, website URLs, and rendered titles remain separate provenance. Ambiguous identity is not silently converted to verified identity.

## Changes made

- Conversion-oriented same-domain page ranking with quote/booking categories, without increasing crawl depth.
- Safe iframe/widget metadata extraction and provenance-aware widget detection.
- Explicit `has_public_contact_path` and conservative `commercially_usable_v2` helpers.
- Regression tests for page ranking, phone/form-only paths, failed audits, low confidence, and provider-only contact rejection.
- CSV/provider provenance and existing security behavior retained.

## Version changes

- Detector version: `rendered_dom_v1.3`.
- Evidence confidence version: `render_coverage_v2` unchanged; no historical rows overwritten.
- Commercial definition: `commercially_usable_v2`.
- Opportunity score weights: unchanged (`website_conversion_v1`).

## New Stage A — 25

- Requested/discovered/unique/websites: 25/25/25/25.
- Audits: 15 completed, 7 partial, 3 failed, 0 blocked.
- Numeric scores: 22; unknown: 3.
- Evidence confidence: 15 high, 4 medium, 6 low/zero.
- Commercially usable v2: 19/25 (76%).
- Browser concurrency/pages: 2/3; New pagination used two API requests and reached target.

## Stage A manual validation

A stratified review of 12 records covered completed/high-confidence, partial, high/low opportunity, and failed/unknown cases. Identity and website checks found no systemic wrong-site pattern; ambiguous cases remained ambiguous. Reported email and phone paths were checked against rendered/provider source evidence; no guessed contacts were present. Detector direction and evidence-confidence ordering matched the observed completeness: completed pages scored high, partial pages lower, and failed pages unknown/zero.

## Stage A quality gate

**PASS.** Discovery reached 25, New pagination succeeded, the revised rule produced 19 commercially usable candidates, medium/high evidence confidence was 76%, no systemic identity error or guessed contact was observed, and cleanup/persistence remained stable.

## Stage B — 50

- Requested/discovered: 50/50.
- Websites: 49 (one New record had no usable website URI).
- Audits: 31 completed, 12 partial, 4 failed, 2 blocked; one item remained unverified.
- Processed/qualified: 50/43.
- Evidence confidence among scored records: 31 high, 8 medium, 11 low/zero.
- Numeric/unknown scores: 43/7.
- Commercially usable v2: 39/50 (78%).
- A stratified 12-record review covered high, medium, low, partial, failed/unknown, usable and unusable cases. No systemic wrong-site issue or guessed contact was found.

## Discovery and contact quality

New Text Search pagination returned the requested target without Legacy fallback. Stage A had 25 provider website candidates; Stage B had 49. Stage A contained 63 email and 177 phone contact rows; Stage B contained 91 email and 281 phone rows. Manual precision checks found all sampled emails and at least ten sampled phone/contact paths source-backed. Detector false positives remained absent/low; failed pages were not treated as confirmed absence.

## Score distribution

Stage A scores: 22 known, 3 unknown; mean 37.12, median 36.99, range 26.83–57.98. Stage B scores: 43 known, 7 unknown; mean 35.16, median 33.70, range 23.74–57.98. The distribution remained conservative; no opportunity-weight change was justified.

## Browser performance

- Stage A average audit: 16.89 seconds; range 2.79–47.13 seconds.
- Stage B average audit: 13.78 seconds; range 0.01–45.27 seconds.
- Concurrency remained 2; pages/business remained 3; hard cap remained 4.
- Sessions were closed after each audit; idle CamoFox health showed zero active tabs/sessions and no cleanup-pending rows.
- No concurrency tuning or infrastructure was added.

## Persistence

Both fresh jobs, historical Phase 3C.2 records, item states, audit history, scores, contacts and cleanup markers remained separate and durable. No duplicate score per audit run, SQLite lock/write error, or cancellation/restart regression was observed. Export remains owner-scoped and now includes provider/provider-record provenance alongside browser source URLs.

## Security

SSRF/private-IP and redirect validation, owner scoping, cancellation, cleanup, no guessed contacts, no personal enrichment, no login/cookies, no form submission, no CAPTCHA bypass, no proxy circumvention, unknown/partial/failed semantics, XSS-safe rendering, formula-safe CSV, retired outreach routes, and key redaction remain covered.

## Google data-policy note

Google attribution, retention, caching and unrestricted export policy remain unresolved. Place IDs and Google-sourced fields must remain provenance-separated from independently observed website evidence; Phase 4 must define compliant retention, attribution, CSV/export and provider-substitution policy.

## Remaining limitations

Render and navigation instability still causes meaningful partial/failed audits, especially on third-party or TLS-problematic websites. Widget absence cannot be asserted when the page is incomplete. No aggressive crawl-depth increase or score-weight tuning was made.

## Recommendation

### NEEDS MORE PHASE 3 PRODUCT QUALITY FIXES

The revised Stage A gate passed and Stage B completed with 39 commercially usable candidates, but Stage B still had 18 partial/failed/blocked audits. Browser evidence reliability needs another bounded quality pass before Phase 4 architecture.

## Stop

Do not begin Phase 4 automatically.
