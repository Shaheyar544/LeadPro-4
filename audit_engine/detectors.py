"""Evidence detectors operate on bounded rendered facts, never raw source HTML."""
import re
from urllib.parse import urlsplit, unquote, urljoin
from engine_store import now, uid, domain
from url_safety import normalize_url, UnsafeURL

VERSION = "rendered_dom_v1.1"
KEYS = (
    "reachable", "final_url", "https", "title", "viewport_meta", "rendered_page_status",
    "email", "phone", "mailto", "tel", "contact_page", "facebook", "instagram", "linkedin", "youtube",
    "contact_form", "quote_form", "booking_form", "primary_cta", "click_to_call", "request_quote_cta",
    "booking_cta", "contact_cta", "booking_widget", "chat_widget", "cms", "google_analytics",
    "google_tag_manager", "meta_pixel", "mobile_layout", "pagespeed",
)
STATUSES = {"present", "absent", "unknown", "blocked", "failed", "not_applicable"}


def evidence(key, status, value=None, *, url="", page_type="homepage", page_id=None,
             excerpt="", locator="", confidence=0.9):
    if status not in STATUSES:
        raise ValueError("Invalid evidence status")
    return dict(id=uid(), detector_key=key, status=status, value=value, source_url=url,
                page_type=page_type, page_id=page_id, excerpt=str(excerpt)[:240],
                locator=str(locator)[:200], confidence=confidence if status in ("present", "absent") else 0,
                detector_version=VERSION, observed_at=now())


def email_address(value):
    value = unquote(str(value or "").removeprefix("mailto:").split("?")[0]).strip().lower()
    if len(value) > 254 or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}", value):
        return None
    local, host = value.rsplit("@", 1)
    if host in {"example.com", "example.org", "example.net", "test.com", "domain.com", "email.com", "yourdomain.com", "sentry.io"} or host.endswith((".png", ".jpg", ".svg", ".webp", ".js", ".css")):
        return None
    if local in {"example", "yourname", "test", "username", "user"} or ".." in value or not all(host.split(".")):
        return None
    return value


def phone_number(value):
    raw = unquote(str(value or "").removeprefix("tel:")).strip()
    match = re.fullmatch(r"([+()\d\s.-]+)(?:\s*(?:ext\.?|x|;ext=)\s*(\d{1,6}))?", raw, re.I)
    if not match:
        return None
    digits = re.sub(r"\D", "", match[1])
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) != 10 or digits[0] not in "23456789" or digits[3] not in "23456789":
        return None
    if len(set(digits)) == 1:
        return None
    return "+1" + digits + (";ext=" + match[2] if match[2] else "")


def public_contacts(facts, url):
    contacts = {}
    for item in facts.get("contacts", [])[:150]:
        if not isinstance(item, dict) or item.get("kind") not in {"mailto", "tel", "visible_text", "provider_public"}:
            continue
        kind = item.get("type")
        value = email_address(item.get("value")) if kind == "email" else phone_number(item.get("value")) if kind == "phone" else None
        if not value:
            continue
        confidence = 0.98 if item["kind"] in {"mailto", "tel"} else 0.8 if item["kind"] == "visible_text" else 0.5
        key = (kind, value)
        result = dict(type=kind, display=str(item.get("value", ""))[:320], normalized=value,
                      source_url=url, evidence_type=item["kind"], confidence=confidence,
                      excerpt=str(item.get("excerpt", ""))[:240], locator=item.get("locator", ""))
        if key not in contacts or contacts[key]["confidence"] < confidence:
            contacts[key] = result
    roles = {"info", "contact", "hello", "sales", "office", "support", "booking", "service"}
    return sorted(contacts.values(), key=lambda c: (c["normalized"].split("@")[0] not in roles, -c["confidence"], c["normalized"]))


def selected_links(links, homepage, max_pages=3):
    candidates = []
    for link in links[:250]:
        if not isinstance(link, dict):
            continue
        try:
            url = normalize_url(urljoin(homepage, str(link.get("href", ""))))
        except UnsafeURL:
            continue
        p = urlsplit(url)
        if domain(url) != domain(homepage) or p.query:
            continue
        description = unquote(p.path) + " " + str(link.get("text", ""))
        if re.search(r"login|log.?out|sign.?in|account|cart|checkout|privacy|terms|download|\.(pdf|zip|docx?|xlsx?|exe)(?:$|\s)", description, re.I):
            continue
        page_type = "contact" if re.search(r"contact|quote|estimate", description, re.I) else "about" if re.search(r"about", description, re.I) else "services" if re.search(r"services?", description, re.I) else None
        if page_type and url.rstrip("/") != homepage.rstrip("/"):
            rank = 0 if re.search("contact", description, re.I) else 1 if page_type == "contact" else 2 if page_type == "about" else 3
            candidates.append((rank, url, page_type))
    selected, seen, types = [], {homepage.rstrip("/")}, set()
    for _, url, page_type in sorted(candidates):
        group = "contact" if page_type == "contact" else "secondary"
        if group in types or url.rstrip("/") in seen:
            continue
        selected.append((url, page_type)); seen.add(url.rstrip("/")); types.add(group)
        if len(selected) >= max(0, min(max_pages, 4) - 1):
            break
    return selected if max_pages > 1 else []


