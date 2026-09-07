# V0.1 product contract

This fork is becoming a Local Business Lead Intelligence Engine for a single
local workspace. Phase 3B adds persistent rendered evidence; this remains a local prototype.

## Input

`POST /api/leadgen/start` requires a bearer token and exactly these fields:

```json
{
  "category": "Plumber",
  "city": "Austin",
  "state": "Texas",
  "target_count": 25,
  "opportunity_profile": "website_conversion"
}
```

| Field | Contract |
| --- | --- |
| category | Required text, 1–100 characters after normalization. |
| city | Required text, 1–100 characters after normalization. |
| state | Full U.S. state name or two-letter abbreviation, case insensitive. Normalize to the two-letter code. All 50 states and DC are supported; territories are outside this initial scope. |
| target_count | Required integer, 1–100 inclusive. Booleans, floats and numeric strings are rejected. This is a maximum, not a guarantee. |
| opportunity_profile | Required literal `website_conversion`, displayed as **Website Conversion Improvement**. |

Text is trimmed and repeated whitespace collapses to one space. Control and
invisible formatting characters are rejected before normalization. Raw text
over 200 characters, empty values, invalid states, unsupported profiles and
unknown fields return field-specific 422 errors. Backend validation is authoritative.

The country is fixed to United States. Category, city and state form the search
query. Search jobs and businesses store state explicitly. The request profile maps
to the versioned `website_conversion_v1` score. See the exact formula and
applicability rules in [Phase 3B architecture](PHASE_3B_ARCHITECTURE.md).

## Current behavior

Dashboard → Lead Generation → Leads → Settings. One configured Serper Maps,
Google Places or Yelp key is required to create a search; startup needs no live
API keys or OpenRouter. Missing discovery configuration returns 503. A configured
but unavailable CamoFox service produces stored browser_unavailable findings.

The official CamoFox REST service renders public business websites behind a
browser-provider interface. The crawl is bounded to homepage, one contact/quote
and one about or services page. Links must be observed, internal and safe; no
paths, websites or emails are guessed. Yelp listing URLs are provenance only.
Public mailto/tel and visible text contacts are normalized with source evidence.
Provider phone evidence is labeled separately. Personal LinkedIn profiles are
excluded; only company LinkedIn URLs can be business evidence.

New normalized tables are authoritative. Legacy lead data is preserved separately
without converting its booleans or historical enrichment into rendered evidence.
Scores expose opportunity, digital gap, strength and two separate confidences.
Unknown, blocked, failed and not-applicable findings do not count as feature gaps.
Evidence detail includes pages, detectors, excerpts, sources, confidence, versions,
timestamps and score explanation. CSV uses the same owner scope and formula safety.

Jobs persist across refreshes and restarts. Default execution is one job and two
concurrent business audits. Up to ten active jobs per owner can queue; additional
requests return 429/Retry-After. Cancellation is persistent, pending items stop
immediately, and active work stops at a bounded safe boundary. SSE disconnection
never cancels work. A stale lease is recovered within the 60-second lease window
plus polling; completed items are not reprocessed.

The target is a cap on unique discovered businesses, not a guaranteed number of
sales-qualified contacts. `qualified_count` means enough evidence for a gap score.
Discovery pages/quotas and unavailable websites can cause partial results. Google
and Yelp pagination are bounded; Serper Maps currently uses one verified request
contract and reports provider_limit for unmet targets. No quotas or blocks are bypassed.

## Explicitly out of scope

- Cold email, follow-up email, email warm-up, campaign sending and automated outreach.
- SMS, WhatsApp and LinkedIn messaging.
- Reply scanning, proposal generation and the public audit email funnel.
- Personal owner enrichment, personal contact enrichment and guessed email generation.
- Billing and multi-tenancy.
- CAPTCHA bypass, login automation and form submission.

Legacy source remains for later removal, but its router is never mounted.
Feature flags cannot reactivate it in this release. Phase 3C is not implemented.
The browser is Firefox-based, not Chromium verification. SQLite is durable local
storage, not a distributed queue or a production browser network sandbox.
