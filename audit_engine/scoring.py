"""website_conversion_v1: transparent arithmetic, no AI or inferred revenue."""
import math
import re
from .detectors import aggregate

WEIGHTS = {"contact_cta": 15, "primary_cta": 15, "click_to_call": 10,
           "contact_form": 15, "quote_form": 10, "booking_form": 10,
           "mobile_layout": 10, "contact_page": 10, "pagespeed": 5}
QUOTE_CATEGORIES = r"plumb|roof|paint|hvac|landscap|remodel|clean|electric|contract|pest|pressure wash|pool|handyman"
BOOKING_CATEGORIES = r"dent|salon|spa\b|barber|veterinar|chiropract|physiotherap|auto repair|massage"


def has_public_contact_path(audit):
    """A verified public business phone, email, form, booking or contact page."""
    if any(c.get("confidence", 0) >= 0.8 for c in audit.get("contacts", [])):
        return True
    return any(e.get("detector_key") in {"contact_form", "quote_form", "booking_form", "contact_page"}
               and e.get("status") == "present" for e in audit.get("evidence", []))


def commercially_usable_v2(business, audit, score, identity_confidence=1.0):
    """Conservative v2 rule; partial audits require medium confidence."""
    return bool(identity_confidence >= 0.7 and business.get("website_url") and
                audit.get("status") in {"completed", "partial"} and
                score.get("opportunity_score") is not None and
                score.get("evidence_confidence", 0) >= 40 and
                has_public_contact_path(audit))


def bounded(value):
    return round(max(0, min(100, value)), 2)


def score_audit(business, audit):
    findings = aggregate(audit["evidence"], audit["status"] == "completed")
    category = business.get("category", "") or ""
    components = []
    applicable_weight = assessed_weight = lost = 0
    for key, weight in WEIGHTS.items():
        finding = findings[key]
        status = finding["status"]
        if key in {"quote_form", "booking_form"} and status != "present":
            pattern = QUOTE_CATEGORIES if key == "quote_form" else BOOKING_CATEGORIES
            if not re.search(pattern, category, re.I):
                status = "not_applicable"
        assessed = status in {"present", "absent"}
        loss = 100 if status == "absent" else 0
        if key == "pagespeed" and status == "present":
            value = finding.get("value")
            loss = 100 - value["score"] if isinstance(value, dict) and isinstance(value.get("score"), (int, float)) else 0
        if status != "not_applicable":
            applicable_weight += weight
        if assessed:
            assessed_weight += weight
            lost += loss * weight
        components.append(dict(detector_key=key, status=status, weight=weight,
                               gap_points=loss if assessed else None, evidence_ids=finding["evidence_ids"]))
    assessed_count = sum(c["status"] in {"present", "absent"} for c in components)
    coverage = assessed_weight / applicable_weight if applicable_weight else 0
    # A single failed/absent check is insufficient to assign a business-wide gap.
    sufficient = assessed_count >= 3 and coverage >= 0.35
    gap = bounded(lost / assessed_weight) if assessed_weight and sufficient else None
    strength_parts = []
    rating, reviews = business.get("rating"), business.get("review_count")
    if isinstance(rating, (int, float)) and 0 < rating <= 5:
        strength_parts.append({"key": "provider_rating", "value": rating, "weight": 60, "score": rating * 20})
    if isinstance(reviews, (int, float)) and reviews >= 0:
        strength_parts.append({"key": "provider_review_count", "value": reviews, "weight": 30, "score": min(100, math.log1p(reviews) / math.log(501) * 100)})
    # A reachable website alone is not sufficient evidence of business strength.
    if strength_parts and findings["reachable"]["status"] == "present":
        strength_parts.append({"key": "confirmed_active_website", "value": True, "weight": 10, "score": 100,
                               "evidence_ids": findings["reachable"]["evidence_ids"]})
    strength = bounded(sum(p["score"] * p["weight"] for p in strength_parts) / sum(p["weight"] for p in strength_parts)) if strength_parts else None
    opportunity = bounded(0.7 * gap + 0.3 * strength) if gap is not None and strength is not None else gap
    confidence_mean = sum(findings[c["detector_key"]]["confidence"] * c["weight"] for c in components if c["status"] in {"present", "absent"}) / assessed_weight if assessed_weight else 0
    page_coverage = sum(1 if p["status"] == "completed" else .5 if p["status"] == "partial" else 0 for p in audit["pages"]) / max(1, len(audit["pages"]))
    evidence_confidence = bounded(100 * coverage * confidence_mean * page_coverage)
    contact_confidence = bounded(100 * max((c["confidence"] for c in audit["contacts"]), default=0))
    primary = next((c["detector_key"] for c in sorted(components, key=lambda c: -c["weight"]) if c["status"] == "absent"), None)
    return dict(business_strength=strength, digital_gap=gap, opportunity_score=opportunity,
                evidence_confidence=evidence_confidence, contact_confidence=contact_confidence,
                breakdown={"version": "website_conversion_v1", "formula": "0.70 * digital_gap + 0.30 * business_strength",
                           "fallback": "gap_only" if strength is None and gap is not None else "insufficient_assessable_evidence" if gap is None else None,
                           "components": components, "strength_components": strength_parts,
                           "assessed_weight": assessed_weight, "applicable_weight": applicable_weight,
                           "evidence_confidence_version": "render_coverage_v2",
                           "coverage": round(coverage, 4), "page_coverage": round(page_coverage, 4),
                           "minimum_assessment": "3 components and 35% applicable weight",
                           "primary_opportunity": primary, "findings": findings})
