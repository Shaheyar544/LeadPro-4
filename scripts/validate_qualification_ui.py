"""Opt-in, read-only UI validation of existing LIVE data; never submits a search.

Run with the local production stack ready. Uses the existing private local
credentials and public CA, and writes artifacts only to .local-integration.
"""
import csv
import argparse
import io
import json
from pathlib import Path
import ssl

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local-integration'
ORIGIN = 'https://localhost:8443'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True, help='Existing five-business Dallas validation search; never created by this tool')
    args = parser.parse_args()
    private = dict(line.split('=', 1) for line in (LOCAL / 'stack.env').read_text().splitlines() if '=' in line)
    with httpx.Client(base_url=ORIGIN, verify=ssl.create_default_context(cafile=str(LOCAL / 'leadpro-live-root.crt')),
                      trust_env=False, headers={'Origin': ORIGIN}, timeout=20) as client:
        assert client.get('/api/auth/mode').json()['run_mode'] == 'live'
        response = client.post('/api/auth/login', json={'username':'admin', 'password':private['INITIAL_ADMIN_PASSWORD']})
        assert response.status_code == 200, 'Local login failed; credentials withheld'
        client.headers['X-CSRF-Token'] = response.json()['csrf_token']
        latest = client.get('/api/leads').json()
        data = client.get('/api/leads', params={'job_id':args.job_id}).json()
        assert data['total'] == 5, 'Expected the existing five-business search'
        jobs = client.get('/api/leadgen/jobs').json()
        assert latest['job']['id'] == jobs[0]['id']
        assert data['job']['id'] == args.job_id
        statuses, report = [], []
        for lead in data['leads']:
            d = client.get('/api/businesses/' + lead['id'], params={'job_id':data['job']['id']}).json()
            s = d['summary']; statuses.append(s['audit_summary']['status'])
            assert 'fixture-business.test' not in json.dumps(d) and 'Independently observed business' not in json.dumps(d)
            raw_ids = {str(r['id']) for r in d['evidence'] + d['contacts']}
            phones = [c for c in [s['primary_phone'], *s['other_phones']] if c]
            assert len({c['value'] for c in phones}) == len(phones)
            for c in [*phones, *([s['primary_email']] if s['primary_email'] else []), *s['other_emails'], *s['socials']]:
                assert set(c['evidence_ids']) <= raw_ids
            assert all(f['status'] == 'present' for f in s['confirmed_strengths'])
            assert all(f['status'] == 'absent' for f in s['confirmed_gaps'])
            assert not {f['key'] for f in s['confirmed_gaps']} & {f['key'] for f in s['unknown_checks']}
            assert s['score_summary']['opportunity_score'] == d['score']['opportunity_score']
            report.append(dict(name=s['business_name'], audit=s['audit_summary']['label'], opportunity=s['primary_opportunity'],
                score_display=s['score_summary']['opportunity_display'], evidence_confidence=s['score_summary']['evidence_confidence'],
                phone_count=len(phones), raw_contact_count=len(d['contacts']), raw_evidence_count=len(d['evidence'])))
        assert statuses.count('completed') == 2 and statuses.count('partial') == 3
        assert sum(r['opportunity'] == 'Insufficient Evidence' for r in report) == 1
        assert max(r['phone_count'] for r in report) > 1
        exported = list(csv.DictReader(io.StringIO(client.get('/api/leads/export/csv', params={'job_id':args.job_id}).text)))
        assert len(exported) == 5 and 'evidence' not in exported[0]
        filtered = client.get('/api/leads', params={'job_id':args.job_id,'audit_status':'completed', 'sort':'opportunity'}).json()
        assert filtered['total'] == 2
        filtered_csv = list(csv.DictReader(io.StringIO(client.get('/api/leads/export/csv', params={'job_id':args.job_id,'audit_status':'completed','sort':'opportunity'}).text)))
        assert [r['business_name'] for r in filtered_csv] == [r['business_name'] for r in filtered['leads']]
        client.post('/api/auth/logout')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        context = browser.new_context(ignore_https_errors=True, viewport={'width':1440,'height':1000}, reduced_motion='reduce')
        # Browser UI requests cannot navigate to business sites or start discovery.
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(ORIGIN + '/')
                      and '/api/leadgen/start' not in route.request.url else route.abort())
        page = context.new_page(); errors = []; requests = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.method,request.url)))
        page.goto(ORIGIN)
        page.locator('#username').fill('admin'); page.locator('#password').fill(private['INITIAL_ADMIN_PASSWORD'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        expect(page.locator('#layout')).to_be_visible()
        page.reload(); expect(page.locator('#layout')).to_be_visible()
        assert page.evaluate('localStorage.length + sessionStorage.length') == 0
        expect(page.locator('#run-mode-banner')).to_be_hidden()
        page.get_by_role('button', name='Leads', exact=True).click()
        expect(page.locator('#lead-rows tr')).to_have_count(latest['total'])
        page.locator('#search-selector').select_option(args.job_id)
        expect(page.locator('#lead-rows tr')).to_have_count(5)
        expect(page.locator('#current-search')).to_contain_text('Dallas, TX')
        page.screenshot(path=str(LOCAL / 'qualification-live-desktop.png'), full_page=True)
        page.locator('#filter-audit').select_option('completed')
        page.get_by_role('button', name='Apply filters', exact=True).click()
        expect(page.locator('#lead-rows tr')).to_have_count(2)
        with page.expect_download() as download:
            page.get_by_role('button', name='Export this view (CSV)').click()
        assert len(list(csv.DictReader(io.StringIO(Path(download.value.path()).read_text())))) == 2
        page.get_by_role('button', name='Clear filters', exact=True).click()
        expect(page.locator('#lead-rows tr')).to_have_count(5)
        for index in range(5):
            trigger = page.locator('#lead-rows tr').nth(index).get_by_role('button', name='View evidence')
            trigger.click(); expect(page.locator('#business-detail')).to_be_visible()
            technical = page.locator('#detail-content > details')
            assert not technical.evaluate('node => node.open')
            assert 'fixture-business.test' not in page.locator('#detail-content').text_content()
            assert page.locator('#detail-content > section > h3').all_text_contents() == [
                'Digital Growth overview','Audit summary','Primary opportunity','Public contact','Confirmed strengths','Confirmed gaps','Could not confirm','Pages inspected','Why this score',
                'Technical SEO','On-Page SEO','Local SEO','Additional assessments']
            technical.locator('summary').first.click()
            assert page.locator('.evidence-card').count() > 0
            technical.locator('summary').first.click()
            page.keyboard.press('Escape')
            expect(trigger).to_be_focused()
        for width, height, theme in [(1440,1000,'dark'),(820,1180,'dark'),(375,812,'dark'),(375,812,'light'),(812,375,'light')]:
            page.set_viewport_size({'width':width,'height':height})
            page.evaluate('(light) => document.body.classList.toggle("theme-light", light)', theme == 'light')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#lead-rows tr').filter(has_text='PRIORITY ROOFING').get_by_role('button', name='View evidence').click()
            expect(page.locator('#business-detail')).to_be_visible()
            assert page.locator('#business-detail').evaluate('node => node.scrollWidth <= node.clientWidth')
            page.screenshot(path=str(LOCAL / f'qualification-detail-{width}-{height}-{theme}.png'), full_page=True)
            for link in page.locator('#business-detail a').all():
                assert link.get_attribute('href').startswith(('http://','https://'))
                assert link.get_attribute('target') == '_blank' and link.get_attribute('rel') == 'noopener noreferrer'
            page.keyboard.press('Escape')
        page.get_by_role('button', name='Sign out', exact=True).click()
        expect(page.locator('#login-panel')).to_be_visible()
        assert not errors, 'Frontend JavaScript error'
        assert not any('/api/leadgen/start' in url for _,url in requests)
        context.close(); browser.close()
    result = dict(existing_businesses=report, new_live_businesses=0, completed=2, partial=3,
                  checks='Current search, summary/provenance, score integrity, filters, matching CSV, cookie reload, no fixture rows, safe links, collapsed technical evidence, keyboard/focus, desktop/tablet/mobile, both themes: PASS')
    (LOCAL / 'qualification-live-validation.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
