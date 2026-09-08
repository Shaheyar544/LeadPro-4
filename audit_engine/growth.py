"""Digital Growth v1: bounded observations, conservative checks, no provider data.

These checks describe inspected pages. A pass means the check was observed, not
that a page ranks or that a markup implementation qualifies for rich results.
"""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, unquote

from .detectors import evidence, phone_number
from .growth_resources import origin
from url_safety import normalize_url, UnsafeURL

CRAWL_VERSION = 'digital_growth_crawl_v1'
LOCAL_TYPES = frozenset(json.loads(Path(__file__).with_name('local_business_types.json').read_text())['types'])
STOPWORDS = frozenset('the and for with your our from that this home welcome about contact services service company'.split())


def words(text):
    return set(re.findall(r'[a-z0-9]{3,}', str(text).lower())) - STOPWORDS


def page_type(url, title='', headings=(), hint=''):
    path = unquote(urlsplit(url).path).lower()
    if path in {'', '/'}:
        return 'homepage', .95
    for kind, pattern in [('contact', r'contact'), ('about', r'about|our-team'),
                          ('location', r'locations?|areas?-served|service-areas?|near-me'),
                          ('blog', r'blog|news|articles?'), ('service', r'services?|repair|installation|replacement|inspection|maintenance')]:
        if re.search(r'(?:^|[/_-])(?:' + pattern + r')(?:[/_-]|$)', path):
            return kind, .9
    if hint in {'service', 'services', 'location', 'about', 'contact'}:
        return ('service' if hint == 'services' else hint), .8
    if any(re.search(r'\b(?:repair|installation|replacement|services)\b', h.get('text', ''), re.I) for h in headings if h.get('level') == 1):
        return 'service', .75
    return 'other' if title else 'unknown', .5 if title else 0


def candidate_links(links, base, settings, seen=()):
    candidates = []
    for link in links[:250]:
        try:
            url = normalize_url(link.get('href', ''))
            if origin(url) != origin(base) or urlsplit(url).query or url in seen:
                continue
        except (UnsafeURL, TypeError):
            continue
        description = unquote(urlsplit(url).path) + ' ' + str(link.get('text', ''))
        if re.search(r'login|log.?out|sign.?in|account|cart|checkout|privacy|terms|download|\.(?:pdf|zip|docx?|xlsx?|exe|jpe?g|png|svg|mp4)(?:$|\s)', description, re.I):
            continue
        kind, confidence = page_type(url, link.get('text', ''))
        if kind == 'other' and link.get('service_context'):
            kind, confidence = 'service', .8
        if kind in {'contact', 'service', 'location', 'about'} and confidence >= .75:
            candidates.append(({'contact': 0, 'service': 1, 'location': 2, 'about': 3}[kind], url, kind))
    counts, result = {}, []
    for _, url, kind in sorted(set(candidates)):
        cap = settings.seo_services if kind == 'service' else settings.seo_locations if kind == 'location' else 1
        if counts.get(kind, 0) >= cap:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        result.append((url, kind))
    # Balance the extra slots: a directory must not consume the budget before
    # a useful service/location/about page can be sampled.
    groups = {kind: [row for row in result if row[1] == kind] for kind in ('contact', 'service', 'location', 'about')}
    balanced = []
    for index in range(max((len(v) for v in groups.values()), default=0)):
        balanced += [items[index] for items in groups.values() if index < len(items)]
    return balanced


def check(key, label, outcome, page, *, detail='', value=None, confidence=.9):
    row = evidence('growth.' + key, {'pass': 'present', 'gap': 'absent'}.get(outcome, 'unknown'),
                   value=dict(outcome=outcome, label=label, detail=detail[:400], observation=value),
                   url=page.get('final_url', ''), page_id=page.get('id'), page_type=page.get('page_type', 'homepage'),
                   excerpt=detail, locator='Digital Growth: ' + key, confidence=confidence)
    row['detector_version'] = CRAWL_VERSION
    return row


def boolean(value, complete):
    return 'pass' if value else 'gap' if complete else 'unknown'


