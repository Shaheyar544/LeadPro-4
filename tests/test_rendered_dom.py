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
