import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from tests.support import app, database
import audit
import leadgen
from url_safety import FetchResult


RAW = {"placeId": "audit-fixture", "title": "Fixture Plumbing", "website": "https://example.org",
       "phoneNumber": "+15551234567", "_country": "United States", "_niche": "Plumber",
       "_city": "Austin", "userRatingCount": 20, "rating": 4.5}


class AuditTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_observed_or_provider_emails_and_no_owner_inference(self):
        with patch.object(audit, "_guess_emails_from_domain", side_effect=AssertionError("No guesses")), \
             patch.object(audit, "_fetch_hunter_emails", side_effect=AssertionError("No Hunter")), \
             patch.object(audit, "_fetch_clearbit_emails", side_effect=AssertionError("No Clearbit")), \
             patch.object(audit, "extract_owner_from_html", side_effect=AssertionError("No owner inference")), \
             patch.object(audit, "_pagespeed_score", AsyncMock(return_value=-1)):
            for html, provider, expected in (("<html>No email</html>", "", "N/A"),
                                             ("<html>hello@fixtureplumbing.test</html>", "", "hello@fixtureplumbing.test"),
                                             ("<html>No email</html>", "office@fixtureplumbing.test", "office@fixtureplumbing.test")):
                with patch("url_safety.safe_fetch_html", AsyncMock(return_value=FetchResult("ok", RAW["website"], 200, html))):
                    result = await audit.audit_lead({**RAW, "email": provider}, None, skip_if_clean=False)
                self.assertEqual(result["email"], expected)
                self.assertIsNone(result["decision_maker"])
                self.assertIsNone(result["dm_source"])

    async def test_failed_fetches_never_fabricate_contacts_or_broken_site(self):
        for status, code in (("blocked", 403), ("rate_limited", 429), ("timeout", 0),
                             ("unsafe_url", 0), ("tls_error", 0), ("not_found", 404)):
            with patch("url_safety.safe_fetch_html", AsyncMock(return_value=FetchResult(status, RAW["website"], code))):
                result = await audit.audit_lead(RAW, None, skip_if_clean=False)
            self.assertFalse(result["site_dead"])
            self.assertEqual(result["email"], "N/A")
            self.assertNotIn("Broken Website", result["pain_points"])
            self.assertIn(status, result["pain_points"])

    async def test_provider_unsafe_url_uses_central_policy(self):
        import url_safety
        with patch.object(url_safety.aiohttp, "ClientSession") as session:
            result = await audit.audit_lead({**RAW, "website": "http://169.254.169.254"}, None, skip_if_clean=False)
        self.assertIn("unsafe_url", result["pain_points"])
        session.assert_not_called()

    async def test_yelp_does_not_guess_website(self):
        source = leadgen.YelpSource()
        with patch.object(source, "_guess_website_from_business", side_effect=AssertionError("No domain guesses")):
            # The retained adapter must preserve missing authoritative website data.
            lead = source._convert_business_to_lead({"id": "fixture", "name": "Fixture Plumbing", "url": "https://www.yelp.com/biz/fixture", "location": {}}, "Plumber in Austin", "United States")
        self.assertEqual(lead.website, "")

    async def test_engine_target_and_query_bounds_without_live_discovery(self):
        database.init_db()
        candidates = [leadgen.LeadData(str(index), "serper_maps", f"Fixture {index}", "", niche="Plumber") for index in range(120)]
        audited = [{"place_id": str(index), "business_name": f"Fixture {index}", "niche": "Plumber", "phone": "N/A", "email": "N/A", "pain_points": "[]"} for index in range(120)]
        saved = []
        fetch = AsyncMock(return_value=candidates)
        process = AsyncMock(return_value=audited)
        queue = asyncio.Queue()
        with patch.object(leadgen.MultiSourceEngine, "fetch_from_sources", fetch), \
             patch.object(leadgen.MultiSourceEngine, "_process_batch", process), \
             patch.object(leadgen, "get_existing_place_ids", return_value=set()), \
             patch.object(leadgen, "get_existing_emails", return_value=set()), \
             patch.object(leadgen, "upsert_leads", side_effect=lambda rows: saved.extend(rows)), \
             patch.object(leadgen.asyncio, "sleep", AsyncMock()):
            await leadgen.run_engine_web("United States", 1, queue, industry="Plumber", city="Austin", state="TX", include_clean_leads=True)
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(process.call_args.args[1]), 1)
        self.assertIn("Austin, TX, United States", fetch.call_args.args[1])
        with self.assertRaises(ValueError):
            await leadgen.run_engine_web("United States", 101, queue)

    async def test_per_job_website_concurrency_is_bounded(self):
        active = peak = 0
        async def fake_audit(raw, session, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return {"place_id": raw["placeId"]}
        engine = leadgen.MultiSourceEngine()
        candidates = [leadgen.LeadData(str(i), "serper_maps", "Fixture", "") for i in range(6)]
        with patch.object(leadgen, "SCRAPE_THREADS", 2), patch.object(leadgen, "audit_lead", fake_audit):
            results = await engine._process_batch(None, candidates, set(), "United States", "Plumber in Austin")
        self.assertEqual(len(results), 6)
        self.assertEqual(peak, 2)