def social_url(href, platform):
    try:
        url = normalize_url(href)
        p = urlsplit(url); host = p.hostname.removeprefix("www.").removeprefix("m.")
        path = p.path.strip("/")
        hosts = {"facebook": {"facebook.com", "fb.com"}, "instagram": {"instagram.com"}, "linkedin": {"linkedin.com"}, "youtube": {"youtube.com", "youtu.be"}}
        if host not in hosts[platform] or not path:
            return None
        if re.search(r"^(?:share|sharer|intent|login|dialog|plugins|privacy|terms|p/|reel/)", path, re.I):
            return None
        if platform == "linkedin" and not re.match(r"^company/[^/]+", path):
            return None
        # A linked video is not a business channel/profile. This also excludes
        # youtu.be short links while retaining the supported channel URL forms.
        if platform == "youtube" and (host != "youtube.com" or not re.fullmatch(r"(?:@[^/]+|(?:channel|c|user)/[^/]+)(?:/(?:videos|featured|about))?", path)):
            return None
        return url
    except (UnsafeURL, ValueError):
        return None


def detect(facts, page):
    url, page_type = page["final_url"], page["page_type"]
    negative = "absent" if facts.get("complete") else "unknown"
    output = []
    def add(key, value=None, *, status=None, excerpt="", locator="", confidence=0.9):
        output.append(evidence(key, status or ("present" if value else negative), value, url=url,
                               page_type=page_type, page_id=page["id"], excerpt=excerpt,
                               locator=locator, confidence=confidence))
    contacts = public_contacts(facts, url)
    add("reachable", True, locator="document.readyState / location.href")
    add("final_url", url, locator="location.href")
    add("https", url.startswith("https:"), locator="location.protocol")
    add("title", facts.get("title"), locator="title")
    add("viewport_meta", facts.get("viewport"), locator='meta[name="viewport"]')
    add("rendered_page_status", facts.get("ready_state"), status="present" if facts.get("ready_state") == "complete" else "unknown", locator="document.readyState")
    for kind in ("email", "phone"):
        found = [c for c in contacts if c["type"] == kind]
        if not found:
            add(kind)
        for c in found:
            add(kind, c["normalized"], excerpt=c["excerpt"], locator=c["locator"], confidence=c["confidence"])
    for key in ("mailto", "tel"):
        add(key, [c["normalized"] for c in contacts if c["evidence_type"] == key], locator=f'a[href^="{key}:"]')
    links = facts.get("links", [])
    contact_pages = [u for u, t in selected_links(links, url, 3) if t == "contact"]
    contact_url = url if page_type == "contact" else contact_pages[0] if contact_pages else None
    add("contact_page", contact_url, locator="location.href (contact page)" if page_type == "contact" else "a[href]",
        excerpt=contact_url or "")
    for platform in ("facebook", "instagram", "linkedin", "youtube"):
        matches = {value: link for link in links if (value := social_url(link.get("href", ""), platform))}
        found = sorted(matches)
        link = matches[found[0]] if found else {}
        add(platform, found, locator=link.get("locator") or "a[href]", excerpt=link.get("text") or (found[0] if found else ""))
    form_matches = {"contact_form": [], "quote_form": [], "booking_form": []}
    for form in facts.get("forms", [])[:30]:
        fields = form.get("fields", [])
        labels = " ".join(str(f.get(k, "")) for f in fields for k in ("type", "name", "label", "placeholder", "tag"))
        text = " ".join([str(form.get("text", "")), str(form.get("heading", "")), " ".join(form.get("buttons", [])), str(form.get("action", ""))])
        description = (labels + " " + text).lower()
        if any(f.get("type") in {"password", "search"} for f in fields) or re.search(r"newsletter|subscribe|sign.?up for updates|log.?in|sign.?in", text, re.I):
            continue
        contact_input = bool(re.search(r"email|phone|telephone|textarea|message", labels, re.I))
        if not contact_input:
            continue
        if re.search(r"quote|estimate", description):
            form_matches["quote_form"].append(form)
        if re.search(r"book|schedule|appointment|reservation", description):
            form_matches["booking_form"].append(form)
        if re.search(r"contact|message|enquir|inquir|send|submit|quote|estimate|appointment", description):
            form_matches["contact_form"].append(form)
    for key, forms in form_matches.items():
        form = forms[0] if forms else {}
        # Preserve the heading that actually explains a scheduling/quote match;
        # label-free forms still have a useful field/placeholder description.
        excerpt = " ".join(str(form.get(k) or "") for k in ("heading", "text")).strip()
        if forms and not excerpt:
            excerpt = " ".join(str(f.get("label") or f.get("placeholder") or f.get("name") or f.get("type") or "") for f in form.get("fields", []))
        add(key, True if forms else None, excerpt=excerpt, locator=form.get("locator") or "form")
    patterns = {"click_to_call": r"^tel:", "request_quote_cta": r"\b(?:quote|estimate)\b", "booking_cta": r"\b(?:book|schedule|appointment|reserve)\b", "contact_cta": r"\b(?:contact|call|email|talk to|send message)\b"}
    actionable = []
    for key, pattern in patterns.items():
        found = [c for c in facts.get("ctas", []) if re.search(pattern, c.get("href", "") if key == "click_to_call" else c.get("text", ""), re.I)
                 or (key == "contact_cta" and ((c.get("href", "").startswith("tel:") and phone_number(c["href"]))
                                               or (c.get("href", "").startswith("mailto:") and email_address(c["href"]))))]
        if found:
            actionable.extend(found)
        cta = found[0] if found else {}
        add(key, cta.get("text") or cta.get("href"), excerpt=cta.get("text") or cta.get("href", ""), locator=cta.get("locator") or "a,button,input[type=submit]")
    cta = actionable[0] if actionable else {}
    add("primary_cta", cta.get("text") or cta.get("href"), excerpt=cta.get("text", ""), locator=cta.get("locator", ""), confidence=0.8)
    resources = " ".join(facts.get("resources", [])).lower()
    signatures = {"booking_widget": r"calendly\.com|acuityscheduling\.com|squareup\.com/appointments|booksy\.com|setmore\.com|simplybook\.", "chat_widget": r"tawk\.to|intercom(?:cdn)?\.com|crisp\.chat|drift\.com|tidio\.(?:co|com)|livechatinc\.com|zopim\.com|https://webchat\.birdeye\.com/"}
    for key, pattern in signatures.items():
        match = re.search(pattern, resources)
        add(key, match[0] if match else None, status="present" if match else "unknown", locator="rendered resource URL", confidence=0.85)
    cms = resources + " " + facts.get("generator", "").lower()
    cms_patterns = {"WordPress": r"wp-content|wp-includes|wordpress", "Wix": r"wixstatic|wix\.com", "Squarespace": r"squarespace", "Shopify": r"cdn\.shopify|shopify"}
    match = next((name for name, pattern in cms_patterns.items() if re.search(pattern, cms)), None)
    hint = ""
    if match:
        hint = next((resource.split("?", 1)[0] for resource in facts.get("resources", []) if re.search(cms_patterns[match], resource, re.I)), facts.get("generator", ""))
    elif re.match(r"^Framer(?:\s|$)", facts.get("generator", ""), re.I):
        match, hint = "Framer", facts["generator"]
    add("cms", match, status="present" if match else "unknown", locator="generator / rendered resource URL", excerpt=hint)
    for key, flag, pattern in (("google_analytics", "ga", r"google-analytics\.com|googletagmanager\.com/gtag/js"), ("google_tag_manager", "gtm", r"googletagmanager\.com/gtm\.js"), ("meta_pixel", "meta_pixel", r"connect\.facebook\.net/.*/fbevents\.js")):
        found = bool(facts.get("tracking", {}).get(flag) or re.search(pattern, resources))
        add(key, True if found else None, status="present" if found else "unknown", locator="rendered script signature")
    return output, contacts


def aggregate(findings, complete):
    """Absence is scoped to the bounded audit, never asserted on inaccessible pages."""
    result = {}
    for key in KEYS:
        rows = [e for e in findings if e["detector_key"] == key]
        present = [e for e in rows if e["status"] == "present"]
        absent = [e for e in rows if e["status"] == "absent"]
        if present:
            status, used = "present", present
        elif absent and complete and all(e["status"] in {"absent", "not_applicable"} for e in rows):
            status, used = "absent", absent
        elif rows and all(e["status"] == "not_applicable" for e in rows):
            status, used = "not_applicable", rows
        else:
            status = "blocked" if any(e["status"] == "blocked" for e in rows) else "failed" if rows and all(e["status"] == "failed" for e in rows) else "unknown"
            used = rows
        result[key] = {"status": status, "evidence_ids": [e["id"] for e in used], "confidence": max((e["confidence"] for e in used), default=0), "value": present[0].get("value") if present else None}
    return result
