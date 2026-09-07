"""Bounded rendered-DOM observations; never wait for network idle."""
import asyncio
import time
from browser.base import BrowserError

ARRAYS = ("links", "contacts", "forms", "ctas", "resources")


async def observe(browser, page, expression, timeout_ms, validate, expected_domain):
    from engine_store import domain
    end = time.monotonic() + timeout_ms / 1000
    previous, latest, samples = None, None, []
    reason = "browser_dom_timeout"
    while time.monotonic() < end and len(samples) < 8:
        try:
            facts = await asyncio.wait_for(browser.evaluate(page, expression), max(.01, end - time.monotonic()))
            if not isinstance(facts, dict) or not isinstance(facts.get("url"), str):
                raise BrowserError("browser_protocol_error", phase="evaluate")
            final = await validate(facts["url"])
            if domain(final) != expected_domain:
                raise BrowserError("external_redirect", phase="redirect_validation")
            facts["url"] = final
            # A missing detector input makes negative findings unknown, but does
            # not discard unrelated, valid positive contacts/forms/links.
            invalid = []
            for key in ARRAYS:
                if not isinstance(facts.get(key), list) or not all(isinstance(x, str if key == "resources" else dict) for x in facts[key]):
                    invalid.append(key)
                    facts[key] = []
            state = facts.get("ready_state")
            body = facts.get("body_available", state in {"interactive", "complete"})
            text_size = facts.get("text_length", 100 if body else 0)
            links = facts.get("link_count", len(facts["links"]))
            if not isinstance(text_size, int) or not isinstance(links, int):
                raise BrowserError("browser_protocol_error", phase="evaluate")
            usable = body and text_size >= 40 and state in {"interactive", "complete"}
            sample = dict(ready_state=state if state in {"loading", "interactive", "complete"} else "unknown",
                          body=bool(body), text_length=min(max(text_size, 0), 150000),
                          link_count=min(max(links, 0), 10000), title=bool(facts.get("title")),
                          invalid_inputs=invalid, limits_reached=bool(facts.get("limits_reached")))
            samples.append(sample)
            if facts.get("blocked") or facts.get("login_wall") or facts.get("soft_error"):
                error = BrowserError(facts.get("soft_error") or "browser_blocked", phase="dom_ready")
                error.observation = dict(dom=bool(body), title=bool(facts.get("title")), links=bool(facts["links"]), evaluate=True,
                                         soft_error_excerpt=str(facts.get("soft_error_excerpt") or "")[:240])
                raise error
            status = facts.get("http_status")
            if isinstance(status, int) and status >= 400:
                raise BrowserError("browser_blocked" if status in (401, 403, 429) else "browser_navigation_failed",
                                   phase="initial_navigation", http_status=status)
            if usable:
                latest = facts
                stable = previous is not None and links == previous[1] and abs(text_size - previous[0]) <= max(20, previous[0] * .02)
                if stable and state == "complete" and facts.get("complete") and not invalid:
                    return facts, dict(status="ready", reason=None, samples=samples)
                reason = "browser_protocol_error" if invalid else "audit_incomplete" if facts.get("limits_reached") else "browser_render_timeout"
            previous = (text_size, links)
        except (BrowserError, asyncio.TimeoutError) as exc:
            if isinstance(exc, BrowserError) and exc.code in {"browser_blocked", "browser_maintenance", "browser_parking", "browser_javascript_required", "unsafe_navigation", "external_redirect", "browser_tls_error"}:
                raise
            reason = exc.code if isinstance(exc, BrowserError) else "browser_evaluate_timeout"
            break
        await asyncio.sleep(min(.4, max(0, end - time.monotonic())))
    if latest is not None:
        latest["complete"] = False
        return latest, dict(status="partial", reason=reason, samples=samples)
    raise BrowserError(reason, phase="dom_ready" if reason == "browser_dom_timeout" else "evaluate")
