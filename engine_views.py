"""Owner-scoped read models and a formula-safe streaming CSV export."""
import csv
import io
from utils import csv_safe_cell
from provider_policy import policy_for

SCORE_FIELDS = ("opportunity_score", "digital_gap", "business_strength", "evidence_confidence", "contact_confidence")
DETECTOR_FIELDS = ("contact_form", "quote_form", "booking_form", "booking_widget", "chat_widget", "primary_cta", "click_to_call", "request_quote_cta", "booking_cta", "contact_cta", "facebook", "instagram", "linkedin", "youtube", "cms")
CSV_FIELDS = ("business_name", "provider", "provider_record_id", "category", "city", "state", "website", "emails", "phones", "email_source_urls", "phone_source_urls", "profile", *SCORE_FIELDS, *DETECTOR_FIELDS, "audit_status", "observed_at")


def summary(detail):
    business, score, audit = detail["business"], detail["score"] or {}, detail["audit"] or {}
    contacts = detail["contacts"]
    findings = score.get("breakdown", {}).get("findings", {})
    source = (detail.get("sources") or [{}])[0]
    provider = source.get("provider", "")
    policy = policy_for(provider)
    # Google Places content is transient; durable exports carry only place_id and browser evidence.
    row = dict(id=business["id"], business_name="" if provider == "google_places_new" else business["canonical_name"], provider=provider, provider_record_id=source.get("provider_record_id", "") if provider == "google_places_new" else source.get("provider_record_id", ""), category=business["category"],
               city="" if provider == "google_places_new" else business["city"], state="" if provider == "google_places_new" else business["state"], website="" if provider == "google_places_new" else business["website_url"],
               profile=score.get("profile_version", "website_conversion_v1"),
               audit_status=audit.get("status", "pending"), observed_at=audit.get("finished_at"),
               primary_opportunity=score.get("breakdown", {}).get("primary_opportunity"))
    for kind, plural in (("email", "emails"), ("phone", "phones")):
        selected = [c for c in contacts if c["contact_type"] == kind]
        row[plural] = "; ".join(dict.fromkeys(c["normalized_value"] for c in selected))
        row[kind + "_source_urls"] = "; ".join(dict.fromkeys(c["source_url"] or "" for c in selected))
    for key in SCORE_FIELDS:
        row[key] = score.get(key)
    for key in DETECTOR_FIELDS:
        finding = findings.get(key, {})
        value = finding.get("value")
        row[key] = "; ".join(str(v) for v in value) if isinstance(value, list) else str(value) if value not in (None, True, False) else finding.get("status", "unknown")
    return row


def csv_export(store, user):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(CSV_FIELDS)
    yield buffer.getvalue()
    last = ""
    while True:
        with store.transaction() as conn:
            ids = [r[0] for r in conn.execute("SELECT DISTINCT i.business_id FROM search_job_items i JOIN search_jobs j ON j.id=i.job_id WHERE j.user_id=? AND i.business_id>? ORDER BY i.business_id LIMIT 100", (user, last))]
        if not ids:
            return
        buffer.seek(0); buffer.truncate(0)
        for bid in ids:
            row = summary(store.detail(bid, user))
            writer.writerow([csv_safe_cell(row.get(key)) for key in CSV_FIELDS])
        yield buffer.getvalue()
        last = ids[-1]