def topic_outcome(observation):
    title = observation.get('title', '')
    headings = observation.get('headings', [])
    contextual_kind = observation.get('kind') in {'contact', 'about', 'location'}
    # A missing H1 does not erase a clear title/topic; CONTACT US is a clear
    # contact-page topic even though those words are generic SEO stopwords.
    clear = bool(words(title) or any(words(h.get('text', '')) for h in headings) or contextual_kind)
    return boolean(clear, observation.get('complete') is True)


def canonical_info(values, url):
    safe = []
    for value in values:
        try:
            if urlsplit(value).fragment:
                return dict(state='invalid', targets=[], reason='canonical_fragment')
            safe.append(normalize_url(value))
        except UnsafeURL:
            return dict(state='invalid', targets=[])
    unique = sorted(set(safe))
    if not unique:
        return dict(state='missing', targets=[])
    if len(unique) > 1:
        return dict(state='conflicting', targets=unique)
    target = unique[0]
    same = origin(target) == origin(url)
    # Query-free self-canonicals on campaign URLs are ordinary consolidation.
    self_ref = same and urlsplit(target).path.rstrip('/') == urlsplit(url).path.rstrip('/') and not urlsplit(target).query
    return dict(state='self' if self_ref or target == normalize_url(url) else 'same_origin_alternate' if same else 'cross_domain', targets=unique)


def schema_info(raw, url):
    entities = []
    foreign_entities = 0
    for e in raw.get('entities', [])[:100]:
        if not isinstance(e, dict):
            continue
        target = e.get('url') or e.get('id')
        try:
            if target and not str(target).startswith('#') and origin(target) != origin(url):
                foreign_entities += 1
                continue
        except UnsafeURL:
            foreign_entities += 1
            continue
        # Ratings/reviews/offers/arbitrary schema properties cannot cross this boundary.
        entities.append({k: e[k] for k in ('types', 'name', 'url', 'id', 'phone', 'address', 'geo_present', 'hours_present', 'areas') if k in e})
    types = sorted(set(raw.get('microdata_types', [])[:60]) | {t for e in entities for t in e.get('types', []) if isinstance(t, str)})
    local = [e for e in entities if LOCAL_TYPES.intersection(e.get('types', []))]
    return dict(types=types, local_business=bool(LOCAL_TYPES.intersection(types)), organization='Organization' in types or bool(local),
                local_entities=local, invalid_json_count=raw.get('invalid_json_count', 0), complete=raw.get('complete') is True and not foreign_entities,
                excluded_entity_count=foreign_entities,
                structured_names=[e.get('name') for e in local if e.get('name')][:5])


