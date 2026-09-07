import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from audit_engine.detectors import detect, evidence, aggregate, phone_number, email_address, selected_links, social_url, KEYS
from audit_engine.runner import AuditEngine
from audit_engine.scoring import score_audit, WEIGHTS
from browser.base import BrowserError
from browser.mock import MockBrowserProvider
from engine_config import EngineConfig
from tests.engine_fixtures import facts, business


class DetectorTests(unittest.TestCase):
    def test_phone_only_contact_action_does_not_inflate_gap(self):
        f = facts(ctas=[{'text': '(512) 555-1234', 'href': 'tel:5125551234', 'locator': 'a#phone'}])
        page = dict(id='page', final_url=f['url'], page_type='homepage', status='completed')
        rows, contacts = detect(f, page)
        audit = dict(status='completed', pages=[page], contacts=contacts, evidence=rows)
        finding = aggregate(rows, True)
        self.assertEqual(finding['contact_cta']['status'], 'present')
        score = score_audit(business(), audit)
        component = next(c for c in score['breakdown']['components'] if c['detector_key']=='contact_cta')
        self.assertEqual(component['gap_points'], 0)
        for href in ['mailto:office@realbusiness.com', 'tel:5125551234']:
            rows, _ = detect(facts(ctas=[{'text':'', 'href':href}]), page)
            self.assertEqual(aggregate(rows, True)['contact_cta']['status'], 'present')
        rows, _ = detect(facts(ctas=[{'text':'', 'href':'mailto:example@example.com'}]), page)
        self.assertEqual(aggregate(rows, True)['contact_cta']['status'], 'absent')

    def test_profile_evidence_excludes_video_links_and_retains_traceable_sources(self):
        f = facts(links=[{'href':'https://www.youtube.com/@business', 'text':'', 'locator':'a#channel'},
                         {'href':'https://www.youtube.com/watch?v=123', 'text':'Watch our video'},
                         {'href':'https://linkedin.com/in/person', 'text':'Person'}],
                  contacts=[{'type':'phone','kind':'tel','value':'tel:5125551234','locator':'a#phone'}])
        rows, _ = detect(f, dict(id='p', final_url=f['url'], page_type='homepage'))
        self.assertEqual(aggregate(rows, True)['youtube']['value'], ['https://www.youtube.com/@business'])
        for row in rows:
            if row['status']=='present':
                self.assertTrue(row['locator'] or row['excerpt'], row['detector_key'])
                self.assertEqual(row['detector_version'], 'rendered_dom_v1.1')
        for href in ['https://youtu.be/video', 'https://youtu.be/@business', 'https://youtube.com/watch?v=123', 'https://youtube.com/shorts/123']:
            self.assertIsNone(social_url(href, 'youtube'))
        self.assertEqual(social_url('https://youtube.com/channel/UCbusiness', 'youtube'), 'https://youtube.com/channel/UCbusiness')

    def test_scheduling_heading_is_retained_as_classification_evidence(self):
        f = facts(forms=[{'heading':'Schedule a free inspection', 'text':'Name Email Message Submit',
                          'fields':[{'type':'email'}, {'tag':'textarea'}], 'locator':'form#inspection'}])
        rows, _ = detect(f, dict(id='p', final_url=f['url'], page_type='homepage'))
        booking = next(e for e in rows if e['detector_key']=='booking_form')
        self.assertEqual(booking['status'], 'present')
        self.assertIn('Schedule a free inspection', booking['excerpt'])
        self.assertEqual(booking['locator'], 'form#inspection')

    def test_observed_birdeye_chat_and_explicit_framer_generator(self):
        page = dict(id='p', final_url='https://business.test/', page_type='homepage')
        rows, _ = detect(facts(generator='Framer abc123', resources=['https://webchat.birdeye.com/getBubbleContent']), page)
        findings = aggregate(rows, True)
        self.assertEqual(findings['chat_widget']['status'], 'present')
        self.assertEqual(findings['cms']['value'], 'Framer')
        self.assertIn('Framer abc123', next(e for e in rows if e['detector_key']=='cms')['excerpt'])
        rows, _ = detect(facts(generator='Unknown website builder', resources=['https://webchat.birdeye.com.evil.test/not-chat', 'https://site.test/framer-logo.png']), page)
        findings = aggregate(rows, True)
        self.assertEqual(findings['chat_widget']['status'], 'unknown')
        self.assertEqual(findings['cms']['status'], 'unknown')

    def test_contact_normalization_and_false_positives(self):
        self.assertEqual(email_address("mailto:Office@realbusiness.com?subject=Hello"), "office@realbusiness.com")
        for value in ["photo@2x.png", "person@example.com", "bad@domain.com", "hidden source map", "test@validbusiness.com"]:
            self.assertIsNone(email_address(value))
        self.assertEqual(phone_number("+1 (512) 555-1234 ext. 12"), "+15125551234;ext=12")
        self.assertEqual(phone_number("tel:512-555-1234"), "+15125551234")
        for value in ["123456", "441234567890", "+44 1234 567890", "1111111111", "5121234567", "tracking_id=5125551234"]:
            self.assertIsNone(phone_number(value))

    def test_real_contacts_forms_social_and_widget_evidence(self):
        f = facts(contacts=[{"type": "email", "value": "info@realbusiness.com", "kind": "mailto", "excerpt": "Contact us"}, {"type": "email", "value": "hello@realbusiness.com", "kind": "visible_text", "excerpt": "Business enquiries"}, {"type": "email", "value": "script@realbusiness.com", "kind": "script"}],
                  forms=[{"text": "Request an estimate", "fields": [{"name": "email", "type": "email"}, {"tag": "textarea", "name": "project"}], "buttons": ["Request quote"], "locator": "form#quote"}, {"text": "Subscribe to newsletter", "fields": [{"type": "email"}], "buttons": ["Subscribe"]}],
                  links=[{"href": "https://linkedin.com/in/person", "text": "Person"}, {"href": "https://linkedin.com/company/real-business", "text": "Company"}],
                  resources=["https://assets.calendly.com/assets/external/widget.js", "https://embed.tawk.to/id", "https://site.test/wp-content/theme.css", "https://www.googletagmanager.com/gtm.js?id=GTM-AAA"],
                  ctas=[{"text": "Request a quote", "href": "/quote", "locator": "a#quote"}])
        page = dict(id="page", final_url=f["url"], page_type="homepage")
        rows, contacts = detect(f, page)
        finding = aggregate(rows, True)
        self.assertEqual(len(contacts), 2)
        self.assertEqual(contacts[0]["confidence"], .98)
        self.assertEqual(finding["quote_form"]["status"], "present")
        self.assertEqual(finding["booking_form"]["status"], "absent")
        self.assertEqual(finding["linkedin"]["value"], ["https://linkedin.com/company/real-business"])
        self.assertEqual(finding["booking_widget"]["status"], "present")
        self.assertEqual(finding["chat_widget"]["status"], "present")
        self.assertEqual(finding["cms"]["value"], "WordPress")
        self.assertEqual(finding["google_tag_manager"]["status"], "present")
        self.assertEqual(finding["google_analytics"]["status"], "unknown")
        self.assertTrue(all(e["id"] and e["detector_version"] and len(e["excerpt"]) <= 240 for e in rows))

    def test_newsletter_login_search_are_not_contact_forms(self):
        forms = [{"text": text, "fields": [{"type": kind}], "buttons": ["Submit"]}
                 for text, kind in [("Newsletter", "email"), ("Log in", "password"), ("Search", "search")]]
        rows, _ = detect(facts(forms=forms), dict(id="p", final_url="https://business.test/", page_type="homepage"))
        self.assertEqual(aggregate(rows, True)["contact_form"]["status"], "absent")

    def test_link_scope_priority_dedupe_and_no_invented_paths(self):
        links = [{"href": href, "text": text} for href, text in [
            ("/about", "About"), ("/services", "Services"), ("/quote", "Estimate"), ("/contact", "Contact"),
            ("/contact#team", "Contact"), ("https://evil.test/contact", "Contact"),
            ("https://sub.business.test/contact", "Contact"), ("/login", "Contact"), ("/contact.pdf", "Contact")]]
        self.assertEqual(selected_links(links, "https://business.test/"), [("https://business.test/contact", "contact"), ("https://business.test/about", "about")])
        self.assertEqual(selected_links([], "https://business.test/"), [])
        self.assertEqual(selected_links(links, "https://business.test/", 1), [])
        self.assertIsNone(social_url("https://linkedin.com/in/owner", "linkedin"))
        self.assertIsNone(social_url("https://facebook.com/sharer.php", "facebook"))

    def test_statuses_never_turn_unobserved_into_absence(self):
        for status in ("unknown", "blocked", "failed"):
            result = aggregate([evidence("contact_form", "absent"), evidence("contact_form", status)], False)
            self.assertNotEqual(result["contact_form"]["status"], "absent")
        self.assertEqual(aggregate([evidence("email", "present", "info@realbusiness.com"), evidence("email", "blocked")], False)["email"]["status"], "present")


