import asyncio
from copy import deepcopy
import csv
import io
import json
from unittest.mock import AsyncMock, patch

import pytest

from audit_engine.growth import page_observation, cross_page_checks, canonical_info, page_type, candidate_links, LOCAL_TYPES, check
from audit_engine.growth_resources import Robots, Resources, probe, sitemap_document, rep_path
from audit_engine.runner import AuditEngine
from browser.mock import MockBrowserProvider
from engine_config import EngineConfig
from growth_scoring import build_growth, profile, rollup, PROFILES, RULES, GROWTH_CSV_FIELDS
from production_scoring import score_browser_evidence
from tests.growth_fixtures import BASE, facts, FixtureResources


def collected(kind='strong'):
    observations, rows, pages = [], [], []
    for i, url in enumerate([BASE, BASE + 'services/repair', BASE + 'contact']):
        f = facts(kind, url)
        page = dict(id=str(i), final_url=url, page_type='homepage' if i == 0 else 'service' if i == 1 else 'contact')
        o, r = page_observation(f, page)
        rows += r
        if o:
            observations.append(o); pages.append(page)
    more, analysis = cross_page_checks(observations, pages)
    rows += more
    if kind != 'blocked':
        for key in ('robots', 'sitemap', 'http', 'broken_links'):
            rows.append(check(key, key, 'gap' if kind == 'technical' and key in {'sitemap', 'broken_links'} else 'pass', pages[0]))
    conversion = score_browser_evidence(dict(status='blocked', evidence=[], contacts=[]))
    return build_growth(rows, conversion, assessed=True, observations=observations, page_analysis=analysis), rows


def test_five_site_classes_and_score_direction():
    strong, _ = collected()
    technical, _ = collected('technical')
    on_page, _ = collected('on_page')
    local, _ = collected('local')
    blocked, _ = collected('blocked')
    for version in PROFILES:
        assert strong['profiles'][version]['opportunity_score'] == 0
        assert blocked['profiles'][version]['opportunity_score'] is None
        assert blocked['profiles'][version]['confirmed_gaps'] == []
    assert technical['profiles']['technical_seo_v1']['opportunity_score'] > 40
    assert on_page['profiles']['on_page_seo_v1']['opportunity_score'] > 0
    assert local['profiles']['local_seo_v1']['opportunity_score'] > 40
    assert strong['recommended_services']['services'] == []
    assert blocked['recommended_services']['services'] == []


@pytest.mark.parametrize('values,url,state', [([], BASE, 'missing'), ([BASE], BASE, 'self'),
    ([BASE], BASE + '?utm_source=search', 'self'), ([BASE + 'other'], BASE, 'same_origin_alternate'),
    (['https://external.test/'], BASE, 'cross_domain'), ([BASE, BASE + 'other'], BASE, 'conflicting'),
    (['javascript:alert(1)'], BASE, 'invalid')])
def test_canonical_observation_not_google_selection(values, url, state):
    assert canonical_info(values, url)['state'] == state


@pytest.mark.parametrize('subtype', ['LocalBusiness', 'Restaurant', 'Dentist', 'MedicalBusiness',
    'HomeAndConstructionBusiness', 'ProfessionalService', 'Store', 'Plumber', 'RoofingContractor', 'HVACBusiness'])
def test_schema_subtypes_from_official_type_closure(subtype):
    assert subtype in LOCAL_TYPES
    f = facts(); f['growth']['schema']['entities'][0]['types'] = [subtype]
    o, _ = page_observation(f, dict(id='one', final_url=BASE))
    assert o['schema']['local_business']


def test_schema_policy_invalid_json_and_no_schema_contact_fallback():
    f = facts()
    entity = f['growth']['schema']['entities'][0]
    entity.update(aggregateRating={'ratingValue': 'GOOGLE_RATING_CANARY'}, review='GOOGLE_REVIEW_CANARY',
                  phone='GOOGLE_PHONE_CANARY', arbitrary='SECRET_CANARY')
    # Schema phone is context only; it must never become a contact or guessed NAP number.
    f['contacts'] = []
    f['growth']['schema']['invalid_json_count'] = 1
    o, rows = page_observation(f, dict(id='one', final_url=BASE))
    assert o['phones'] == []
    encoded = json.dumps(rows)
    for canary in ('GOOGLE_RATING_CANARY', 'GOOGLE_REVIEW_CANARY', 'SECRET_CANARY'):
        assert canary not in encoded
    assert 'present_but_invalid_json' in encoded
    assert any(r['detector_key'] == 'growth.schema_valid' and r['status'] == 'absent' for r in rows)


