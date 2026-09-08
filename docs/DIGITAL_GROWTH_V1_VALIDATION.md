# Digital Growth v1 local validation

Validated September 9, 2026 (Asia/Karachi), on `lead-engine-v1`. This is a local commercial-validation candidate, not a public deployment or evidence of general SEO accuracy.

## Scope and data conservation

The existing five-business Dallas conversion sample was checked first. Its earlier captures did not contain the SEO facts required to validate the new detectors. Exactly one fresh Google Places New search processed **five Roofing businesses in Dallas, TX**, using the production worker and private CamoFox. No additional search or business crawl was submitted. The discovered identities matched existing businesses.

The database now contains 25 businesses, 7 searches, 30 audits and 90 saved pages. Checksums of all pre-existing rows in businesses, searches/items, audits/pages/evidence, contacts, scores and provider references matched the pre-change snapshot. A local PostgreSQL dump was taken before live validation. No records or volumes were deleted.

Two pre-release calibrations used only the new search's saved structured facts: removing false topic gaps and correcting shared-family aggregation. Their dry runs were reviewed before applying. All five original conversion scores, contacts, page records and raw structured observations remained identical. Earlier searches were not recalculated.

## Measured LIVE results

Scores below are **opportunities**, not health scores or ranks. Zero means no confirmed gap in the assessable checks. Unknown checks do not contribute gap points.

| Observed business | Audit | Pages observed / attempted | Technical | On-Page | Local | Overall | Recommended services |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Blue Hammer Roofing | Completed | 10 / 10 | 0 | 0 | 0 | 12.24 | Quote Funnel Improvements; Conversion Optimization |
| New View Roofing | Completed | 10 / 10 | 0.5 | 0 | 0 | 8.04 | Quote Funnel Improvements; Conversion Optimization |
| PRIORITY ROOFING | Partial | 8 / 8 | 0 | 0 | 50 | 12.2 | Schema Implementation |
| Arrington Roofing (longer browser title retained) | Partial | 1 / 2 | 5.56 | 0 | 0 | 3.45 | Internal Linking Improvements |
| Unverified business | Failed: robots preflight unavailable | 0 / 0 | Not enough evidence | Not enough evidence | Not enough evidence | Not enough evidence | None |

The last result is not assigned a name or website from transient provider data. An older search contains independently observed identity for that business, but the failed current audit does not borrow it. There were **zero fixture businesses** in LIVE results or CSV.

## Manual evidence review

Five leads were reviewed across sitemap, canonical, title/description, H1, schema, service-page analysis, local context and recommendations. Four had assessable SEO captures; the fifth had none and remained Unknown. Review compared findings with saved structured CamoFox observations and bounded HTTP probe records. It was not a second sitewide crawl.

| Business | Sitemap | Canonical / metadata | H1 | Schema / local handling | Service analysis / recommendation review |
| --- | --- | --- | --- | --- | --- |
| Blue Hammer | Index observed | Self canonical, title and description on all 10 pages | Present on all 10 | LocalBusiness/RoofingContractor on location pages satisfies presence; other pages need not repeat it | Service/location pages observed; unsampled topics remain possible only. Contact heading must not become an unclear-topic gap. Conversion recommendations retained. |
| New View | Index observed; URL sample capped | Self canonicals and title/descriptions observed | One of 10 pages lacks a visible H1 | HomeAndConstructionBusiness/LocalBusiness recognized | Clear storm-repair title and content establish topic despite missing H1. The minor H1 issue stays in evidence, below Top Sales promotion threshold. |
| Priority | Index observed | Self canonicals and metadata observed | Multiple H1s on location pages are informational | Only BreadcrumbList found in these captures; LocalBusiness/subtype missing in the sample. Branch phone differences remain Unknown | Location pages exist; possible service-page suggestions remain unscored. Schema recommendation supported by captured markup. |
| Arrington | URL-set sitemap observed | Self canonical, title and description observed on the one useful page | Multiple H1s informational | HomeAndConstructionBusiness/RoofingContractor recognized; limited coverage explicit | One sampled link returned HTTP 404 at capture. Link cleanup is limited to that observation; missing service pages are not asserted. |
| Unverified | Unknown | Unknown | Unknown | Unknown | No services or numeric SEO scores fabricated. |

