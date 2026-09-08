# Google Places API (New)

The benchmark provider is `google_places_new`, implemented behind the existing discovery interface. It uses `POST https://places.googleapis.com/v1/places:searchText` with `X-Goog-Api-Key` and an explicit `X-Goog-FieldMask`. Text Search (New) supplies the website, phone, rating, and identity fields used by discovery, so the adapter does not make redundant per-result Place Details calls.

Configure `GOOGLE_PLACES_API_VERSION=new` and preferably a separate restricted `GOOGLE_PLACES_NEW_API_KEY`. The existing `GOOGLE_PLACES_API_KEY` remains a Legacy-only rollback/testing key and may be tested for New authorization when the New key is absent. No key is logged or returned by diagnostics. Fields such as website, phone, rating, and review count can increase Places pricing tiers.

Requests use `textQuery`, `pageSize: 20`, `regionCode: US`, and `languageCode: en`; later pages use `pageToken`. At most three pages are requested and results are deduplicated by namespaced ID `google_places_new:<place-id>`. New HTTP/API failures are normalized separately from Legacy errors, and page-one records are retained when a later page fails.

Google-supplied `websiteUri` is only a candidate. It still goes through URL normalization, SSRF and redirect checks, public-network validation, and the browser evidence pipeline; no domain is inferred from a business name. Provider fields and browser evidence retain separate provenance.

Legacy remains available by setting `GOOGLE_PLACES_API_VERSION=legacy` for rollback/testing. Google Maps Platform terms and attribution/retention rules remain unresolved for unrestricted production exports: Place IDs have distinct caching treatment, and Phase 4 must establish policy before durable CSV distribution.
