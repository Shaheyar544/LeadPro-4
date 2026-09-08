"""Production v2 uses only independently observed browser evidence."""
from audit_engine.detectors import aggregate
VERSION = 'website_conversion_v2'
CORE = ('contact_form', 'quote_form', 'booking_form', 'contact_page', 'primary_cta', 'click_to_call', 'mobile_layout')

def score_browser_evidence(audit):
    supplied = audit.get('findings', {}) if isinstance(audit, dict) else {}
    if 'evidence' in audit:
        supplied = aggregate(audit['evidence'], audit.get('status') == 'completed')
    # Only allowlisted detector findings may enter a score.
    findings = {k: {p: v for p, v in supplied.get(k, {'status': 'unknown'}).items()
                    if p in {'status', 'confidence', 'evidence_ids'}}
                for k in CORE}
    assessed = sum(f['status'] in ('present', 'absent') for f in findings.values())
    absent = sum(f['status'] == 'absent' for f in findings.values())
    confidence = round(100 * assessed / len(CORE), 2)
    gap = round(100 * absent / assessed, 2) if assessed >= 3 else None
    return {'profile_version': VERSION, 'opportunity_score': gap, 'digital_gap': gap,
            'business_strength': None, 'evidence_confidence': confidence,
            'contact_confidence': round(100 * max((c.get('confidence', 0) for c in audit.get('contacts', [])), default=0), 2),
            'breakdown': {'findings': findings, 'source': 'browser_evidence_only',
                          'formula': '100 * absent / assessed (minimum 3 assessed checks)',
                          'components': [], 'fallback': 'insufficient_assessable_evidence' if gap is None else None}}
