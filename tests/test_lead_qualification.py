"""Qualification is a read-only view over observations; never guesses or rescales."""
from copy import deepcopy
import csv
import io
import pytest
from audit_engine.detectors import evidence
from production_scoring import CORE, score_browser_evidence
from lead_summary import qualify, business_name, display_url, safe_url, lead_row, filter_sort, summary_csv


def detail(status='completed', changes=None):
    rows = [evidence(k, (changes or {}).get(k, 'present'), True, url='https://business.test/', locator='form') for k in CORE]
    audit = dict(status=status, evidence=rows, contacts=[], finished_at='2026-09-08T16:00:00Z')
    return dict(business=dict(id='one', canonical_name='Observed Business', website_url='https://business.test/', city='Dallas', state='TX'),
                audit=audit, evidence=rows, contacts=[], pages=[dict(id='home', page_type='homepage', status=status, title='Observed Business', final_url='https://business.test/')],
                score=score_browser_evidence(audit), sources=[], history=[])


def contact(value, kind='phone', page='https://business.test/', **kwargs):
    return dict(id=value + page, type=kind, normalized_value=value, evidence_type='tel' if kind == 'phone' else 'mailto',
                source_url=page, confidence=.98, provenance='browser', **kwargs)


def test_canonical_phone_formats_preserve_raw_and_all_sources():
    d = detail()
    values = ['6024973674', '602-497-3674', '(602) 497-3674', '+1 602 497 3674']
    d['contacts'] = [contact(v, page='https://business.test/' + str(i % 3)) for i, v in enumerate(values)]
    before = deepcopy(d)
    s = qualify(d)
    assert s['primary_phone']['display'] == '(602) 497-3674'
    assert s['primary_phone']['observed_pages'] == 3
    assert len(s['primary_phone']['evidence_ids']) == 4
    assert s['primary_phone']['confidence_label'] == 'High'
    assert s['other_phones'] == [] and d == before


def test_distinct_branches_and_extensions_are_not_collapsed_or_guessed():
    d = detail()
    d['contacts'] = [contact('6024973674'), contact('2145551212', branch_label='Dallas', branch_label_verified=True),
                     contact('6024973674 ext 10'), contact('6024973674 ext 11', excerpt='Dallas office and Phoenix office')]
    s = qualify(d)
    assert s['primary_phone']['value'] == '+12145551212'
    assert s['primary_phone']['label'] == 'Dallas'
    assert len(s['other_phones']) == 3
    assert all(c['label'] == 'Additional public number' for c in s['other_phones'])


def test_home_and_contact_phone_has_priority_over_explicit_main_and_branch():
    d = detail()
    d['pages'].append(dict(page_type='contact', final_url='https://business.test/contact'))
    d['contacts'] = [contact('6024973674'), contact('6024973674', page='https://business.test/contact'),
                     contact('2145551212', phone_role='main', phone_role_verified=True)]
    assert qualify(d)['primary_phone']['value'] == '+16024973674'


def test_ambiguous_numbers_explain_selection_without_branch_inference():
    d = detail(); d['contacts'] = [contact('6024973674'), contact('2145551212', excerpt='Dallas (602) 497-3674 Phoenix (214) 555-1212')]
    s = qualify(d)
    assert 'no main or local branch' in s['phone_selection']
    assert s['other_phones'][0]['label'] == 'Additional public number'


def test_email_case_and_repeated_observations():
    d = detail(); d['contacts'] = [contact('Office@business.test', 'email'), contact('office@business.test', 'email', page='https://business.test/contact')]
    s = qualify(d)
    assert s['primary_email']['value'] == 'office@business.test'
    assert s['primary_email']['observed_pages'] == 2 and s['other_emails'] == []


def test_observed_general_email_preferred_to_a_different_branch_address():
    d = detail(); d['contacts'] = [contact('albuquerque@business.test', 'email'), contact('office@business.test', 'email')]
    s = qualify(d)
    assert s['primary_email']['value'] == 'office@business.test'
    assert s['other_emails'][0]['value'] == 'albuquerque@business.test'


