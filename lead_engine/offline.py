"""Explicit local-only provider fixture; no network calls or request overrides."""
import asyncio
from urllib.parse import urldefrag
from discovery import ProviderDiscovery
from browser.mock import MockBrowserProvider
from browser.base import BrowserError

URL = 'https://fixture-business.test/'
SENTINELS = ['GOOGLE_SENTINEL_NAME', 'GOOGLE_SENTINEL_ADDRESS', 'GOOGLE_SENTINEL_PHONE',
             'GOOGLE_SENTINEL_WEBSITE', '4.918237', '9182736', 'GOOGLE_SENTINEL_TYPE', 'GOOGLE_SENTINEL_STATUS']

class OfflineGoogle(ProviderDiscovery):
    def __init__(self):
        super().__init__('google_places_new', 'OFFLINE_KEY_NOT_SENT')

    async def fetch_page(self, *args, **kwargs):
        page = await super().fetch_page(*args, **kwargs)
        for row in page.records:
            row['provider'] = 'fixture'
            row['provider_record_id'] = row['provider_record_id'].replace('google_places_new:', 'fixture:', 1)
        return page

    async def _json(self, http, method, url, **kwargs):
        return {'places': [dict(id='phase4a2-place-' + str(i),
            displayName={'text': SENTINELS[0]}, formattedAddress=SENTINELS[1],
            websiteUri=URL + '#' + SENTINELS[3], nationalPhoneNumber=SENTINELS[2],
            rating=4.918237, userRatingCount=9182736, primaryType=SENTINELS[6],
            businessStatus=SENTINELS[7]) for i in range(1, 6)]}

def browser_fixture():
    facts = dict(url=URL, title='Independently observed business', ready_state='complete', complete=True,
                 viewport='width=device-width,initial-scale=1', links=[], forms=[], ctas=[], resources=[],
                 generator='', tracking={}, blocked=False, contacts=[
                     dict(type='phone', kind='tel', value='+1 512 555 0199', excerpt='Call our office'),
                     dict(type='email', kind='mailto', value='info@fixture-business.test', excerpt='Business enquiries')])
    facts['growth'] = dict(version='digital_growth_crawl_v1', title=facts['title'],
        descriptions=['Independent offline test business with public contact information.'], canonicals=[URL], robots_meta=[],
        viewport=facts['viewport'], headings=[dict(level=1, text=facts['title'])], headings_complete=True,
        schema=dict(entities=[dict(types=['LocalBusiness'], name=facts['title'], url=URL,
            address=dict(streetAddress='12 Offline Test Street', addressLocality='Austin', addressRegion='TX'), areas=['Austin'])],
            microdata_types=[], invalid_json_count=0, script_count=1, complete=True),
        images=dict(count=0, missing_alt=0, empty_alt=0, dimensions_missing=0, lazy=0), mixed_content=0,
        visible_words=80, paragraphs=2, section_count=1, faq=False, video=False, addresses=['12 Offline Test Street Austin TX'],
        links=[], links_complete=True, body_complete=True, service_area_context=True, supporting_detail=True, h1_body_overlap=True, testimonials=False)
    return MockBrowserProvider({URL: facts})


def fixture_resources(base):
    from audit_engine.growth_resources import Resources
    async def fetch(url, origin, **kwargs):
        # Injection exists only in the explicit offline worker branch. No socket
        # is opened, and no provider payload is used to manufacture SEO evidence.
        from urllib.parse import urlsplit
        if urlsplit(url).hostname != 'fixture-business.test':
            return dict(status='unknown', reason='offline_resource_rejected')
        result = dict(status='observed', http_status=200, url=url.replace('http:', 'https:'), redirects=int(url.startswith('http:')))
        if url.endswith('/robots.txt'):
            result['body'] = 'User-agent: *\nAllow: /\nSitemap: ' + URL + 'sitemap.xml'
        elif url.endswith('/sitemap.xml'):
            result['body'] = '<urlset><url><loc>' + URL + '</loc></url></urlset>'
        return result
    return Resources(base, fetch=fetch)

async def validate_fixture(url):
    if urldefrag(url)[0] != URL:
        raise BrowserError('unsafe_navigation')
    return URL
