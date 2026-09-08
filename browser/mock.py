"""Deterministic offline provider. It never performs network operations."""
import copy
from .base import BrowserProvider, BrowserSession, BrowserPage, BrowserHealth, BrowserError
from engine_utils import uid


class MockBrowserProvider(BrowserProvider):
    name = "mock"
    version = "fixture-v1"

    def __init__(self, pages=None, available=True):
        self.fixtures = pages or {}
        self.available = available
        self.sessions = {}
        self.closed_sessions = []
        self.visited = []
        self.active_pages = 0
        self.max_active_pages = 0

    async def health(self):
        return BrowserHealth(self.name, True, self.available, "available" if self.available else "browser_unavailable", self.version)

    async def open_session(self):
        session = BrowserSession(uid(), uid())
        self.sessions[session.user_id] = session
        return session

    async def open_page(self, session, url):
        if not self.available:
            raise BrowserError("browser_unavailable")
        self.visited.append(url)
        fixture = self.fixtures.get(url)
        if fixture is None:
            raise BrowserError("browser_navigation_failed")
        if isinstance(fixture, BrowserError):
            raise fixture
        page = BrowserPage(uid(), session, fixture.get("url", url))
        page.fixture_url = url
        session.pages.add(page.id)
        self.active_pages += 1
        self.max_active_pages = max(self.active_pages, self.max_active_pages)
        return page

    async def navigate(self, page, url):
        if url not in self.fixtures:
            raise BrowserError("browser_navigation_failed")
        page.fixture_url = url
        page.url = self.fixtures[url].get("url", url)
        return page.url

    async def evaluate(self, page, expression):
        facts = self.fixtures[page.fixture_url]
        if expression == "location.href":
            return page.url
        if "scroll_width: document.documentElement.scrollWidth" in expression:
            return {"url": page.url, "width": 390, "scroll_width": facts.get("mobile_scroll_width", 390)}
        return copy.deepcopy(facts)

    async def get_links(self, page):
        return copy.deepcopy(self.fixtures[page.fixture_url].get("links", []))

    async def get_snapshot(self, page):
        return {"url": page.url, "snapshot": "Offline fixture", "truncated": False}

    async def screenshot(self, page):
        import base64
        return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a6VQAAAAASUVORK5CYII=")

    async def set_viewport(self, page, width, height):
        return True

    async def close_page(self, page):
        if page.id in page.session.pages:
            page.session.pages.remove(page.id)
            self.active_pages -= 1

    async def close_session(self, session):
        self.active_pages -= len(session.pages)
        session.pages.clear()
        self.sessions.pop(session.user_id, None)
        self.closed_sessions.append(session.user_id)

    async def shutdown(self):
        for session in list(self.sessions.values()):
            await self.close_session(session)
