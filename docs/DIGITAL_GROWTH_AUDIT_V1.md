# Digital Growth Audit v1

Digital Growth adds Technical SEO, On-Page SEO and Local SEO opportunities to the existing public business website audit. Higher opportunity scores mean stronger **confirmed improvement opportunities**, not better SEO health. Rankings, traffic, purchase intent and results are not predicted or guaranteed.

## Architecture and evidence ownership

The production worker still uses PostgreSQL jobs and leases, Redis coordination and one isolated CamoFox session per business. `AuditEngine` performs one controlled crawl. Its existing rendered-DOM observation now also returns bounded metadata, headings, schema facts, image counts, internal navigation and location context. Conversion and the three SEO profiles share these observations. There is no second HTML scraper or SEO browser pipeline.

The original conversion page selection runs first. A separate view of those page IDs, observations and contacts goes to the unchanged `website_conversion_v2` scorer. Additional SEO pages cannot change the conversion denominator, audit completeness or contact-confidence input. Additional verified public contacts remain available in the contact view.

`digital_growth_crawl_v1` identifies the shared detector facts. Generic `AuditEvidence` JSONB records retain facts, sources, observation IDs, timestamps and detector versions. The existing single `LeadScore` row remains `website_conversion_v2`; its JSONB breakdown contains the versioned `digital_growth_summary` and SEO profiles. No new tables, migration, SQLite production path or transaction around browsing is introduced. The current Alembic head remains `0003` (local mode isolation).

Raw page observations are stored once in `AuditEvidence`. Detail/report views hydrate them on read; the client report reuses the canonical browser-observed business name and profile evidence. The overall profile references its module findings by key instead of copying their raw facts.

Historical audits without SEO observations display **Not assessed**. An attempted audit with insufficient evidence displays **Not enough evidence**. Reading the dashboard never re-audits historical businesses. The development read model can project profiles from explicit versioned growth evidence, but never infer missing facts from an old conversion score.

## Controls and bounds

Production Compose enables the audit. Configuration is environment-only and uses the existing launchers and Compose projects:

| Setting | Default | Hard bound |
| --- | ---: | ---: |
| `DIGITAL_GROWTH_AUDIT_ENABLED` | `true` in production; `false` in development | Boolean |
| `SEO_MAX_PAGES_PER_SITE` | 6 | 1–10 |
| `SEO_MAX_LINK_CHECKS` | 12 | 0–50 |
| `SEO_RESOURCE_BUDGET_SECONDS` | 12 | 1–30 seconds |
| `SEO_MAX_SERVICE_PAGES` | 5 | 0–5 |
| `SEO_MAX_LOCATION_PAGES` | 5 | 0–5 |

The page cap includes conversion pages, failed attempts and SEO pages. Original conversion selection is capped by the configured total when an operator deliberately lowers it. Priority is the existing homepage/contact/quote/booking selection, followed by advertised service, location and about pages. URLs are deduplicated; query-driven pages, account/logout/cart actions and download routes are not crawl candidates. A page can be retried only under the existing browser recovery rules. Session, tab and timeout bounds remain in force.

Small HTTP probes supplement browser evidence for robots, sitemaps, response headers and sampled internal-link status. They do not extract page HTML or discover a second page graph. Each hop is normalized, public DNS addresses are checked and pinned, TLS is verified, and automatic redirects, proxies, cookies and credentials are disabled. Resource requests stay on the exact origin; only the explicit HTTP-to-HTTPS test allows a scheme change on the same host. At most three redirects and six seconds per resource request are allowed. Resource bodies are capped at 512 KiB with no decompression. Internal-link checks run at concurrency two with a 30-second overall budget. Unfinished, denied and failed checks remain Unknown.

The entire post-crawl resource phase has a tighter configurable **12-second default budget**. Cancellation closes outstanding probes and preserves completed facts. Initial HTTP URLs may establish an observed same-host HTTPS upgrade before selecting the robots origin; robots itself never follows across origins. No protocol upgrade is guessed.

Robots rules are read before browsing. LeadEngine honors the matching agent/path rules; an unavailable or unparseable policy stops browsing conservatively. A missing robots file (404/410) permits access. Agent matching, merged groups, longest path precedence, allow ties, wildcard/end matching and percent-encoding are tested. A Googlebot disallow finding describes only the inspected path; it does not claim deindexing or sitewide blocking.

