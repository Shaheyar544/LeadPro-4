# Lead qualification and evidence UX

The Leads page answers who the business is, how to contact it, which website conversion gaps were confirmed, and how much of the audit was reliable. It uses saved browser evidence and performs no discovery or browsing when a salesperson opens a result.

## Summary model and provenance

`lead_summary.py` computes `qualification_summary_v1` on demand. It is a read model, with no schema migration, database writes, contact deletion, score recalculation, or duplicated durable truth. Production API list/detail responses include `summary`; the table, detail view and CSV share this projection.

The summary contains browser-observed display identity, website/location, canonical contacts, source references, confirmed strengths/gaps, unknown checks, Primary Opportunity, audit explanation, page cards, stored scores and commercially usable status. Contacts and findings retain evidence IDs, source URLs and confidence. Production detail retains all current-audit raw evidence and contacts; `observation_id` also preserves the detector's original ID alongside its database row ID. Stored score references are unchanged.

Production loads a search in a bounded batch (eight read queries with observations), then filters/sorts before pagination. Results, counts, detail and CSV use the selected owner's search in the current run mode. The legacy development server uses the same presentation model while retaining its provider suppression policy.

## Evidence and audit semantics

Scoring statuses remain authoritative for the seven `website_conversion_v2` checks. Other browser checks use the existing conservative aggregation. No scoring weights or formulas changed.

| Evidence status | Presentation |
| --- | --- |
| present | Confirmed strengths |
| absent, with confidence ≥ 0.8 and supporting observations | Confirmed conversion gaps |
| unknown | Could not confirm |
| failed | Could not confirm, explicitly marked failed |
| blocked | Could not confirm, explicitly marked blocked |
| not_applicable | Omitted from the main summary, retained in technical evidence |

Partial page absence cannot override an aggregate Unknown finding. Unavailable checks never count as missing features. Summaries focus on contact/conversion features; diagnostic detectors remain in technical evidence. Rejected contacts do not become public-contact strengths.

| Audit status | Label |
| --- | --- |
| completed | Completed |
| partial, numeric opportunity and evidence confidence ≥ 40 | Partial — useful evidence |
| other partial | Partial — limited evidence |
| failed | Failed — insufficient evidence |
| blocked | Blocked by website |
| no audit | Website not verified |

Partial explanations normalize navigation failures, rendering timeouts and browser unavailability. Unknown error codes receive a neutral explanation; raw errors or stack traces are never shown as the customer-facing explanation. Findings describe the bounded set of inspected pages, not the entire website.

## Contact canonicalization

Only existing public browser observations are eligible. Provider-only, rejected, script-only and invalid contacts are excluded. Eligible contacts require confidence ≥ 0.8. No email, telephone number, branch designation or contact path is constructed.

US telephone formatting variants normalize through the existing phone validator and display once. Distinct numbers and extensions remain distinct. Canonical contacts combine all raw IDs and page URLs and display an observation count plus High/Medium/Low confidence language. Original rows remain unchanged.

Phone selection favors a number observed on both homepage and contact page, then an explicitly evidenced main number, then an explicitly evidenced matching branch, then other public numbers. Ties use confidence, page count and stable value ordering. Arbitrary excerpts containing several branches do not establish a branch label. Ambiguous selection is explained; other numbers are collapsed as “Additional public number” unless a verified branch label exists.

Email case and repeated observations normalize to a single entry. An already observed general address (`office`, `info`, `contact`, etc.) is preferred over another branch's address; remaining addresses are collapsed. This ordering never creates an address or asserts that it belongs to a searched branch.

Facebook, Instagram and LinkedIn company profiles normalize platform host/profile variations. YouTube channel/profile URLs collapse supported tab variations; case-sensitive channel IDs remain distinct. Posts, videos, share links and short video URLs are excluded. Raw observations preserve original URLs.

## Primary Opportunity and scores

Primary Opportunity is deterministic; it uses no AI. The priority is:

1. Insufficient Evidence when a reliable numeric opportunity is unavailable, evidence confidence is below 40, or the audit is failed/blocked/unverified.
2. Quote / Estimate Conversion for a confirmed absent quote form.
3. Online Booking for a confirmed absent booking form.
4. Contact Conversion for a confirmed absent contact form or contact page.
5. Click-to-Call for a confirmed absent click-to-call path.
6. CTA Improvement for a confirmed absent meaningful primary CTA.
7. Mobile Conversion for a confirmed mobile-layout issue.
8. Website Performance for a confirmed performance issue.
9. No Strong Gap Confirmed when no qualifying gap is confirmed.

Unknown/failed/blocked findings never create an opportunity label. Weakness is not inferred from a missing measurement. Performance findings outside the v2 scoring profile do not change its score.

| Stored assessment | Opportunity display |
| --- | --- |
| Missing score, insufficient confidence, failed/blocked/unverified audit | Not enough evidence |
| Completed, sufficient assessment, numeric zero | 0; No confirmed conversion gap |
| Useful partial assessment, numeric zero | No confirmed gap |
| Sufficient assessment, positive score | Stored numeric score |

The four score cards show Opportunity, Digital Gap, Evidence Confidence and Contact Confidence. Keyboard-accessible “About” disclosures contain the score explanations. “Why this score” lists confirmed scored gaps/strengths and explains that Unknown checks were excluded. Numeric values and `website_conversion_v2` remain intact internally and in CSV.

“Usable lead” calls the existing `commercially_usable_v2` predicate with verified browser identity/URL, audit, stored score and public contacts. It indicates enough evidence and a contact path for review. It never means purchase intent.

## Identity and website presentation

Browser-observed structured identity and verified visible branding take priority when supplied. Current production identity comes from the selected audit's homepage observation, never a later search's title/URL or a Google display name. Missing website identity remains unverified.

SEO title fragments are shortened only if the same bounded brand fragment occurs in titles on at least two distinct observed pages. One-page titles remain intact. Examples validated against saved Dallas audits: New View Roofing, PRIORITY ROOFING, T Rock Roofing and Blue Hammer Roofing. Arrington's single-page SEO title is retained because independent corroboration was unavailable.

