"""jo-inc/camofox-browser 1.14.0 REST contract (not an embedded worker).

Checks top-level destinations before and after navigation. These checks cannot
intercept Firefox subresources or intermediate redirects: service-side network
egress isolation is required before deploying against untrusted sites at scale.
"""
import asyncio
import errno
import ipaddress
import json
import re
import uuid
from urllib.parse import urlsplit, quote
from engine_store import domain

import aiohttp

from url_safety import normalize_url, resolve_public, UnsafeURL
from .base import BrowserProvider, BrowserSession, BrowserPage, BrowserHealth, BrowserError


async def validate_destination(url: str) -> str:
    try:
        url = normalize_url(url)
        await resolve_public(urlsplit(url).hostname, urlsplit(url).port or (443 if url.startswith("https:") else 80))
        return url
    except (UnsafeURL, ValueError, OSError, asyncio.TimeoutError):
        raise BrowserError("unsafe_navigation", phase="redirect_validation") from None


def service_url(value: str, access_key: str) -> str:
    """Only operator configuration calls this; never accept request overrides."""
    try:
        p = urlsplit(value)
        if p.scheme not in ("http", "https") or not p.hostname or p.username is not None or p.password is not None:
            raise ValueError
        if p.query or p.fragment or p.path not in ("", "/") or any(ord(c) <= 32 for c in value):
            raise ValueError
        _ = p.port
        loopback = p.hostname == "localhost"
        try:
            loopback = loopback or ipaddress.ip_address(p.hostname).is_loopback
        except ValueError:
            pass
        if not loopback and not access_key:
            raise ValueError
        if any(ord(c) < 32 or ord(c) == 127 for c in access_key):
            raise ValueError
        return value.rstrip("/")
    except ValueError:
        raise ValueError("Invalid CamoFox configuration: use an HTTP(S) service URL; non-loopback requires CAMOFOX_ACCESS_KEY") from None


