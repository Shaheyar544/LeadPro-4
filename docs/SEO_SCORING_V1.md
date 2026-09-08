# SEO opportunity scoring v1

These are internal product conventions, not universal SEO standards. **Higher means a stronger confirmed improvement opportunity.** A low score is not a Google ranking, sitewide quality certification or guarantee. Unknown never becomes absent.

## Per-profile calculation

Each detector produces an observed pass, confirmed gap or Unknown, with its source page, confidence, observation ID and detector version. Only pass/gap observations with confidence at least **0.8** qualify. A URL/check contributes once. Exact duplicate evidence cannot increase score or evidence confidence; conflicting captures select the highest-confidence, latest observation deterministically.

For check `k`:

```text
gap_fraction[k] = confirmed_gap_pages / assessed_pages
assessed_weight = sum(weight[k] for assessable checks)
coverage = 100 * assessed_weight / sum(all profile weights)
opportunity = 100 * sum(weight[k] * gap_fraction[k]) / assessed_weight
```

Each profile's weights total 100. Values are rounded to two decimals. Scoring requires at least **3 assessable checks** and **40% weighted coverage**. Otherwise the numeric score is `null`, with **Not enough evidence**. Historical unassessed profiles use `null` and **Not assessed**. Partial browser audits can score when these thresholds are met. An incomplete DOM cannot confirm a page-level absence; independently observed complete-head metadata and explicit facts such as an image missing an alt attribute can remain assessable.

Site-level presence checks (`schema`, `local_schema`, `address`, `directions`, `review_integration`) use positive presence from any suitable inspected page. They do not penalize other pages for omitting the same feature. JSON-LD syntax is a separate check. Unparseable markup does not prove LocalBusiness markup is absent. Other checks use the observed page gap fraction. Findings always retain the sampled URLs and never assert sitewide absence.

### technical_seo_v1

| Check | Weight |
| --- | ---: |
| Indexing directives | 15 |
| Canonical declaration | 10 |
| HTTPS delivery | 5 |
| Page title | 5 |
| Meta description | 5 |
| Distinct sampled titles | 5 |
| Distinct sampled descriptions | 5 |
| Viewport declaration | 5 |
| Structured-data presence | 5 |
| JSON-LD syntax | 5 |
| H1 presence | 5 |
| Image alt attributes | 5 |
| Secure resource references | 5 |
| HTTP response health | 5 |
| Sampled internal link health | 5 |
| Sitemap discovery | 5 |
| Robots path permission | 5 |

404/410 confirms a missing probed destination. Timeouts, access blocks, unsupported HEAD responses and transient server errors remain Unknown, with available status retained as evidence. Missing canonical or sitemap is an observed optimization opportunity, not proof that either is mandatory or that rankings are impaired. Alternate/cross-domain canonicals remain manual-review observations. Multiple H1s, title lengths and optional image settings are informational.

### on_page_seo_v1

| Check | Weight |
| --- | ---: |
| Descriptive title | 20 |
| Title/H1/supporting-text topic alignment | 20 |
| Identifiable page topic | 15 |
| Supporting service detail | 20 |
| Internal contact navigation | 15 |
| Location/service-area context | 10 |

A clearly generic title can be a confirmed gap. A missing H1 is a technical observation; it does not erase a clear topic established by the title or contact/about/location context. Lack of lexical overlap alone is Unknown, not a mismatch penalty. Supporting detail is assessed on service pages. Word count/FAQ/video are observations, not score thresholds. A dedicated service page not found in the sample is Unknown and does not add points. Conversion CTA/form checks are displayed through the original conversion profile and are not rescored as on-page failures.

### local_seo_v1

| Check | Weight |
| --- | ---: |
| Website address context | 20 |
| Same-address NAP comparison | 20 |
| Location/service-area context | 15 |
| LocalBusiness/subtype presence | 25 |
| Contact/directions evidence | 10 |
| Website review integration presence | 10 |

Absent street addresses, unresolvable multi-branch phone differences, absent review widgets and unavailable direction checks are Unknown. Only comparable same-address, single-phone pages can confirm differing public phones, with a call-tracking caveat. LocalBusiness schema is recognized through the checked-in official subtype closure, not an exact-string-only test. GBP, external citations and Google review metrics are not assessed.

## Bands

| Opportunity | Label |
| --- | --- |
| 0 to less than 20 | Low |
| 20 to less than 40 | Moderate |
| 40 to less than 60 | Meaningful |
| 60 to less than 80 | Strong |
| 80 to 100 | Very Strong |

Evidence confidence is **weighted assessment coverage**, not a probability that a lead will buy. Per-observation confidence is recorded separately. A partial score of zero means no gap was confirmed in assessable checks; it does not mean a perfect website.

## digital_growth_opportunity_v1

The aggregate uses assessable checks from sufficiently supported SEO profiles. Each check carries its profile weight. Shared signal families contribute once: title/descriptive title, H1/page topic, general/local schema, and internal contact navigation/contact-page conversion. The greatest assessed gap fraction owns the family; ties retain fixed Technical, On-Page, Local, Conversion precedence. This prevents generic schema presence from erasing a confirmed LocalBusiness markup gap while avoiding two votes for that family. Identical keys such as location context also contribute once. JSON-LD syntax is distinct from presence.

