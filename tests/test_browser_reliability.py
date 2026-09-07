import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch
from dataclasses import replace
from browser.base import BrowserError
from browser.camofox import CamoFoxProvider
from browser.mock import MockBrowserProvider
from audit_engine.runner import AuditEngine, EXTRACT
from audit_engine.readiness import observe
from audit_engine.scoring import score_audit
from audit_engine.detectors import aggregate
from engine_config import EngineConfig
from engine_worker import PersistentWorker
from tests.engine_fixtures import FixtureStore, FixtureSource, facts, business

URL = "https://business.test/"
VALIDATE = AsyncMock(side_effect=lambda url: url)


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def read(self, values):
        browser = MockBrowserProvider({URL: facts()})
        session = await browser.open_session()
        page = await browser.open_page(session, URL)
        browser.evaluate = AsyncMock(side_effect=values)
        result = await observe(browser, page, EXTRACT, 500, VALIDATE, "business.test")
        return result

    async def test_complete_requires_two_stable_samples(self):
        f = facts(body_available=True, text_length=300, link_count=2)
        _, d = await self.read([f, copy.deepcopy(f)])
        self.assertEqual(d["status"], "ready")
        self.assertEqual(len(d["samples"]), 2)

    async def test_arrington_interactive_preserves_content_but_no_absence(self):
        f = facts(ready_state="interactive", complete=False, body_available=True, text_length=7201, link_count=112)
        out, d = await self.read([f, copy.deepcopy(f)])
        self.assertEqual((out["complete"], d["status"], d["reason"]), (False, "partial", "browser_render_timeout"))

    async def test_changing_complete_dom_is_partial(self):
        out, d = await self.read([facts(text_length=100, link_count=1), facts(text_length=200, link_count=2)])
        self.assertFalse(out["complete"])
        self.assertEqual(d["status"], "partial")

    async def test_later_evaluate_timeout_preserves_previous_facts(self):
        out, d = await self.read([facts(), BrowserError("browser_evaluate_timeout")])
        self.assertEqual(d["status"], "partial")
        self.assertEqual(d["reason"], "browser_evaluate_timeout")
        self.assertFalse(out["complete"])

    async def test_missing_forms_input_preserves_visible_phone(self):
        f = facts(forms=None, contacts=[dict(type="phone", kind="tel", value="tel:5125551234")])
        out, d = await self.read([f, copy.deepcopy(f)])
        self.assertEqual(d["status"], "partial")
        from audit_engine.detectors import detect
        rows, contacts = detect(out, dict(id="page", final_url=URL, page_type="homepage"))
        self.assertEqual(len(contacts), 1)
        self.assertEqual(aggregate(rows, False)["contact_form"]["status"], "unknown")

    async def test_no_usable_dom_fails(self):
        with self.assertRaises(BrowserError) as caught:
            await self.read([facts(ready_state="loading", body_available=False, text_length=0), facts(ready_state="loading", body_available=False, text_length=0)])
        self.assertEqual(caught.exception.code, "browser_dom_timeout")

    async def test_soft_errors_and_cross_domain_stop(self):
        for code in ("browser_blocked", "browser_maintenance", "browser_parking", "browser_javascript_required"):
            with self.assertRaises(BrowserError) as caught:
                await self.read([facts(soft_error=code)])
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(BrowserError) as caught:
            await self.read([facts("https://unverified.test/")])
        self.assertEqual(caught.exception.code, "external_redirect")


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def audit(self, browser):
        session = await browser.open_session()
        try:
            return await AuditEngine(browser, EngineConfig(settle_ms=0, readiness_ms=500), validate=VALIDATE).run(business(), session)
        finally:
            await browser.close_session(session)

    async def test_snapshot_failure_keeps_contacts_and_marks_partial(self):
        browser = MockBrowserProvider({URL: facts(contacts=[dict(type="phone", kind="tel", value="tel:5125551234")])})
        browser.get_snapshot = AsyncMock(side_effect=BrowserError("browser_snapshot_timeout", phase="snapshot"))
        result = await self.audit(browser)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["contacts"]), 1)
        self.assertFalse(any(e["status"] == "absent" for e in result["evidence"]))
        self.assertEqual(result["pages"][0]["attempts"][0]["operations_failed"][0]["phase"], "snapshot")

    async def test_unavailable_viewport_and_malformed_snapshot_are_partial(self):
        browser = MockBrowserProvider({URL: facts()})
        browser.set_viewport = AsyncMock(return_value=False)
        browser.get_snapshot = AsyncMock(return_value=None)
        result = await self.audit(browser)
        self.assertEqual(result["status"], "partial")
        self.assertFalse(any(e["status"] == "absent" for e in result["evidence"]))
        self.assertTrue(any(e["status"] == "present" for e in result["evidence"]))

    async def test_screenshot_failure_keeps_already_collected_evidence(self):
        browser = MockBrowserProvider({URL: facts()})
        browser.screenshot = AsyncMock(side_effect=BrowserError("browser_snapshot_timeout"))
        engine = AuditEngine(browser, EngineConfig(settle_ms=0, readiness_ms=500, screenshots=True), validate=VALIDATE)
        session = await browser.open_session()
        result = await engine.run(business(), session)
        await browser.close_session(session)
        self.assertEqual(result["status"], "partial")
        self.assertTrue(any(e["status"] == "present" for e in result["evidence"]))
        self.assertFalse(any(e["status"] == "absent" for e in result["evidence"]))

    async def test_recovered_navigation_preserves_partial_without_replay(self):
        browser = MockBrowserProvider({URL: facts()})
        original = browser.open_page
        async def open_page(session, url):
            page = await original(session, url)
            page.navigation_error = BrowserError("browser_navigation_timeout", phase="initial_navigation")
            return page
        browser.open_page = open_page
        result = await self.audit(browser)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(browser.visited), 1)

    def test_confidence_version_partial_half_credit_does_not_tune_opportunity(self):
        from audit_engine.detectors import evidence
        from audit_engine.scoring import WEIGHTS
        a = dict(status="completed", pages=[dict(status="completed")], contacts=[], evidence=[evidence(k,"present",True) for k in WEIGHTS if k != "pagespeed"])
        first = score_audit(business(), a)
        a["status"] = "partial"; a["pages"][0]["status"] = "partial"
        second = score_audit(business(), a)
        self.assertEqual(first["opportunity_score"], second["opportunity_score"])
        self.assertAlmostEqual(first["evidence_confidence"] / 2, second["evidence_confidence"], places=1)
        self.assertEqual(second["breakdown"]["evidence_confidence_version"], "render_coverage_v2")

    def test_allowlisted_taxonomy_redacts_and_denials_never_retry(self):
        for phase, code in [("tab_create","browser_tab_timeout"),("initial_navigation","browser_navigation_timeout"),("evaluate","browser_evaluate_timeout"),("snapshot","browser_snapshot_timeout"),("cleanup","browser_cleanup_timeout"),("connect","browser_connect_timeout")]:
            error = CamoFoxProvider.response_error(504, {"error":"SECRET timed out"}, phase)
            self.assertEqual(error.code, code)
            self.assertEqual(error.phase, phase)
            self.assertNotIn("SECRET", str(error))
        for status, body, code in [(403,{},"browser_unavailable"),(429,{},"browser_blocked"),(502,{"code":"ssl_error"},"browser_tls_error"),(500,{"error":"captcha SECRET"},"browser_blocked"),(500,{},"browser_navigation_failed")]:
            error = CamoFoxProvider.response_error(status, body, "initial_navigation")
            self.assertEqual(error.code, code); self.assertFalse(error.retryable)
        error = CamoFoxProvider.response_error(500, {"error":"page.goto: NS_ERROR_NET_RESET SECRET"}, "initial_navigation")
        self.assertEqual(error.code, "browser_connection_reset"); self.assertTrue(error.retryable)


class RetryPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def run_worker(self, failure, repeat=False, cleanup_error=False):
        fixture = FixtureStore(); self.addCleanup(fixture.close)
        browser = MockBrowserProvider({URL: facts()})
        original = browser.open_page
        calls = []
        async def open_page(session, url):
            calls.append(session.user_id)
            if repeat or len(calls) == 1: raise failure
            return await original(session,url)
        browser.open_page = open_page
        if cleanup_error: browser.close_session = AsyncMock(side_effect=BrowserError("browser_cleanup_timeout"))
        settings = EngineConfig(settle_ms=0, readiness_ms=500)
        worker = PersistentWorker(fixture.store, settings, browser, [FixtureSource()], AuditEngine(browser,settings,validate=VALIDATE))
        job = fixture.job()
        await worker.run_once()
        item = fixture.store.items(job["id"],"alice")[0]
        detail = fixture.store.detail(item["business_id"],"alice")
        return fixture, browser, calls, item, detail

    async def test_session_restart_retry_uses_fresh_ids_and_persists_two_attempts(self):
        fixture, browser, calls, item, detail = await self.run_worker(BrowserError("browser_session_lost",phase="initial_navigation",retryable=True))
        self.assertEqual(item["status"], "completed")
        self.assertEqual(len(set(calls)), 2)
        self.assertEqual(len(detail["navigation"]), 2)
        self.assertEqual(len(browser.closed_sessions), 2)
        self.assertFalse(browser.sessions)
        self.assertEqual(fixture.store.pending_cleanup(), [])
        self.assertIsNone(fixture.store.detail(item["business_id"], "bob"))
        with fixture.store.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM lead_scores").fetchone()[0],1)

    async def test_reilly_timeout_and_legends_reset_retry_are_bounded(self):
        for code in ("browser_navigation_timeout", "browser_connection_reset"):
            _, browser, calls, item, detail = await self.run_worker(BrowserError(code, phase="initial_navigation",retryable=True), repeat=True)
            self.assertEqual(len(calls),2)
            self.assertEqual(item["status"],"failed")
            self.assertIsNone(detail["score"]["digital_gap"])
            self.assertFalse(browser.sessions)

    async def test_denial_tls_unsafe_and_unknown_failures_are_not_retried(self):
        for code in ("browser_blocked", "browser_tls_error", "unsafe_navigation", "external_redirect", "browser_navigation_failed", "browser_tab_timeout"):
            _, _, calls, _, _ = await self.run_worker(BrowserError(code, retryable=True))
            self.assertEqual(len(calls),1)

    async def test_cleanup_failure_prevents_session_replacement(self):
        fixture, _, calls, _, _ = await self.run_worker(BrowserError("browser_session_lost",retryable=True), cleanup_error=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(len(fixture.store.pending_cleanup()),1)


    async def test_attempt_is_durable_before_browser_call_and_survives_restart(self):
        fixture=FixtureStore(); self.addCleanup(fixture.close)
        browser=MockBrowserProvider({URL:facts()})
        settings=EngineConfig(settle_ms=0, readiness_ms=500)
        worker=PersistentWorker(fixture.store,settings,browser,[FixtureSource()],AuditEngine(browser,settings,validate=VALIDATE))
        started=asyncio.Event()
        async def interrupted(session,url):
            with fixture.store.transaction() as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM audit_navigation_attempts").fetchone()[0],1)
            started.set()
            await asyncio.Event().wait()
        browser.open_page=interrupted
        job=fixture.job()
        task=asyncio.create_task(worker.run_once())
        await asyncio.wait_for(started.wait(),2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertFalse(browser.sessions)
        fresh=PersistentWorker(fixture.store,settings,browser,[FixtureSource()],AuditEngine(browser,settings,validate=VALIDATE))
        browser.open_page=MockBrowserProvider.open_page.__get__(browser)
        await fresh.run_once()
        with fixture.store.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM audit_navigation_attempts").fetchone()[0],2)
            self.assertEqual(conn.execute("SELECT count(*) FROM lead_scores").fetchone()[0],1)
        self.assertEqual(fixture.store.job(job["id"])["processed_count"],1)

    async def test_cancel_during_backoff_prevents_second_navigation(self):
        browser=MockBrowserProvider({URL:facts()})
        browser.open_page=AsyncMock(side_effect=BrowserError("browser_session_lost",retryable=True))
        session=await browser.open_session()
        cancel=False
        async def backoff(delay):
            nonlocal cancel
            cancel=True
        recover=AsyncMock()
        with patch("audit_engine.runner.asyncio.sleep",side_effect=backoff):
            result=await AuditEngine(browser,EngineConfig(),validate=VALIDATE).run(business(),session,cancelled=lambda:cancel,recover_session=recover)
        self.assertEqual(result["status"],"cancelled")
        self.assertEqual(browser.open_page.await_count,1)
        recover.assert_not_awaited()
        await browser.close_session(session)
