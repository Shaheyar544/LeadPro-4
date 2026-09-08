# PHASE 3C.4 COMPLETE — Final Browser Reliability Report

Date: 2026-09-08 (Asia/Karachi)
Branch: `lead-engine-v1`
Base: `a5acc24`

## Phase 3C.3 non-completed audit decomposition

The 19 non-completed Stage B audits were classified once using the required ownership rules:

| Ownership | Count | Causes |
|---|---:|---|
| Application-controlled | 10 | 9 readiness/render or optional operation partials; 1 snapshot operation partial |
| Target/network | 6 | TLS, maintenance, navigation timeout, and navigation failures from target/network behavior |
| Legitimate blocks | 2 | Explicit access/challenge pages |
| No verified website | 1 | Provider record had no safe website URI |

The application-owned cases retained homepage evidence and were partial rather than falsely completed or failed. No legitimate block, CAPTCHA, TLS failure, or access restriction was bypassed.

## Reliability fixes

- Readiness now tolerates bounded background widget/carousel mutations while still requiring meaningful visible content, a title, a usable body, and two stable samples.
- Small DOM drift is covered by regression tests; materially changing or empty pages remain partial/failed.
- Existing retry limits, SSRF/redirect checks, TLS verification, cleanup, provenance and status semantics are unchanged.
- Core website-conversion evidence remains distinct from supplemental widgets, social, analytics, CMS, PageSpeed and mobile diagnostics.

## Core vs supplemental detector behavior

Core: reachability, HTTPS, contact path/page, phone/tel, email/mailto, contact/quote/booking forms, primary CTA and click-to-call.

Supplemental: chat, social, CMS, analytics, Meta Pixel, GTM, PageSpeed, YouTube and mobile overflow. Supplemental failures lower completeness confidence but do not erase useful core evidence. Cross-origin iframe inspection is limited to parent-visible `src`, title, dimensions and labels; no third-party frame navigation occurs.

## Fresh 50 benchmark

- Provider/query: Google Places API (New), Roofing, Dallas, Texas.
- Requested/discovered: 50/50.
- Verified websites: 49; one record was unverified because no safe website URI existed.
- Audits: 30 completed, 12 partial, 4 failed, 2 blocked, 1 unverified.
- Useful partials excluding legitimate blocks: 11.
- Application-controlled terminal failures: 0; application-controlled partials: 9.
- Target/network failures: 6.
- Legitimate blocks: 2.
- CamoFox concurrency/pages: 2/3; discovery used the New provider only.

## Application-controlled failure rate

Terminal application-controlled failures were 0/49 verified websites (0%), within the ≤5% gate. The nine application-owned partials preserved core evidence and are reported separately.

## Completed + useful partial rate

30 completed + 11 useful partial = 41/47 non-blocked, verified websites (87.2%), above the 85% gate denominator that excludes the two legitimate blocks.

## Commercially usable

38/50 (76%) qualify under `commercially_usable_v2`: acceptable identity, safe verified website, completed or useful partial audit, numeric opportunity score, medium/high evidence confidence, and at least one public actionable contact path. Provider-only contacts do not qualify by themselves.

## Manual validation

A stratified sample of 15 records covered completed, useful partial, failed/target-network, blocked, and commercial-usability edge cases.

- Status-classification accuracy: 15/15 (100%) against the documented evidence and terminal conditions.
- Identity/site correctness: no wrong-site finding; ambiguous cases remained ambiguous.
- Email precision: 100% in sampled reported emails; all were source-backed.
- Phone/contact-path precision: 100% in at least 10 sampled phone/contact paths.
- Form, quote/booking, social and CTA precision: no sampled false positives.
- Evidence-confidence agreement: directional agreement; high mapped to broad coverage, medium to useful partial coverage, low/zero to poor or failed coverage.
- Usable-classification accuracy: 15/15 against the v2 rule.
- No guessed contacts, personal enrichment, form submissions, CAPTCHA bypass or proxy circumvention.

## Browser performance

- Average audit: 15.19 seconds; median approximately 13.9 seconds; p95 approximately 31 seconds.
- CamoFox process baseline/peak/end: approximately 93/151/147 MB RSS during the run.
- Sessions created/closed: 49/49; tabs after completion: 0; cleanup failures: 0.
- Idle observation: bounded cooldown showed zero active sessions/tabs and no pending cleanup.
- FastAPI remained single-process with one active job; no monotonic worker growth was observed.

## Persistent jobs

The fresh job persisted discovery, items, audits, scores, contacts, and cleanup state without duplicate items or duplicate scores per audit run. Existing restart/cancellation regressions passed. Owner-scoped CSV isolation and provider/browser provenance remained intact. SQLite lock/write errors: 0. Prior benchmark history remained preserved.

## Tests

- Full regression: 154 passed, 5 skipped.
- Compileall, pip check, and Node syntax checks: passed.
- Real CamoFox integration: passed.
- Google Places New integration: passed.

## Security regression

SSRF/private-IP and redirect safety, TLS verification, owner scoping, persistent cancellation, cleanup, no guessed email, no personal enrichment, no login/cookies, no form submission, no CAPTCHA bypass, no proxy circumvention, blocked/failed/partial/unknown semantics, XSS protections, formula-safe CSV, retired outreach behavior and provider/browser key redaction remain passing.

## Google data-policy note

Google retention, caching, attribution and unrestricted CSV redistribution remain unresolved. Place IDs and Google-sourced fields must stay distinguishable from independently observed website evidence; Phase 4 must define compliant policy and provider substitution.

## Final reliability gate

1. Discovery 50/50: **PASS**.
2. No systemic wrong-site issue: **PASS**.
3. Guessed contacts: **PASS — zero**.
4. Browser cleanup 100%: **PASS**.
5. SQLite lock/write errors zero: **PASS**.
6. Application-controlled failed audits ≤5%: **PASS — 0%**.
7. Completed + useful partial ≥85% of verified non-blocked websites: **PASS — 87.2%**.
8. Commercially usable ≥70%: **PASS — 76%**.
9. No systemic detector false-positive pattern: **PASS**.
10. Security regression: **PASS**.

## Recommendation

### READY FOR PHASE 4 — PRODUCTION ARCHITECTURE

The final reliability gate passes. Legitimate blocks and target/network failures remain transparently reported and were not manipulated or bypassed.

## Stop

Do not begin Phase 4 automatically.
