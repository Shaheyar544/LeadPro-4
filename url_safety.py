"""Bounded HTTP HTML fetches with validated, pinned public destinations.

No browser or subresource fetching. Production still needs network egress rules.
"""
import asyncio
from dataclasses import dataclass
import ipaddress
import re
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp

MAX_REDIRECTS = 3
MAX_BODY_BYTES = 2 * 1024 * 1024
TOTAL_TIMEOUT = 20
CONNECT_TIMEOUT = 5


class UnsafeURL(ValueError):
    pass


def public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not ip.is_global or any((ip.is_loopback, ip.is_private, ip.is_link_local,
                               ip.is_multicast, ip.is_unspecified, ip.is_reserved)):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        # Avoid address translation/tunneling ambiguities in this initial policy.
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            return False
    return True


def normalize_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise UnsafeURL("Invalid URL length")
    if any(ord(c) <= 32 or ord(c) == 127 for c in value) or "\\" in value:
        raise UnsafeURL("Invalid URL characters")
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"}:
            raise UnsafeURL("Only HTTP and HTTPS are allowed")
        if parts.username is not None or parts.password is not None:
            raise UnsafeURL("URL credentials are forbidden")
        host = parts.hostname
        if not host or "%" in host:
            raise UnsafeURL("Invalid hostname")
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        expected_port = 443 if parts.scheme.lower() == "https" else 80
        if parts.port is not None and parts.port != expected_port:
            raise UnsafeURL("Only the scheme's standard web port is allowed")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            labels = host.split(".")
            if len(host) > 253 or len(labels) < 2 or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in labels
            ):
                raise UnsafeURL("Invalid public hostname")
            if host == "localhost.localdomain" or host.endswith(
                (".localhost", ".local", ".localdomain", ".internal", ".home", ".lan")
            ):
                raise UnsafeURL("Local hostnames are forbidden")
        else:
            if not public_ip(host):
                raise UnsafeURL("Destination is not public")
        authority = f"[{host}]" if ":" in host else host
        return urlunsplit((parts.scheme.lower(), authority, parts.path or "/", parts.query, ""))
    except (ValueError, UnicodeError) as exc:
        if isinstance(exc, UnsafeURL):
            raise
        raise UnsafeURL("Malformed URL") from None


async def resolve_public(host: str, port: int) -> tuple[str, ...]:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        records = await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM),
            timeout=CONNECT_TIMEOUT,
        )
        addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    else:
        addresses = (host,)
    if not addresses or not all(public_ip(address) for address in addresses):
        raise UnsafeURL("DNS destination is not public")
    return addresses


class _PinnedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self, host, addresses):
        self.host, self.addresses = host, addresses

    async def resolve(self, host, port=0, family=socket.AF_UNSPEC):
        if host != self.host:
            raise UnsafeURL("Unexpected connection hostname")
        return [dict(hostname=host, host=address, port=port,
                     family=socket.AF_INET6 if ":" in address else socket.AF_INET,
                     proto=socket.IPPROTO_TCP, flags=socket.AI_NUMERICHOST)
                for address in self.addresses]

    async def close(self):
        pass


@dataclass(frozen=True)
class FetchResult:
    status: str
    url: str = ""
    http_status: int = 0
    html: str = ""


def classify_http(status: int) -> str:
    if 200 <= status < 300:
        return "ok"
    return {401: "blocked", 403: "blocked", 429: "rate_limited",
            404: "not_found", 410: "not_found"}.get(status, "http_error")


async def _fetch_chain(url: str) -> FetchResult:
    for hop in range(MAX_REDIRECTS + 1):
        current = normalize_url(url)
        parsed = urlsplit(current)
        addresses = await resolve_public(parsed.hostname, 443 if parsed.scheme == "https" else 80)
        connector = aiohttp.TCPConnector(
            resolver=_PinnedResolver(parsed.hostname, addresses), use_dns_cache=False,
            limit=1, force_close=True, ssl=True,
        )
        timeout = aiohttp.ClientTimeout(total=TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT, sock_read=10)
        # Never reuse provider credentials, cookies, proxies or an unvalidated pool.
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False,
            cookie_jar=aiohttp.DummyCookieJar(), auto_decompress=False,
        ) as session:
            async with session.get(current, allow_redirects=False, headers={
                "User-Agent": "LeadEngine/0.1 (public business website review)",
                "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity",
            }) as response:
                if response.status in {301, 302, 303, 307, 308}:
                    destination = response.headers.get("Location")
                    if not destination:
                        return FetchResult("http_error", current, response.status)
                    # Revalidate even the final disallowed hop; never follow automatically.
                    url = normalize_url(urljoin(current, destination))
                    if hop == MAX_REDIRECTS:
                        return FetchResult("redirect_limit", current, response.status)
                    continue
                status = classify_http(response.status)
                if status != "ok":
                    return FetchResult(status, current, response.status)
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    return FetchResult("unsupported_content", current, response.status)
                if response.content_type not in {"text/html", "application/xhtml+xml"}:
                    return FetchResult("unsupported_content", current, response.status)
                if response.content_length is not None and response.content_length > MAX_BODY_BYTES:
                    return FetchResult("body_too_large", current, response.status)
                data = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    if len(data) + len(chunk) > MAX_BODY_BYTES:
                        return FetchResult("body_too_large", current, response.status)
                    data.extend(chunk)
                try:
                    html = data.decode(response.charset or "utf-8", errors="replace")
                except LookupError:
                    html = data.decode("utf-8", errors="replace")
                return FetchResult("ok", current, response.status, html)


async def safe_fetch_html(url: str) -> FetchResult:
    try:
        # Includes DNS, all redirects, reading and connection time, not 20s per hop.
        return await asyncio.wait_for(_fetch_chain(url), timeout=TOTAL_TIMEOUT)
    except UnsafeURL:
        return FetchResult("unsafe_url")
    except asyncio.TimeoutError:
        return FetchResult("timeout")
    except (aiohttp.ClientSSLError, ssl.SSLError):
        return FetchResult("tls_error")
    except (aiohttp.ClientError, OSError, ValueError):
        return FetchResult("network_error")
