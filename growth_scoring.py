"""Versioned, deterministic opportunity scoring. No ranking predictions.

Unknown is excluded from the assessed denominator, never converted to a gap.
One URL/check contributes once; shared signal families contribute once overall.
"""
from collections import defaultdict

MIN_CHECKS = 3
MIN_COVERAGE = 40
MIN_CONFIDENCE = .8
MIN_TOP_GAP_FRACTION = .25
CRITICAL_SEVERITY = 85
BANDS = ((20, 'Low'), (40, 'Moderate'), (60, 'Meaningful'), (80, 'Strong'), (101, 'Very Strong'))
PROFILES = {
    'technical_seo_v1': dict(label='Technical SEO', weights=dict(indexability=15, canonical=10, https=5, title=5,
        description=5, duplicate_title=5, duplicate_description=5, viewport=5, schema=5, schema_valid=5, h1=5, image_alt=5,
        mixed_content=5, http=5, broken_links=5, sitemap=5, robots=5)),
    'on_page_seo_v1': dict(label='On-Page SEO', weights=dict(descriptive_title=20, topic_alignment=20,
        page_topic=15, supporting_content=20, internal_contact=15, location_context=10)),
    'local_seo_v1': dict(label='Local SEO', weights=dict(address=20, nap_consistency=20,
        location_context=15, local_schema=25, directions=10, review_integration=10)),
}
RULES_VERSION = 'recommended_services_v1'
# key -> priority, primary opportunity, recommended service. This is the one
# configurable rules table for profile labels, packages and top opportunities.
RULES = {
    'indexability': (100, 'Indexability / Crawlability', 'Technical SEO Cleanup'),
    'robots': (98, 'Sitemap / Robots Configuration', 'Technical SEO Cleanup'),
    'canonical': (90, 'Canonicalization', 'Technical SEO Cleanup'),
    'http': (95, 'Broken Link Cleanup', 'Technical SEO Cleanup'),
    'broken_links': (88, 'Broken Link Cleanup', 'Internal Linking Improvements'),
    'https': (96, 'Mobile Technical Setup', 'Technical SEO Cleanup'),
    'mixed_content': (92, 'Mobile Technical Setup', 'Technical SEO Cleanup'),
    'schema': (75, 'Structured Data', 'Schema Implementation'),
    'schema_valid': (91, 'Structured Data', 'Schema Implementation'),
    'local_schema': (76, 'Local Business Schema', 'Schema Implementation'),
    'title': (80, 'Metadata Cleanup', 'On-Page SEO Optimization'),
    'description': (65, 'Metadata Cleanup', 'On-Page SEO Optimization'),
    'duplicate_title': (82, 'Metadata Cleanup', 'On-Page SEO Optimization'),
    'duplicate_description': (66, 'Metadata Cleanup', 'On-Page SEO Optimization'),
    'h1': (72, 'Metadata Cleanup', 'On-Page SEO Optimization'),
    'image_alt': (50, 'Image SEO', 'On-Page SEO Optimization'),
    'viewport': (85, 'Mobile Technical Setup', 'Technical SEO Cleanup'),
    'sitemap': (55, 'Sitemap / Robots Configuration', 'Technical SEO Cleanup'),
    'descriptive_title': (78, 'Title / Heading Optimization', 'On-Page SEO Optimization'),
    'page_topic': (74, 'Page Topic Clarity', 'Service Page Optimization'),
    'supporting_content': (73, 'Service Page Optimization', 'Service Page Optimization'),
    'internal_contact': (70, 'Internal Link Health', 'Internal Linking Improvements'),
    'location_context': (77, 'Location Page Optimization', 'Location Page Optimization'),
    'nap_consistency': (89, 'NAP / Location Consistency', 'Local SEO Management'),
    'quote_form': (84, 'Quote Form', 'Quote Funnel Improvements'),
    'booking_form': (81, 'Booking / Scheduling', 'Conversion Optimization'),
    'contact_form': (83, 'Contact Form', 'Conversion Optimization'),
    'contact_page': (87, 'Contact Page', 'Conversion Optimization'),
    'primary_cta': (86, 'Primary Call to Action', 'Conversion Optimization'),
    'click_to_call': (79, 'Click-to-Call', 'Conversion Optimization'),
    'mobile_layout': (71, 'Mobile Layout', 'Conversion Optimization'),
}
FAMILIES = {'title': 'title', 'descriptive_title': 'title', 'h1': 'heading', 'page_topic': 'heading',
            'schema': 'schema', 'local_schema': 'schema', 'contact_page': 'contact_navigation',
            'internal_contact': 'contact_navigation'}
