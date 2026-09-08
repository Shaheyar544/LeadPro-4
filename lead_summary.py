"""Pure, browser-evidence-only qualification views. Never writes or rescales evidence."""
import csv
import io
import re
from urllib.parse import urlsplit, urlunsplit, unquote_plus

from audit_engine.detectors import aggregate, email_address, phone_number, social_url
from audit_engine.scoring import commercially_usable_v2
from production_scoring import CORE

VERSION = 'qualification_summary_v1'
TRACKING = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'}
LABELS = {
    'contact_page': 'Public contact page', 'contact_form': 'Contact form',
    'quote_form': 'Quote / estimate form', 'booking_form': 'Online booking',
    'primary_cta': 'Primary call to action', 'click_to_call': 'Click-to-call',
    'mobile_layout': 'Mobile layout', 'pagespeed': 'Website performance',
    'phone': 'Public phone', 'email': 'Public email', 'chat_widget': 'Live chat',
    'booking_widget': 'Booking widget', 'facebook': 'Facebook profile',
    'instagram': 'Instagram profile', 'linkedin': 'LinkedIn company profile', 'youtube': 'YouTube channel',
}
GAPS = {
    'quote_form': 'No quote / estimate form found', 'booking_form': 'No online booking found',
    'contact_form': 'No contact form found', 'contact_page': 'No public contact page found',
    'click_to_call': 'No click-to-call found', 'primary_cta': 'No meaningful conversion call to action found',
    'mobile_layout': 'Mobile layout issue confirmed', 'pagespeed': 'Website performance issue confirmed',
}
OPPORTUNITIES = {
    'quote_form': 'Quote / Estimate Conversion', 'booking_form': 'Online Booking',
    'contact_form': 'Contact Conversion', 'contact_page': 'Contact Conversion',
    'click_to_call': 'Click-to-Call', 'primary_cta': 'CTA Improvement',
    'mobile_layout': 'Mobile Conversion', 'pagespeed': 'Website Performance',
}
TOOLTIPS = {
    'opportunity_score': 'Opportunity Score reflects confirmed website-conversion gaps. Unknown checks are not counted as missing features.',
    'evidence_confidence': 'Evidence Confidence reflects how much of the website could be reliably assessed.',
    'contact_confidence': 'Contact Confidence reflects the quality and provenance of public contact evidence.',
}


