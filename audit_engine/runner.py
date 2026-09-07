"""One isolated, bounded public business audit using any BrowserProvider."""
import asyncio
from pathlib import Path
import time

from browser.base import BrowserError
from browser.camofox import validate_destination
from engine_store import now, uid, domain
from .detectors import KEYS, evidence, detect, selected_links, public_contacts

EXTRACT = Path(__file__).with_name("extract.js").read_text(encoding="utf-8")
MOBILE = "({url: location.href, width: innerWidth, scroll_width: document.documentElement.scrollWidth})"


class AuditEngine:
    def __init__(self, browser, settings, *, validate=validate_destination):
        self.browser = browser
        self.settings = settings
        self.validate = validate

    async def run(self, business, session, *, cancelled=lambda: False):
        website = business.get("website_url") or ""
        result = dict(status="completed", final_url=None, error_code=None, pages=[], evidence=[], contacts=[])
        # Explicit provider phone is public provenance, kept separate from rendered contacts.
        if business.get("provider_phone"):
            result["contacts"] += public_contacts({"contacts": [{"type": "phone", "kind": "provider_public", "value": business["provider_phone"]}]}, business.get("provider_source_url", ""))
        if not website:
            result.update(status="unverified", error_code="website_unverified")
            result["evidence"] = [evidence(key, "unknown") for key in KEYS]
            return result
        pending = [(website, "homepage")]
        base = None
        while pending and len(result["pages"]) < min(self.settings.pages, 4):
            if cancelled():
                result.update(status="cancelled", error_code="cancelled")
                break
            url, page_type = pending.pop(0)
            page_record = dict(id=uid(), url=url, page_type=page_type, status="failed", observed_at=now())
            result["pages"].append(page_record)
            page = None
            started = time.monotonic()
            try:
                # Same policy applies even to injected or future providers.
                url = await self.validate(url)
                if base and domain(url) != domain(base):
                    raise BrowserError("unsafe_navigation")
                page = await self.browser.open_page(session, url)
                final_url = await self.validate(page.url)
                if base and domain(final_url) != domain(base):
                    raise BrowserError("unsafe_navigation")
                facts = await self.browser.evaluate(page, EXTRACT)
                if not isinstance(facts, dict) or not all(key in facts for key in ("url", "ready_state", "complete", "links", "contacts", "forms", "ctas", "resources")):
                    raise BrowserError("browser_protocol_error")
                if not all(isinstance(facts[k], list) for k in ("links", "contacts", "forms", "ctas", "resources")):
                    raise BrowserError("browser_protocol_error")
                if not all(isinstance(item, dict) for key in ("links", "contacts", "forms", "ctas") for item in facts[key]) or not all(isinstance(item, str) for item in facts["resources"]):
                    raise BrowserError("browser_protocol_error")
                final_url = await self.validate(facts["url"])
                if domain(final_url) != domain(url):
                    # Only www alias changes are accepted; cross-domain identity needs verification.
                    raise BrowserError("unsafe_navigation")
                page_record.update(final_url=final_url, title=str(facts.get("title", ""))[:240],
                                   navigation_ms=round((time.monotonic() - started) * 1000))
                result["final_url"] = result["final_url"] or final_url
                if facts.get("blocked") or facts.get("login_wall"):
                    raise BrowserError("browser_blocked")
                if facts.get("http_status") and facts["http_status"] >= 400:
                    raise BrowserError("browser_navigation_failed")
                if facts.get("ready_state") not in {"complete", "interactive"}:
                    raise BrowserError("browser_navigation_failed")
                page_record["status"] = "completed"
                findings, contacts = detect(facts, page_record)
                result["evidence"] += findings
                result["contacts"] += contacts
                if not facts.get("complete"):
                    result.update(status="partial", error_code="audit_incomplete")
                if page_type == "homepage":
                    base = final_url
                    pending = selected_links(facts["links"], final_url, self.settings.pages)
                    # Viewport control is supported in pinned CamoFox 1.14.0.
                    await self._mobile(page, page_record, result)
                if cancelled():
                    result.update(status="cancelled", error_code="cancelled")
                    break
                if self.settings.screenshots and page_type in {"homepage", "contact"}:
                    await self._screenshot(page, page_record)
            except BrowserError as exc:
                status = "blocked" if exc.code == "browser_blocked" else "failed"
                page_record["status"] = status
                result.update(status="partial" if any(p["status"] == "completed" for p in result["pages"]) else status, error_code=exc.code)
                result["evidence"] += [evidence(key, status, url=url, page_type=page_type, page_id=page_record["id"]) for key in KEYS]
                # Never retry denial/challenges/unsafe redirects in another session.
                if exc.code in {"browser_blocked", "unsafe_navigation", "browser_unavailable", "browser_session_lost"}:
                    break
            finally:
                if page is not None:
                    try:
                        await self.browser.close_page(page)
                    except BrowserError:
                        pass  # Session cleanup remains mandatory in the worker's finally.
        # Optional external measurement; never reinterpret navigation milliseconds.
        if result["status"] == "completed" and not cancelled():
            import config
            if config.PAGESPEED_API_KEY:
                from .pagespeed import measure
                measurement = await measure(result["final_url"], config.PAGESPEED_API_KEY)
                result["evidence"].append(evidence("pagespeed", "present" if measurement else "unknown", measurement,
                                                   url=result["final_url"], locator="PageSpeed Insights mobile performance", confidence=0.95))
        if not any(e["detector_key"] == "pagespeed" for e in result["evidence"]):
            result["evidence"].append(evidence("pagespeed", "unknown", url=website, excerpt="PageSpeed was not measured."))
        return result

    async def _mobile(self, page, record, result):
        finding = evidence("mobile_layout", "unknown", url=record["final_url"], page_id=record["id"])
        try:
            if await self.browser.set_viewport(page, 390, 844):
                await asyncio.sleep(min(self.settings.settle_ms, 500) / 1000)
                layout = await self.browser.evaluate(page, MOBILE)
                if not isinstance(layout, dict):
                    raise BrowserError("browser_protocol_error")
                final_url = await self.validate(layout.get("url", ""))
                if domain(final_url) != domain(record["final_url"]):
                    raise BrowserError("unsafe_navigation")
                width, scroll = layout.get("width"), layout.get("scroll_width")
                if isinstance(width, (int, float)) and isinstance(scroll, (int, float)) and 385 <= width <= 395 and scroll > 0:
                    finding = evidence("mobile_layout", "present" if scroll <= width + 2 else "absent",
                                       {"viewport_width": width, "scroll_width": scroll, "browser": self.browser.name},
                                       url=record["final_url"], page_id=record["id"], locator="document.documentElement.scrollWidth",
                                       excerpt="Firefox layout overflow check at 390 CSS px; not a Chromium/device certification.", confidence=0.75)
        except BrowserError as exc:
            if exc.code in {"unsafe_navigation", "browser_session_lost"}:
                raise
        finally:
            result["evidence"].append(finding)

    async def _screenshot(self, page, record):
        # Recheck destination immediately before capture, including client-side redirects.
        url = await self.browser.evaluate(page, "location.href")
        url = await self.validate(url)
        if domain(url) != domain(record["final_url"]):
            raise BrowserError("unsafe_navigation")
        data = await self.browser.screenshot(page)
        root = self.settings.artifacts.resolve()
        root.mkdir(parents=True, exist_ok=True)
        name = uid() + ".png"
        target = root / name
        with target.open("xb") as stream:
            stream.write(data)
        record.update(screenshot_path=name, screenshot_bytes=len(data))
