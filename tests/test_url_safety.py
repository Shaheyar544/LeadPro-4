import asyncio
import socket
import ssl
import unittest
from unittest.mock import AsyncMock, patch

import url_safety as safety


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=None):
        self.status = status
        self.headers = headers or {}
        self.content_type = self.headers.get("Content-Type", "text/html")
        length = self.headers.get("Content-Length")
        self.content_length = int(length) if length else None
        self.charset = "utf-8"
        self.content = self
        self.chunks = chunks or [b"<html>Public business</html>"]
        self.chunks_read = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            self.chunks_read += 1
            yield chunk


def fake_sessions(responses, calls):
    class Session:
        def __init__(self, **kwargs):
            self.connector = kwargs["connector"]
            assert kwargs["trust_env"] is False
            assert kwargs["auto_decompress"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, url, **kwargs):
            assert kwargs["allow_redirects"] is False
            calls.append(url)
            return responses.pop(0)
    return Session


class URLSyntaxTests(unittest.TestCase):
    def test_unsafe_destinations(self):
        urls = ["http://localhost", "http://localhost.localdomain", "http://127.0.0.1",
                "http://[::1]", "http://10.0.0.1", "http://172.16.0.1", "http://192.168.1.1",
                "http://169.254.169.254", "http://169.254.1.2", "http://[fc00::1]",
                "http://[fe80::1]", "http://0.0.0.0", "http://224.0.0.1",
                "http://[ff02::1]", "http://[::]", "http://100.64.0.1",
                "http://[::ffff:127.0.0.1]", "http://[64:ff9b::7f00:1]",
                "http://user:password@example.org", "http://@example.org",
                "http://example.org:22", "https://example.org:80", "http://example.org:8080",
                "file:///etc/passwd", "ftp://example.org", "gopher://example.org",
                "data:text/html,hello", "javascript:alert(1)", "custom://example.org",
                "http:///missing", "http://example.org\\@127.0.0.1", "http://bad_name.org",
                "http://example.org\n", "http://[fe80::1%25eth0]", "http://printer.lan"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(safety.UnsafeURL):
                safety.normalize_url(url)

    def test_valid_public_syntax(self):
        self.assertEqual(safety.normalize_url("HTTPS://Example.org:443/about#contact"), "https://example.org/about")
        self.assertEqual(safety.normalize_url("http://8.8.8.8"), "http://8.8.8.8/")
        self.assertTrue(safety.public_ip("2606:4700:4700::1111"))


class URLFetchTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, responses, url="https://example.org"):
        calls = []
        with patch.object(safety, "resolve_public", AsyncMock(return_value=("93.184.216.34",))), \
             patch.object(safety.aiohttp, "ClientSession", fake_sessions(responses, calls)):
            result = await safety.safe_fetch_html(url)
        return result, calls

    async def test_dns_all_addresses_are_checked(self):
        loop = asyncio.get_running_loop()
        for addresses, allowed in [(["93.184.216.34"], True), (["2606:4700:4700::1111"], True),
                                   (["127.0.0.1"], False), (["93.184.216.34", "10.0.0.1"], False),
                                   (["169.254.169.254"], False), (["fd00::1"], False), ([], False)]:
            records = [(socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]
            with self.subTest(addresses=addresses), patch.object(loop, "getaddrinfo", AsyncMock(return_value=records)):
                if allowed:
                    self.assertEqual(await safety.resolve_public("example.org", 443), tuple(addresses))
                else:
                    with self.assertRaises(safety.UnsafeURL):
                        await safety.resolve_public("example.org", 443)

    async def test_dns_alias_to_metadata_is_blocked_before_request(self):
        loop = asyncio.get_running_loop()
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 80))]
        with patch.object(loop, "getaddrinfo", AsyncMock(return_value=records)), patch.object(safety.aiohttp, "ClientSession") as session:
            self.assertEqual((await safety.safe_fetch_html("http://public-looking.example.org")).status, "unsafe_url")
            session.assert_not_called()

    async def test_public_html_and_pinned_resolver(self):
        result, calls = await self.fetch([FakeResponse()])
        self.assertEqual(result.status, "ok")
        self.assertIn("Public business", result.html)
        self.assertEqual(calls, ["https://example.org/"])
        resolver = safety._PinnedResolver("example.org", ("93.184.216.34",))
        with patch("socket.getaddrinfo", side_effect=AssertionError("Must not re-resolve")):
            self.assertEqual((await resolver.resolve("example.org", 443))[0]["host"], "93.184.216.34")
        with self.assertRaises(safety.UnsafeURL):
            await resolver.resolve("another.org", 443)

    async def test_unsafe_redirect_is_not_followed(self):
        for destination in ("http://127.0.0.1/admin", "http://169.254.169.254/latest", "file:///secret", "http://[::1]"):
            result, calls = await self.fetch([FakeResponse(302, {"Location": destination})])
            self.assertEqual(result.status, "unsafe_url")
            self.assertEqual(len(calls), 1)

    async def test_dns_is_rechecked_for_redirect_hostname(self):
        calls = []
        loop = asyncio.get_running_loop()
        def records(address):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))]
        with patch.object(loop, "getaddrinfo", AsyncMock(side_effect=[records("93.184.216.34"), records("10.0.0.1")])), \
             patch.object(safety.aiohttp, "ClientSession", fake_sessions([FakeResponse(302, {"Location": "https://elsewhere.org"})], calls)):
            result = await safety.safe_fetch_html("https://example.org")
        self.assertEqual(result.status, "unsafe_url")
        self.assertEqual(len(calls), 1)

    async def test_safe_relative_redirect_and_limit(self):
        result, calls = await self.fetch([FakeResponse(302, {"Location": "/about"}), FakeResponse()])
        self.assertEqual(result.url, "https://example.org/about")
        self.assertEqual(len(calls), 2)
        result, calls = await self.fetch([FakeResponse(302, {"Location": "/again"}) for _ in range(4)])
        self.assertEqual(result.status, "redirect_limit")
        self.assertEqual(len(calls), 4)

    async def test_http_classifications(self):
        for code, expected in ((403, "blocked"), (429, "rate_limited"), (404, "not_found"), (500, "http_error")):
            result, _ = await self.fetch([FakeResponse(code)])
            self.assertEqual(result.status, expected)
            self.assertEqual(result.html, "")

    async def test_body_bounds_and_content_type(self):
        result, _ = await self.fetch([FakeResponse(headers={"Content-Length": str(safety.MAX_BODY_BYTES + 1)})])
        self.assertEqual(result.status, "body_too_large")
        response = FakeResponse(chunks=[b"x" * (1024 * 1024)] * 4)
        result, _ = await self.fetch([response])
        self.assertEqual(result.status, "body_too_large")
        self.assertEqual(response.chunks_read, 3)
        for headers in ({"Content-Encoding": "gzip"}, {"Content-Type": "application/octet-stream"}):
            result, _ = await self.fetch([FakeResponse(headers=headers)])
            self.assertEqual(result.status, "unsupported_content")

    async def test_error_classification_and_deadline(self):
        for error, status in ((asyncio.TimeoutError(), "timeout"), (ssl.SSLError(), "tls_error"), (OSError(), "network_error")):
            with patch.object(safety, "_fetch_chain", AsyncMock(side_effect=error)):
                self.assertEqual((await safety.safe_fetch_html("https://example.org")).status, status)
        async def slow_fetch(url):
            await asyncio.sleep(1)
        with patch.object(safety, "TOTAL_TIMEOUT", 0.01), patch.object(safety, "_fetch_chain", new=slow_fetch):
            self.assertEqual((await safety.safe_fetch_html("https://example.org")).status, "timeout")