class CamoFoxProvider(BrowserProvider):
    name = "camofox"
    version = "1.14.0+e5a36f5"

    def __init__(self, base_url="http://127.0.0.1:9377", access_key="", timeout=35, settle_ms=1200):
        self.base_url = service_url(base_url, access_key)
        self._key = access_key
        self.timeout = max(1, min(float(timeout), 60))
        self.settle_ms = max(0, min(int(settle_ms), 3000))
        self._http = None

    @staticmethod
    def _phase(method, path):
        if method == "DELETE": return "cleanup"
        if path == "/tabs": return "tab_create"
        return {"navigate": "initial_navigation", "evaluate": "evaluate", "links": "link_extract",
                "snapshot": "snapshot", "screenshot": "snapshot", "viewport": "viewport"}.get(path.rsplit("/", 1)[-1], "connect")

    @staticmethod
    def _timeout_code(phase):
        return {"connect": "browser_connect_timeout", "tab_create": "browser_tab_timeout",
                "initial_navigation": "browser_navigation_timeout", "evaluate": "browser_evaluate_timeout",
                "snapshot": "browser_snapshot_timeout", "cleanup": "browser_cleanup_timeout"}.get(phase, "browser_timeout")

    @classmethod
    def response_error(cls, status, data, phase):
        # Allowlisted classifications only; raw messages never leave this function.
        code, retry = "browser_protocol_error", False
        supplied = str(data.get("code", ""))
        message = str(data.get("error", ""))[:4096]
        if status in (401, 403): code = "browser_unavailable"
        elif status == 429: code = "browser_blocked"
        elif supplied == "ssl_error" or re.search(r"SEC_ERROR|SSL_ERROR|MOZILLA_PKIX_ERROR", message): code = "browser_tls_error"
        elif re.search(r"access denied|captcha|too many requests|robots restriction", message, re.I): code = "browser_blocked"
        elif status in (408, 504) or supplied == "tab_timeout" or re.search(r"timed out|timeout", message, re.I):
            code, retry = cls._timeout_code(phase), True
        elif status in (404, 410, 503): code, retry = ("browser_unavailable", False) if phase == "connect" else ("browser_session_lost", True)
        elif "NS_ERROR_NET_RESET" in message: code, retry = "browser_connection_reset", True
        elif status >= 500: code = "browser_navigation_failed"
        return BrowserError(code, phase=phase, http_status=status, retryable=retry)

    async def _request(self, method, path, *, body=None, params=None, binary=False):
        phase = self._phase(method, path)
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout), trust_env=False,
                cookie_jar=aiohttp.DummyCookieJar(),
                headers={"Authorization": f"Bearer {self._key}"} if self._key else {})
        # Only idempotent GET/DELETE transport failures are retried once.
        # Tab creation/navigation/evaluation must never replay after an ambiguous timeout.
        attempts = 2 if method in ("GET", "DELETE") else 1
        for attempt in range(attempts):
            try:
                async with self._http.request(method, self.base_url + path, json=body,
                                              params=params, allow_redirects=False,
                                              timeout=aiohttp.ClientTimeout(total=max(35, self.timeout) if method == "POST" and path == "/tabs" else self.timeout)) as response:
                    chunks, size = [], 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        if size > (8 * 1024 * 1024 if response.status == 200 else 8192):
                            raise BrowserError("browser_protocol_error")
                        chunks.append(chunk)
                    payload = b"".join(chunks)
                    if response.status != 200:
                        try:
                            error_data = json.loads(payload)
                        except (ValueError, UnicodeError):
                            error_data = {}
                        raise self.response_error(response.status, error_data if isinstance(error_data, dict) else {}, phase)
                    if binary:
                        if response.content_type != "image/png" or not payload.startswith(b"\x89PNG\r\n\x1a\n"):
                            raise BrowserError("browser_protocol_error")
                        return payload
                    result = json.loads(payload)
                    if not isinstance(result, dict):
                        raise BrowserError("browser_protocol_error")
                    return result
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.15)
                    continue
                code = "browser_connect_timeout" if isinstance(exc, getattr(aiohttp, "ConnectionTimeoutError", ())) else self._timeout_code(phase) if isinstance(exc, asyncio.TimeoutError) else "browser_unavailable"
                reset = isinstance(exc, aiohttp.ServerDisconnectedError) or (isinstance(exc, aiohttp.ClientOSError) and exc.errno in {errno.ECONNRESET, 10054})
                if reset: code = "browser_connection_reset"
                raise BrowserError(code, phase=phase, retryable=reset or isinstance(exc, asyncio.TimeoutError)) from None
            except BrowserError as exc:
                if exc.phase is None: exc.phase = phase
                raise
            except (ValueError, UnicodeError):
                raise BrowserError("browser_protocol_error", phase=phase) from None

    async def health(self):
        try:
            data = await self._request("GET", "/health")
            if data.get("ok") is not True:
                raise BrowserError("browser_unavailable")
            return BrowserHealth(self.name, True, True, "available", self.version)
        except BrowserError as exc:
            return BrowserHealth(self.name, True, False, exc.code, self.version)

    async def open_session(self):
        # CamoFox creates the context lazily on POST /tabs. ID exists beforehand
        # so teardown is possible even if that POST times out after allocation.
        return BrowserSession("lead-engine-" + uuid.uuid4().hex, uuid.uuid4().hex)

    async def _create_tab(self, session):
        # Let the bounded, non-replayed creation request settle before worker
        # teardown. Deleting its context mid-POST makes CamoFox's new-page
        # recovery recreate that context after DELETE has already succeeded.
        request = asyncio.create_task(self._request("POST", "/tabs", body={
            "userId": session.user_id, "sessionKey": session.session_key, "trace": False}))
        cancelled = False
        while True:
            try:
                data = await asyncio.shield(request)
                break
            except asyncio.CancelledError:
                if request.cancelled():
                    raise
                cancelled = True  # Also tolerate repeated shutdown cancellation.
            except BrowserError:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError
        tab_id = data.get("tabId")
        if not isinstance(tab_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", tab_id):
            raise BrowserError("browser_protocol_error")
        session.pages.add(tab_id)
        # Blank internal allocation gives us a cleanup ID before navigation.
        # about:blank is accepted ONLY as this service-created empty tab result.
        if data.get("url") != "about:blank":
            raise BrowserError("browser_protocol_error", phase="tab_create")
        return BrowserPage(tab_id, session, "about:blank")

    async def open_page(self, session, url):
        url = await validate_destination(url)  # Unsafe input never reaches even POST /tabs.
        try:
            page = await self._create_tab(session)
        except BaseException:
            try:
                await self.close_session(session)
            except BrowserError:
                pass
            raise
        try:
            await self.navigate(page, url)
            return page
        except BrowserError as exc:
            # A timed-out navigation can leave useful DOM. Observe it once on the
            # known tab, without replaying POST or guessing another destination.
            if exc.code not in {"browser_blocked", "browser_tls_error", "unsafe_navigation", "external_redirect", "browser_unavailable", "browser_session_lost"}:
                try:
                    actual = await self.evaluate(page, "location.href")
                    if actual != "about:blank":
                        page.url = await validate_destination(actual)
                        if domain(page.url) != domain(url):
                            raise BrowserError("external_redirect", phase="redirect_validation")
                        page.navigation_error = exc
                        return page
                except BrowserError as probe:
                    if probe.code in {"unsafe_navigation", "external_redirect"}:
                        raise probe from None
            raise

    def _path(self, page, operation=""):
        return "/tabs/" + quote(page.id, safe="") + ("/" + operation if operation else "")

    async def navigate(self, page, url):
        url = await validate_destination(url)
        await self._request("POST", self._path(page, "navigate"), body={"userId": page.session.user_id, "url": url})
        result = await self.evaluate(page, "location.href")
        try:
            page.url = await validate_destination(result)
            if domain(page.url) != domain(url):
                raise BrowserError("external_redirect", phase="redirect_validation")
        except BrowserError:
            try:
                await self.close_session(page.session)
            except BrowserError:
                pass
            raise
        return page.url

    async def get_links(self, page):
        data = await self._request("GET", self._path(page, "links"), params={"userId": page.session.user_id, "limit": "250"})
        if not isinstance(data.get("links"), list):
            raise BrowserError("browser_protocol_error")
        if not all(isinstance(link, dict) and isinstance(link.get("url"), str) for link in data["links"][:250]):
            raise BrowserError("browser_protocol_error")
        return [{"href": link["url"], "text": str(link.get("text", ""))[:240]} for link in data["links"][:250]]

    async def evaluate(self, page, expression):
        data = await self._request("POST", self._path(page, "evaluate"), body={
            "userId": page.session.user_id, "expression": expression})
        if data.get("ok") is not True or "result" not in data:
            raise BrowserError("browser_protocol_error")
        return data["result"]

    async def get_snapshot(self, page):
        data = await self._request("GET", self._path(page, "snapshot"), params={
            "userId": page.session.user_id, "format": "text", "includeScreenshot": "false"})
        if not isinstance(data.get("snapshot"), str) or not isinstance(data.get("url"), str):
            raise BrowserError("browser_protocol_error")
        try:
            await validate_destination(data["url"])
        except BrowserError:
            try:
                await self.close_session(page.session)
            except BrowserError:
                pass
            raise
        # Transient only; callers must not persist full accessibility snapshots.
        return {"url": data["url"], "snapshot": data["snapshot"][:12000], "truncated": data.get("truncated", False)}

    async def screenshot(self, page):
        return await self._request("GET", self._path(page, "screenshot"), params={"userId": page.session.user_id}, binary=True)

    async def set_viewport(self, page, width, height):
        data = await self._request("POST", self._path(page, "viewport"), body={
            "userId": page.session.user_id, "width": width, "height": height})
        if data.get("ok") is not True:
            raise BrowserError("browser_protocol_error")
        return True

    async def close_page(self, page):
        try:
            await self._request("DELETE", self._path(page), params={"userId": page.session.user_id})
        except BrowserError as exc:
            if exc.code != "browser_session_lost":
                raise
        finally:
            page.session.pages.discard(page.id)

    async def close_session(self, session):
        try:
            await self._request("DELETE", "/sessions/" + quote(session.user_id, safe=""))
        except BrowserError as exc:
            if exc.code != "browser_session_lost":
                raise
        finally:
            session.pages.clear()

    async def shutdown(self):
        if self._http is not None:
            await self._http.close()