DISCLAIMER = ('Findings cover inspected public pages only. Opportunity scores prioritize observed improvements; '
              'they do not measure Google rankings, purchase intent or guarantee traffic, rankings or leads.')


def band(score):
    return 'Not enough evidence' if score is None else next(label for upper, label in BANDS if score < upper)


def rollup(evidence):
    buckets = defaultdict(dict)
    for row in evidence:
        if not str(row.get('detector_key', '')).startswith('growth.') or not isinstance(row.get('value'), dict):
            continue
        key = row['detector_key'][7:]
        outcome = row['value'].get('outcome')
        if outcome not in {'pass', 'gap', 'unknown'}:
            continue
        # Exact duplicate observations cannot increase score or confidence.
        token = row.get('source_url') or row.get('page_id') or ''
        old = buckets[key].get(token)
        if old is None or (row.get('confidence', 0), row.get('observed_at', ''), str(row.get('id', ''))) > (old.get('confidence', 0), old.get('observed_at', ''), str(old.get('id', ''))):
            buckets[key][token] = row
    checks = {}
    for key, values in buckets.items():
        rows = list(values.values())
        assessed = [r for r in rows if r['value']['outcome'] in {'pass', 'gap'} and r.get('confidence', 0) >= MIN_CONFIDENCE]
        if key in {'schema', 'local_schema', 'address', 'directions', 'review_integration'} and any(r['value']['outcome'] == 'pass' for r in assessed):
            # Site-level presence is established by one suitable observed page.
            # Do not require LocalBusiness markup on every contact/service page.
            assessed = [r for r in assessed if r['value']['outcome'] == 'pass']
        gaps = [r for r in assessed if r['value']['outcome'] == 'gap']
        checks[key] = dict(key=key, label=rows[0]['value'].get('label', key), status='gap' if gaps else 'pass' if assessed else 'unknown',
            gap_fraction=len(gaps) / len(assessed) if assessed else None,
            confidence=round(sum(r.get('confidence', 0) for r in assessed) / len(assessed), 3) if assessed else 0,
            assessed_pages=len(assessed), unknown_pages=len(rows) - len(assessed),
            source_urls=sorted({r.get('source_url') for r in (gaps or assessed or rows) if r.get('source_url')}),
            evidence_ids=sorted({str(r['id']) for r in (gaps or assessed or rows) if r.get('id')}),
            details=sorted({r['value'].get('detail', '') for r in (gaps or assessed or rows) if r['value'].get('detail')}))
    return checks


def profile(version, checks, *, assessed=True, pages=()):
    spec = PROFILES[version]
    weighted = {k: checks.get(k, dict(key=k, label=k.replace('_', ' ').title(), status='unknown', gap_fraction=None,
                                    confidence=0, source_urls=[], evidence_ids=[], details=[])) for k in spec['weights']}
    known = {k: c for k, c in weighted.items() if c['gap_fraction'] is not None}
    denominator = sum(spec['weights'][k] for k in known)
    coverage = round(100 * denominator / sum(spec['weights'].values()), 2)
    sufficient = assessed and len(known) >= MIN_CHECKS and coverage >= MIN_COVERAGE
    numerator = sum(spec['weights'][k] * c['gap_fraction'] for k, c in known.items())
    score = round(100 * numerator / denominator, 2) if sufficient else None
    gaps = sorted([c for c in known.values() if c['status'] == 'gap'], key=lambda c: (-RULES.get(c['key'], (0, '', ''))[0], c['key']))
    primary = RULES[gaps[0]['key']][1] if sufficient and gaps else 'No Strong ' + spec['label'] + ' Gap Confirmed' if sufficient else 'Insufficient Evidence'
    return dict(profile_version=version, label=spec['label'], status='assessed' if sufficient else 'insufficient_evidence' if assessed else 'not_assessed',
        opportunity_score=score, evidence_confidence=coverage if assessed else None,
        opportunity_display=band(score) if score is not None else 'Not enough evidence' if assessed else 'Not assessed',
        opportunity_band=band(score), primary_opportunity=primary, sufficient=sufficient,
        confirmed_gaps=gaps, confirmed_strengths=[c for c in known.values() if c['status'] == 'pass'],
        unknown_checks=[c for c in weighted.values() if c['status'] == 'unknown'],
        recommendations=list(dict.fromkeys(RULES[c['key']][2] for c in gaps if c['key'] in RULES))[:3] if sufficient else [],
        pages_audited=list(pages), scope='Inspected pages only', breakdown=dict(weights=spec['weights'], numerator=numerator,
        assessed_weight=denominator, possible_weight=sum(spec['weights'].values()), assessed_checks=len(known),
        minimum_checks=MIN_CHECKS, minimum_coverage=MIN_COVERAGE, checks=weighted,
        formula='100 * sum(weight * confirmed_gap_fraction) / sum(assessed_weight)'))


