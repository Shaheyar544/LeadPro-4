"""Actual rendered fixture extraction; installed Edge is only a local test tool."""
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright
from audit_engine.runner import EXTRACT
from audit_engine.detectors import detect, aggregate

FIXTURES = Path(__file__).with_name("fixtures")
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")


@unittest.skipUnless(EDGE.exists(), "Installed Windows Edge required for local DOM fixture checks")
class DOMFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="msedge", headless=True)
        cls.context = cls.browser.new_context()
        cls.context.route("**/*", lambda route: route.abort())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.playwright.stop()

    def extract(self, name):
        page = self.context.new_page()
        try:
            page.set_content((FIXTURES / name).read_text(encoding="utf-8"), wait_until="load")
            if name == "js_contact.html":
                page.locator('#contact a').wait_for()
            facts = page.evaluate(EXTRACT)
            facts["url"] = "https://business.test/"
            return facts
        finally:
            page.close()

    def test_visible_contacts_exclude_hidden_scripts_and_tracking_ids(self):
        facts = self.extract("business.html")
        rows, contacts = detect(facts, dict(id="fixture", final_url=facts["url"], page_type="homepage"))
        values = {c["normalized"] for c in contacts}
        self.assertEqual(values, {"office@oakplumbing.test", "hello@oakplumbing.test", "+15125551234", "+15125559876"})
        finding = aggregate(rows, True)
        self.assertEqual(finding["quote_form"]["status"], "present")
        self.assertEqual(finding["booking_form"]["status"], "absent")
        self.assertEqual(finding["linkedin"]["value"], ["https://linkedin.com/company/oak-plumbing"])

    def test_javascript_rendered_contact(self):
        self.assertEqual(self.extract("js_contact.html")["contacts"][0]["value"], "mailto:contact@oakplumbing.test")

    def test_booking_form_block_and_no_contact(self):
        facts = self.extract("booking.html")
        rows, _ = detect(facts, dict(id="fixture", final_url=facts["url"], page_type="homepage"))
        self.assertEqual(aggregate(rows, True)["booking_form"]["status"], "present")
        self.assertTrue(self.extract("blocked.html")["blocked"])
        self.assertEqual(self.extract("no_contact.html")["contacts"], [])
        page = self.context.new_page()
        try:
            page.set_content('<title>Business</title><h1>Verify you are human</h1><p>' + 'Long challenge response. ' * 1000 + '</p>')
            self.assertTrue(page.evaluate(EXTRACT)['blocked'])
        finally:
            page.close()


    def test_soft_error_pages_and_business_negative_control(self):
        cases = [("Access denied", "browser_blocked"), ("Site under maintenance", "browser_maintenance"),
                 ("This domain is for sale", "browser_parking"), ("Please enable JavaScript to continue", "browser_javascript_required"),
                 ("Enable cookies to continue", "browser_javascript_required"), ("Bad Gateway", "browser_maintenance"),
                 ("Oak Plumbing repair and maintenance services", None)]
        for title, expected in cases:
            page = self.context.new_page()
            try:
                page.set_content(f"<title>{title}</title><h1>{title}</h1><p>Contact information is currently unavailable.</p>")
                self.assertEqual(page.evaluate(EXTRACT)["soft_error"], expected)
            finally:
                page.close()

    def test_shared_seo_dom_extraction_and_policy_boundary(self):
        import json
        from audit_engine.growth import page_observation
        schema = {'@context':'https://schema.org','@type':'Plumber','name':'Oak Plumbing','url':'https://business.test/',
                  'address':{'streetAddress':'12 Oak Street','addressLocality':'Austin','addressRegion':'TX'},
                  'aggregateRating':{'ratingValue':'GOOGLE_RATING_CANARY'}, 'review':{'reviewBody':'GOOGLE_REVIEW_CANARY'}}
        html = '''<html><head><title>Oak Plumbing Austin</title><meta name="description" content="Plumbing repairs in Austin">
          <meta name="viewport" content="width=device-width"><meta name="robots" content="noindex,nofollow">
          <link rel="canonical" href="https://business.test/"></head><body><main>
          <h1>Oak Plumbing Austin</h1><h3>Repair services</h3><p>Oak plumbing repairs include clear inspections and practical repair options for homes in Austin, TX.</p>
          <address>12 Oak Street Austin, TX</address><a href="https://business.test/services/repair">Repair service</a>
          <img src="data:," width="20" height="20"><img src="data:," width="20" height="20" alt="">
          <script type="application/ld+json">''' + json.dumps(schema) + '''</script>
          <script type="application/ld+json">{invalid json}</script></main></body></html>'''
        page = self.context.new_page()
        try:
            page.set_content(html)
            f = page.evaluate(EXTRACT); f['url'] = 'https://business.test/'
            raw = f['growth']
            assert raw['canonicals'] == ['https://business.test/']
            assert raw['images']['missing_alt'] == raw['images']['empty_alt'] == 1
            assert raw['schema']['invalid_json_count'] == 1
            assert 'Austin, TX' in raw['visible_location_context']
            assert len(raw['visible_location_context']) <= 20
            assert 'GOOGLE_RATING_CANARY' not in json.dumps(raw)
            assert 'GOOGLE_REVIEW_CANARY' not in json.dumps(raw)
            o, rows = page_observation(f, dict(id='dom', final_url=f['url']))
            assert o['schema']['local_business']
            assert o['heading_hierarchy_skip']
            assert next(r for r in rows if r['detector_key'] == 'growth.indexability')['status'] == 'absent'
            # A type beyond a bounded graph/microdata sample must not become
            # a confident absence of LocalBusiness markup.
            graph = {'@graph':[{'@type':'Thing'}] * 100 + [{'@type':'LocalBusiness'}]}
            page.set_content('<script type="application/ld+json">' + json.dumps(graph) + '</script><main><h1>Business</h1></main>')
            bounded = page.evaluate(EXTRACT); bounded['url'] = 'https://business.test/'
            assert not bounded['growth']['schema']['complete']
            _, bounded_rows = page_observation(bounded, dict(id='bounded',final_url=bounded['url']))
            assert next(r for r in bounded_rows if r['detector_key']=='growth.local_schema')['status'] == 'unknown'
            page.set_content('<div itemscope itemtype="https://schema.org/Thing"></div>' * 61)
            assert not page.evaluate(EXTRACT)['growth']['schema']['complete']
        finally:
            page.close()
