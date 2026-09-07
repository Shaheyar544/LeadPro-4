import asyncio
import os
import unittest
from unittest.mock import patch, AsyncMock
from aiohttp import web
from browser.camofox import CamoFoxProvider, service_url
from browser.base import BrowserError

PNG = b"\x89PNG\r\n\x1a\nfixture"


class CamoFoxContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.failure = None
        self.redirect = None
        self.malformed = False
        async def handle(request):
            body = await request.json() if request.can_read_body else None
            self.calls.append((request.method, request.path, dict(request.query), request.headers.get("Authorization"), body))
            if self.failure:
                return web.json_response({"error": "SECRET do not expose"}, status=self.failure)
            if self.malformed:
                return web.Response(text="not-json SECRET")
            if request.path == "/health":
                return web.json_response({"ok": True, "browserRunning": False})
            if request.path == "/tabs":
                return web.json_response({"tabId": "fixture-tab", "url": self.redirect or body["url"]})
            if request.path.endswith("/links"):
                return web.json_response({"links": [{"url": "https://business.test/contact", "text": "Contact"}], "pagination": {"hasMore": False}})
            if request.path.endswith("/evaluate"):
                return web.json_response({"ok": True, "result": "https://business.test/"})
            if request.path.endswith("/snapshot"):
                return web.json_response({"url": "https://business.test/", "snapshot": "Public business"})
            if request.path.endswith("/screenshot"):
                return web.Response(body=PNG, content_type="image/png")
            return web.json_response({"ok": True})
        server = web.Application()
        server.router.add_route("*", "/{path:.*}", handle)
        self.runner = web.AppRunner(server)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]
        self.provider = CamoFoxProvider(f"http://127.0.0.1:{self.port}", "fixture-secret", settle_ms=0)
        self.dns = patch("browser.camofox.resolve_public", AsyncMock(return_value=("93.184.216.34",)))
        self.dns.start()

    async def asyncTearDown(self):
        await self.provider.shutdown()
        await self.runner.cleanup()
        self.dns.stop()

    async def test_complete_actual_rest_contract_and_auth(self):
        self.assertTrue((await self.provider.health()).available)
        session = await self.provider.open_session()
        second = await self.provider.open_session()
        self.assertNotEqual(session.user_id, second.user_id)
        self.assertNotEqual(session.session_key, second.session_key)
        page = await self.provider.open_page(session, "https://business.test/")
        self.assertEqual((await self.provider.get_links(page))[0]["href"], "https://business.test/contact")
        self.assertEqual(await self.provider.evaluate(page, "location.href"), "https://business.test/")
        self.assertEqual((await self.provider.get_snapshot(page))["snapshot"], "Public business")
        self.assertEqual(await self.provider.screenshot(page), PNG)
        self.assertTrue(await self.provider.set_viewport(page, 390, 844))
        await self.provider.navigate(page, "https://business.test/contact")
        await self.provider.close_page(page)
        await self.provider.close_session(session)
        self.assertFalse(session.pages)
        self.assertTrue(all(call[3] == "Bearer fixture-secret" for call in self.calls))
        self.assertFalse(any("cookies" in call[1] for call in self.calls))
        self.assertFalse(any("macro" in (call[4] or {}) for call in self.calls))

    async def test_unsafe_candidate_never_sent_and_redirect_tears_down(self):
        session = await self.provider.open_session()
        with self.assertRaises(BrowserError) as caught:
            await self.provider.open_page(session, "http://127.0.0.1/")
        self.assertEqual(caught.exception.code, "unsafe_navigation")
        self.assertEqual(self.calls, [])
        self.redirect = "http://169.254.169.254/"
        with self.assertRaises(BrowserError):
            await self.provider.open_page(session, "https://business.test/")
        self.assertEqual(self.calls[-1][0], "DELETE")
        self.assertIn("/sessions/", self.calls[-1][1])

    async def test_denial_restart_block_and_protocol_are_normalized(self):
        session = await self.provider.open_session()
        for status, code in [(401, "browser_unavailable"), (403, "browser_unavailable"), (404, "browser_session_lost"), (429, "browser_blocked"), (503, "browser_session_lost"), (504, "browser_timeout")]:
            self.failure = status
            before = len(self.calls)
            with self.assertRaises(BrowserError) as caught:
                await self.provider.open_page(session, "https://business.test/")
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual(len(self.calls) - before, 1)
        self.failure = None; self.malformed = True
        with self.assertRaises(BrowserError) as caught:
            await self.provider.open_page(session, "https://business.test/")
        self.assertEqual(caught.exception.code, "browser_protocol_error")

    async def test_transport_timeout_bounded_and_service_down_health(self):
        session = await self.provider.open_session()
        await self.provider.health()  # initialize HTTP client
        with patch.object(self.provider._http, "request", side_effect=asyncio.TimeoutError):
            with self.assertRaises(BrowserError) as caught:
                await self.provider.open_page(session, "https://business.test/")
            self.assertEqual(caught.exception.code, "browser_timeout")
            health = await self.provider.health()
            self.assertFalse(health.available)
            self.assertEqual(health.status, "browser_timeout")

    def test_admin_only_service_configuration(self):
        self.assertEqual(service_url("http://127.0.0.1:9377", ""), "http://127.0.0.1:9377")
        for url, key in [("http://10.0.0.4:9377", ""), ("http://u:p@localhost:9377", "x"), ("file:///tmp", "x"), ("http://localhost:9377/?key=x", "x")]:
            with self.assertRaises(ValueError):
                service_url(url, key)


@unittest.skipUnless(os.getenv("RUN_CAMOFOX_INTEGRATION_TESTS") == "1", "Opt-in CamoFox integration disabled")
class LiveCamoFoxTests(unittest.IsolatedAsyncioTestCase):
    async def test_example_dot_com(self):
        provider = CamoFoxProvider(os.getenv("CAMOFOX_BASE_URL", "http://127.0.0.1:9377"), os.getenv("CAMOFOX_ACCESS_KEY", ""))
        session = await provider.open_session()
        try:
            self.assertTrue((await provider.health()).available)
            page = await provider.open_page(session, "https://example.com/")
            self.assertIn("Example", await provider.evaluate(page, "document.title"))
            await provider.close_page(page)
        finally:
            await provider.close_session(session)
            await provider.shutdown()