def test_partial_absence_unknown_but_independent_head_facts_survive():
    f = facts('local'); f['complete'] = False
    o, rows = page_observation(f, dict(id='partial', final_url=BASE))
    by_key = {r['detector_key']: r for r in rows}
    assert by_key['growth.location_context']['status'] == 'unknown'
    assert by_key['growth.address']['status'] == 'unknown'
    assert by_key['growth.local_schema']['status'] == 'absent'
    assert by_key['growth.title']['status'] == 'present'
    assert o['complete'] is False


def test_robots_meta_noindex_and_nofollow_differ():
    f = facts()
    f['growth']['robots_meta'] = [dict(agent='robots', content='nofollow')]
    _, rows = page_observation(f, dict(id='one', final_url=BASE))
    assert rollup(rows)['indexability']['status'] == 'pass'
    f['growth']['robots_meta'][0]['content'] = 'noindex, nofollow'
    _, rows = page_observation(f, dict(id='one', final_url=BASE))
    assert rollup(rows)['indexability']['status'] == 'gap'


def test_multiple_h1_empty_alt_dimensions_and_faq_not_automatic_gaps():
    f = facts()
    f['growth']['headings'].append(dict(level=1, text='Plumbing repair'))
    f['growth'].update(faq=False, video=False)
    f['growth']['images'].update(empty_alt=2, dimensions_missing=2, lazy=0)
    o, rows = page_observation(f, dict(id='one', final_url=BASE))
    assert o['h1_count'] == 2
    assert rollup(rows)['h1']['status'] == 'pass'
    assert rollup(rows)['image_alt']['status'] == 'pass'
    assert all(r['detector_key'] not in {'growth.faq', 'growth.video', 'growth.dimensions'} for r in rows)


def test_duplicates_only_distinct_audited_urls_and_not_sitewide():
    g, rows = collected()
    assert rollup(rows)['duplicate_title']['status'] == 'pass'
    o = g['observations'][0]
    other = deepcopy(o); other['url'] = BASE + 'distinct'
    extra, _ = cross_page_checks([o, other], [dict(id='x', final_url=BASE)])
    assert rollup(extra)['duplicate_title']['status'] == 'gap'
    extra, _ = cross_page_checks([o, deepcopy(o)], [dict(id='x', final_url=BASE)])
    assert rollup(extra)['duplicate_title']['status'] == 'unknown'


def test_services_not_sampled_are_unknown_and_expansion_requires_observed_areas():
    g, _ = collected()
    # The fixture's service page was sampled, so it isn't a missing-page finding.
    assert not any(a.get('url') == BASE + 'services/repair' for a in g['page_analysis'])
    o = g['observations'][0]
    rows, analysis = cross_page_checks([o], [dict(id='one', final_url=BASE)])
    missing = next(a for a in analysis if a['kind'] == 'possible_missing_service_page')
    assert missing['status'] == 'unknown'
    assert missing['label'] == 'Dedicated page not found in audited sample'
    assert not any(a['kind'] == 'location_expansion_review' for a in analysis)
    o['explicit_areas'] = ['Austin', 'Round Rock']
    _, analysis = cross_page_checks([o], [dict(id='one', final_url=BASE)])
    assert any('genuinely serves' in a['label'] for a in analysis)


def test_nap_requires_same_address_and_single_phone_and_allows_branch_unknown():
    g, _ = collected(); observations = g['observations'][:2]
    observations[1]['phones'] = ['+15125550888']
    rows, _ = cross_page_checks(observations, [dict(id='one', final_url=BASE)])
    assert rollup(rows)['nap_consistency']['status'] == 'gap'
    observations[1]['addresses'] = ['100 Branch Road Dallas TX']
    rows, _ = cross_page_checks(observations, [dict(id='one', final_url=BASE)])
    assert rollup(rows)['nap_consistency']['status'] == 'unknown'
    observations[0]['addresses'] = []
    observations[1]['addresses'] = []
    rows, _ = cross_page_checks(observations, [dict(id='one', final_url=BASE)])
    assert rollup(rows)['nap_consistency']['status'] == 'unknown'


