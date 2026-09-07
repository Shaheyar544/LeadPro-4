"""Explicit offline UI harness. Never imported by production app startup."""
import asyncio
from unittest.mock import AsyncMock
from app import app
import app as application
from browser.mock import MockBrowserProvider
from browser.base import BrowserError
from audit_engine.runner import AuditEngine
from engine_worker import PersistentWorker
from discovery import DiscoveryPage
from tests.engine_fixtures import business, facts

PAYLOAD = '=SUM(1,2) <img src=x onerror="window.__xss=1"> Fixture Business'
home = facts(links=[{"href": "/contact", "text": "Contact"}, {"href": "/about", "text": "About"}])
contact = facts("https://business.test/contact", contacts=[
    {"type": "email", "value": "mailto:office@public-business.test", "kind": "mailto", "excerpt": PAYLOAD},
    {"type": "phone", "value": "+1 (512) 555-1234", "kind": "tel", "excerpt": "Call our office"}])


class SlowMock(MockBrowserProvider):
    async def open_page(self, session, url):
        await asyncio.sleep(0.5)
        return await super().open_page(session, url)


class Source:
    name = "fixture"
    async def fetch_page(self, job, cursor=None, limit=20, cancelled=lambda: False):
        offline = job["category"] == "Offline"
        return DiscoveryPage([business(1, canonical_name=PAYLOAD, website_url="https://offline.test/" if offline else "https://business.test/"),
                              business(2, canonical_name="Blocked business", website_url="https://blocked.test/")], terminal_reason="discovery_exhausted")


browser = SlowMock({home["url"]: home, contact["url"]: contact,
                   "https://business.test/about": facts("https://business.test/about"),
                   "https://blocked.test/": facts("https://blocked.test/", blocked=True),
                   "https://offline.test/": BrowserError("browser_unavailable")})
application.evidence_worker = PersistentWorker(application.engine_store, application.engine_settings,
    browser, [Source()], AuditEngine(browser, application.engine_settings, validate=AsyncMock(side_effect=lambda url: url)))