def build_growth(evidence, conversion, *, assessed=False, observations=(), page_analysis=(), metrics=None):
    checks = rollup(evidence)
    pages = [dict(url=o['url'], kind=o['kind'], confidence=o['kind_confidence']) for o in observations]
    profiles = {v: profile(v, checks, assessed=assessed, pages=pages) for v in PROFILES}
    candidates, signals = [], {}
    def add_signal(family, signal):
        # A generic pass must not erase a specific confirmed gap (for example,
        # BreadcrumbList present while LocalBusiness markup is missing).
        # Count the family once using its greatest assessed gap fraction.
        if family not in signals or signal['fraction'] > signals[family]['fraction']:
            signals[family] = signal
    for version, p in profiles.items():
        if not p['sufficient']:
            continue
        for key, c in p['breakdown']['checks'].items():
            if c['gap_fraction'] is None:
                continue
            family = FAMILIES.get(key, key)
            add_signal(family, dict(key=key, profile=version, weight=p['breakdown']['weights'][key], fraction=c['gap_fraction']))
        for c in p['confirmed_gaps']:
            if c['key'] not in RULES:
                continue
            rank, label, service = RULES[c['key']]
            if c['gap_fraction'] < MIN_TOP_GAP_FRACTION and rank < CRITICAL_SEVERITY:
                continue
            candidates.append(dict(key=c['key'], profile=version, label=label, service=service,
                severity=rank, confidence=c['confidence'], source_urls=c['source_urls'], evidence_ids=c['evidence_ids'],
                reason=c['details'][0] if c['details'] else c['label']))
    stored = (conversion.get('breakdown') or {}).get('findings', {})
    conversion_sufficient = conversion.get('opportunity_score') is not None and (conversion.get('evidence_confidence') or 0) >= 40
    if conversion_sufficient:
        for key, value in stored.items():
            state = value.get('status')
            if state not in {'present', 'absent'}:
                continue
            add_signal(FAMILIES.get(key, key), dict(key=key, profile='website_conversion_v2', weight=10, fraction=int(state == 'absent')))
            raw = [e for e in evidence if e.get('detector_key') == key and e.get('status') == 'absent' and e.get('confidence', 0) >= MIN_CONFIDENCE]
            if state == 'absent' and raw and key in RULES:
                rank, label, service = RULES[key]
                candidates.append(dict(key=key, profile='website_conversion_v2', label=label, service=service, severity=rank,
                    confidence=max(e.get('confidence', 0) for e in raw), source_urls=sorted({e.get('source_url') for e in raw if e.get('source_url')}),
                    evidence_ids=sorted({str(e['id']) for e in raw if e.get('id')}), reason='Confirmed conversion gap in the inspected pages.'))
    candidates.sort(key=lambda c: (-c['severity'], -c['confidence'], c['profile'], c['key']))
    top, used_families, labels = [], set(), set()
    for c in candidates:
        family = FAMILIES.get(c['key'], c['key'])
        if family in used_families or c['label'] in labels:
            continue
        top.append(c); used_families.add(family); labels.add(c['label'])
        if len(top) == 3:
            break
    services = list(dict.fromkeys(c['service'] for c in top))[:3]
    sufficient_profiles = sum(p['sufficient'] for p in profiles.values())
    total_weight = sum(s['weight'] for s in signals.values())
    overall_sufficient = sufficient_profiles >= 2 and len(signals) >= 5
    overall = round(100 * sum(s['weight'] * s['fraction'] for s in signals.values()) / total_weight, 2) if overall_sufficient and total_weight else None
    coverage = round(sum(p['evidence_confidence'] or 0 for p in profiles.values()) / 3, 2) if assessed else None
    contactable = (conversion.get('contact_confidence') or 0) >= 80 or any(stored.get(k, {}).get('status') == 'present' for k in ('contact_page', 'contact_form', 'quote_form', 'booking_form'))
    priority = 'High' if top and top[0]['severity'] >= 80 and top[0]['confidence'] >= .85 and contactable else 'Medium' if top else 'Low' if overall_sufficient else 'Insufficient Evidence'
    future = {key: dict(profile_version=key, status='not_configured', score=None, message=message) for key, message in (
        ('serp_rank_tracking_v1', 'Rank tracking not configured'), ('off_page_seo_v1', 'Off-Page SEO not configured'),
        ('social_media_audit_v1', 'Social Media Audit not configured'), ('page_performance_v1', 'Performance assessment not configured'))}
    performance = next((e.get('value') for e in evidence if e.get('detector_key') == 'pagespeed' and e.get('status') == 'present' and isinstance(e.get('value'), dict) and e['value'].get('provider') == 'Google PageSpeed Insights'), None)
    if performance:
        future['page_performance_v1'] = dict(profile_version='page_performance_v1', status='assessed', measurement=performance, core_web_vitals='Not assessed')
    else:
        future['page_performance_v1']['core_web_vitals'] = 'Not assessed'
        if (metrics or {}).get('performance_configured'):
            future['page_performance_v1'].update(status='unavailable', message='Performance assessment unavailable; configured provider returned no measurement')
    result = dict(version='digital_growth_summary', assessed=assessed, profiles=profiles,
        website_conversion=dict(profile_version=conversion.get('profile_version'), opportunity_score=conversion.get('opportunity_score'), evidence_confidence=conversion.get('evidence_confidence')),
        top_sales_opportunities=top, recommended_services=dict(version=RULES_VERSION, services=services, rules='Confirmed gaps only; at most three services; no pricing.'),
        sales_opportunity_priority=dict(version='sales_opportunity_priority_v1', label=priority, contactable=contactable, purchase_intent=False),
        overall_evidence_confidence=coverage, digital_growth_opportunity=dict(profile_version='digital_growth_opportunity_v1',
            opportunity_score=overall, evidence_confidence=coverage, sufficient=overall_sufficient, opportunity_band=band(overall),
            display=band(overall) if overall is not None else 'Not enough evidence' if assessed else 'Not assessed',
            confirmed_strengths=[dict(profile=v, key=c['key']) for v,p in profiles.items() for c in p['confirmed_strengths']],
            confirmed_gaps=[dict(profile=v, key=c['key']) for v,p in profiles.items() for c in p['confirmed_gaps']],
            unknown_checks=[dict(profile=v, key=c['key']) for v,p in profiles.items() for c in p['unknown_checks']],
            recommended_services=services,
            breakdown=dict(signals=signals, total_weight=total_weight, formula='100 * sum(unique_signal_weight * gap_fraction) / sum(unique_assessed_signal_weight)')),
        page_analysis=list(page_analysis), observations=list(observations), metrics=metrics or {}, future_modules=future, disclaimer=DISCLAIMER)
    result['client_growth_audit'] = dict(version='client_growth_audit_v1', business_name=None, agency_name=None, agency_logo_url=None,
        executive_summary='Review the confirmed opportunities from the inspected public pages.', top_opportunities=top,
        evidence=[dict(profile=v, strengths=p['confirmed_strengths'], gaps=p['confirmed_gaps'], unknown=p['unknown_checks']) for v, p in profiles.items()],
        recommendations=services, disclaimer=DISCLAIMER)
    return result