class ScoreTests(unittest.TestCase):
    def audit(self, status="absent"):
        return dict(status="completed", pages=[{"status": "completed"}], contacts=[], evidence=[evidence(k, status) for k in WEIGHTS if k != "pagespeed"])

    def test_strong_business_weak_website_exact_formula(self):
        a = self.audit(); a["evidence"].append(evidence("reachable", "present", True))
        score = score_audit(business(rating=5, review_count=500), a)
        self.assertEqual(score["business_strength"], 100)
        self.assertEqual(score["digital_gap"], 100)
        self.assertEqual(score["opportunity_score"], 100)
        self.assertTrue(all(c["evidence_ids"] for c in score["breakdown"]["components"] if c["status"] == "absent"))

    def test_low_coverage_is_low_confidence_and_unknown_gap(self):
        a = self.audit("unknown"); a["evidence"] = [evidence("contact_form", "absent")]
        s = score_audit(business(), a)
        self.assertIsNone(s["digital_gap"])
        self.assertIsNone(s["opportunity_score"])
        self.assertLess(s["evidence_confidence"], 20)

    def test_blocked_is_not_high_gap(self):
        a = self.audit("blocked"); a["status"] = "blocked"; a["pages"] = [{"status": "blocked"}]
        s = score_audit(business(), a)
        self.assertIsNone(s["opportunity_score"])
        self.assertEqual(s["evidence_confidence"], 0)

    def test_excellent_site_has_low_gap(self):
        s = score_audit(business(rating=5, review_count=500), self.audit("present"))
        self.assertEqual(s["digital_gap"], 0)
        self.assertEqual(s["opportunity_score"], 30)

    def test_contact_missing_only_changes_contact_confidence(self):
        a = self.audit(); s1 = score_audit(business(), a)
        a["contacts"] = [{"confidence": .98}]; s2 = score_audit(business(), a)
        self.assertEqual(s1["digital_gap"], s2["digital_gap"])
        self.assertEqual(s1["opportunity_score"], s2["opportunity_score"])
        self.assertEqual((s1["contact_confidence"], s2["contact_confidence"]), (0, 98))

    def test_missing_strength_falls_back_to_gap_only(self):
        s = score_audit(business(rating=None, review_count=None), self.audit())
        self.assertIsNone(s["business_strength"])
        self.assertEqual(s["opportunity_score"], s["digital_gap"])
        self.assertEqual(s["breakdown"]["fallback"], "gap_only")

    def test_scores_are_bounded(self):
        for status in ["present", "absent", "unknown", "failed", "blocked"]:
            s = score_audit(business(rating=5, review_count=1000000), self.audit(status))
            for key in ("digital_gap", "business_strength", "opportunity_score", "evidence_confidence", "contact_confidence"):
                self.assertTrue(s[key] is None or 0 <= s[key] <= 100)

    def test_determinism_including_breakdown(self):
        a = self.audit()
        self.assertEqual(score_audit(business(), a), score_audit(business(), copy.deepcopy(a)))


