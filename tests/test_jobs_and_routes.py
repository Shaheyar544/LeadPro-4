import asyncio
import csv
import io
import json
import os
import re
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import httpx
from jobs import Job, JobManager, CapacityExceeded
from tests.support import app, config, database, TEST_ENV
from tests.test_inputs_and_secrets import VALID


class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_capacity_completion_and_ownership(self):
        manager = JobManager(1)
        release = asyncio.Event()
        async def run(job):
            await job.put({"type": "info", "message": "working"})
            await release.wait()
        job = manager.start("alice", run)
        self.assertEqual(len(job.id), 36)
        self.assertIs(manager.get(job.id, "alice"), job)
        self.assertIsNone(manager.get(job.id, "bob"))
        with self.assertRaises(CapacityExceeded):
            manager.start("bob", run)
        release.set()
        await asyncio.gather(*manager.tasks)
        self.assertEqual(manager.active, 0)
        self.assertEqual(job.status, "completed")

    async def test_failure_releases_capacity_without_exception_leak(self):
        manager = JobManager(1)
        async def fail(job):
            raise RuntimeError("sensitive-provider-credential")
        job = manager.start("alice", fail)
        await asyncio.gather(*manager.tasks)
        self.assertEqual(manager.active, 0)
        self.assertEqual(job.status, "failed")
        self.assertNotIn("sensitive-provider", json.dumps(job.snapshot()))

    async def test_bounded_nondestructive_events_and_retention(self):
        manager = JobManager()
        job = Job("alice")
        for index in range(500):
            await job.put({"type": "info", "message": "x" * 3000})
        self.assertEqual(len(job.events), 200)
        self.assertEqual(len(job.events[0]["message"]), 2000)
        self.assertEqual(job.snapshot(), job.snapshot())
        self.assertEqual(len(job.snapshot(after=499)["events"]), 1)
        import time
        job.finished_at = time.monotonic() - 3601
        manager.jobs[job.id] = job
        self.assertIsNone(manager.get(job.id, "alice"))

    async def test_shutdown_cancels_running_work(self):
        manager = JobManager()
        started = asyncio.Event()
        async def run(job):
            started.set()
            await asyncio.Event().wait()
        job = manager.start("alice", run)
        await started.wait()
        await manager.shutdown()
        self.assertEqual(manager.active, 0)
        self.assertEqual(job.status, "interrupted")

    async def test_shutdown_before_task_starts_releases_slot(self):
        manager = JobManager()
        job = manager.start("alice", AsyncMock())
        await manager.shutdown()
        self.assertEqual(manager.active, 0)
        self.assertEqual(job.status, "interrupted")


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        database.init_db()

    def setUp(self):
        self.client = TestClient(app.app)
        self.addCleanup(self.client.close)
        self.user = {"username": "alice", "role": "admin", "id": 1, "password_hash": "fixture"}
        self.user_patch = patch.object(database, "get_user", return_value=self.user)
        self.user_patch.start()
        self.addCleanup(self.user_patch.stop)
        self.token = app.create_access_token({"sub": "alice", "role": "admin"})
        self.headers = {"Authorization": "Bearer " + self.token}
        self.manager_patch = patch.object(app, "job_manager", JobManager())
        self.manager_patch.start()
        self.addCleanup(self.manager_patch.stop)

    def test_every_legacy_route_unmounted_and_returns_404(self):
        self.assertFalse(config.OUTREACH_ENABLED)
        self.assertFalse(config.PUBLIC_AUDIT_ENABLED)
        self.assertFalse(config.SCHEDULER_ENABLED)
        self.assertGreater(len(app.legacy_routes.routes), 50)
        with patch("smtplib.SMTP", side_effect=AssertionError("SMTP must not run")), \
             patch("imaplib.IMAP4_SSL", side_effect=AssertionError("IMAP must not run")):
            for route in app.legacy_routes.routes:
                path = re.sub(r"\{[^}]+\}", "1", route.path)
                for method in route.methods:
                    with self.subTest(method=method, path=path):
                        response = self.client.request(method, path, headers=self.headers)
                        self.assertEqual(response.status_code, 404)
                        self.assertEqual(response.json(), {"detail": "Not Found"})
        active = self.client.get("/openapi.json").json()["paths"]
        for route in app.legacy_routes.routes:
            self.assertNotIn(route.path, active)

    def test_job_status_and_stream_auth_ownership_and_query_token(self):
        job = Job("alice", status="completed")
        app.job_manager.jobs[job.id] = job
        for family in ("status", "stream"):
            path = f"/api/leadgen/{family}/{job.id}"
            self.assertEqual(self.client.get(path).status_code, 401)
            self.assertEqual(self.client.get(path, params={"token": self.token}).status_code, 401)
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200)
            bob = {"Authorization": "Bearer " + app.create_access_token({"sub": "bob"})}
            self.assertEqual(self.client.get(path, headers=bob).status_code, 404)
            self.assertEqual(self.client.get(f"/api/leadgen/{family}/missing", headers=self.headers).status_code, 404)
        self.assertIs(app.job_manager.get(job.id, "alice"), job)

    def test_backend_input_validation_before_job(self):
        for update in ({"target_count": 0}, {"target_count": 101}, {"category": ""}, {"state": "ZZ"}, {"opportunity_profile": "email"}):
            response = self.client.post("/api/leadgen/start", json={**VALID, **update}, headers=self.headers)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(app.job_manager.active, 0)

    def test_missing_discovery_keys_are_clear_and_do_not_start_job(self):
        with patch.multiple(config, SERPER_API_KEY="", GOOGLE_PLACES_API_KEY="", YELP_API_KEY=""):
            response = self.client.post("/api/leadgen/start", json=VALID, headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(app.job_manager.active, 0)

    def test_capacity_exhaustion_returns_retryable_429(self):
        app.job_manager.active = 1
        with patch.object(config, "SERPER_API_KEY", "fixture"):
            response = self.client.post("/api/leadgen/start", json=VALID, headers=self.headers)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["Retry-After"], "10")

    def test_current_db_role_controls_settings(self):
        self.user["role"] = "user"
        for method in ("GET", "PUT"):
            response = self.client.request(method, "/api/config", headers=self.headers, json={})
            self.assertEqual(response.status_code, 403)
        self.user["role"] = "admin"
        with patch.object(config, "SERPER_API_KEY", "sensitive-provider-value"):
            response = self.client.get("/api/config", headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn("sensitive-provider-value", response.text)
        for updates in ({"JWT_SECRET": "bad"}, {"OUTREACH_ENABLED": "true"}, {"SERPER_API_KEY": "bad\nvalue"}):
            self.assertEqual(self.client.put("/api/config", headers=self.headers, json=updates).status_code, 400)

    def test_deleted_user_and_expired_token_denied(self):
        with patch.object(database, "get_user", return_value=None):
            self.assertEqual(self.client.get("/api/auth/me", headers=self.headers).status_code, 401)
        from jose import jwt
        for claims in ({"sub": "alice", "exp": 1}, {"sub": "alice"}):
            token = jwt.encode(claims, config.JWT_SECRET, algorithm="HS256")
            self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).status_code, 401)

    def test_health_failure_is_503_and_redacted(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        with patch.object(database, "get_conn", side_effect=RuntimeError("secret internal path")):
            response = self.client.get("/health")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {"status": "unavailable"})

    def test_csv_endpoint_neutralizes_formula_and_keeps_quoting(self):
        with database.get_conn() as conn:
            conn.execute("DELETE FROM leads")
            conn.execute("INSERT INTO leads (place_id,business_name,email,phone,source_query) VALUES (?,?,?,?,?)",
                         ("csv-fixture", '=HYPERLINK("https://example.org")', "@formula", "+15551234567", 'Austin, "TX"'))
        response = self.client.get("/api/leads/export/csv", headers=self.headers)
        row = list(csv.DictReader(io.StringIO(response.text)))[0]
        self.assertTrue(row["business_name"].startswith("'="))
        self.assertEqual(row["email"], "'@formula")
        self.assertEqual(row["phone"], "'+15551234567")
        self.assertEqual(row["source_query"], 'Austin, "TX"')
        self.assertNotIn("decision_maker", row)

    def test_security_headers_static_assets_and_no_inline_js(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("onclick=", response.text)
        self.assertNotIn("EventSource", response.text)
        for path in ("/foundation.js", "/base_style.css", "/new_style.css"):
            self.assertEqual(self.client.get(path).status_code, 200)
        script = self.client.get("/foundation.js").text
        self.assertNotIn("innerHTML", script)
        self.assertNotIn("insertAdjacentHTML", script)

    def test_admin_bootstrap_never_prints_password(self):
        output = io.StringIO()
        password = "Unique-test-password-123"
        with patch.object(database, "count_users", return_value=0), patch.object(database, "create_user") as create, \
             patch.dict(os.environ, {"INITIAL_ADMIN_PASSWORD": password}), redirect_stdout(output), redirect_stderr(output):
            app._ensure_default_admin()
        self.assertNotIn(password, output.getvalue())
        args = create.call_args.args
        self.assertTrue(app._verify_password(password, args[1]))


class RouteJobIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_uses_normalized_contract_and_bounded_manager(self):
        from leadgen import run_engine_web
        mock_run = AsyncMock()
        manager = JobManager(1)
        headers = {"Authorization": "Bearer " + app.create_access_token({"sub": "alice"})}
        with patch.object(database, "get_user", return_value={"username": "alice", "role": "admin"}), \
             patch.object(config, "SERPER_API_KEY", "fixture"), patch.object(app, "job_manager", manager), \
             patch("leadgen.run_engine_web", mock_run):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.app), base_url="http://test") as client:
                response = await client.post("/api/leadgen/start", json={**VALID, "state": "Texas"}, headers=headers)
                self.assertEqual(response.status_code, 202)
                await asyncio.gather(*manager.tasks)
                jid = response.json()["job_id"]
                self.assertEqual((await client.get(f"/api/leadgen/status/{jid}", headers=headers)).json()["status"], "completed")
        kwargs = mock_run.call_args.kwargs
        self.assertEqual((kwargs["city"], kwargs["state"], kwargs["target"]), ("Austin", "TX", 25))
        self.assertEqual(kwargs["source_selection"], ["serper_maps"])


class StartupTests(unittest.TestCase):
    def test_lifespan_starts_without_keys_or_network(self):
        import socket
        import scheduler
        with patch.dict(os.environ, TEST_ENV), patch.object(socket, "create_connection", side_effect=AssertionError("No network")), \
             patch.object(scheduler, "start_scheduler") as start, patch("smtplib.SMTP") as smtp, patch("imaplib.IMAP4_SSL") as imap:
            with TestClient(app.app) as client:
                self.assertEqual(client.get("/health").status_code, 200)
            start.assert_not_called()
            smtp.assert_not_called()
            imap.assert_not_called()

    def test_scheduler_cannot_start_retired_jobs(self):
        import scheduler
        with patch.object(config, "SCHEDULER_ENABLED", True), patch.object(scheduler.scheduler, "start") as start:
            scheduler.start_scheduler()
            start.assert_not_called()

    def test_disabled_flags_fail_closed_if_enabled(self):
        with patch.dict(os.environ, TEST_ENV):
            for flag in ("OUTREACH_ENABLED", "PUBLIC_AUDIT_ENABLED"):
                with patch.object(config, flag, True), self.assertRaises(RuntimeError):
                    config.validate_config()
