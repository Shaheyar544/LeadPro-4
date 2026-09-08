"""Bounded provider discovery. No browser searches, guessed sites or enrichment."""
import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from urllib.parse import quote
import aiohttp
from engine_store import domain
from url_safety import normalize_url, UnsafeURL


class DiscoveryError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never carry URLs, keys or raw provider bodies.


@dataclass
class DiscoveryPage:
    records: list[dict] = field(default_factory=list)
    cursor: str | int | None = None
    terminal_reason: str | None = None
    diagnostics: dict = field(default_factory=dict)


def text(value, length=300):
    return str(value or "").strip()[:length]


def numeric(value, maximum, integer=False):
    try:
        number = float(value)
        if not math.isfinite(number) or number < 0 or number > maximum:
            return None
        return int(number) if integer else number
    except (ValueError, TypeError):
        return None


def website(value):
    try:
        url = normalize_url(text(value, 2048))
        # A listing/social profile is provenance, not a verified business site.
        if domain(url) in {"yelp.com", "google.com", "maps.google.com", "facebook.com", "instagram.com", "linkedin.com", "youtube.com"}:
            return ""
        return url
    except UnsafeURL:
        return ""


def record(provider, raw, job):
    rid = text(raw.get("id"), 300)
    name = text(raw.get("name"))
    if not name:
        return None
    if not rid:
        rid = "composite-" + hashlib.sha256(json.dumps([name, raw.get("address"), raw.get("phone"), raw.get("website"), job["city"], job["state"]]).encode()).hexdigest()
    return dict(provider=provider, provider_record_id=rid, canonical_name=name,
                website_url=website(raw.get("website")), provider_phone=text(raw.get("phone"), 100),
                address=text(raw.get("address"), 500), city=text(raw.get("city") or job["city"], 100),
                state=text(raw.get("state") or job["state"], 50), category=job["category"],
                rating=numeric(raw.get("rating"), 5), review_count=numeric(raw.get("reviews"), 100000000, True),
                source_url=text(raw.get("source_url"), 2048))


