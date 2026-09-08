"""Read-only Digital Growth browser/API checks against one existing LIVE search.

Never creates a search or browses a business. Uses the existing private local
credentials and public CA; local-only artifacts are ignored by Git.
"""
import argparse
import csv
import io
import json
import ssl

import httpx
from playwright.sync_api import sync_playwright, expect

from validate_qualification_ui import LOCAL, ORIGIN


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    args = parser.parse_args()
    private = dict(line.split('=', 1) for line in (LOCAL / 'stack.env').read_text().splitlines() if '=' in line)
    params = {'job_id':args.job_id}
    with httpx.Client(base_url=ORIGIN, trust_env=False, timeout=20, headers={'Origin':ORIGIN},
                      verify=ssl.create_default_context(cafile=str(LOCAL / 'leadpro-live-root.crt'))) as client:
        assert client.get('/api/auth/mode').json()['run_mode'] == 'live'
        login = client.post('/api/auth/login', json={'username':'admin','password':private['INITIAL_ADMIN_PASSWORD']})
        assert login.status_code == 200, 'Login failed; credentials withheld'
        client.headers['X-CSRF-Token'] = login.json()['csrf_token']
        data = client.get('/api/leads', params=params).json()
        assert 1 <= data['total'] <= 5 and data['job']['id'] == args.job_id
        details, report = [], []
        for row in data['leads']:
            detail = client.get('/api/businesses/' + row['id'], params=params).json()
            details.append(detail); g = detail['digital_growth']
            assert g['assessed'] and len(g['recommended_services']['services']) <= 3
            assert len(g['top_sales_opportunities']) <= 3
            assert g['client_growth_audit']['business_name'] == detail['summary']['business_name']
            assert 'fixture-business.test' not in json.dumps(detail) and 'Independently observed business' not in json.dumps(detail)
            ids = {e['id'] for e in detail['evidence']} | {e.get('observation_id') for e in detail['evidence']}
            for module in g['profiles'].values():
                assert all(c['status'] == 'gap' and set(c['evidence_ids']) <= ids for c in module['confirmed_gaps'])
                assert all(c['status'] == 'unknown' for c in module['unknown_checks'])
                if not module['sufficient']:
                    assert module['opportunity_score'] is None and not module['recommendations']
            for key in ('serp_rank_tracking_v1','off_page_seo_v1','social_media_audit_v1'):
                assert g['future_modules'][key]['status'] == 'not_configured'
                assert g['future_modules'][key]['score'] is None
            report.append(dict(name=detail['summary']['business_name'], status=detail['audit']['status'],
                scores={k:v['opportunity_score'] for k,v in g['profiles'].items()},
                services=g['recommended_services']['services'], metrics=g['metrics']))
        cases = [{'sort':s} for s in ('top_opportunity','technical','on_page','local','growth_evidence','contact','business')]
        cases += [{'min_technical':0}, {'min_on_page':0}, {'min_local':1}, {'min_growth_evidence':50}]
        services = sorted({s for d in details for s in d['digital_growth']['recommended_services']['services']})
        cases += [{'recommended_service':s} for s in services]
        top_labels = sorted({o['label'] for d in details for o in d['digital_growth']['top_sales_opportunities']})
        cases += [{'top_opportunity':s} for s in top_labels]
        for filters in cases:
            selected = client.get('/api/leads', params=dict(params, **filters)).json()
            exported = list(csv.DictReader(io.StringIO(client.get('/api/leads/export/csv', params=dict(params, **filters)).text)))
            assert [r['business_name'] for r in exported] == [r['business_name'] for r in selected['leads']]
            for row in exported:
                assert 'technical_seo_opportunity' in row and 'recommended_service_3' in row
                assert not {'evidence','observations','raw_response'} & row.keys()
        client.post('/api/auth/logout')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(ORIGIN + '/')
                      and '/api/leadgen/start' not in route.request.url else route.abort())
        page = context.new_page(); errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(ORIGIN)
        page.locator('#username').fill('admin'); page.locator('#password').fill(private['INITIAL_ADMIN_PASSWORD'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.locator('#layout')).to_be_visible()
        page.reload(); expect(page.locator('#layout')).to_be_visible()
        assert page.evaluate('localStorage.length + sessionStorage.length') == 0
        page.get_by_role('button', name='Leads', exact=True).click()
        page.locator('#search-selector').select_option(args.job_id)
        expect(page.locator('#lead-rows tr')).to_have_count(data['total'])
        expect(page.locator('#export-leads')).to_be_enabled()
        page.screenshot(path=str(LOCAL / 'growth-live-desktop.png'), full_page=True)
        page.locator('#lead-filters details summary').click()
        if services:
            page.locator('#filter-service').select_option(services[0])
            page.get_by_role('button',name='Apply filters',exact=True).click()
            expected = sum(services[0] in d['digital_growth']['recommended_services']['services'] for d in details)
            expect(page.locator('#lead-rows tr')).to_have_count(expected)
            with page.expect_download() as download:
                page.get_by_role('button',name='Export this view (CSV)').click()
            from pathlib import Path
            exported = list(csv.DictReader(io.StringIO(Path(download.value.path()).read_text())))
            assert len(exported) == expected and all(services[0] in [r[f'recommended_service_{i}'] for i in (1,2,3)] for r in exported)
        page.get_by_role('button',name='Clear filters',exact=True).click()
        expect(page.locator('#lead-rows tr')).to_have_count(data['total'])
        for index in range(data['total']):
            trigger = page.locator('#lead-rows tr').nth(index).get_by_role('button',name='View evidence')
            trigger.click(); expect(page.locator('#business-detail')).to_be_visible()
            technical = page.locator('#detail-content > details')
            assert not technical.evaluate('node => node.open')
            expect(page.get_by_role('heading',name='Top Sales Opportunities',exact=True)).to_be_visible()
            for label in ('Technical SEO','On-Page SEO','Local SEO'):
                node = page.locator('#detail-content > section').filter(has=page.get_by_role('heading',name=label,exact=True))
                node.locator('details summary').first.click()
                expect(node).to_contain_text('Unknown checks do not imply missing features')
            expect(page.locator('#detail-content')).to_contain_text('Rank tracking not configured')
            technical.locator('summary').first.click()
            assert page.locator('.evidence-card').count() > 0 or 'Unverified business' in page.locator('#detail-title').text_content()
            page.keyboard.press('Escape'); expect(trigger).to_be_focused()
        for width,height,theme in [(1440,1000,'dark'),(820,1180,'dark'),(375,812,'dark'),(375,812,'light'),(812,375,'light')]:
            page.set_viewport_size({'width':width,'height':height})
            page.evaluate('(light) => document.body.classList.toggle("theme-light",light)',theme=='light')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#lead-rows tr').first.get_by_role('button',name='View evidence').click()
            expect(page.locator('#business-detail')).to_be_visible()
            assert page.locator('#business-detail').evaluate('node => node.scrollWidth <= node.clientWidth')
            page.screenshot(path=str(LOCAL / f'growth-detail-{width}-{height}-{theme}.png'),full_page=True)
            for link in page.locator('#business-detail a').all():
                assert link.get_attribute('href').startswith(('http://','https://'))
                assert link.get_attribute('rel') == 'noopener noreferrer'
            page.keyboard.press('Escape')
        page.get_by_role('button',name='Sign out',exact=True).click()
        expect(page.locator('#login-panel')).to_be_visible()
        assert not errors, 'Frontend JavaScript error'
        context.close(); browser.close()
    (LOCAL / 'growth-live-ui-validation.json').write_text(json.dumps(dict(leads=report, api_csv_cases=len(cases),
        browser='Desktop/tablet/mobile, dark/light, cookie reload, filters/CSV, source links, keyboard, disclosures: PASS',
        new_searches=0),indent=2),encoding='utf-8')
    print(f'PASS: {len(details)} saved LIVE growth leads, {len(cases)} API/CSV views, responsive browser checks; zero new searches.')


if __name__ == '__main__':
    main()