The location is explicitly the **search location**, not a claim that every phone belongs to that branch. URL labels remove only `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `gclid` and `fbclid`. Functional query parameters remain. Stored/source URLs and validated destination hrefs remain available.

## Workflow, filters and sorting

The default is the latest search in the current mode, including an empty or unfinished search. Historical rows are not silently mixed in as fallback. The selector lists the last 50 searches with category, location, local date/time and discovered count. Selecting a previous search also selects its audit, score, identity, detail and CSV context.

Table columns: Business, Location, Website, Primary Opportunity, Opportunity, Evidence, Contact, Audit Status, Details. Contact lists Phone/Email/Contact Page/Form availability with confidence secondary. Failed/blocked records remain visible unless filtered.

Filters: audit status, Primary Opportunity, minimum evidence confidence, has phone, has email, has actionable contact path and minimum opportunity. A minimum opportunity filter excludes insufficient assessments, even if a stale numeric value exists. Filters apply on submit and can be cleared together.

Sort options: useful leads first (then opportunity, then evidence), opportunity descending, evidence descending, contact confidence descending, business name and audit status. Ties are stable. CSV exports every matched row in the displayed search/order, not just the current page; unsubmitted control edits do not change the export.

## Detail, accessibility and security

Detail order: identity → audit summary and score cards → Primary Opportunity → public contact → confirmed strengths → confirmed gaps → could not confirm → pages inspected → why this score → collapsed technical evidence.

“Show technical evidence” exposes every detector key/status/value, source URL, excerpt, confidence, detector version, timestamp and ID. Nested disclosures retain raw contacts and the stored score breakdown. No provenance rows are removed.

The native dialog supports Escape, keyboard close and focus return. Statuses include text. Semantic headings, visible focus, native controls and reduced-motion styles are retained. Tables become business cards on smaller screens; contact/page sections stack on mobile. Dark and light themes use the existing tokens. Desktop, tablet, narrow mobile and landscape layouts are exercised by the opt-in browser check.

Untrusted data uses element creation/text content, never HTML interpolation. All clickable evidence/website links require validated HTTP(S), open in a new tab and set `noopener noreferrer`. Credentials, userinfo, control characters and unsafe schemes are rejected. Session/logout race protection, cookie auth, CSRF and separate LIVE/OFFLINE projects/volumes remain in place.

## CSV

Default export fields: business name, search location, validated canonical website, primary phone/email, contact page, contact paths, Primary Opportunity, stored opportunity plus its display label, Digital Gap, Evidence Confidence, Contact Confidence, raw audit status, commercially usable flag and score profile/version.

Raw evidence, detector dumps and provider payloads are excluded by default. Formula-leading values remain apostrophe-protected and CSV quoting is handled by the standard writer. Google display names, ratings, reviews, addresses and other restricted provider content are not introduced into the summary/export. Runtime CSVs are excluded from the Docker build context.

## Validation

Default tests use no external discovery API. The regression suite covers contact normalization/provenance, branch distinctions, rejected contacts, social profile exclusions, opportunity rules, unavailable/zero/positive scores, status grouping, immutable raw evidence, tracking-only display cleaning, XSS/CSV safety, mode/owner/search isolation, historical identity and bounded query count.

Run the Python suite, compileall, dependency check and both JavaScript syntax checks. `tests/browser_smoke.py` exercises stored XSS and development UI behavior. `scripts/validate_local_stack.py` exercises isolated OFFLINE cookie/CSRF/worker/Redis/CSV behavior. It must never be redirected to LIVE.

For the existing five-business LIVE validation dataset:

```powershell
.venv/Scripts/python.exe scripts/validate_qualification_ui.py --job-id <existing-five-business-search-id>
```

This opt-in script checks current-search isolation, detail/score/contact provenance, filtered CSV, cookie reload, collapsed raw evidence, keyboard focus, safe links and responsive themes. It permits only local UI traffic and explicitly blocks search submission. Artifacts stay under ignored `.local-integration`. No new Google searches are required.

## Recorded local validation — 2026-09-08

- Windows: **242 passed, 16 skipped**, plus 143 subtests. PostgreSQL test container: **249 passed, 9 skipped**, plus 143 subtests. The existing AnyIO deprecation warning remains.
- Full compileall, dependency check, both JavaScript syntax checks, Alembic schema check and Gitleaks passed.
- Real Edge checks passed for LIVE and isolated OFFLINE: cookie reload, filtered CSV, stored XSS, collapsed technical data, logout races, Escape/focus return, desktop/tablet/mobile/landscape and both themes.
- Isolated OFFLINE production validation passed auth/CSRF/rate limiting, API/worker/Redis restart recovery, browser outage handling and provider/log leakage checks.
- Existing Dallas validation: Blue Hammer and New View completed; T Rock and Priority had useful partial evidence; Arrington had limited partial evidence and an unavailable opportunity score. Priority retained 37 distinct public numbers with additional numbers collapsed, preserving 77 raw contact records.
- The newer saved Phoenix HVAC search (10 businesses) remained the default; switching to the older Dallas search (5 businesses) selected that search's evidence and CSV only.
- **Zero new LIVE searches/businesses were submitted.** Nine LIVE data tables retained identical complete-row hashes: 15 businesses, 15 items, 15 audits, 42 pages, 1,327 evidence rows, 116 contact rows, 15 scores, 15 provider references and five retained jobs (including three legacy jobs).
- Evidence/scoring functions, LIVE/OFFLINE Compose isolation and persistent data were preserved. Screenshots, runtime exports, private configuration and instruction files are excluded from commits.