Sitemap discovery checks up to two robots declarations plus `/sitemap.xml`, on the same origin only. XML DTDs/entities are rejected. At most 500 URLs per document, two children of one index and no recursive index traversal are inspected. External locations are rejected. A negative finding means **not found at the checked locations**, never “the site has no sitemap.” Sitemap URLs do not expand the browser crawl.

## Technical SEO

The profile covers observed noindex directives, canonical declarations, HTTPS and mixed resource references, response health, robots path permissions, sitemap discovery, titles/descriptions and duplicate metadata within the sample, viewport metadata, H1 presence, structured-data presence and JSON-LD syntax, missing image alt attributes and sampled broken internal links.

Canonical observations distinguish self references, same-origin alternatives, cross-domain targets, conflicting/invalid declarations and absence. Alternative targets require manual review; the engine cannot know Google's selected canonical. An unqualified `X-Robots-Tag: noindex` can confirm a directive; agent-qualified headers remain technical evidence. Redirect counts come only from an observable HTTP probe chain. Browser-service HTTP errors are never presented as business website HTTP status.

Schema extraction uses `JSON.parse`, bounded traversal and an allowlist of entity fields and relationships. It never executes JSON-LD or persists arbitrary schema, ratings, review bodies or offers. The checked-in type closure contains 150 LocalBusiness types/subtypes from the official Schema.org graph, retrieved September 9, 2026. Microdata types are recognized. Syntax validity does not establish rich-result eligibility. LocalBusiness/structured-data presence on one suitable page satisfies the presence check; it is not required on every contact page. A malformed block is tracked independently as `present_but_invalid_json`.

Entities pointing to another origin are excluded from business identity. Their exclusion makes a negative schema conclusion Unknown, since the engine cannot resolve that identity safely. Name and address strings are normalized conservatively for within-site comparison; unresolved brand variations and branch differences are not automatic NAP failures.

Multiple H1s, heading hierarchy skips, title/description length, empty decorative alt, image dimensions and lazy-loading counts are informational. Missing alt attributes are distinct from empty alt. The audit does not identify orphan pages from this limited graph.

## On-Page SEO

Page classification uses URL, observed navigation hints, title and headings, with an explicit confidence. The audit records identifiable topics, title/H1/supporting-text overlap, generic titles, supporting service details, contact navigation, observed local context, headings, paragraph/section counts, FAQ and media presence. Word count, exact-match keywords and keyword density are not ranking rules. Missing FAQ/video is not automatically a gap.

Advertised service topics come from observed headings and service links. A service not represented in the sample is a **possible_missing_service_page**, labeled **Dedicated page not found in audited sample**, with lower confidence and Unknown status. It does not receive confirmed-gap points or an automatic service recommendation. Multi-area expansion is shown for manual review only when the website explicitly names multiple served areas: “Create useful, unique location/service pages where the business genuinely serves those areas.” No doorway-page prescription is generated.

## Local SEO

The audit uses website-observed address context, public phone observations, LocalBusiness/subtype schema, service areas, contact/location pages, map/directions paths and testimonial/review integration presence. The schema's address/geo/hours fields are observed context; optional fields are not mandatory. Structured phone values never become extracted contacts. Public contacts continue to require the existing visible-text/tel/mailto evidence and normalizers.

NAP comparison is within the website sample only. It compares single-phone pages associated with the same explicit normalized address. Different numbers become a review finding, including the possibility of call tracking. Multiple addresses, branch directories, multiple phones or unconfirmed addresses remain Unknown. No address is guessed, geocoded or supplemented from Google Places. Short visible location-text snippets are contextual observations, not a canonical city parser.

Missing street addresses are Unknown because service-area businesses may omit them intentionally. Review/map integration means an observed section or link, not its review contents. **GBP audit not configured** remains explicit. This is not a citation audit or an assessment of Google Business Profile completeness.

## Sales and presentation

`digital_growth_summary` contains the unchanged conversion result, three SEO profiles, `digital_growth_opportunity_v1`, top opportunities, `recommended_services_v1`, `sales_opportunity_priority_v1`, overall evidence coverage, page analysis and measurement limitations. `client_growth_audit_v1` is a reusable report model with empty future agency name/logo fields, executive summary, evidence, recommendations and disclaimer; no PDF or agency configuration flow is added.

