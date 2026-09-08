# Production provider data policy

Phase 4A.2 enabled provider: Google Places New, with browser-independent v2
scoring. Legacy Google is rollback-only; Serper/Yelp require separate policy
review and cannot be selected in production. No live provider request was made
during this validation.

## Durable versus transient

Google discovery displayName, formattedAddress, websiteUri,
nationalPhoneNumber, rating, userRatingCount, primaryType and businessStatus
remain transient. Durable provider_refs contain only the provider identifier,
allowed Place ID reference and application-owned user/business/timestamp links.
There is no raw-provider JSON column.

The production worker passes only the temporary navigation hint to AuditEngine.
It does not pass provider phone/name/address/rating into browser evidence or
scoring. Failed/unobserved navigation hints are not persisted as audit URLs.
Successful independently observed browser URL/title, public phone/email, pages
and evidence may persist with browser provenance. User-entered search context is
application data, not a copied provider address/category.

The existing Phase 3 development data model remains historical and separate.
No automatic SQLite import or policy reclassification was performed.

## Proof

The offline fixture goes through the real Google New response parser and carries
unique sentinels in every restricted field (including distinctive numeric
rating/review-count values). Independent browser facts are then processed by the
real worker's AuditEngine and stored in PostgreSQL. Every public table is scanned
using row_to_json text, including provider references, audits and score breakdowns.
The restore database is scanned again.

The production CSV route includes browser website, phone/email, evidence,
website_conversion_v2 opportunity/confidence, permitted provider ID and user
search context. Restricted synthetic provider values, raw responses and secrets
are absent. Formula-leading cells are prefixed safely for spreadsheets.

API, worker, Caddy, Postgres, Redis and CamoFox logs are scanned for full test
credentials/session values and provider sentinels. Caddy removes request objects
from runtime logs; CamoFox logs only static events and numeric/boolean metrics.

Production scoring uses only allowlisted browser findings. Missing/unknown
findings do not count as absence; fewer than three assessable checks yields an
unknown score. Removing every transient Google field leaves v2 unchanged.
Historical website_conversion_v1 remains historical.

This document records the implemented local technical boundary; any broader
provider retention, attribution or commercial-use change needs its own policy
review before rollout.