class ProviderDiscovery:
    def __init__(self, name, key):
        self.name, self._key = name, key
        self._last_google_token = None

    async def _json(self, http, method, url, **kwargs):
        try:
            async with http.request(method, url, allow_redirects=False, **kwargs) as response:
                if response.status == 429:
                    raise DiscoveryError("google_over_query_limit" if self.name == "google_places" else "provider_limit")
                if response.status != 200:
                    raise DiscoveryError("google_http_error" if self.name == "google_places" else "provider_unavailable")
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 2 * 1024 * 1024:
                        raise DiscoveryError("provider_protocol_error")
                    chunks.append(chunk)
                data = json.loads(b"".join(chunks))
                if not isinstance(data, dict):
                    raise ValueError
                return data
        except asyncio.TimeoutError:
            raise DiscoveryError("google_transport_timeout" if self.name == "google_places" else "provider_unavailable") from None
        except aiohttp.ClientError:
            raise DiscoveryError("google_http_transport_error" if self.name == "google_places" else "provider_unavailable") from None
        except (ValueError, UnicodeError):
            raise DiscoveryError("google_malformed_response" if self.name == "google_places" else "provider_protocol_error") from None

    async def fetch_page(self, job, cursor=None, limit=20, cancelled=lambda: False):
        limit = max(1, min(limit, 20))
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20),
                                         cookie_jar=aiohttp.DummyCookieJar(), trust_env=False) as http:
            query = f"{job['category']} in {job['city']}, {job['state']}, United States"
            if self.name == "serper_maps":
                # Public official documentation does not establish a stable Maps
                # pagination contract. Explicitly one page; never invent a cursor.
                data = await self._json(http, "POST", "https://google.serper.dev/maps", headers={"X-API-KEY": self._key}, json={"q": query, "gl": "us", "hl": "en"})
                places = data.get("places")
                if not isinstance(places, list):
                    raise DiscoveryError("provider_protocol_error")
                rows = [record(self.name, {"id": p.get("placeId") or p.get("cid"), "name": p.get("title"), "website": p.get("website"), "phone": p.get("phoneNumber") or p.get("phone"), "address": p.get("address"), "rating": p.get("rating"), "reviews": p.get("ratingCount"), "source_url": "https://www.google.com/maps/search/?api=1&query=" + quote(p.get("title", "")) + "&query_place_id=" + quote(p.get("placeId", ""))}, job) for p in places[:limit] if isinstance(p, dict)]
                return DiscoveryPage([r for r in rows if r], terminal_reason="provider_limit" if places else "discovery_exhausted")
            if self.name == "yelp":
                offset = int(cursor or 0)
                data = await self._json(http, "GET", "https://api.yelp.com/v3/businesses/search", headers={"Authorization": "Bearer " + self._key}, params={"term": job["category"], "location": f"{job['city']}, {job['state']}, US", "limit": limit, "offset": offset})
                places = data.get("businesses")
                if not isinstance(places, list):
                    raise DiscoveryError("provider_protocol_error")
                rows = []
                for p in places[:limit]:
                    location = p.get("location") or {}
                    r = record(self.name, {"id": p.get("id"), "name": p.get("name"), "phone": p.get("display_phone") or p.get("phone"), "address": ", ".join(location.get("display_address", [])), "city": location.get("city"), "state": location.get("state"), "rating": p.get("rating"), "reviews": p.get("review_count"), "source_url": p.get("url")}, job)
                    if r:
                        rows.append(r)
                end = offset + len(places)
                total = numeric(data.get("total"), 100000000, True) or end
                more = bool(places) and end < min(total, 240)
                return DiscoveryPage(rows, end if more else None, None if more else "provider_limit" if end >= 240 else "discovery_exhausted")
            if self.name != "google_places":
                raise DiscoveryError("provider_protocol_error")
            params = {"key": self._key, "language": "en"}
            params.update({"pagetoken": cursor} if cursor else {"query": query})
            token_attempts = 0
            statuses = []
            token_started = time.monotonic() if cursor else None
            fresh_token = bool(cursor and cursor == self._last_google_token)
            if cursor:
                await asyncio.sleep(2)  # Legacy next_page_token activation delay.
            while True:
                token_attempts += 1 if cursor else 0
                data = await self._json(http, "GET", "https://maps.googleapis.com/maps/api/place/textsearch/json", params=params)
                status = data.get("status")
                statuses.append(status if isinstance(status, str) else "MALFORMED")
                # A fresh token can briefly return INVALID_REQUEST. Retry only
                # this immediately-following token, with a strict four-request
                # bound and no retry for arbitrary first-page requests.
                if status == "INVALID_REQUEST" and fresh_token and token_attempts < 4:
                    await asyncio.sleep(2)
                    continue
                break
            if status not in {"OK", "ZERO_RESULTS"}:
                error_codes = {
                    "INVALID_REQUEST": "page_token_not_ready_timeout" if fresh_token else "google_invalid_request",
                    "OVER_QUERY_LIMIT": "google_over_query_limit",
                    "REQUEST_DENIED": "google_request_denied",
                    "UNKNOWN_ERROR": "google_unknown_error",
                }
                raise DiscoveryError(error_codes.get(status, "google_malformed_response" if not isinstance(status, str) else "google_provider_error"))
            diagnostics = {
                "page": 1 if not cursor else 2,
                "token_attempts": token_attempts,
                "token_wait_ms": round((time.monotonic() - token_started) * 1000) if token_started else 0,
                "statuses": statuses,
            }
            if status == "ZERO_RESULTS":
                return DiscoveryPage([], None, "discovery_exhausted", diagnostics)
            rows = []
            for place in data.get("results", [])[:limit]:
                if cancelled():
                    break
                pid = place.get("place_id")
                if not pid:
                    continue
                details = await self._json(http, "GET", "https://maps.googleapis.com/maps/api/place/details/json", params={"place_id": pid, "key": self._key, "fields": "name,formatted_address,formatted_phone_number,website,rating,user_ratings_total,url"})
                if details.get("status") not in {"OK", "ZERO_RESULTS", "NOT_FOUND"}:
                    detail_status = details.get("status")
                    detail_codes = {"OVER_QUERY_LIMIT": "google_over_query_limit", "REQUEST_DENIED": "google_request_denied", "UNKNOWN_ERROR": "google_unknown_error", "INVALID_REQUEST": "google_invalid_request"}
                    raise DiscoveryError(detail_codes.get(detail_status, "google_provider_error"))
                p = details.get("result") or place
                r = record(self.name, {"id": pid, "name": p.get("name"), "website": p.get("website"), "phone": p.get("formatted_phone_number"), "address": p.get("formatted_address"), "rating": p.get("rating"), "reviews": p.get("user_ratings_total"), "source_url": p.get("url") or "https://www.google.com/maps/search/?api=1&query=" + quote(p.get("name", "")) + "&query_place_id=" + quote(pid)}, job)
                if r:
                    rows.append(r)
            cursor = data.get("next_page_token")
            self._last_google_token = cursor
            diagnostics["next_page_token"] = bool(cursor)
            return DiscoveryPage(rows, cursor, None if cursor else "discovery_exhausted", diagnostics)


def configured_sources():
    import config
    return [ProviderDiscovery(name, key) for name, key in (
        ("serper_maps", config.SERPER_API_KEY), ("google_places", config.GOOGLE_PLACES_API_KEY),
        ("yelp", config.YELP_API_KEY)) if key]


def provider_readiness():
    """Local configuration only. This diagnostic never contacts providers."""
    import config
    providers = (("serper_maps", "SERPER_API_KEY", "one_page", 1),
                 ("google_places", "GOOGLE_PLACES_API_KEY", "next_page_token", 3),
                 ("yelp", "YELP_API_KEY", "offset", 5))
    return {name: dict(configured=bool(getattr(config, env, "")),
                       adapter_enabled=bool(getattr(config, env, "")),
                       pagination=pagination, hard_max_pages=pages,
                       config_status="configured_unverified" if getattr(config, env, "") else "not_configured",
                       quota_status="unknown") for name, env, pagination, pages in providers}
