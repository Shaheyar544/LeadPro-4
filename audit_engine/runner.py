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

    async def run(self, business, session, *, cancelled=lambda: False, recover_session=None, record_attempt=None):
        from .readiness import observe
        website = business.get("website_url") or ""
        result = dict(status="completed", final_url=None, error_code=None, pages=[], evidence=[], contacts=[])
        if business.get("provider_phone"):
            result["contacts"] += public_contacts({"contacts": [{"type": "phone", "kind": "provider_public", "value": business["provider_phone"]}]}, business.get("provider_source_url", ""))
        if not website:
            result.update(status="unverified", error_code="website_unverified")
            result["evidence"] = [evidence(key, "unknown") for key in KEYS]
            return result
        pending = [(website, "homepage")]
        base = None
        stop = False
        while pending and len(result["pages"]) < min(self.settings.pages, 4) and not stop:
            if cancelled():
                result.update(status="cancelled", error_code="cancelled")
                break
            url, page_type = pending.pop(0)
            record = dict(id=uid(), url=url, page_type=page_type, status="failed", observed_at=now(), attempts=[])
            result["pages"].append(record)
            for attempt in range(1, 3):
                page = None
                started = time.monotonic()
                diagnostic = dict(attempt=attempt, phase="redirect_validation", status="running", error_code=None,
                                  dom=False, title=False, links=False, snapshot=False, evaluate=False,
                                  redirects=[url], redirect_chain_complete=False)
                record["attempts"].append(diagnostic)
                def persist():
                    if record_attempt:
                        record_attempt(record["id"], attempt, diagnostic)
                persist()  # Durable attempt count before a browser request, including interrupted runs.
                try:
                    url = await self.validate(url)
                    if base and domain(url) != domain(base):
                        raise BrowserError("external_redirect", phase="redirect_validation")
                    diagnostic["phase"] = "tab_create"
                    page = await self.browser.open_page(session, url)
                    final_url = await self.validate(page.url)
                    if domain(final_url) != domain(url):
                        raise BrowserError("external_redirect", phase="redirect_validation")
                    diagnostic["redirects"] = list(dict.fromkeys([url, final_url]))
                    diagnostic["phase"] = "dom_ready"
                    facts, readiness = await observe(self.browser, page, EXTRACT, self.settings.readiness_ms, self.validate, domain(url))
                    record.update(final_url=facts["url"], title=str(facts.get("title", ""))[:240])
                    diagnostic.update(readiness=readiness, dom=True, title=bool(facts.get("title")), evaluate=True,
                                      links=bool(facts["links"]), phase="link_extract")
                    diagnostic["redirects"] = list(dict.fromkeys([url, final_url, facts["url"]]))
                    errors = []
                    if page.navigation_error:
                        errors.append(page.navigation_error.diagnostic())
                    # REST diagnostics never replace the visibility-filtered DOM links.
                    for phase, operation in (("link_extract", self.browser.get_links), ("snapshot", self.browser.get_snapshot)):
                        diagnostic["phase"] = phase
                        try:
                            observed = await asyncio.wait_for(operation(page), timeout=3)
                            if phase == "snapshot":
                                if not isinstance(observed, dict) or not isinstance(observed.get("snapshot"), str):
                                    raise BrowserError("browser_protocol_error", phase="snapshot")
                                snapshot_url = await self.validate(observed.get("url", ""))
                                if domain(snapshot_url) != domain(url):
                                    raise BrowserError("external_redirect", phase="redirect_validation")
                                diagnostic["snapshot"] = bool(observed.get("snapshot"))
                        except (BrowserError, asyncio.TimeoutError) as exc:
                            if isinstance(exc, BrowserError) and exc.code in {"unsafe_navigation", "external_redirect", "browser_blocked", "browser_tls_error"}:
                                raise
                            errors.append(exc.diagnostic() if isinstance(exc, BrowserError) else dict(code="browser_snapshot_timeout" if phase == "snapshot" else "browser_timeout", phase=phase))
                    if errors or readiness["status"] != "ready":
                        facts["complete"] = False
                        record["status"] = "partial"
                        diagnostic["error_code"] = errors[0]["code"] if errors else readiness["reason"]
                        diagnostic["error_phase"] = errors[0].get("phase") if errors else "render_settle" if readiness["reason"] == "browser_render_timeout" else "evaluate"
                    else:
                        record["status"] = "completed"
                    diagnostic["operations_failed"] = errors
                    findings, contacts = detect(facts, record)
                    result["evidence"] += findings
                    result["contacts"] += contacts
                    result["final_url"] = result["final_url"] or record["final_url"]
                    if page_type == "homepage":
                        base = record["final_url"]
                        diagnostic["phase"] = "page_select"
                        pending = selected_links(facts["links"], base, self.settings.pages)
                        await self._mobile(page, record, result)
                    if cancelled():
                        result.update(status="cancelled", error_code="cancelled")
                        stop = True
                    elif self.settings.screenshots and page_type in {"homepage", "contact"}:
                        diagnostic["phase"] = "snapshot"
                        await self._screenshot(page, record)
                    diagnostic["status"] = record["status"]
                    break
                except BrowserError as exc:
                    diagnostic.update(getattr(exc, "observation", {}))
                    diagnostic.update(error_code=exc.code, phase=exc.phase or diagnostic["phase"], http_status=exc.http_status,
                                      status="blocked" if exc.code == "browser_blocked" else "failed")
                    # Retry only known transient failures, only before useful DOM,
                    # and only after confirmed cleanup of the previous context.
                    can_retry = (attempt == 1 and recover_session is not None and not diagnostic["dom"] and not cancelled()
                                 and exc.retryable and exc.code in {"browser_session_lost", "browser_connection_reset", "browser_navigation_timeout", "browser_protocol_error"})
                    if can_retry:
                        diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                        persist()
                        await asyncio.sleep(.3)
                        if cancelled():
                            result.update(status="cancelled", error_code="cancelled"); stop = True; break
                        try:
                            replacement = await recover_session(session)
                        except BrowserError as recovery_error:
                            replacement = None
                            diagnostic["recovery_error"] = recovery_error.diagnostic()
                        if replacement is not None:
                            session, page = replacement, None
                            diagnostic["retry_scheduled"] = True
                            continue
                    useful = any(e["page_id"] == record["id"] and e["status"] == "present" for e in result["evidence"])
                    record["status"] = "partial" if useful else diagnostic["status"]
                    if not useful:
                        result["evidence"] += [evidence(key, diagnostic["status"], url=url, page_type=page_type, page_id=record["id"]) for key in KEYS]
                    stop = exc.code in {"browser_blocked", "unsafe_navigation", "external_redirect", "browser_tls_error", "browser_unavailable", "browser_session_lost", "browser_parking", "browser_maintenance", "browser_javascript_required"}
                    break
                finally:
                    diagnostic["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                    if page is not None:
                        try:
                            await asyncio.wait_for(self.browser.close_page(page), timeout=8)
                        except (BrowserError, asyncio.TimeoutError) as cleanup_error:
                            code = cleanup_error.code if isinstance(cleanup_error, BrowserError) else "browser_cleanup_timeout"
                            diagnostic["cleanup_error"] = code
                            if record["status"] == "completed":
                                record["status"] = "partial"
                                diagnostic.update(status="partial", error_code=code, error_phase="cleanup")
                    persist()
            record["navigation_ms"] = sum(d["elapsed_ms"] for d in record["attempts"])
            record["error_code"] = record["attempts"][-1].get("error_code")
            if record["status"] == "partial":
                # Including a failed later screenshot/viewport operation: preserve
                # positives while preventing absence from incomplete observations.
                for row in result["evidence"]:
                    if row["page_id"] == record["id"] and row["status"] == "absent":
                        row.update(status="unknown", confidence=0)
        if result["status"] != "cancelled":
            statuses = [p["status"] for p in result["pages"]]
            useful = any(s in {"completed", "partial"} for s in statuses)
            result["status"] = "completed" if statuses and all(s == "completed" for s in statuses) else "partial" if useful else "blocked" if "blocked" in statuses else "failed"
            result["error_code"] = next((p.get("error_code") for p in result["pages"] if p["status"] != "completed" and p.get("error_code")), None)
            if result["status"] == "partial" and not result["error_code"]: result["error_code"] = "audit_incomplete"
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
            if not await self.browser.set_viewport(page, 390, 844):
                raise BrowserError("browser_protocol_error", phase="viewport")
            else:
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
            if exc.phase is None: exc.phase = "viewport"
            if exc.code in {"unsafe_navigation", "external_redirect", "browser_session_lost"}:
                raise
            record["status"] = "partial"
            record["attempts"][-1]["operations_failed"].append(exc.diagnostic())
            record["attempts"][-1]["error_code"] = exc.code
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
