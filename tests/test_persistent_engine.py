import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import unittest
from unittest.mock import AsyncMock, patch
from engine_store import EngineStore, LeaseLost
from engine_worker import PersistentWorker
from engine_config import EngineConfig
from audit_engine.runner import AuditEngine
from browser.mock import MockBrowserProvider
from browser.base import BrowserError
from discovery import DiscoveryPage, ProviderDiscovery, record, website
from tests.engine_fixtures import FixtureStore, FixtureSource, business, facts


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureStore(); self.addCleanup(self.fixture.close)
        self.store = self.fixture.store

    def test_job_restart_ownership_claim_and_cancel(self):
        job = self.fixture.job()
        restored = EngineStore(self.fixture.path)
        self.assertEqual(restored.job(job["id"], "alice")["status"], "queued")
        self.assertIsNone(restored.job(job["id"], "bob"))
        self.assertIsNone(restored.cancel(job["id"], "bob"))
        self.assertEqual(restored.claim_job("worker"), job["id"])
        self.assertIsNone(self.store.claim_job("other-worker"))
        self.store.heartbeat(job["id"], "worker")
        self.assertTrue(restored.job(job["id"])["heartbeat_at"])
        self.store.cancel(job["id"], "alice")
        self.store.finish_job(job["id"], "worker")
        self.assertEqual(restored.job(job["id"])["status"], "cancelled")

    def test_transactional_no_double_claim_with_two_local_workers(self):
        job = self.fixture.job()
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(self.store.claim_job, ["one", "two"]))
        self.assertEqual(values.count(job["id"]), 1)
        winner = "one" if values[0] else "two"
        self.store.save_discovery(job["id"], winner, [business()], {})
        with ThreadPoolExecutor(2) as pool:
            items = list(pool.map(lambda _: self.store.claim_item(job["id"], winner), range(2)))
        self.assertEqual(sum(item is not None for item in items), 1)

    def test_dedupe_sources_preserve_physical_branches(self):
        job = self.fixture.job(target_count=5)
        self.store.claim_job("worker")
        same = business(provider="other", provider_record_id="other-1")
        branch = business(2, canonical_name="Business 1", website_url="https://business.test/")
        self.store.save_discovery(job["id"], "worker", [business(), business(), same, branch], {})
        self.assertEqual(self.store.job(job["id"])["discovered_count"], 2)
        with self.store.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM business_sources").fetchone()[0], 3)

    def test_phone_format_aliases_dedupe_when_address_is_missing(self):
        from engine_store import identity
        a = business(address='', provider_phone='+1 (512) 555-1234')
        b = business(address='', provider_phone='512-555-1234')
        self.assertEqual(identity(a), identity(b))

    def test_queued_cancel_survives_restart_and_pending_items_cancel(self):
        job = self.fixture.job()
        self.store.cancel(job["id"], "alice")
        self.assertEqual(EngineStore(self.fixture.path).job(job["id"])["status"], "cancelled")
        self.assertIsNone(self.store.claim_job("worker"))

    def test_stale_recovery_fences_old_worker_and_preserves_running_history(self):
        job = self.fixture.job()
        self.store.claim_job("old")
        self.store.save_discovery(job["id"], "old", [business()], {})
        item = self.store.claim_item(job["id"], "old")
        from browser.base import BrowserSession
        rid = self.store.start_run(item, "old", MockBrowserProvider(), BrowserSession("orphan", "key"))
        with self.store.transaction(True) as conn:
            conn.execute("UPDATE search_jobs SET lease_until=0 WHERE id=?", (job["id"],))
        self.assertEqual(self.store.claim_job("new"), job["id"])
        with self.assertRaises(LeaseLost):
            self.store.heartbeat(job["id"], "old")
        self.assertEqual(self.store.items(job["id"], "alice")[0]["status"], "pending")
        self.assertEqual(self.store.pending_cleanup()[0]["id"], rid)
        with self.store.transaction() as conn:
            run = conn.execute("SELECT * FROM audit_runs WHERE id=?", (rid,)).fetchone()
            self.assertEqual((run["status"], run["error_code"]), ("failed", "worker_interrupted"))


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fixture = FixtureStore(); self.addCleanup(self.fixture.close)
        self.store = self.fixture.store
        self.settings = EngineConfig(settle_ms=0)

    def worker(self, browser=None, sources=None, audit=None):
        browser = browser or MockBrowserProvider({"https://business.test/": facts()})
        audit = audit or AuditEngine(browser, self.settings, validate=AsyncMock(side_effect=lambda x: x))
        return PersistentWorker(self.store, self.settings, browser, sources or [FixtureSource()], audit)

    async def test_complete_progress_evidence_scores_history_and_restart(self):
        worker = self.worker()
        first = self.fixture.job()
        await worker.run_once()
        self.assertEqual(self.store.job(first["id"])["status"], "completed")
        second = self.fixture.job()
        await worker.run_once()
        restored = EngineStore(self.fixture.path)
        self.assertEqual(restored.job(second["id"])["processed_count"], 1)
        ids, count = restored.result_ids("alice")
        self.assertEqual(count, 1)
        detail = restored.detail(ids[0], "alice")
        self.assertEqual(len(detail["history"]), 2)
        self.assertTrue(detail["evidence"])
        self.assertIsNotNone(detail["score"])
        self.assertFalse(self.store.pending_cleanup())
        self.assertFalse(worker.browser.sessions)
        with restored.transaction() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM lead_scores").fetchone()[0], 2)
        self.assertIsNone(restored.detail(ids[0], "bob"))

    async def test_pagination_partial_exhaustion_and_no_website(self):
        source = FixtureSource([DiscoveryPage([business()], 1), DiscoveryPage([business(), business(2, website_url="")], terminal_reason="discovery_exhausted")])
        job = self.fixture.job(target_count=5)
        worker = self.worker(sources=[source])
        await worker.run_once()
        state = self.store.job(job["id"])
        self.assertEqual((state["status"], state["discovered_count"], state["processed_count"]), ("partial", 2, 2))
        self.assertEqual(state["error_code"], "discovery_exhausted")
        self.assertEqual(source.calls, [None, 1])
        self.assertEqual(len(worker.browser.visited), 1)
        self.assertIn("skipped", [i["status"] for i in self.store.items(job["id"], "alice")])

    async def test_restart_after_one_source_finished_resumes_the_next_source(self):
        job = self.fixture.job(target_count=2)
        self.store.claim_job('old')
        self.store.save_discovery(job['id'], 'old', [business()],
            {'fixture': {'pages': 1, 'cursor': None, 'done': True}}, error='provider_limit')
        self.store.release(job['id'], 'old')
        first = FixtureSource()
        second = FixtureSource([DiscoveryPage([business(2)], terminal_reason='discovery_exhausted')])
        second.name = 'second'
        worker = self.worker(sources=[first, second])
        await worker.run_once()
        self.assertEqual(first.calls, [])
        self.assertEqual(second.calls, [None])
        self.assertEqual(self.store.job(job['id'])['status'], 'completed')

    async def test_partial_audit_is_not_a_completed_job_even_with_enough_evidence(self):
        job = self.fixture.job()
        f = facts(complete=False, ctas=[{'text': 'Contact and request a quote', 'href': 'tel:+15125551234'}])
        browser = MockBrowserProvider({'https://business.test/': f})
        await self.worker(browser).run_once()
        self.assertEqual(self.store.job(job['id'])['qualified_count'], 1)
        self.assertEqual(self.store.job(job['id'])['status'], 'partial')

    async def test_target_cap_does_not_overshoot_or_repeat_pages(self):
        source = FixtureSource([DiscoveryPage([business(i) for i in range(10)], 1)])
        job = self.fixture.job(target_count=2)
        worker = self.worker(sources=[source])
        await worker.run_once()
        self.assertEqual(self.store.job(job["id"])["discovered_count"], 2)
        self.assertEqual(len(source.calls), 1)

    async def test_browser_unavailable_creates_failed_history_without_fake_gap(self):
        job = self.fixture.job()
        worker = self.worker(browser=MockBrowserProvider(available=False))
        await worker.run_once()
        item = self.store.items(job["id"], "alice")[0]
        self.assertEqual(item["error_code"], "browser_unavailable")
        detail = self.store.detail(item["business_id"], "alice")
        self.assertEqual(detail["audit"]["status"], "failed")
        self.assertIsNone(detail["score"]["opportunity_score"])
        self.assertFalse(worker.browser.sessions)

    async def test_user_cancel_closes_active_sessions_and_marks_pending(self):
        job = self.fixture.job(target_count=3)
        browser = MockBrowserProvider({"https://business.test/": facts()})
        engine = AuditEngine(browser, self.settings, validate=AsyncMock(side_effect=lambda x: x))
        original = browser.evaluate
        async def evaluate(page, expression):
            self.store.cancel(job["id"], "alice")
            return await original(page, expression)
        browser.evaluate = evaluate
        worker = self.worker(browser, [FixtureSource([DiscoveryPage([business(i) for i in range(3)])])], engine)
        await worker.run_once()
        self.assertEqual(self.store.job(job["id"])["status"], "cancelled")
        self.assertFalse(browser.sessions)
        self.assertTrue(all(i["status"] == "cancelled" for i in self.store.items(job["id"], "alice")))

    async def test_shutdown_interrupt_resumes_without_rerunning_completed_items(self):
        job = self.fixture.job(target_count=2)
        started = asyncio.Event()
        class InterruptedAudit:
            async def run(self, *args, **kwargs):
                started.set()
                await asyncio.Event().wait()
        browser = MockBrowserProvider({"https://business.test/": facts()})
        worker = self.worker(browser, [FixtureSource([DiscoveryPage([business(1), business(2)])])], InterruptedAudit())
        task = asyncio.create_task(worker.run_once())
        await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertFalse(browser.sessions)
        self.assertEqual(self.store.job(job["id"])["status"], "queued")
        resumed = self.worker()
        await resumed.run_once()
        self.assertEqual(self.store.job(job["id"])["status"], "completed")
        self.assertEqual(len(resumed.browser.visited), 2)

    async def test_orphan_cleanup_after_service_recovery(self):
        job = self.fixture.job()
        self.store.claim_job("old")
        self.store.save_discovery(job["id"], "old", [business()], {}, done=True)
        item = self.store.claim_item(job["id"], "old")
        browser = MockBrowserProvider({"https://business.test/": facts()})
        session = await browser.open_session()
        await browser.open_page(session, "https://business.test/")
        self.store.start_run(item, "old", browser, session)
        with self.store.transaction(True) as conn:
            conn.execute("UPDATE search_jobs SET lease_until=0")
        await self.worker(browser).run_once()
        self.assertIn(session.user_id, browser.closed_sessions)
        self.assertFalse(self.store.pending_cleanup())


class DiscoveryContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_yelp_pagination_never_treats_listing_as_website(self):
        source = ProviderDiscovery("yelp", "not-real-key")
        data = {"total": 42, "businesses": [{"id": "x", "name": "Plumber", "url": "https://yelp.com/biz/x", "location": {"city": "Austin", "state": "TX"}}]}
        with patch.object(source, "_json", AsyncMock(return_value=data)) as request:
            page = await source.fetch_page({"category": "Plumber", "city": "Austin", "state": "TX"}, 20, 20)
        self.assertEqual(request.call_args.kwargs["params"]["offset"], 20)
        self.assertEqual(page.cursor, 21)
        self.assertEqual(page.records[0]["website_url"], "")

    async def test_google_token_and_details_for_every_selected_result(self):
        source = ProviderDiscovery("google_places", "not-real-key")
        responses = [{"status": "OK", "results": [{"place_id": "1"}, {"place_id": "2"}], "next_page_token": "next"},
                     {"status": "OK", "result": {"name": "A", "website": "https://a.test/"}},
                     {"status": "OK", "result": {"name": "B", "website": "https://b.test/"}}]
        with patch.object(source, "_json", AsyncMock(side_effect=responses)) as request, patch("discovery.asyncio.sleep", AsyncMock()):
            page = await source.fetch_page({"category": "Plumber", "city": "Austin", "state": "TX"}, "prior", 2)
        self.assertEqual(request.call_args_list[0].kwargs["params"]["pagetoken"], "prior")
        self.assertEqual(len(page.records), 2)
        self.assertEqual(page.cursor, "next")
        self.assertEqual(request.await_count, 3)

    async def test_serper_unsupported_pagination_reports_limit(self):
        source = ProviderDiscovery("serper_maps", "not-real-key")
        with patch.object(source, "_json", AsyncMock(return_value={"places": [{"title": "A", "website": "https://a.test/"}]})):
            page = await source.fetch_page({"category": "Plumber", "city": "Austin", "state": "TX"})
        self.assertIsNone(page.cursor)
        self.assertEqual(page.terminal_reason, "provider_limit")

    def test_unsafe_and_listing_websites_unverified(self):
        for value in ["javascript:alert(1)", "http://127.0.0.1/", "https://u:p@site.test/", "https://yelp.com/biz/a", ""]:
            self.assertEqual(website(value), "")