def test_determinism_unknown_denominator_max_three_and_shared_signal_dedup():
    g, rows = collected('technical')
    copy_rows = deepcopy(rows)
    for row in copy_rows: row['id'] += '-duplicate'
    checks = rollup(rows + copy_rows)
    p = profile('technical_seo_v1', checks)
    assert p['opportunity_score'] == g['profiles']['technical_seo_v1']['opportunity_score']
    assert len(g['recommended_services']['services']) <= 3
    assert len(g['top_sales_opportunities']) <= 3
    assert len({o['label'] for o in g['top_sales_opportunities']}) == len(g['top_sales_opportunities'])
    assert len(g['digital_growth_opportunity']['breakdown']['signals']) == len(set(g['digital_growth_opportunity']['breakdown']['signals']))
    only = {k: v for k, v in checks.items() if k in {'canonical', 'title'}}
    assert profile('technical_seo_v1', only)['opportunity_score'] is None
    old = build_growth([], {})
    assert all(p['status'] == 'not_assessed' for p in old['profiles'].values())
    assert all(p.get('score') is None for p in old['future_modules'].values())


@pytest.mark.parametrize('url,expected', [('contact-us', 'contact'), ('services/repair', 'service'),
    ('locations/austin', 'location'), ('about', 'about'), ('blog/article', 'blog'), ('unclassified', 'other')])
def test_page_classification(url, expected):
    assert page_type(BASE + url, 'Business')[0] == expected


def test_link_selection_caps_and_unsafe_external_query_non_pages():
    settings = EngineConfig(seo_services=2, seo_locations=1)
    links = [dict(href=BASE + 'services/' + str(i), text='Repair') for i in range(20)]
    links += [dict(href=u, text='Service') for u in ['http://127.0.0.1/', 'https://external.test/services', BASE + 'services?a=1', BASE + 'services.pdf']]
    selected = candidate_links(links, BASE, settings)
    assert len(selected) == 2
    assert all(url.startswith(BASE + 'services/') for url, _ in selected)


@pytest.mark.parametrize('text,path,agent,expected', [
    ('User-agent: *\nDisallow: /private', '/public', 'LeadEngine', True),
    ('User-agent: *\nDisallow: /private', '/private/x', 'LeadEngine', False),
    ('User-agent: *\nDisallow: /\nAllow: /public', '/public', 'LeadEngine', True),
    ('User-agent: *\nDisallow: /x\nAllow: /x', '/x', 'LeadEngine', True),
    ('User-agent: Googlebot\nDisallow: /\nUser-agent: *\nAllow: /', '/', 'LeadEngine', True),
    ('User-agent: LeadEngine\nDisallow: /one\nUser-agent: LeadEngine\nDisallow: /two', '/two', 'LeadEngine', False),
    ('User-agent: *\nDisallow: /*.pdf$', '/file.pdf', 'LeadEngine', False),
    ('User-agent: *\nDisallow: /*.pdf$', '/file.pdf?x=1', 'LeadEngine', True),
    ('User-agent: *\nDisallow: /café', '/caf%C3%A9', 'LeadEngine', False),
    ('User-agent: *\nDisallow: /%7Eadmin', '/~admin', 'LeadEngine', False),
    ('User-agent: *\nDisallow: /a%2Fb', '/a/b', 'LeadEngine', True),
])
def test_robots_agent_path_longest_wildcards_encoding(text, path, agent, expected):
    assert Robots(text).allowed(BASE.rstrip('/') + path, agent) is expected


def test_robots_empty_group_and_adversarial_rules_are_safe():
    robots = Robots('User-agent: LeadEngine\nDisallow:\nUser-agent: Other\nDisallow: /')
    assert robots.allowed(BASE)
    assert not robots.allowed(BASE, 'Other')
    assert not Robots('<html>Access challenge</html>').valid
    assert not Robots('User-agent: *\nDisallow: /' + 'x' * 2048).valid
    robots = Robots('User-agent: *\nDisallow: /' + '*a' * 100 + 'b')
    assert robots.allowed(BASE + 'a' * 200)


