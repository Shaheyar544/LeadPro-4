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
    return MockBrowserProvider({URL: facts})

async def validate_fixture(url):
    if urldefrag(url)[0] != URL:
        raise BrowserError('unsafe_navigation')
    return URL
