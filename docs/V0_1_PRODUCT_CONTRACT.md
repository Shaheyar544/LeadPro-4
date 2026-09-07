# V0.1 product contract

This fork is becoming a Local Business Lead Intelligence Engine for a single
local workspace. Phase 3A is a foundation, not a production release.

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
query. The existing lead table remains: state appears in `source_query`, rather
than a new dedicated column. The single opportunity profile identifies this
workflow; structured search records and the new score belong to Phase 3B.

## Current behavior

Dashboard → Lead Generation → Leads → Settings. At least one Serper Maps,
Google Places or Yelp API key is needed to start discovery, but no API key or
OpenRouter client is required to boot. Missing discovery configuration returns
503 before job creation. Yelp websites are left unknown instead of guessed.

Website checks read bounded HTTP HTML. There is no browser execution or
contact/about crawling. New emails come only from explicit provider business
emails or literal addresses observed in fetched HTML. These observations do
not yet prove visible DOM evidence or mailbox ownership. No guessed/enriched
contacts or inferred owner identities are newly collected. Existing records
are preserved and may still contain contacts collected before Phase 3A.

The old technology/scoring rules remain provisional; scores are labeled as
legacy in the UI. The opportunity profile does not imply a new scoring model.
CSV exports all saved businesses using a single server-side formula-safety policy.

Jobs belong to the authenticated starter. Default capacity is one; excess
requests return retryable 429. Closing the page does not cancel work, so there
is no Stop button. Restart loses in-memory jobs and possibly buffered results.
Discovery pagination is not improved here, so a search can return fewer results
than requested even when its target is 100.

## Explicitly out of scope

- Cold email, follow-up email, email warm-up, campaign sending and automated outreach.
- SMS, WhatsApp and LinkedIn messaging.
- Reply scanning, proposal generation and the public audit email funnel.
- Personal owner enrichment, personal contact enrichment and guessed email generation.
- Billing and multi-tenancy.
- CAPTCHA bypass, login automation and form submission.

Legacy source remains for later removal, but its router is never mounted.
Feature flags cannot reactivate it in this release. Phase 3B will add the isolated
Playwright worker, rendered evidence, contact/about crawling, persistent jobs,
restart recovery, discovery pagination and a new deterministic opportunity score.