def growth_for_detail(detail):
    from lead_summary import business_name
    score = detail.get('score') or {}
    stored = score.get('digital_growth')
    observations = [e['value'] for e in detail.get('evidence', []) if e.get('detector_key') == 'growth.page_observation'
                    and e.get('detector_version') == 'digital_growth_crawl_v1' and isinstance(e.get('value'), dict)]
    if isinstance(stored, dict) and stored.get('version') == 'digital_growth_summary':
        result = dict(stored, observations=observations)
        result['client_growth_audit'] = dict(stored['client_growth_audit'], evidence=[
            dict(profile=v, strengths=p['confirmed_strengths'], gaps=p['confirmed_gaps'], unknown=p['unknown_checks'])
            for v,p in stored['profiles'].items()])
        result['client_growth_audit']['business_name'] = business_name(detail)[0]
        return result
    if observations:
        # Legacy development storage has generic evidence but no production JSONB
        # score envelope. Historical audits without these facts are never inferred.
        from audit_engine.growth import cross_page_checks
        _, analysis = cross_page_checks(observations, detail.get('pages', []))
        result = build_growth(detail.get('evidence', []), score, assessed=True, observations=observations, page_analysis=analysis)
    else:
        result = build_growth(detail.get('evidence', []), score)
    result['client_growth_audit']['business_name'] = business_name(detail)[0]
    return result