def page_observation(facts, page):
    raw = facts.get('growth')
    if facts.get('blocked') or facts.get('login_wall') or facts.get('soft_error') or not isinstance(raw, dict) or raw.get('version') != CRAWL_VERSION:
        return None, []
    url = page['final_url']
    head_complete = facts.get('ready_state') == 'complete'
    body_complete = raw.get('body_complete') is True and facts.get('complete') is True
    headings = raw.get('headings', [])[:60]
    h1s = [h.get('text', '') for h in headings if h.get('level') == 1]
    title, description = str(raw.get('title', ''))[:240], next((d for d in raw.get('descriptions', []) if d), '')[:320]
    kind, kind_confidence = page_type(url, title, headings, page.get('page_type', ''))
    schema = schema_info(raw.get('schema', {}), url)
    canonical = canonical_info(raw.get('canonicals', [])[:8], url)
    links = []
    for link in raw.get('links', [])[:250]:
        try:
            target = normalize_url(link.get('href', ''))
            if origin(target) == origin(url):
                links.append(dict(url=target, text=str(link.get('text', ''))[:120], navigation=bool(link.get('navigation')),
                                  service_context=bool(link.get('service_context'))))
        except (UnsafeURL, TypeError):
            continue
    phones = sorted({p for c in facts.get('contacts', []) if c.get('type') == 'phone' and c.get('kind') in {'tel', 'visible_text'}
                     if (p := phone_number(c.get('value')))})
    observation = dict(url=url, page_id=page['id'], kind=kind, kind_confidence=kind_confidence, title=title,
        description=description, title_length=len(title), description_length=len(description), headings=headings,
        h1_count=len(h1s), canonical=canonical, robots_meta=raw.get('robots_meta', [])[:8], schema=schema,
        images=raw.get('images', {}), visible_words=raw.get('visible_words'), paragraphs=raw.get('paragraphs'),
        section_count=raw.get('section_count'), faq=bool(raw.get('faq')), video=bool(raw.get('video')),
        links=links, addresses=[str(a)[:240] for a in raw.get('addresses', [])[:12]], phones=phones,
        visible_location_context=[str(a)[:100] for a in raw.get('visible_location_context', [])[:20]],
        service_topics=sorted({h.get('text', '') for h in headings if re.search(r'\b(?:repair|installation|replacement|inspection|maintenance|cleaning|remodeling)\b', h.get('text', ''), re.I)})[:20],
        service_area_context=bool(raw.get('service_area_context')), complete=body_complete,
        internal_link_count=len(links), navigation_link_count=sum(l['navigation'] for l in links),
        breadcrumbs=bool(raw.get('breadcrumbs')) or 'BreadcrumbList' in schema['types'],
        heading_hierarchy_skip=any(b.get('level', 1) > a.get('level', 1) + 1 for a, b in zip(headings, headings[1:])),
        content_signature=hashlib.sha256('|'.join(h.get('text', '') for h in headings).encode()).hexdigest())
    rows = []
    def add(key, label, outcome, detail='', value=None, confidence=.9):
        rows.append(check(key, label, outcome, page, detail=detail, value=value, confidence=confidence))
    directives = [r.get('content', '').lower() for r in observation['robots_meta'] if r.get('agent') in {'robots', 'googlebot'}]
    noindex = any(re.search(r'\b(?:noindex|none)\b', value) for value in directives)
    add('indexability', 'Indexing directives', 'gap' if noindex else 'pass' if head_complete else 'unknown',
        'Noindex directive observed; verify whether exclusion is intentional.' if noindex else 'No noindex directive observed in inspected metadata; actual indexing is not measured.', directives)
    add('canonical', 'Canonical declaration', 'gap' if canonical['state'] in {'missing', 'invalid', 'conflicting'} and head_complete else
        'pass' if canonical['state'] == 'self' else 'unknown',
        'Canonical ' + canonical['state'].replace('_', ' ') + ' on this page. Alternate targets require editorial review; no automatic mismatch claim.', canonical)
    add('https', 'HTTPS delivery', 'pass' if urlsplit(url).scheme == 'https' else 'gap', 'Observed final page scheme only.')
    add('title', 'Page title', boolean(title, head_complete), 'Title ' + ('observed.' if title else 'not found on this page.'), dict(length=len(title), length_note='very short' if 0 < len(title) < 15 else 'long' if len(title) > 70 else 'ordinary'))
    add('description', 'Meta description', boolean(description, head_complete), 'Meta description ' + ('observed.' if description else 'not found on this page.'))
    add('viewport', 'Mobile viewport metadata', boolean(raw.get('viewport'), head_complete), 'Viewport declaration observed.' if raw.get('viewport') else 'Viewport declaration not found on this page.')
    valid_schema = bool(schema['types'])
    add('schema', 'Structured data', 'pass' if valid_schema else 'unknown' if schema['invalid_json_count'] else boolean(False, head_complete and schema['complete']),
        'Recognized schema types observed; rich-result eligibility is not assessed.' if valid_schema else 'Structured data could not be interpreted.' if schema['invalid_json_count'] else 'Structured data not found in inspected markup.', schema['types'])
    add('schema_valid', 'JSON-LD syntax', 'gap' if schema['invalid_json_count'] else 'pass' if valid_schema and schema['complete'] else 'unknown',
        'JSON-LD present_but_invalid_json; syntactic validation only.' if schema['invalid_json_count'] else 'No syntax error observed in the inspected JSON-LD blocks.')
    headings_complete = body_complete and raw.get('headings_complete') is True
    add('h1', 'Main page heading', boolean(h1s, headings_complete), 'H1 observed. Multiple H1s are informational.' if h1s else 'H1 not found in the rendered page sample.', len(h1s))
    images = observation['images']
    missing_alt = images.get('missing_alt', 0)
    add('image_alt', 'Image alternative text', 'gap' if missing_alt else 'pass' if images.get('count') and body_complete else 'unknown',
        'Images without an alt attribute: ' + str(missing_alt) + '. Empty alt is tracked separately and may be decorative.', images)
    add('mixed_content', 'Secure resource references', 'gap' if urlsplit(url).scheme == 'https' and raw.get('mixed_content') else 'pass' if head_complete else 'unknown',
        'Insecure resource references observed; the browser may upgrade or block them.' if raw.get('mixed_content') else 'No insecure resource reference observed.', raw.get('mixed_content', 0))
    generic_title = title.strip().lower() in {'home', 'homepage', 'welcome', 'untitled', 'services', 'page'}
    add('descriptive_title', 'Descriptive title', 'gap' if generic_title else 'pass' if words(title) else 'gap' if head_complete else 'unknown',
        'Generic title observed.' if generic_title else 'Title specificity is an observable heuristic, not a ranking prediction.')
    alignment = bool(words(title) & words(' '.join(h1s)))
    add('topic_alignment', 'Title and H1 topic alignment', 'pass' if alignment and raw.get('h1_body_overlap') else 'unknown',
        'Shared topic terms observed in title, heading and supporting text.' if alignment else 'Topic alignment could not be established; no keyword-density penalty.')
    add('page_topic', 'Identifiable page topic', topic_outcome(observation), 'Topic assessed from the observed title, headings and page context; a missing H1 alone does not erase a clear topic.')
    add('supporting_content', 'Supporting service detail', boolean(raw.get('supporting_detail'), body_complete) if kind == 'service' else 'unknown',
        'Supporting paragraphs observed.' if raw.get('supporting_detail') else 'Supporting service detail not found in inspected page sections. Word count alone does not determine quality.')
    contact_link = any(re.search(r'contact|quote|book|schedule', l['url'] + ' ' + l['text'], re.I) for l in links)
    add('internal_contact', 'Internal contact navigation', boolean(contact_link or kind == 'contact', body_complete and raw.get('links_complete') is True), 'Contact navigation is assessed on this page only.')
    areas = [a for e in schema['local_entities'] for a in e.get('areas', []) if isinstance(a, str)]
    address_context = bool(observation['addresses'] or any(e.get('address') for e in schema['local_entities']))
    location_context = address_context or observation['visible_location_context'] or areas
    add('location_context', 'Location or service-area context', boolean(location_context, body_complete) if kind in {'homepage', 'service', 'location', 'contact'} else 'unknown',
        'Website location/service-area context observed.' if location_context else 'Location or service-area context not found on this inspected page.')
    add('local_schema', 'Local business structured data', ('pass' if schema['local_business'] else 'unknown' if schema['invalid_json_count'] else boolean(False, head_complete and schema['complete'])) if kind in {'homepage', 'location', 'contact'} else 'unknown',
        'LocalBusiness or a recognized subtype observed.' if schema['local_business'] else 'Local business schema not found on this inspected page.', schema['types'])
    add('address', 'Website address context', 'pass' if address_context else 'unknown', 'Physical address observed.' if address_context else 'Address not confirmed; a service-area business may intentionally omit its street address.')
    all_links = raw.get('links', [])[:250]
    maps = any(re.search(r'google\.[^/]+/maps|maps\.google\.|maps\.apple\.|bing\.com/maps', str(l.get('href', '')), re.I) for l in all_links)
    maps = maps or any(re.search(r'google\.[^/]+/maps|maps\.google\.', str(i.get('src', '')), re.I) for i in facts.get('iframes', []))
    add('directions', 'Contact and directions', 'pass' if maps or kind == 'contact' else 'unknown', 'Map/directions or contact-page path observed; map contents were not collected.')
    reviews = bool(raw.get('testimonials')) or any(re.search(r'^(https?://)?(?:www\.)?(?:g\.page/[^?]+/review|search\.google\.com/local/writereview|yelp\.com/biz/|trustpilot\.com/review/)', str(l.get('href', '')), re.I) for l in all_links)
    add('review_integration', 'Website review integration', 'pass' if reviews else 'unknown', 'A testimonial/review section or public review link was observed; review text and provider ratings were not collected.')
    observation['explicit_areas'] = sorted(set(areas))[:12]
    local_terms = [e.get('address', {}).get('addressLocality', '') for e in schema['local_entities']]
    observation['local_terms_in_title_heading'] = sorted({t for t in local_terms if t and t.casefold() in (title + ' ' + ' '.join(h1s)).casefold()})
    # Nofollow, hierarchy, FAQ, media and image dimensions are informational.
    row = evidence('growth.page_observation', 'present', observation, url=url, page_id=page['id'], page_type=page.get('page_type', 'homepage'), locator='Shared rendered DOM facts')
    row['detector_version'] = CRAWL_VERSION
    rows.append(row)
    return observation, rows