Services and top opportunities come from one deterministic, versioned mapping in `growth_scoring.py`. Only sufficiently supported confirmed gaps qualify. At most three opportunities and three distinct services are returned. Severity, evidence confidence and commercial usefulness are encoded in the documented rules, and public contactability affects priority. No prices or purchase-intent claim are added. See [SEO scoring](SEO_SCORING_V1.md) for exact formulas and precedence.

The Leads table stays at ten compact columns: Business, Location, Website, Top opportunity, Opportunity, Recommended service, Evidence, Contact, Audit status and Details. Older rows explicitly identify conversion-only scores. Detail preserves the existing conversion/contact experience and adds a Growth overview, Technical SEO, On-Page SEO and Local SEO sections. Findings/unknowns and raw technical evidence use native accessible disclosures. Public contact deduplication, partial explanations and source access remain intact.

Growth filters select top opportunity, recommended service, minimum module opportunity and minimum growth evidence. Sorting includes top opportunities, each module and growth evidence; existing conversion/contact/business filters remain. API and CSV use the same owner/mode/search projection, filters and order. CSV retains current conversion/contact columns and adds all fifteen requested growth summary columns, without raw evidence. All cells remain formula-safe and all links use the existing safe-link policy. Rendering uses DOM text properties, not untrusted HTML.

## Isolation, security and future providers

LIVE still uses Google Places New discovery, real private CamoFox, PostgreSQL and Redis. Only allowed provider IDs and independently observed website evidence persist. No Google name/address/phone/rating/review-count/type/status payload enters SEO detection. OFFLINE uses explicitly injected SEO/resource fixtures and a separate project/database volume, with no external resource calls and no LIVE fallback. No existing data is deleted.

Cookie auth, CSRF, rate limits, lease fencing, browser cleanup, SSRF rules, network isolation, XSS protections and safe CSV remain active. The audit does not click forms, authenticate to businesses, bypass challenges, use proxies or collect private content.

`growth_providers.py` provides abstract contracts for `serp_rank_tracking_v1`, `off_page_seo_v1`, `social_media_audit_v1` and `page_performance_v1`. Rank, backlink and social modules stay **NOT CONFIGURED**, with no scores or network implementations. Existing PageSpeed Insights may supply a real attributed lab measurement when configured and successful. Otherwise performance is not configured/unavailable and Core Web Vitals remain **Not assessed**. Navigation timing is only an operational duration metric.

## Validation and limitations

Regression fixtures cover strong, technical-gap, weak on-page, weak local and blocked sites. Tests cover the shared crawl and preserved conversion result, robots/XML/SSRF bounds, metadata/schema, service/NAP conservatism, scoring/deduplication, persistence, filters/CSV and browser UI/XSS. PostgreSQL tests run only in the isolated test database. Local launcher, recovery and auth checks use OFFLINE Compose; saved LIVE data and at most five fresh businesses validate the real pipeline.

Operational metrics include attempted/observed pages, one session plus any controlled recovery, elapsed duration, page cleanup errors and partial status. Final measured results and manual precision are recorded in the task report. Small samples cannot establish general production latency, sitewide SEO coverage or market precision. No historical bulk re-audit or next development phase is started.

### Re-evaluating a small validation from saved evidence

The operator-only `python -m lead_engine.reprocess_growth --job-id JOB_ID` command dry-runs one completed validation of at most five businesses in the active mode. Review its before/after scores and services, then append `--apply` to persist the reviewed calculation. It makes **zero browser/provider requests**, records an audit event, and preserves original conversion results, contacts, page facts, timestamps and historical searches. It is intended for this pre-release calibration, not a bulk historical re-audit. This release corrects topic interpretation when a clear title exists without an H1 or a contact-page heading contains generic words.

Run `python scripts/validate_growth_ui.py --job-id JOB_ID` for read-only LIVE API/CSV and responsive browser validation. It blocks search submission and external browser requests. `validate_qualification_ui.py` continues to verify the earlier conversion-only Dallas sample. Artifacts, screenshots and credentials remain in the ignored local integration directory.

## Detector references

- [Robots Exclusion Protocol, RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html)
- [Google robots interpretation](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec)
- [Google canonical URL guidance](https://developers.google.com/search/docs/crawling-indexing/consolidate-duplicate-urls)
- [Google robots meta and X-Robots-Tag guidance](https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag)
- [Schema.org LocalBusiness](https://schema.org/LocalBusiness) and its [official vocabulary graph](https://schema.org/version/latest/schemaorg-current-https.jsonld)