@pytest.mark.parametrize('row', [contact('test@example.com', 'email'), contact('hello@business.test', 'email', rejected=True),
    contact('hello@business.test', 'email', status='rejected'), contact('hello@business.test', 'email', locator='script')])
def test_rejected_and_script_email_never_displayed(row):
    d = detail(); d['contacts'] = [row]
    assert qualify(d)['primary_email'] is None


@pytest.mark.parametrize('platform,urls,expected', [
    ('facebook', ['https://www.facebook.com/Business/', 'https://m.facebook.com/business?utm_source=a', 'https://facebook.com/business/posts/123'], ['https://facebook.com/business']),
    ('instagram', ['https://instagram.com/Business/', 'https://www.instagram.com/business?igsh=abc', 'https://instagram.com/p/123'], ['https://instagram.com/business']),
    ('linkedin', ['https://linkedin.com/company/business/', 'https://www.linkedin.com/company/business', 'https://linkedin.com/posts/123'], ['https://linkedin.com/company/business']),
    ('youtube', ['https://youtube.com/@Business', 'https://www.youtube.com/@business/videos', 'https://youtube.com/watch?v=abc', 'https://youtu.be/abc'], ['https://youtube.com/@business']),
])
def test_social_profiles_deduplicate_without_posts_videos_or_share_urls(platform, urls, expected):
    d = detail(); d['evidence'].append(evidence(platform, 'present', urls, url='https://business.test/', locator='a'))
    assert [c['value'] for c in qualify(d)['socials']] == expected


@pytest.mark.parametrize('key,label', [('quote_form','Quote / Estimate Conversion'), ('booking_form','Online Booking'),
    ('contact_form','Contact Conversion'), ('contact_page','Contact Conversion'), ('click_to_call','Click-to-Call'),
    ('primary_cta','CTA Improvement'), ('mobile_layout','Mobile Conversion')])
def test_deterministic_primary_gap(key, label):
    assert qualify(detail(changes={key:'absent'}))['primary_opportunity'] == label


def test_primary_order_and_no_gap():
    assert qualify(detail(changes={'quote_form':'absent','booking_form':'absent'}))['primary_opportunity'] == 'Quote / Estimate Conversion'
    assert qualify(detail())['primary_opportunity'] == 'No Strong Gap Confirmed'


@pytest.mark.parametrize('status', ['failed','blocked','unverified'])
def test_failed_blocked_unverified_hide_even_stale_numeric_score(status):
    d = detail(); d['audit']['status'] = status
    s = qualify(d)
    assert s['primary_opportunity'] == 'Insufficient Evidence'
    assert s['score_summary']['opportunity_display'] == 'Not enough evidence'
    assert not s['commercially_usable_v2']


def test_unknown_is_never_gap_or_zero():
    d = detail(changes={k:'unknown' for k in CORE})
    s = qualify(d)
    assert s['confirmed_gaps'] == []
    assert s['primary_opportunity'] == 'Insufficient Evidence'
    assert s['score_summary']['opportunity_display'] == 'Not enough evidence'


@pytest.mark.parametrize('status,confidence,score,display', [
    ('completed',85,0,'0'), ('partial',57,0,'No confirmed gap'), ('partial',28,0,'Not enough evidence'),
    ('completed',85,None,'Not enough evidence'), ('completed',85,33.33,'33.33')])
def test_score_display_preserves_stored_number(status, confidence, score, display):
    d = detail(status); d['score'].update(evidence_confidence=confidence, opportunity_score=score)
    s = qualify(d)
    assert s['score_summary']['opportunity_display'] == display
    assert s['score_summary']['opportunity_score'] == score and d['score']['opportunity_score'] == score


def test_grouping_and_not_applicable_raw_preservation():
    d = detail(changes={'quote_form':'absent','booking_form':'unknown','mobile_layout':'not_applicable','click_to_call':'failed'})
    before = deepcopy(d); s = qualify(d)
    assert 'contact_form' in {i['key'] for i in s['confirmed_strengths']}
    assert {i['key'] for i in s['confirmed_gaps']} == {'quote_form'}
    assert {'booking_form','click_to_call'} <= {i['key'] for i in s['unknown_checks']}
    assert all(i['key'] != 'mobile_layout' for k in ['confirmed_gaps','confirmed_strengths','unknown_checks'] for i in s[k])
    assert d == before