def cross_page_checks(observations, pages):
    if not observations:
        return [], []
    page = pages[0]
    rows, analyses = [], []
    unique = list({o['url']: o for o in observations}.values())
    for field, key in [('title', 'duplicate_title'), ('description', 'duplicate_description')]:
        values = [o[field].strip().casefold() for o in unique if o[field]]
        duplicates = sorted({v for v in values if values.count(v) > 1})
        affected = sum(v in duplicates for v in values)
        state = 'gap' if duplicates else 'pass' if len(values) >= 2 else 'unknown'
        rows.append(check(key, 'Distinct ' + field + ' across audited pages', state, page,
                          detail=f'Duplicate across {affected} of {len(values)} audited pages.' if duplicates else 'Comparison covers distinct inspected URLs only.', value=dict(compared=len(values), duplicate_count=len(duplicates), affected_pages=affected)))
    addresses = {re.sub(r'[^a-z0-9]', '', a.casefold()) for o in unique for a in o['addresses'] if a}
    comparable = [o for o in unique if len(o['phones']) == 1 and o['addresses']]
    # Do not compare multi-branch directory numbers, call tracking, or inferred entities.
    comparable = comparable if len(addresses) == 1 else []
    phone_values = {o['phones'][0] for o in comparable}
    observed_names = {re.sub(r'[^a-z0-9]', '', n.casefold()) for o in comparable for n in o['schema'].get('structured_names', []) if n}
    state = 'gap' if len(comparable) >= 2 and len(phone_values) > 1 else 'pass' if len(comparable) >= 2 else 'unknown'
    rows.append(check('nap_consistency', 'Website NAP consistency', state, page,
        detail='Different public phones observed with the same explicit address; verify call tracking or intended routing.' if state == 'gap' else 'Only same-address, single-phone pages can be compared. This is not an external citation audit.',
        value=dict(compared_pages=len(comparable), distinct_phones=len(phone_values), distinct_names=len(observed_names),
                   name_comparison='consistent_observed_strings' if len(observed_names) == 1 else 'unknown',
                   address_comparison='same_normalized_observed_string' if comparable else 'unknown')))
    sampled = {o['url'] for o in unique}
    for o in unique:
        for link in o['links']:
            kind, conf = page_type(link['url'], link['text'])
            if (kind == 'service' or link['service_context']) and link['text'] and link['url'] not in sampled:
                analyses.append(dict(kind='possible_missing_service_page', topic=link['text'], url=link['url'], confidence=min(conf, .7),
                    status='unknown', label='Dedicated page not found in audited sample', source_url=o['url']))
        for topic in o.get('service_topics', []):
            if o['kind'] != 'service' and not any(p['kind'] == 'service' and len(words(topic) & words(p['title'] + ' ' + ' '.join(h['text'] for h in p['headings']))) >= 2 for p in unique):
                analyses.append(dict(kind='possible_missing_service_page', topic=topic, confidence=.6, status='unknown',
                    label='Dedicated page not found in audited sample', source_url=o['url']))
    areas = sorted({a for o in unique for a in o['explicit_areas']})
    if len(areas) > 1:
        analyses.append(dict(kind='location_expansion_review', areas=areas, confidence=.7, status='unknown',
            label='Create useful, unique location/service pages where the business genuinely serves those areas.'))
    return rows, list({json.dumps(a, sort_keys=True): a for a in analyses}.values())[:20]