def test_resource_concurrency_cap_and_stop_after_access_block():
    async def run():
        active = maximum = calls = 0
        async def fetch(url, base, **kwargs):
            nonlocal active, maximum, calls
            calls += 1; active += 1; maximum = max(maximum, active)
            await asyncio.sleep(.01)
            active -= 1
            return dict(status='observed', http_status=200, url=url)
        resources = Resources(BASE, fetch=fetch); resources.robots = Robots('')
        checked = await resources.links([BASE + str(i) for i in range(100)], 5)
        assert len(checked) == calls == 5 and maximum == 2
        async def blocked(url, base, **kwargs):
            nonlocal calls
            calls += 1
            return dict(status='blocked', http_status=429)
        resources = Resources(BASE, fetch=blocked); resources.robots = Robots('')
        calls = 0
        await resources.links([BASE + str(i) for i in range(50)], 50)
        assert calls == 1
    asyncio.run(run())


def test_resource_redirect_revalidates_origin_and_pins_dns():
    class Response:
        content_length = None
        def __init__(self, code, headers): self.status, self.headers = code, headers
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class Session:
        def __init__(self, responses, calls, **kwargs):
            self.responses, self.calls = responses, calls
            assert kwargs['trust_env'] is False and kwargs['auto_decompress'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def request(self, method, url, **kwargs):
            self.calls.append(url)
            assert not kwargs['allow_redirects'] and 'Authorization' not in kwargs['headers']
            return self.responses.pop(0)
    async def run():
        for destination, count in [('http://169.254.169.254/', 1), ('https://external.test/', 1), (BASE + 'final', 2)]:
            calls = []
            responses = [Response(302, {'Location':destination}), Response(200, {})]
            resolve = AsyncMock(return_value=('93.184.216.34',))
            with patch('audit_engine.growth_resources.resolve_public', resolve), \
                 patch('audit_engine.growth_resources.aiohttp.TCPConnector') as connector, \
                 patch('audit_engine.growth_resources.aiohttp.ClientSession', side_effect=lambda **kwargs: Session(responses, calls, **kwargs)):
                result = await probe(BASE, BASE)
            assert len(calls) == resolve.await_count == count
            assert result['status'] == ('observed' if count == 2 else 'unknown')
            pinned = connector.call_args.kwargs['resolver']
            assert pinned.addresses == ('93.184.216.34',)
    asyncio.run(run())


def test_local_schema_presence_not_required_on_every_page_and_invalid_is_unknown():
    one = facts(); two = facts(url=BASE + 'contact')
    two['growth']['schema']['entities'] = []
    rows = []
    for i, f in enumerate((one, two)):
        _, extracted = page_observation(f, dict(id=str(i), final_url=f['url']))
        rows += extracted
    assert rollup(rows)['local_schema']['status'] == 'pass'
    two['growth']['schema']['invalid_json_count'] = 1
    _, extracted = page_observation(two, dict(id='broken', final_url=two['url']))
    assert rollup(extracted)['local_schema']['status'] == 'unknown'
    assert rollup(extracted)['schema_valid']['status'] == 'gap'


def test_clear_topic_survives_missing_h1_and_contact_stopwords():
    from audit_engine.growth import topic_outcome
    assert topic_outcome(dict(title='Hail & Storm Damage Roof Repair', headings=[], kind='service', complete=True)) == 'pass'
    assert topic_outcome(dict(title='Contact Us', headings=[dict(level=1,text='CONTACT US')], kind='contact', complete=True)) == 'pass'
    assert topic_outcome(dict(title='Home', headings=[], kind='homepage', complete=True)) == 'gap'
    assert topic_outcome(dict(title='', headings=[], kind='unknown', complete=False)) == 'unknown'


def test_foreign_schema_identity_is_unknown_not_missing_or_a_contact():
    f = facts()
    f['growth']['schema']['entities'][0].update(url='https://another-business.example/', name='FOREIGN_NAME')
    observation, rows = page_observation(f, dict(id='p', final_url=BASE))
    assert 'FOREIGN_NAME' not in json.dumps(observation)
    assert observation['schema']['excluded_entity_count'] == 1
    assert rollup(rows)['local_schema']['status'] == 'unknown'


def test_overall_report_references_and_canonical_business_identity():
    from growth_scoring import growth_for_detail
    from tests.test_lead_qualification import detail
    from lead_summary import business_name
    d = detail(); d['score']['digital_growth'], _ = collected('technical')
    g = growth_for_detail(d)
    assert g['client_growth_audit']['business_name'] == business_name(d)[0]
    for field in ('confirmed_strengths', 'confirmed_gaps', 'unknown_checks'):
        for ref in g['digital_growth_opportunity'][field]:
            assert any(c['key'] == ref['key'] for c in g['profiles'][ref['profile']][field])
    unavailable = build_growth([], {}, metrics={'performance_configured':True})
    assert unavailable['future_modules']['page_performance_v1']['status'] == 'unavailable'
    assert unavailable['future_modules']['page_performance_v1']['score'] is None


def test_generic_schema_pass_does_not_erase_local_schema_gap_from_overall():
    g, rows = collected()
    rows = [r for r in rows if r['detector_key'] != 'growth.local_schema']
    rows.append(check('local_schema','LocalBusiness schema','gap',dict(id='p',final_url=BASE)))
    result = build_growth(rows, {}, assessed=True, observations=g['observations'])
    overall = result['digital_growth_opportunity']
    assert overall['opportunity_score'] > 0
    assert overall['breakdown']['signals']['schema']['key'] == 'local_schema'
    assert sum(s['key'] in {'schema','local_schema'} for s in overall['breakdown']['signals'].values()) == 1


def test_initial_location_counts_toward_cap_and_resource_timeout_preserves_facts():
    async def run():
        first, second = BASE+'locations/first', BASE+'locations/second'
        f = facts(url=first)
        f['links'] = f['growth']['links'] = [dict(href=second, text='Second office', navigation=True)]
        browser = MockBrowserProvider({first:f, second:facts(url=second)})
        class SlowResources(FixtureResources):
            async def sitemap(self):
                await asyncio.sleep(2)
        settings = EngineConfig(growth_enabled=True, seo_locations=1, pages=1, seo_resource_seconds=.02, settle_ms=0, readiness_ms=500)
        async def validate(url): return url
        session = await browser.open_session()
        try:
            result = await AuditEngine(browser, settings, validate=validate, resources_factory=SlowResources).run({'website_url':first},session)
        finally:
            await browser.close_session(session)
        assert len(result['pages']) == 1
        assert result['pages'][0]['page_type'] == 'homepage'
        assert result['growth_observations'][0]['kind'] == 'location'
        assert result['growth_metrics']['resource_budget_exhausted']
        assert not any(r['detector_key']=='growth.sitemap' and r['status']=='absent' for r in result['evidence'])
        assert result['growth_observations'] and result['status'] == 'completed'
    asyncio.run(run())


def test_isolated_minor_gap_is_not_promoted_as_top_sales_opportunity():
    g, rows = collected()
    for i in range(10):
        rows.append(check('h1', 'Main heading', 'gap' if i == 0 else 'pass', dict(id=str(i),final_url=BASE+str(i))))
    result = build_growth(rows, {}, assessed=True, observations=g['observations'])
    assert result['profiles']['technical_seo_v1']['confirmed_gaps']
    assert result['recommended_services']['services'] == []


def test_http_upgrade_establishes_origin_before_same_origin_robots():
    async def run():
        calls = []
        async def fetch(url, base, **kwargs):
            calls.append((url, base, kwargs))
            if kwargs.get('upgrade'):
                return dict(status='observed',http_status=200,url='https://growth-business.test/',redirects=1)
            return dict(status='observed',http_status=200,body='User-agent: *\nAllow: /')
        resources = Resources('http://growth-business.test/',fetch=fetch)
        await resources.initialize()
        assert resources.base == 'https://growth-business.test/'
        assert calls[-1][0] == 'https://growth-business.test/robots.txt'
        assert resources.allowed(resources.base)
    asyncio.run(run())


def test_cancelled_resource_batch_closes_all_outstanding_probes():
    async def run():
        active = 0
        async def fetch(*args, **kwargs):
            nonlocal active
            active += 1
            try:
                await asyncio.sleep(2)
            finally:
                active -= 1
        resources = Resources(BASE, fetch=fetch); resources.robots = Robots('')
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(resources.links([BASE+str(i) for i in range(50)],50),.02)
        assert active == 0
    asyncio.run(run())


def test_sitemap_bounded_xml_external_and_entities():
    parsed = sitemap_document('<urlset><url><loc>' + BASE + '</loc></url><url><loc>https://external.test/</loc></url></urlset>', BASE)
    assert parsed['urls'] == [BASE] and parsed['external_rejected'] == 1
    assert sitemap_document('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///secret">]><urlset>&e;</urlset>', BASE)['status'] == 'unknown'
    assert sitemap_document('<invalid>', BASE)['status'] == 'unknown'
    huge = '<urlset>' + ''.join('<url><loc>' + BASE + str(i) + '</loc></url>' for i in range(501)) + '</urlset>'
    parsed = sitemap_document(huge, BASE)
    assert parsed['limited'] and len(parsed['urls']) == 500


def test_ssrf_resource_probe_rejects_before_network():
    async def run():
        with patch('audit_engine.growth_resources.aiohttp.ClientSession') as session:
            for url in ('http://127.0.0.1/', 'http://169.254.169.254/', 'https://external.test/', BASE + '@bad'):
                if url.startswith(BASE):
                    with patch('audit_engine.growth_resources.resolve_public', AsyncMock(side_effect=UnsafeURL('Private DNS'))):
                        assert (await probe(url, BASE))['status'] == 'unknown'
                else:
                    assert (await probe(url, BASE))['status'] == 'unknown'
            session.assert_not_called()
    from url_safety import UnsafeURL
    asyncio.run(run())


def test_shared_runner_one_session_page_cap_no_duplicate_crawl_and_conversion_unchanged():
    async def run():
        urls = [BASE, BASE + 'contact', BASE + 'services/repair', BASE + 'locations/austin']
        browser = MockBrowserProvider({u: facts(url=u) for u in urls})
        settings = EngineConfig(growth_enabled=True, seo_pages=4, pages=2, settle_ms=0, readiness_ms=500)
        async def validate(url): return url
        runner = AuditEngine(browser, settings, validate=validate, resources_factory=FixtureResources)
        session = await browser.open_session()
        try:
            result = await runner.run({'website_url': BASE}, session)
        finally:
            await browser.close_session(session)
        assert len(result['pages']) == 4
        assert len({p['url'] for p in result['pages']}) == 4
        assert result['growth_metrics']['browser_sessions'] == 1
        assert result['growth_metrics']['page_cleanup_errors'] == 0
        assert result['growth_observations']
        legacy_browser = MockBrowserProvider({u: facts(url=u) for u in urls})
        old_session = await legacy_browser.open_session()
        try:
            legacy = await AuditEngine(legacy_browser, EngineConfig(growth_enabled=False, pages=2, settle_ms=0, readiness_ms=500), validate=validate).run({'website_url': BASE}, old_session)
        finally:
            await legacy_browser.close_session(old_session)
        first, second = score_browser_evidence(result['conversion_view']), score_browser_evidence(legacy)
        for value in (first, second):
            for finding in value['breakdown']['findings'].values(): finding.pop('evidence_ids', None)
        assert first == second
    asyncio.run(run())


def test_robots_denied_prevents_browser_navigation_and_false_scores():
    async def run():
        browser = MockBrowserProvider({BASE: facts()})
        async def validate(url): return url
        runner = AuditEngine(browser, EngineConfig(growth_enabled=True), validate=validate,
            resources_factory=lambda base: FixtureResources(base, denied=True))
        session = await browser.open_session()
        result = await runner.run({'website_url': BASE}, session)
        await browser.close_session(session)
        assert result['status'] == 'blocked'
        assert result['pages'] == result['evidence'] == result['contacts'] == []
    asyncio.run(run())


def test_csv_filters_search_projection_preserve_unknown_and_formula_safety():
    from tests.test_lead_qualification import detail
    from lead_summary import qualify, lead_row, filter_sort, summary_csv
    d = detail()
    g, _ = collected('technical')
    d['score']['digital_growth'] = g
    d['summary'] = qualify(d)
    row = lead_row(d)
    assert filter_sort([row], min_technical=1)
    assert not filter_sort([row], min_local=99)
    assert filter_sort([row], recommended_service=g['recommended_services']['services'][0])
    exported = list(csv.DictReader(io.StringIO(summary_csv([row]))))[0]
    assert set(GROWTH_CSV_FIELDS) <= set(exported)
    assert exported['technical_seo_opportunity'] != ''
    assert 'observations' not in exported
