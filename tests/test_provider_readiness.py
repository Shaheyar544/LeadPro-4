import os
import unittest
from unittest.mock import AsyncMock, patch
from discovery import DiscoveryError, ProviderDiscovery, provider_readiness
from engine_config import EngineConfig
from engine_worker import PersistentWorker
from tests.engine_fixtures import FixtureStore, REQUEST


class ReadinessTests(unittest.TestCase):
    def test_configuration_diagnostic_has_no_network_or_secret(self):
        import config
        with patch.object(config,"SERPER_API_KEY","SECRET"), patch.object(config,"GOOGLE_PLACES_API_KEY",""), patch.object(config,"YELP_API_KEY",""), patch("aiohttp.ClientSession", side_effect=AssertionError("No network")):
            result = provider_readiness()
        self.assertTrue(result["serper_maps"]["configured"])
        self.assertFalse(result["yelp"]["configured"])
        self.assertEqual(result["serper_maps"]["pagination"], "one_page")
        self.assertNotIn("SECRET",str(result))
        self.assertTrue(all(r["quota_status"]=="unknown" for r in result.values()))


class PaginationTests(unittest.IsolatedAsyncioTestCase):
    async def discover(self, provider, target, pages):
        fixture = FixtureStore(); self.addCleanup(fixture.close)
        worker = PersistentWorker(fixture.store, EngineConfig(discovery_pages=pages), sources=[provider])
        job = fixture.job(target_count=target)
        fixture.store.claim_job(worker.id)
        await worker._discover(job["id"])
        return fixture.store, job["id"]

    async def test_google_tokens_activation_dedupe_target_and_page_bound(self):
        for target, pages, expected_calls, count in [(2,3,1,2),(20,2,2,3),(20,5,3,4)]:
            provider=ProviderDiscovery("google_places","SECRET")
            search=[]
            async def response(http, method, url, **kw):
                params=kw["params"]
                if "textsearch" in url:
                    search.append(params.copy()); index=len(search)
                    return {"status":"OK","results":[{"place_id":"same"},{"place_id":str(index)}],"next_page_token":f"token-{index}"}
                pid=params["place_id"]
                return {"status":"OK","result":{"name":f"Business {pid}","formatted_address":pid,"website":f"https://business{pid}.test/"}}
            provider._json=AsyncMock(side_effect=response)
            with patch("discovery.asyncio.sleep",new=AsyncMock()):
                store,jid=await self.discover(provider,target,pages)
            self.assertEqual(len(search),expected_calls)
            self.assertEqual(store.job(jid)["discovered_count"],count)
            for i,params in enumerate(search[1:],1):
                self.assertEqual(params["pagetoken"],f"token-{i}")
                self.assertNotIn("query",params)

    async def test_google_activation_retry_once_and_cancellation(self):
        provider=ProviderDiscovery("google_places","SECRET")
        provider._last_google_token = "token"
        provider._json=AsyncMock(side_effect=[{"status":"INVALID_REQUEST"},{"status":"OK","results":[],"next_page_token":"next"}])
        with patch("discovery.asyncio.sleep",new=AsyncMock()) as sleep:
            page=await provider.fetch_page(REQUEST,"token",1)
        self.assertEqual(provider._json.await_count,2)
        self.assertEqual(sleep.await_count,2)
        self.assertEqual(page.cursor,"next")

    async def test_google_fresh_token_retry_succeeds_after_invalid_request(self):
        provider = ProviderDiscovery("google_places", "SECRET")
        provider._json = AsyncMock(side_effect=[
            {"status": "OK", "results": [{"place_id": "p1"}], "next_page_token": "fresh"},
            {"status": "OK", "result": {"name": "P1", "website": "https://p1.test/"}},
            {"status": "INVALID_REQUEST"},
            {"status": "OK", "results": [{"place_id": "p2"}]},
            {"status": "OK", "result": {"name": "A", "website": "https://a.test/"}},
        ])
        with patch("discovery.asyncio.sleep", new=AsyncMock()):
            first = await provider.fetch_page(REQUEST, None, 20)
            second = await provider.fetch_page(REQUEST, first.cursor, 20)
        self.assertEqual(first.cursor, "fresh")
        self.assertEqual(second.records[0]["canonical_name"], "A")
        self.assertEqual(second.diagnostics["statuses"], ["INVALID_REQUEST", "OK"])
        self.assertEqual(second.diagnostics["token_attempts"], 2)

    async def test_google_fresh_token_retry_bound_preserves_page_one(self):
        provider = ProviderDiscovery("google_places", "SECRET")
        provider._last_google_token = "fresh"
        provider._json = AsyncMock(side_effect=[
            {"status": "INVALID_REQUEST"}, {"status": "INVALID_REQUEST"},
            {"status": "INVALID_REQUEST"}, {"status": "INVALID_REQUEST"},
        ])
        with patch("discovery.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(DiscoveryError) as caught:
                await provider.fetch_page(REQUEST, "fresh", 20)
        self.assertEqual(caught.exception.code, "page_token_not_ready_timeout")
        self.assertEqual(provider._json.await_count, 4)
        self.assertEqual(sleep.await_count, 4)

    async def test_google_token_statuses_do_not_retry(self):
        for status, expected in (("OVER_QUERY_LIMIT", "google_over_query_limit"),
                                 ("REQUEST_DENIED", "google_request_denied"),
                                 ("UNKNOWN_ERROR", "google_unknown_error")):
            provider = ProviderDiscovery("google_places", "SECRET")
            provider._json = AsyncMock(return_value={"status": status})
            with patch("discovery.asyncio.sleep", new=AsyncMock()) as sleep:
                with self.assertRaises(DiscoveryError) as caught:
                    await provider.fetch_page(REQUEST, "fresh", 20)
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(provider._json.await_count, 1)
            self.assertEqual(sleep.await_count, 1)

    async def test_google_stale_invalid_token_is_not_token_readiness(self):
        provider = ProviderDiscovery("google_places", "SECRET")
        provider._json = AsyncMock(return_value={"status": "INVALID_REQUEST"})
        with patch("discovery.asyncio.sleep", new=AsyncMock()) as sleep:
            with self.assertRaises(DiscoveryError) as caught:
                await provider.fetch_page(REQUEST, "stale", 20)
        self.assertEqual(caught.exception.code, "google_invalid_request")
        self.assertEqual(provider._json.await_count, 1)
        self.assertEqual(sleep.await_count, 1)

    async def test_google_zero_results_completes(self):
        provider = ProviderDiscovery("google_places", "SECRET")
        provider._json = AsyncMock(return_value={"status": "ZERO_RESULTS", "results": []})
        page = await provider.fetch_page(REQUEST, None, 20)
        self.assertEqual(page.records, [])
        self.assertIsNone(page.cursor)
        self.assertEqual(page.terminal_reason, "discovery_exhausted")

    async def test_yelp_offsets_dedupe_target_bound_and_no_guessed_site(self):
        for target, pages, expected, count in [(2,3,[0],2),(20,2,[0,2],3)]:
            provider=ProviderDiscovery("yelp","SECRET"); offsets=[]
            async def response(http,method,url,**kw):
                offset=kw["params"]["offset"]; offsets.append(offset)
                ids=["same",str(offset)]
                return {"total":100,"businesses":[{"id":pid,"name":"Business "+pid,"url":"https://yelp.com/biz/"+pid,"location":{"display_address":[pid]}} for pid in ids]}
            provider._json=AsyncMock(side_effect=response)
            store,jid=await self.discover(provider,target,pages)
            self.assertEqual(offsets,expected)
            self.assertEqual(store.job(jid)["discovered_count"],count)
            with store.transaction() as conn:
                self.assertTrue(all(not r[0] for r in conn.execute("SELECT website_url FROM businesses")))

    async def test_serper_stays_one_page_even_if_response_suggests_cursor(self):
        provider=ProviderDiscovery("serper_maps","SECRET")
        provider._json=AsyncMock(return_value={"places":[{"placeId":"a","title":"Business","website":"https://business.test/"}],"nextPageToken":"not-supported"})
        store,jid=await self.discover(provider,20,5)
        self.assertEqual(provider._json.await_count,1)
        self.assertEqual(store.job(jid)["discovered_count"],1)

    async def test_google_new_pagination_mapping_and_deduplication(self):
        provider = ProviderDiscovery("google_places_new", "SECRET")
        requests = []
        async def response(http, method, url, **kw):
            requests.append((method, url, kw))
            page = len(requests)
            if page == 1:
                return {"places": [{"id": "a", "displayName": {"text": "Alpha"}, "formattedAddress": "A", "websiteUri": "https://alpha.test", "nationalPhoneNumber": "+1 1", "rating": 4.5, "userRatingCount": 10}], "nextPageToken": "p2"}
            if page == 2:
                return {"places": [{"id": "a", "displayName": {"text": "Alpha"}}, {"id": "b", "displayName": {"text": "Beta"}, "formattedAddress": "B"}], "nextPageToken": "p3"}
            return {"places": [{"id": "c", "displayName": {"text": "Gamma"}}]}
        provider._json = AsyncMock(side_effect=response)
        fixture = FixtureStore(); self.addCleanup(fixture.close)
        job = fixture.job(target_count=50); worker = PersistentWorker(fixture.store, EngineConfig(discovery_pages=3), sources=[provider]); fixture.store.claim_job(worker.id)
        await worker._discover(job["id"])
        self.assertEqual(fixture.store.job(job["id"])["discovered_count"], 3)
        self.assertEqual([r[2].get("json", {}).get("pageToken") for r in requests], [None, "p2", "p3"])
        with fixture.store.transaction() as conn:
            ids = [r[0] for r in conn.execute("SELECT provider_record_id FROM business_sources WHERE provider='google_places_new'")]
        self.assertIn("google_places_new:a", ids)
        self.assertEqual(len(ids), 3)

    async def test_google_new_http_failures_and_partial_page(self):
        provider = ProviderDiscovery("google_places_new", "SECRET")
        provider._json = AsyncMock(side_effect=[{"places": [{"id": "a", "displayName": {"text": "Alpha"}}], "nextPageToken": "p2"}, DiscoveryError("google_new_forbidden")])
        first = await provider.fetch_page(REQUEST, None, 20)
        self.assertEqual(len(first.records), 1)
        with self.assertRaises(DiscoveryError) as caught:
            await provider.fetch_page(REQUEST, first.cursor, 20)
        self.assertEqual(caught.exception.code, "google_new_forbidden")


class ProviderIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def smoke(self, provider, flag, key_name):
        if os.getenv(flag)!="1": self.skipTest("Opt-in provider integration disabled")
        key=os.getenv(key_name,"")
        if not key: self.skipTest("Provider credential not configured")
        adapter=ProviderDiscovery(provider,key)
        try:
            page=await adapter.fetch_page(dict(category="Roofing",city="Dallas",state="TX"),limit=1)
        except Exception as exc:
            self.fail("Provider smoke failed: " + getattr(exc,"code","provider_error"))
        self.assertTrue(page.records,"Provider returned no parsed business identity")
        self.assertLessEqual(len(page.records),1)
        record=page.records[0]
        self.assertTrue(record["canonical_name"] and record["provider_record_id"])
        self.assertEqual(record["provider"],provider)
        self.assertTrue(record["source_url"].startswith("https://"))
        if provider=="yelp": self.assertFalse(record["website_url"])
        elif record["website_url"]: self.assertTrue(record["website_url"].startswith(("https://","http://")))
        if provider=="serper_maps": self.assertIsNone(page.cursor)
        elif page.cursor is not None: self.assertIsInstance(page.cursor,int if provider=="yelp" else str)
        # No follow-up cursor request, raw response persistence or contact output.

    async def test_serper(self):
        await self.smoke("serper_maps","RUN_SERPER_INTEGRATION_TESTS","SERPER_API_KEY")

    async def test_google_places(self):
        await self.smoke("google_places","RUN_GOOGLE_PLACES_INTEGRATION_TESTS","GOOGLE_PLACES_API_KEY")

    async def test_google_places_new(self):
        if os.getenv("RUN_GOOGLE_PLACES_NEW_INTEGRATION_TESTS") != "1":
            self.skipTest("Opt-in Google Places New integration disabled")
        import config
        key = os.getenv("GOOGLE_PLACES_NEW_API_KEY") or os.getenv("GOOGLE_PLACES_API_KEY", "")
        if not key:
            self.skipTest("Google Places New credential not configured")
        page = await ProviderDiscovery("google_places_new", key).fetch_page(dict(category="Roofing", city="Dallas", state="TX"), limit=1)
        self.assertTrue(page.records)
        self.assertTrue(page.records[0]["provider_record_id"].startswith("google_places_new:"))

    async def test_yelp(self):
        await self.smoke("yelp","RUN_YELP_INTEGRATION_TESTS","YELP_API_KEY")
