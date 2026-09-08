"""Optional PageSpeed measurement, separate from navigation timing."""
import asyncio
import aiohttp
from browser.camofox import validate_destination
from browser.base import BrowserError
from engine_utils import now, domain


async def measure(url, api_key):
    if not api_key:
        return None
    try:
        await validate_destination(url)
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25), trust_env=False,
                                         cookie_jar=aiohttp.DummyCookieJar()) as session:
            async with session.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                                   params={"url": url, "key": api_key, "strategy": "mobile", "category": "performance"},
                                   allow_redirects=False) as response:
                if response.status != 200:
                    return None
                # PSI JSON is larger than our evidence; discard the response after
                # extracting this measurement and never retain page content.
                chunks, size = [], 0
                async for chunk in response.content.iter_chunked(65536):
                    size += len(chunk)
                    if size > 5 * 1024 * 1024:
                        return None
                    chunks.append(chunk)
                import json
                data = json.loads(b"".join(chunks))
                lighthouse = data["lighthouseResult"]
                final_url = await validate_destination(lighthouse["finalUrl"])
                if domain(final_url) != domain(url):
                    return None
                score = lighthouse["categories"]["performance"]["score"]
                if isinstance(score, (int, float)) and 0 <= score <= 1:
                    return {"provider": "Google PageSpeed Insights", "score": round(score * 100),
                            "strategy": "mobile", "observed_at": now(), "lighthouse_version": lighthouse.get("lighthouseVersion")}
    except (aiohttp.ClientError, asyncio.TimeoutError, BrowserError, KeyError, ValueError, TypeError):
        pass
    return None