**Gap precision within this saved-evidence review:** the original five SEO gap findings contained three supported findings and two false topic findings (**3/5, 60%**). The two false findings were removed and regression-tested. The remaining three agree with their captured source facts (**3/3, 100% observed-evidence agreement**). This is a tiny calibration sample, not independently established market-wide detector precision. Recall was not measured; the inaccessible business is excluded from that precision denominator.

Independent read-only spot checks corroborated New View's homepage metadata/schema/sitemap and the clear topic of its storm-repair page and Blue Hammer's contact page. Several direct rechecks could not obtain a usable robots response and were stopped. A cached public rendering of Arrington's link existed while the audit's live HEAD response was 404; a later direct probe was unavailable. Its finding therefore describes the timestamped probe, not a guaranteed persistent outage. No access restriction was bypassed.

The source pages used for the topic correction were [New View storm repair](https://newviewroofing.com/storm-damage-repair/) and [Blue Hammer contact](https://bluehammerroofing.com/contact/). Neither supports an unclear-topic claim merely because a heading is missing or generic contact wording is used.

## Performance and bounds

The measured fresh run used the initial **10-page / 50-link** limits. Durations were 46.399, 63.210, 51.420, 9.357 and 0.997 seconds. Mean: **34.277 seconds/business**; nearest-rank p95: **63.210 seconds**. Mean observed pages: **5.8**; attempts: **6.0**. Four browser contexts were needed; the fifth stopped before creating one. No page cleanup error occurred. CamoFox ended with zero tabs/sessions and no pending cleanup records.

The previous conversion-only Dallas search took **65.966 seconds** end to end for 13 saved pages. The fresh growth search took **173.516 seconds** for 29 saved pages. These are different observations, not a controlled latency comparison, but the increase was substantial. Final defaults were reduced to **6 pages, 12 links and a 12-second supplemental resource budget**, retaining hard caps of 10 pages, 50 links and concurrency two. Location/service limits include the classified starting page. Cancellation and caps are regression-tested.

**The reduced defaults were not remeasured on another LIVE search**, to respect the five-business limit. Latency under those defaults should be measured in the next explicitly authorized commercial validation. Partial audits keep useful evidence; unavailable checks stay Unknown. A browser timing is never a Core Web Vitals or PageSpeed score.

An idle snapshot after validation used approximately 95 MiB API, 63 MiB worker and 132 MiB CamoFox memory. These are point-in-time observations, not peak capacity claims.

## Regression and security checks

- Real PostgreSQL suite: **311 passed, 10 skipped, 143 subtests passed**. Skips are environment-specific browser/provider checks; actual Windows browser checks run separately.
- Windows full suite: **304 passed, 17 skipped, 143 subtests passed**. The installed-Edge DOM/UI harness covers extraction, stored XSS, formula-safe CSV, search cancellation/reload, keyboard behavior, dark/light and responsive layouts.
- Read-only LIVE growth UI validation covers five results and **20 API/CSV views**, including sorting and service/module/evidence filters. Historical five-lead conversion UI validation also passes.
- OFFLINE production-like stack checks pass for cookie sessions, CSRF, rate limiting, session revocation, PostgreSQL readiness, Redis restart, API restart and worker SIGKILL recovery without duplicate audit/score rows.
- Private CamoFox open/evaluate/close, blocked SSRF targets, browser network isolation and private service ports pass. Only loopback Caddy is published.
- PostgreSQL custom dump restored to a new isolated validation database with equal row counts/checksums, including new SEO JSONB evidence and scores. Existing Alembic head remains `0003`; no new migration was needed.
- Provider canaries are absent from durable tables, CSV and service logs. Candidate-tree Gitleaks scan reports no leaks.
- LIVE/OFFLINE projects, volumes and fixtures remain separate. Existing one-click launcher rebuild/readiness validation passes. Runtime exports, backups, credentials, screenshots and instruction files are excluded from commits.

CI status and exact commits are recorded in the final task report. Rank tracking, Off-Page SEO, Social Media Audit and GBP assessment remain not configured. No public deployment or next phase was started.