class RenderedAuditTests(unittest.IsolatedAsyncioTestCase):
    async def run_audit(self, fixtures, **business_updates):
        browser = MockBrowserProvider(fixtures)
        settings = EngineConfig(settle_ms=0)
        validate = AsyncMock(side_effect=lambda url: url)
        engine = AuditEngine(browser, settings, validate=validate)
        session = await browser.open_session()
        try:
            result = await engine.run(business(**business_updates), session)
        finally:
            await browser.close_session(session)
        return result, browser

    async def test_three_pages_contacts_and_js_rendered_facts(self):
        home = facts(links=[{"href": "/contact", "text": "Contact"}, {"href": "/about", "text": "About"}, {"href": "/services", "text": "Services"}])
        contact = facts("https://business.test/contact", contacts=[{"type": "email", "value": "hello@realbusiness.com", "kind": "mailto", "excerpt": "JS rendered business contact"}])
        result, browser = await self.run_audit({home["url"]: home, contact["url"]: contact, "https://business.test/about": facts("https://business.test/about")})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["pages"]), 3)
        self.assertEqual(len(result["contacts"]), 1)
        self.assertFalse(browser.sessions)
        self.assertNotIn("html", json.dumps(result))

    async def test_no_website_never_guesses_or_opens_page(self):
        result, browser = await self.run_audit({}, website_url="")
        self.assertEqual(result["status"], "unverified")
        self.assertFalse(browser.visited)
        self.assertFalse(result["contacts"])

    async def test_partial_failure_and_blocked_preserve_known_evidence(self):
        home = facts(links=[{"href": "/contact", "text": "Contact"}])
        for failure in [BrowserError("browser_timeout"), facts("https://business.test/contact", blocked=True)]:
            result, browser = await self.run_audit({home["url"]: home, "https://business.test/contact": failure})
            self.assertEqual(result["status"], "partial")
            s = score_audit(business(), result)
            self.assertNotEqual(s["breakdown"]["findings"]["contact_form"]["status"], "absent")
            self.assertFalse(browser.sessions)

    async def test_unsafe_final_url_is_rejected(self):
        browser = MockBrowserProvider({"https://business.test/": facts("http://127.0.0.1/")})
        async def validate(url):
            if "127.0.0.1" in url:
                raise BrowserError("unsafe_navigation")
            return url
        engine = AuditEngine(browser, EngineConfig(settle_ms=0), validate=validate)
        session = await browser.open_session()
        result = await engine.run(business(), session)
        await browser.close_session(session)
        self.assertEqual(result["error_code"], "unsafe_navigation")
        self.assertFalse(result["contacts"])

    async def test_default_screenshots_off_and_bounded_generated_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            browser = MockBrowserProvider({"https://business.test/": facts()})
            settings = EngineConfig(settle_ms=0, screenshots=True, artifacts=Path(tmp))
            engine = AuditEngine(browser, settings, validate=AsyncMock(side_effect=lambda x: x))
            session = await browser.open_session()
            result = await engine.run(business(), session)
            await browser.close_session(session)
            self.assertEqual(len(list(Path(tmp).glob("*.png"))), 1)
            self.assertRegex(result["pages"][0]["screenshot_path"], r"^[a-f0-9]{32}\.png$")
        self.assertFalse(EngineConfig().screenshots)