def stored_growth(growth):
    """Raw page facts live once in AuditEvidence; hydrate report views on read."""
    result = {k:v for k,v in growth.items() if k != 'observations'}
    result['client_growth_audit'] = {k:v for k,v in growth['client_growth_audit'].items() if k != 'evidence'}
    return result


def compact_growth(detail):
    g = detail.get('digital_growth') or growth_for_detail(detail)
    result = {k: g[k] for k in ('version', 'assessed', 'top_sales_opportunities', 'recommended_services',
        'sales_opportunity_priority', 'overall_evidence_confidence', 'disclaimer')}
    fields = ('profile_version', 'label', 'status', 'opportunity_score', 'evidence_confidence', 'opportunity_display',
              'opportunity_band', 'primary_opportunity', 'sufficient')
    result['profiles'] = {v: {k: p[k] for k in fields} for v, p in g['profiles'].items()}
    result['digital_growth_opportunity'] = {k: v for k, v in g['digital_growth_opportunity'].items() if k not in {'breakdown', 'confirmed_strengths', 'confirmed_gaps', 'unknown_checks'}}
    return result


GROWTH_CSV_FIELDS = ('technical_seo_opportunity', 'technical_seo_primary_opportunity', 'technical_seo_evidence_confidence',
    'on_page_seo_opportunity', 'on_page_primary_opportunity', 'on_page_evidence_confidence',
    'local_seo_opportunity', 'local_seo_primary_opportunity', 'local_seo_evidence_confidence',
    'top_sales_opportunity', 'recommended_service_1', 'recommended_service_2', 'recommended_service_3',
    'sales_opportunity_priority', 'digital_growth_evidence_confidence')


def csv_fields(g):
    data = {}
    for version, prefix, primary in [('technical_seo_v1', 'technical_seo', 'technical_seo'),
            ('on_page_seo_v1', 'on_page_seo', 'on_page'), ('local_seo_v1', 'local_seo', 'local_seo')]:
        p = g['profiles'][version]
        data[prefix + '_opportunity'] = p['opportunity_score']
        data[primary + '_primary_opportunity'] = p['primary_opportunity'] if p['status'] != 'not_assessed' else 'Not assessed'
        data[primary + '_evidence_confidence'] = p['evidence_confidence']
    data['top_sales_opportunity'] = next((o['label'] for o in g['top_sales_opportunities']), '')
    services = g['recommended_services']['services']
    data.update({f'recommended_service_{i + 1}': services[i] if i < len(services) else '' for i in range(3)})
    data.update(sales_opportunity_priority=g['sales_opportunity_priority']['label'], digital_growth_evidence_confidence=g['overall_evidence_confidence'])
    return data