def safe_url(value):
    """Presentation validation only; navigation by the crawler still uses its SSRF guard."""
    if not isinstance(value, str) or re.search(r'[\x00-\x20\x7f\\]', value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme not in {'http', 'https'} or not p.hostname or p.username or p.password or p.port not in (None, 443 if p.scheme == 'https' else 80):
            return None
        return value
    except ValueError:
        return None


def display_url(value):
    if not safe_url(value):
        return ''
    p = urlsplit(value)
    # Keep the spelling, encoding and order of functional parameters intact.
    query = '&'.join(pair for pair in p.query.split('&') if pair and unquote_plus(pair.split('=', 1)[0]).lower() not in TRACKING)
    return urlunsplit(('', p.netloc, p.path, query, p.fragment)).removeprefix('//').removesuffix('/')


def confidence_label(value):
    return 'High' if value >= .8 else 'Medium' if value >= .5 else 'Low'


def provenance(rows):
    urls = sorted({r['source_url'] for r in rows if safe_url(r.get('source_url'))})
    confidence = max((float(r.get('confidence') or 0) for r in rows), default=0)
    return dict(evidence_ids=list(dict.fromkeys(str(r['id']) for r in rows if r.get('id') is not None)),
                source_urls=urls, observed_pages=len({display_url(u) for u in urls}),
                confidence=confidence, confidence_label=confidence_label(confidence))


def business_name(detail):
    business = detail['business']
    # These fields are accepted only from browser identity, never from provider payloads.
    for key in ('structured_name', 'branding_name', 'observed_identity'):
        identity = business.get(key)
        if isinstance(identity, dict) and identity.get('provenance') == 'browser_observed' and identity.get('confidence', 0) >= .8 and identity.get('value'):
            return identity['value'], key
    fallback = business.get('canonical_name') or 'Unverified business'
    # Repeated brand fragments must be supported by a DIFFERENT page title.
    pages = detail.get('pages', [])
    candidates = re.split(r'\s*[|–—]\s*|\s[-:]\s', fallback)
    generic = {'contact us', 'about us', 'home page', 'free estimate', 'free roof inspection', 'roofing contractor'}
    supported = []
    for fragment in candidates:
        fragment = fragment.strip().rstrip('™®').strip()
        if len(fragment) < 6 or len(fragment.split()) < 2 or fragment.casefold() in generic:
            continue
        pattern = r'(?<!\w)' + re.escape(fragment) + r'(?!\w)'
        matches = {display_url(p.get('final_url') or p.get('url')) for p in pages
                   if p.get('title') and re.search(pattern, p['title'], re.I)}
        if len(matches - {''}) >= 2:
            supported.append(fragment)
    return (min(supported, key=len), 'repeated_browser_title') if supported else (fallback, 'browser_identity_or_title')


def canonical_social(value, platform):
    value = safe_url(value)
    if not value or not social_url(value, platform):
        return None
    p = urlsplit(value)
    path = p.path.strip('/')
    host = p.hostname.removeprefix('www.').removeprefix('m.')
    if platform == 'facebook':
        host = 'facebook.com'
        if not re.fullmatch(r'[^/]+', path) or path.casefold() in {'watch', 'reel', 'posts', 'photos', 'videos', 'profile.php', 'share.php', 'sharer.php'}:
            return None
    elif platform == 'instagram' and (not re.fullmatch(r'[^/]+', path) or path.casefold() in {'p', 'reel', 'reels', 'stories', 'explore'}):
        return None
    elif platform == 'linkedin' and not re.fullmatch(r'company/[^/]+/?', path):
        return None
    elif platform == 'youtube':
        path = re.sub(r'/(videos|featured|about)$', '', path)
    # Channel IDs are case-sensitive; human profile handles on other platforms are not.
    if platform != 'youtube' or path.startswith('@'):
        path = path.lower()
    return 'https://' + host + '/' + path


def contact_summary(detail):
    groups = {'phone': {}, 'email': {}, 'social': {}}
    observations = []
    for contact in detail.get('contacts', []):
        if contact.get('provenance') not in (None, 'browser', 'browser_observed'):
            continue
        if contact.get('evidence_type') not in {'tel', 'mailto', 'visible_text'} or contact.get('status', 'present') != 'present' or contact.get('rejected') or 'script' in str(contact.get('locator', '')).lower():
            continue
        observations.append(dict(contact, kind=contact.get('type', contact.get('contact_type')),
                                 value=contact.get('normalized_value', contact.get('normalized'))))
    for e in detail.get('evidence', []):
        key = e.get('detector_key')
        if e.get('status') != 'present' or e.get('provenance') not in (None, 'browser', 'browser_observed'):
            continue
        if key in {'phone', 'email', 'tel', 'mailto', 'facebook', 'instagram', 'linkedin', 'youtube'}:
            # Detector contacts require rendered, public provenance, not arbitrary scripts.
            if key in {'phone', 'email', 'tel', 'mailto'} and (not e.get('locator') or 'script' in e['locator'].lower()):
                continue
            values = e.get('value') if isinstance(e.get('value'), list) else [e.get('value')]
            for value in values:
                observations.append(dict(e, kind={'tel': 'phone', 'mailto': 'email'}.get(key, key), value=value))
    for row in observations:
        if not safe_url(row.get('source_url')) or float(row.get('confidence') or 0) < .8:
            continue
        kind, raw = row['kind'], row.get('value')
        if kind == 'phone':
            value = phone_number(raw)
        elif kind == 'email':
            value = email_address(raw)
        else:
            value = canonical_social(raw, kind) if kind in {'facebook', 'instagram', 'linkedin', 'youtube'} else None
        if value:
            group = kind if kind in {'phone', 'email'} else 'social'
            groups[group].setdefault(value, []).append(row)
    result = {}
    for kind, entries in groups.items():
        items = []
        for value, rows in entries.items():
            meta = provenance(rows)
            item = dict(value=value, **meta)
            if kind == 'phone':
                digits, _, extension = value.removeprefix('+1').partition(';ext=')
                item['display'] = f'({digits[:3]}) {digits[3:6]}-{digits[6:]}' + (f' ext. {extension}' if extension else '')
                page_types = {p.get('page_type') for p in detail.get('pages', [])
                              if display_url(p.get('final_url') or p.get('url')) in {display_url(u) for u in meta['source_urls']}}
                page_types.update(r.get('page_type') for r in rows)
                # Only explicit structured labels count; proximity in a directory is ambiguous.
                labels = {r['branch_label'] for r in rows if r.get('branch_label') and r.get('branch_label_verified') is True}
                main = any(r.get('phone_role') == 'main' and r.get('phone_role_verified') is True for r in rows)
                local = any(label.casefold() == str(detail['business'].get('city', '')).casefold() for label in labels)
                item.update(label=next(iter(labels)) if len(labels) == 1 else 'Additional public number',
                            priority=0 if {'homepage', 'contact'} <= page_types else 1 if main else 2 if local else 3)
            else:
                item['display'] = value if kind == 'email' else display_url(value)
                if kind == 'email':
                    # Prefer an already observed general contact address over
                    # another branch's address; do not construct either one.
                    item['priority'] = 0 if value.split('@')[0] in {'info', 'contact', 'hello', 'sales', 'office', 'support', 'booking', 'service'} else 1
                if kind == 'social':
                    item['platform'] = rows[0]['kind']
            items.append(item)
        result[kind] = sorted(items, key=lambda i: (i.get('priority', 0), -i['confidence'], -i['observed_pages'], i['value']))
    phones, emails = result['phone'], result['email']
    return dict(primary_phone=phones[0] if phones else None, other_phones=phones[1:],
                phone_selection='Public number shown first; no main or local branch designation was established.'
                if len(phones) > 1 and phones[0]['priority'] == 3 else None,
                primary_email=emails[0] if emails else None, other_emails=emails[1:], socials=result['social'])


def qualify(detail):
    """Build a disposable summary without mutating raw detail or stored scoring."""
    b, audit, score = detail['business'], detail.get('audit') or {}, detail.get('score') or {}
    raw = [e for e in detail.get('evidence', []) if e.get('detector_key') and e.get('status')]
    findings = aggregate(raw, audit.get('status') == 'completed')
    stored = score.get('breakdown', {}).get('findings', {})
    # Authoritative scoring statuses remain authoritative, including partial unknowns.
    for key in CORE:
        if key in stored:
            findings[key] = stored[key]
    strengths, gaps, unknown = [], [], []
    for key, label in LABELS.items():
        finding = findings.get(key, {})
        status = finding.get('status', 'unknown')
        rows = [e for e in raw if e['detector_key'] == key and (e['status'] == status or status in {'unknown', 'failed', 'blocked'})]
        item = dict(key=key, label=GAPS.get(key, label) if status == 'absent' else label, status=status, **provenance(rows))
        if status == 'present':
            strengths.append(item)
        elif status == 'absent' and key in GAPS and finding.get('confidence', 0) >= .8 and rows:
            gaps.append(item)
        elif status in {'unknown', 'blocked', 'failed'}:
            unknown.append(item)
    contacts = contact_summary(detail)
    verified_contact_keys = ({'phone'} if contacts['primary_phone'] else set()) | ({'email'} if contacts['primary_email'] else set()) | {s['platform'] for s in contacts['socials']}
    strengths = [s for s in strengths if s['key'] not in {'phone', 'email', 'facebook', 'instagram', 'linkedin', 'youtube'} or s['key'] in verified_contact_keys]
    contact_rows = [e for e in raw if e['detector_key'] == 'contact_page' and e['status'] == 'present' and safe_url(e.get('value'))]
    contact_page = dict(value=contact_rows[0]['value'], display=display_url(contact_rows[0]['value']), **provenance(contact_rows)) if contact_rows else None
    paths = []
    if contacts['primary_phone']: paths.append('Phone')
    if contacts['primary_email']: paths.append('Email')
    if contact_page: paths.append('Contact Page')
    if any(f['key'] in {'contact_form', 'quote_form', 'booking_form'} for f in strengths): paths.append('Form')
    status = audit.get('status', 'unverified')
    sufficient = status in {'completed', 'partial'} and score.get('opportunity_score') is not None and (score.get('evidence_confidence') or 0) >= 40
    primary = 'Insufficient Evidence' if not sufficient else next((label for key, label in OPPORTUNITIES.items() if any(g['key'] == key for g in gaps)), 'No Strong Gap Confirmed')
    value = score.get('opportunity_score')
    opportunity = 'Not enough evidence' if not sufficient else 'No confirmed gap' if value == 0 and status == 'partial' else f'{value:g}'
    audit_labels = {'completed': 'Completed', 'partial': 'Partial — useful evidence' if sufficient else 'Partial — limited evidence',
                    'failed': 'Failed — insufficient evidence', 'blocked': 'Blocked by website'}
    cause = audit.get('error_code') or audit.get('error_message')
    explanations = {
        'browser_navigation_failed': 'Some pages could not be opened.',
        'browser_render_timeout': 'Some pages did not finish loading in time.',
        'browser_unavailable': 'The browser service was unavailable.',
    }
    explanation = {
        'completed': 'The selected pages were inspected. Findings describe these pages, not every page on the website.',
        'partial': explanations.get(cause, 'Some browser checks could not be completed.') + ' Confirmed evidence was preserved; unavailable checks remain Unknown.',
        'failed': 'The website could not be assessed reliably. There is not enough evidence to qualify a conversion opportunity.',
        'blocked': 'The website blocked browser access. Unavailable checks are not counted as missing features.',
    }.get(status, 'A website audit is not available yet.')
    name, name_basis = business_name(detail)
    usable_audit = dict(audit, contacts=[dict(confidence=c['confidence']) for c in [contacts['primary_phone'], contacts['primary_email']] if c], evidence=raw)
    identity_confidence = 1.0 if b.get('canonical_name') not in (None, '', 'Unverified business') else 0.0
    usable = commercially_usable_v2(b, usable_audit, score, identity_confidence=identity_confidence) if safe_url(b.get('website_url')) and score else False
    scored_keys = set(stored)
    return dict(version=VERSION, business_name=name, name_basis=name_basis,
                website=safe_url(b.get('website_url')), website_display=display_url(b.get('website_url')),
                location=', '.join(str(b[k]) for k in ('city', 'state') if b.get(k)),
                **contacts, contact_page=contact_page, contact_paths=paths,
                confirmed_strengths=strengths, confirmed_gaps=gaps, unknown_checks=unknown,
                primary_opportunity=primary, commercially_usable_v2=usable,
                audit_summary=dict(status=status, label=audit_labels.get(status, 'Website not verified'), explanation=explanation, observed_at=audit.get('finished_at')),
                pages=[dict(id=p.get('id'), label=str(p.get('page_type') or 'page').replace('_', ' ').title(),
                            status=p.get('status', 'unknown'), url=safe_url(p.get('final_url') or p.get('url')),
                            display_url=display_url(p.get('final_url') or p.get('url'))) for p in detail.get('pages', [])],
                score_summary=dict(opportunity_display=opportunity, opportunity_note='No confirmed conversion gap' if sufficient and value == 0 else '',
                                   sufficient=sufficient, **{k: score.get(k) for k in ('opportunity_score', 'digital_gap', 'evidence_confidence', 'contact_confidence', 'profile_version')},
                                   tooltips=TOOLTIPS, strengths=[f for f in strengths if f['key'] in scored_keys], gaps=[f for f in gaps if f['key'] in scored_keys],
                                   formula=score.get('breakdown', {}).get('formula')))


def lead_row(detail):
    s = detail.get('summary') or qualify(detail)
    b, score = detail['business'], detail.get('score') or {}
    return dict(id=b['id'], business_name=s['business_name'], city=b.get('city'), state=b.get('state'), website=s['website'],
                **{k: score.get(k) for k in ('opportunity_score', 'digital_gap', 'evidence_confidence', 'contact_confidence')},
                primary_opportunity=s['primary_opportunity'], audit_status=s['audit_summary']['status'], summary=s)


def filter_sort(rows, *, audit_status=None, primary_opportunity=None, min_evidence=0, has_phone=False,
                has_email=False, has_contact=False, min_opportunity=None, sort='useful'):
    rows = [r for r in rows if (not audit_status or r['audit_status'] == audit_status)
            and (not primary_opportunity or r['primary_opportunity'] == primary_opportunity)
            and (r['evidence_confidence'] or 0) >= min_evidence
            and (not has_phone or r['summary']['primary_phone']) and (not has_email or r['summary']['primary_email'])
            and (not has_contact or r['summary']['contact_paths'])
            and (min_opportunity is None or (r['summary']['score_summary']['sufficient'] and r['opportunity_score'] >= min_opportunity))]
    def negative(row, key):
        value = row.get(key)
        return -value if value is not None else 1
    keys = {
        'useful': lambda r: (not r['summary']['commercially_usable_v2'], negative(r, 'opportunity_score'), negative(r, 'evidence_confidence')),
        'opportunity': lambda r: (not r['summary']['score_summary']['sufficient'], negative(r, 'opportunity_score')),
        'evidence': lambda r: (negative(r, 'evidence_confidence'),),
        'contact': lambda r: (negative(r, 'contact_confidence'),),
        'business': lambda r: (r['business_name'].casefold(),),
        'audit': lambda r: (r['audit_status'],),
    }
    return sorted(rows, key=lambda r: (*keys.get(sort, keys['useful'])(r), r['business_name'].casefold(), r['id']))


CSV_FIELDS = ('business_name', 'location', 'website', 'primary_phone', 'primary_email', 'contact_page', 'contact_paths',
              'primary_opportunity', 'opportunity_score', 'opportunity_display', 'digital_gap', 'evidence_confidence',
              'contact_confidence', 'audit_status', 'commercially_usable_v2', 'score_profile_version')


def safe_cell(value):
    value = '' if value is None else str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')) else value


def summary_csv(rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(CSV_FIELDS)
    for row in rows:
        s, score = row['summary'], row['summary']['score_summary']
        data = dict(business_name=s['business_name'], location=s['location'], website=s['website'],
                    **{k: (s[k] or {}).get('value') for k in ('primary_phone', 'primary_email', 'contact_page')},
                    contact_paths='; '.join(s['contact_paths']), primary_opportunity=s['primary_opportunity'],
                    **{k: score[k] for k in ('opportunity_score', 'opportunity_display', 'digital_gap', 'evidence_confidence', 'contact_confidence')},
                    audit_status=s['audit_summary']['status'], commercially_usable_v2=s['commercially_usable_v2'], score_profile_version=score['profile_version'])
        writer.writerow([safe_cell(data.get(k)) for k in CSV_FIELDS])
    return output.getvalue()