def test_partial_absence_remains_unknown_despite_raw_absent_observation():
    s = qualify(detail('partial', {'quote_form':'absent'}))
    assert not s['confirmed_gaps']
    assert 'quote_form' in {i['key'] for i in s['unknown_checks']}


def test_tracking_display_only_preserves_functional_query_and_source():
    url = 'https://business.test/location/?utm_source=google&branch=Dallas%20North&gclid=x&step=2#contact'
    assert display_url(url) == 'business.test/location/?branch=Dallas%20North&step=2#contact'
    assert safe_url(url) == url
    assert safe_url('https://business.test:443/') == 'https://business.test:443/'


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'data:text/html,x', 'https://user:pass@business.test/', 'https://business.test:8080/', 'https://business.test/\nx', 'https://business.test\\evil'])
def test_unsafe_links_remain_inert(url):
    assert safe_url(url) is None and display_url(url) == ''


@pytest.mark.parametrize('title,other,expected', [
    ('New View Roofing - 5 Star Dallas Roofing Contractors', 'Free Roof Inspection| New View Roofing | Dallas, TX | Roofing Contractor', 'New View Roofing'),
    ('Local Roof Repair & Replacement In Dallas, Texas | PRIORITY ROOFING™', 'Contact Us | PRIORITY ROOFING™', 'PRIORITY ROOFING'),
    ('Dallas Roofing Company Since 1959 | T Rock Roofing', 'Contact Us - T Rock Roofing and Contracting', 'T Rock Roofing'),
    ('Top-Rated Roofing Company in Dallas, TX | Blue Hammer Roofing', 'About Us | Blue Hammer Roofing', 'Blue Hammer Roofing'),
    ('Dallas Roofing Contractor Since 1983 | Arrington Roofing', None, 'Dallas Roofing Contractor Since 1983 | Arrington Roofing'),
])
def test_existing_live_title_patterns_require_independent_page_support(title, other, expected):
    d = detail(); d['business']['canonical_name'] = title; d['pages'][0]['title'] = title
    if other: d['pages'].append(dict(title=other, final_url='https://business.test/contact'))
    assert business_name(d)[0] == expected


def test_structured_browser_brand_precedes_title_but_provider_brand_does_not():
    d = detail(); d['business']['structured_name'] = dict(value='Browser Brand', confidence=.9, provenance='browser_observed')
    assert business_name(d)[0] == 'Browser Brand'
    d['business']['structured_name']['provenance'] = 'google_places_new'
    assert business_name(d)[0] == 'Observed Business'


def test_csv_is_summary_only_formula_safe_and_uses_same_filtered_sorted_rows():
    a = detail(changes={'quote_form':'absent'}); a['business']['canonical_name'] = '=SUM(1,2)'
    a['contacts'] = [contact('6024973674')]
    b = detail(); b['business']['id'] = 'two'
    rows = filter_sort([lead_row(a), lead_row(b)], has_phone=True, min_opportunity=1)
    parsed = list(csv.DictReader(io.StringIO(summary_csv(rows))))
    assert len(parsed) == 1 and parsed[0]['business_name'] == "'=SUM(1,2)"
    assert parsed[0]['primary_phone'] == "'+16024973674"
    assert parsed[0]['primary_opportunity'] == 'Quote / Estimate Conversion'
    assert not {'evidence','provider_identifier','raw_value','excerpt'} & parsed[0].keys()


def test_sort_filter_and_useful_indicator_keep_failed_records_by_default():
    a = detail(); a['business']['id'] = 'a'
    b = detail('failed', {k:'failed' for k in CORE}); b['business']['id'] = 'b'
    c = detail(changes={'quote_form':'absent'}); c['business']['id'] = 'c'
    rows = [lead_row(d) for d in (b,a,c)]
    assert [r['id'] for r in filter_sort(rows)] == ['c','a','b']
    assert len(filter_sort(rows, audit_status='failed')) == 1
    assert len(filter_sort(rows, min_evidence=85)) == 2
    assert len(filter_sort(rows, primary_opportunity='Insufficient Evidence')) == 1
