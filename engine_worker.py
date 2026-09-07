"""Single persistent worker with leased claims and bounded concurrent audits."""
import asyncio
import json
import logging
import time
from contextlib import suppress
from browser.base import BrowserError, BrowserSession
from audit_engine.runner import AuditEngine
from audit_engine.scoring import score_audit
from audit_engine.detectors import KEYS, evidence
from discovery import DiscoveryError, configured_sources
from engine_store import uid, LeaseLost

log = logging.getLogger("evidence_worker")


def event(phase, *, jid=None, item=None, bid=None, rid=None, provider=None, code=None, elapsed=None):
    # Only opaque identifiers and fixed phase/error names; no exception text or URLs.
    log.info(json.dumps(dict(phase=phase, job_id=jid, item_id=item, business_id=bid,
                            audit_run_id=rid, provider=provider, error_code=code,
                            elapsed_ms=round(elapsed * 1000) if elapsed is not None else None)))


class PersistentWorker:
    def __init__(self, store, settings, browser=None, sources=None, audit=None):
        self.store, self.settings = store, settings
        self.browser = browser or settings.browser()
        self.sources = sources  # None resolves current configuration at job start.
        self.audit = audit or AuditEngine(self.browser, settings)
        self.id = uid()
        self.task = None
        self.wake = None
        self._last_cleanup = 0

    def start(self):
        if self.task is None or self.task.done():
            self.wake = asyncio.Event()
            self.task = asyncio.create_task(self._loop())

    def notify(self):
        if self.wake:
            self.wake.set()

    async def shutdown(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        await self.browser.shutdown()

    async def _loop(self):
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                event("worker_loop", code="internal_error")
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    async def run_once(self):
        jid = self.store.claim_job(self.id)
        if not jid:
            await self.cleanup_orphans()
            return False
        heartbeat = asyncio.create_task(self._heartbeat(jid))
        try:
            # Keep the lease alive while cleaning recovered contexts.
            await self.cleanup_orphans()
            await self._discover(jid)
            tasks = [asyncio.create_task(self._items(jid)) for _ in range(self.settings.concurrency)]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            self.store.finish_job(jid, self.id)
        except asyncio.CancelledError:
            with suppress(LeaseLost):
                self.store.release(jid, self.id)
            raise
        except LeaseLost:
            event("lease_lost", jid=jid, code="worker_interrupted")
        except Exception as exc:
            code = exc.code if isinstance(exc, (BrowserError, DiscoveryError)) else "internal_error"
            event("job_failed", jid=jid, code=code)
            with suppress(LeaseLost):
                self.store.finish_job(jid, self.id, code)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, LeaseLost):
                await heartbeat
        return True

    async def _heartbeat(self, jid):
        while True:
            await asyncio.sleep(10)
            self.store.heartbeat(jid, self.id)

    def cancelled(self, jid):
        job = self.store.job(jid)
        return job is None or bool(job["cancel_requested"]) or job["status"] != "running"

    async def _discover(self, jid):
        states, done = self.store.discovery_state(jid)
        if done or self.cancelled(jid):
            return
        sources = self.sources if self.sources is not None else configured_sources()
        if not sources:
            raise DiscoveryError("provider_unavailable")
        job = self.store.job(jid)
        error = job["error_code"]
        for source in sources:
            state = states.get(source.name, {"pages": 0, "cursor": None, "done": False})
            max_pages = min(self.settings.discovery_pages, 3 if source.name == "google_places" else 5)
            while not state["done"] and state["pages"] < max_pages:
                job = self.store.job(jid)
                remaining = job["target_count"] - job["discovered_count"]
                if self.cancelled(jid) or remaining <= 0:
                    break
                try:
                    page = await source.fetch_page(job, state["cursor"], min(20, remaining), lambda: self.cancelled(jid))
                    state = {"pages": state["pages"] + 1, "cursor": page.cursor, "done": page.cursor is None}
                    error = error if error not in (None, "discovery_exhausted") else page.terminal_reason or error
                    if state["pages"] >= max_pages and not state["done"]:
                        state["done"], error = True, "provider_limit"
                    states[source.name] = state
                    self.store.save_discovery(jid, self.id, page.records, states, error=error)
                except DiscoveryError as exc:
                    error = exc.code
                    state["done"] = True
                    states[source.name] = state
                    self.store.save_discovery(jid, self.id, [], states, error=error)
                    event("discovery", jid=jid, provider=source.name, code=error)
            if self.cancelled(jid) or self.store.job(jid)["discovered_count"] >= job["target_count"]:
                break
        job = self.store.job(jid)
        shortfall = job["discovered_count"] < job["target_count"]
        self.store.save_discovery(jid, self.id, [], states, done=True,
                                  error=(error or "discovery_exhausted") if shortfall else None)

    async def _items(self, jid):
        while not self.cancelled(jid):
            item = self.store.claim_item(jid, self.id)
            if not item:
                return
            business = self.store.business(item["business_id"])
            business["provider_source_url"] = item.get("source_url") or ""
            session, rid = None, None
            started = time.monotonic()
            try:
                session = await self.browser.open_session()
                rid = self.store.start_run(item, self.id, self.browser, session)
                result = await self.audit.run(business, session, cancelled=lambda: self.cancelled(jid))
                score = score_audit(business, result)
                self.store.finish_run(jid, item, self.id, rid, result, score)
                event("audit_finished", jid=jid, item=item["id"], bid=business["id"], rid=rid, provider=self.browser.name, code=result.get("error_code"), elapsed=time.monotonic() - started)
            except asyncio.CancelledError:
                raise
            except LeaseLost:
                raise
            except Exception as exc:
                if rid is None:
                    raise
                code = exc.code if isinstance(exc, BrowserError) else "internal_error"
                result = dict(status="failed", error_code=code, pages=[], contacts=[], evidence=[evidence(k, "failed") for k in KEYS])
                self.store.finish_run(jid, item, self.id, rid, result, score_audit(business, result))
                event("audit_failed", jid=jid, item=item["id"], bid=business["id"], rid=rid, provider=self.browser.name, code=code, elapsed=time.monotonic() - started)
            finally:
                if session is not None:
                    await self._cleanup(rid, session)

    async def _cleanup(self, rid, session):
        try:
            await asyncio.wait_for(self.browser.close_session(session), timeout=8)
            if rid is not None:
                self.store.cleaned(rid)
        except (BrowserError, asyncio.TimeoutError):
            event("session_cleanup_pending", rid=rid, provider=self.browser.name, code="browser_unavailable")

    async def cleanup_orphans(self):
        # A down service is not hammered once per orphan on every poll.
        if time.monotonic() - self._last_cleanup < 10:
            return
        pending = self.store.pending_cleanup()
        if not pending:
            return
        self._last_cleanup = time.monotonic()
        if not (await self.browser.health()).available:
            return
        for run in pending[:5]:
            await self._cleanup(run["id"], BrowserSession(run["browser_user_id"], run["browser_session_key"]))
