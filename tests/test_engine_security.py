import asyncio
import json
import logging
import unittest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from tests.support import app, database
from tests.engine_fixtures import FixtureStore, FixtureSource, facts, business, REQUEST
from browser.mock import MockBrowserProvider
from browser.base import BrowserError
from audit_engine.runner import AuditEngine
from engine_config import EngineConfig
from engine_worker import PersistentWorker, event


class EngineRouteSecurityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = FixtureStore(); self.addCleanup(self.fixture.close)
        self.browser = MockBrowserProvider({"https://business.test/": facts()})
        self.settings = EngineConfig(settle_ms=0)
        self.worker = PersistentWorker(self.fixture.store, self.settings, self.browser, [FixtureSource()],
            AuditEngine(self.browser, self.settings, validate=AsyncMock(side_effect=lambda x: x)))
        for target, value in [("engine_store", self.fixture.store), ("evidence_worker", self.worker)]:
            patcher = patch.object(app, target, value); patcher.start(); self.addCleanup(patcher.stop)
        patcher = patch.object(database, "get_user", return_value={"username": "alice", "role": "admin"})
        patcher.start(); self.addCleanup(patcher.stop)
        self.client = TestClient(app.app); self.addCleanup(self.client.close)
        self.alice = {"Authorization": "Bearer " + app.create_access_token({"sub": "alice"})}
        self.bob = {"Authorization": "Bearer " + app.create_access_token({"sub": "bob"})}

    def test_owner_scope_all_persistent_job_and_business_routes(self):
        job = self.fixture.job()
        asyncio.run(self.worker.run_once())
        bid = self.fixture.store.result_ids("alice")[0][0]
        paths = [f"/api/leadgen/jobs/{job['id']}", f"/api/leadgen/jobs/{job['id']}/items", f"/api/businesses/{bid}"]
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, headers=self.bob).status_code, 404)
            self.assertEqual(self.client.get(path, headers=self.alice).status_code, 200)
        cancel = f"/api/leadgen/jobs/{job['id']}/cancel"
        self.assertEqual(self.client.post(cancel, headers=self.bob).status_code, 404)
        self.assertEqual(self.client.get('/api/leadgen/jobs', headers=self.bob).json(), [])
        self.assertEqual(self.client.get('/api/leads', headers=self.bob).json()['total'], 0)
        self.assertEqual(len(self.client.get('/api/leads/export/csv', headers=self.bob).text.splitlines()), 1)
        detail = self.client.get(f"/api/businesses/{bid}", headers=self.alice).text
        self.assertNotIn('browser_session_key', detail)
        self.assertNotIn('browser_user_id', detail)
        self.assertNotIn('discovery_state', self.client.get(paths[0], headers=self.alice).text)

    def test_browser_health_auth_redaction_and_no_request_override(self):
        self.assertEqual(self.client.get('/api/browser/health').status_code, 401)
        self.browser.available = False
        data = self.client.get('/api/browser/health', headers=self.alice).json()
        self.assertEqual(data['status'], 'browser_unavailable')
        self.assertFalse(data['available'])
        self.assertEqual(set(data), {'provider', 'configured', 'available', 'status', 'contract_version'})
        for key in ['CAMOFOX_BASE_URL', 'CAMOFOX_ACCESS_KEY', 'BROWSER_PROVIDER']:
            self.assertEqual(self.client.post('/api/leadgen/start', json={**REQUEST, key: 'secret'}, headers=self.alice).status_code, 422)
            self.assertEqual(self.client.put('/api/config', json={key: 'secret'}, headers=self.alice).status_code, 400)

    def test_cancellation_survives_new_store_instance(self):
        response = self.client.post('/api/leadgen/start', json=REQUEST, headers=self.alice)
        jid = response.json()['job_id']
        self.assertEqual(self.client.post(f'/api/leadgen/jobs/{jid}/cancel', headers=self.alice).status_code, 200)
        from engine_store import EngineStore
        self.assertEqual(EngineStore(self.fixture.path).job(jid, 'alice')['status'], 'cancelled')

    def test_structured_logs_only_allow_expected_fields(self):
        with self.assertLogs('evidence_worker', level='INFO') as captured:
            event('audit_finished', jid='opaque', item='opaque', bid='opaque', rid='opaque', provider='camofox', code='browser_timeout', elapsed=1.25)
        record = json.loads(captured.records[0].message)
        self.assertEqual(record['elapsed_ms'], 1250)
        self.assertEqual(set(record), {'phase', 'job_id', 'item_id', 'business_id', 'audit_run_id', 'provider', 'error_code', 'elapsed_ms'})


class CleanupRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_teardown_failure_is_persisted_and_retried(self):
        fixture = FixtureStore(); self.addCleanup(fixture.close)
        browser = MockBrowserProvider({'https://business.test/': facts()})
        settings = EngineConfig(settle_ms=0)
        worker = PersistentWorker(fixture.store, settings, browser, [FixtureSource()],
            AuditEngine(browser, settings, validate=AsyncMock(side_effect=lambda x: x)))
        fixture.job()
        original = browser.close_session
        browser.close_session = AsyncMock(side_effect=BrowserError('browser_unavailable'))
        await worker.run_once()
        self.assertEqual(len(fixture.store.pending_cleanup()), 1)
        browser.close_session = original
        await worker.run_once()
        self.assertFalse(fixture.store.pending_cleanup())
        self.assertFalse(browser.sessions)


class MigrationTests(unittest.TestCase):
    def test_additive_migration_failure_is_atomic_and_success_is_idempotent(self):
        fixture = FixtureStore(); self.addCleanup(fixture.close)
        with patch.object(database, 'get_conn', fixture.store.transaction), \
             patch.object(database, 'SCHEMA_MIGRATIONS', [(51, 'CREATE TABLE rollback_probe(id); INVALID SQL;')]):
            with self.assertRaisesRegex(RuntimeError, 'Phase 3B database migration failed'):
                database.run_migrations()
        with fixture.store.transaction() as conn:
            self.assertFalse(conn.execute("SELECT name FROM sqlite_master WHERE name='rollback_probe'").fetchone())
            self.assertFalse(conn.execute('SELECT version FROM schema_versions WHERE version=51').fetchone())
        with patch.object(database, 'get_conn', fixture.store.transaction), \
             patch.object(database, 'SCHEMA_MIGRATIONS', [(51, 'CREATE TABLE success_probe(id);')]):
            database.run_migrations()
            database.run_migrations()
        with fixture.store.transaction() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM schema_versions WHERE version=51').fetchone()[0], 1)