Assessable conversion checks contribute weight **10 each**, appended after SEO, when conversion has a numeric score and at least 40% coverage. Conversion's existing seven-check score is never rewritten. Shared contact navigation is not counted again. Unknown conversion checks are excluded.

```text
overall = 100 * sum(unique_signal_weight * gap_fraction)
                  / sum(unique_assessed_signal_weight)
```

An overall number requires at least **2 sufficient SEO profiles** and **5 unique assessable signals**. The full unique-signal breakdown records each owner, weight and fraction. Overall growth evidence coverage is the mean of the three SEO coverage values; unavailable modules contribute zero coverage, never gap points. Rank/backlink/social/performance data do not enter this formula. The aggregate is not an average or inversion of unrelated health scores.

## Primary opportunities, services and priority

The versioned `RULES` table in `growth_scoring.py` is the configurable service/priority mapping. Changes to its meaning require a new rules/profile version and regression expectations. It contains no prices or agency credentials.

Within a sufficient profile, the highest rule priority among confirmed gaps becomes the primary label. Ties use the detector key. Without a gap, the label is **No Strong [module] Gap Confirmed**; without sufficient coverage it is **Insufficient Evidence**.

Top Sales Opportunities combine eligible profile gaps and confirmed conversion gaps. A SEO check qualifies when at least **25% of its assessable page observations** confirm the gap, or its severity is at least **85**. This keeps an isolated minor heading issue visible in evidence without promoting it into a sales recommendation. Order is descending rule severity, then descending observation confidence, then stable profile/key order. Repeated signal families and labels are removed. Return at most **3**. `recommended_services_v1` returns at most **3 distinct services** from these opportunities, preserving their order. Unknown checks, possible missing pages and unconfigured providers never generate recommendations.

`sales_opportunity_priority_v1` is **High** for a top severity of at least 80, confidence of at least 0.85 and a public contact path; **Medium** for other confirmed opportunities; **Low** for sufficient overall evidence with no confirmed opportunity; otherwise **Insufficient Evidence**. A contact path means contact confidence at least 80/100 or an observed contact/form/quote/booking path in the conversion findings. Commercial relevance is encoded in the fixed rule precedence, not inferred revenue or purchase intent.

Examples: an explicit noindex directive outranks metadata cleanup; invalid JSON-LD can recommend Schema Implementation; comparable phone inconsistencies can recommend Local SEO Management; weak observed service detail can recommend Service Page Optimization. A page outside the sample never earns a confirmed “missing page” recommendation.

## Versioned recommendation rules

The exact mapping is listed below. Tests exercise deterministic order, repeated evidence, unknown denominators, coverage thresholds and the three-item limits.

| Detector | Priority | Opportunity | Service |
| --- | ---: | --- | --- |
| `indexability` | 100 | Indexability / Crawlability | Technical SEO Cleanup |
| `robots` | 98 | Sitemap / Robots Configuration | Technical SEO Cleanup |
| `https` | 96 | Mobile Technical Setup | Technical SEO Cleanup |
| `http` | 95 | Broken Link Cleanup | Technical SEO Cleanup |
| `mixed_content` | 92 | Mobile Technical Setup | Technical SEO Cleanup |
| `schema_valid` | 91 | Structured Data | Schema Implementation |
| `canonical` | 90 | Canonicalization | Technical SEO Cleanup |
| `nap_consistency` | 89 | NAP / Location Consistency | Local SEO Management |
| `broken_links` | 88 | Broken Link Cleanup | Internal Linking Improvements |
| `contact_page` | 87 | Contact Page | Conversion Optimization |
| `primary_cta` | 86 | Primary Call to Action | Conversion Optimization |
| `viewport` | 85 | Mobile Technical Setup | Technical SEO Cleanup |
| `quote_form` | 84 | Quote Form | Quote Funnel Improvements |
| `contact_form` | 83 | Contact Form | Conversion Optimization |
| `duplicate_title` | 82 | Metadata Cleanup | On-Page SEO Optimization |
| `booking_form` | 81 | Booking / Scheduling | Conversion Optimization |
| `title` | 80 | Metadata Cleanup | On-Page SEO Optimization |
| `click_to_call` | 79 | Click-to-Call | Conversion Optimization |
| `descriptive_title` | 78 | Title / Heading Optimization | On-Page SEO Optimization |
| `location_context` | 77 | Location Page Optimization | Location Page Optimization |
| `local_schema` | 76 | Local Business Schema | Schema Implementation |
| `schema` | 75 | Structured Data | Schema Implementation |
| `page_topic` | 74 | Page Topic Clarity | Service Page Optimization |
| `supporting_content` | 73 | Service Page Optimization | Service Page Optimization |
| `h1` | 72 | Metadata Cleanup | On-Page SEO Optimization |
| `mobile_layout` | 71 | Mobile Layout | Conversion Optimization |
| `internal_contact` | 70 | Internal Link Health | Internal Linking Improvements |
| `duplicate_description` | 66 | Metadata Cleanup | On-Page SEO Optimization |
| `description` | 65 | Metadata Cleanup | On-Page SEO Optimization |
| `sitemap` | 55 | Sitemap / Robots Configuration | Technical SEO Cleanup |
| `image_alt` | 50 | Image SEO | On-Page SEO Optimization |
