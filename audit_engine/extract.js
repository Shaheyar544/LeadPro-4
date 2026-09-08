(() => {
  // Read-only: no clicks, requests, forms, cookies, storage or HTML serialization.
  const visible = el => {
    if (!el || el.closest('script,style,noscript,template,[hidden],[aria-hidden="true"]')) return false;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      const style = getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    }
    return el.getClientRects().length > 0;
  };
  const clean = (value, max = 240) => String(value || '').replace(/\s+/g, ' ').trim().slice(0, max);
  const locator = el => el.id ? `${el.tagName.toLowerCase()}#${clean(el.id, 80)}` : el.tagName.toLowerCase();
  const bodyText = document.body ? document.body.innerText.slice(0, 150000) : '';
  const nav = performance.getEntriesByType('navigation')[0];
  const httpStatus = nav && Number.isInteger(nav.responseStatus) ? nav.responseStatus : null;
  const wall = /verify (?:that )?you are human|checking your browser|access denied|too many requests|unusual traffic|security verification|just a moment|enable javascript and cookies to continue/i;
  const blocked = [401, 403, 429].includes(httpStatus) || wall.test(document.title) ||
    wall.test(bodyText.slice(0, 3000)) || wall.test([...document.querySelectorAll('h1,h2')].map(el => el.innerText).join(' ')) ||
    (bodyText.length < 2000 && /sign in to continue|log in to continue/i.test(bodyText)) || /captcha/i.test(document.title);
  const heading = clean([...document.querySelectorAll('h1,h2')].filter(visible).map(el => el.innerText).join(' '), 500);
  const errorText = document.title + ' ' + heading + (bodyText.length < 2000 ? ' ' + bodyText : '');
  const softError = blocked ? 'browser_blocked' :
    /^(?:.*\s)?(?:this domain (?:is |may be )?for sale|buy this domain|domain (?:is )?parked|website coming soon)(?:[.!\s]|$)/i.test(errorText) ? 'browser_parking' :
    /(?:site (?:is )?under maintenance|temporarily unavailable|service unavailable|bad gateway|error 50[0234]|web server is down|origin is unreachable)/i.test(errorText) ? 'browser_maintenance' :
    /(?:please enable javascript to (?:continue|view)|javascript (?:is )?disabled|enable cookies to continue)/i.test(errorText) ? 'browser_javascript_required' : null;
  const anchors = [...document.querySelectorAll('a[href]')].filter(visible);
  const links = anchors.slice(0, 250).map(el => ({href: clean(el.href, 2048), text: clean(el.innerText), locator: locator(el)}));
  const contacts = [];
  for (const a of anchors.slice(0, 500)) {
    if (/^(mailto:|tel:)/i.test(a.getAttribute('href') || '')) {
      contacts.push({type: /^mailto:/i.test(a.href) ? 'email' : 'phone', value: clean(a.getAttribute('href'), 320),
        kind: /^mailto:/i.test(a.href) ? 'mailto' : 'tel', excerpt: clean(a.innerText), locator: locator(a)});
    }
  }
  const walker = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  let node, count = 0;
  while ((node = walker.nextNode()) && count++ < 10000 && contacts.length < 150) {
    const el = node.parentElement;
    if (!visible(el) || el.closest('input,textarea,select,code,pre')) continue;
    const value = node.textContent;
    for (const m of value.matchAll(/[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi))
      contacts.push({type: 'email', value: m[0], kind: 'visible_text', excerpt: clean(value), locator: locator(el)});
    // Formatting or explicit phone context is required; bare tracking IDs are ignored.
    const phoneContext = /phone|call|telephone|contact|fax/i.test(value);
    for (const m of value.matchAll(/(?:\+?1[\s.-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[\s.-]?\d{3}[\s.-]?\d{4}(?:\s*(?:ext\.?|x)\s*\d{1,6})?/g)) {
      if (phoneContext || /[(). -]/.test(m[0])) contacts.push({type: 'phone', value: m[0], kind: 'visible_text', excerpt: clean(value), locator: locator(el)});
    }
  }
  const allForms = [...document.forms].filter(visible);
  const forms = allForms.slice(0, 30).map(form => ({
    locator: locator(form), text: clean(form.innerText, 700), action: clean(form.getAttribute('action'), 200),
    heading: clean(form.closest('section,article')?.querySelector('h1,h2,h3')?.innerText),
    fields: [...form.querySelectorAll('input,textarea,select')].filter(visible).slice(0, 40).map(el => ({
      tag: el.tagName.toLowerCase(), type: el.type, name: clean(el.name, 80),
      label: clean([...el.labels || []].map(label => label.innerText).join(' ')), placeholder: clean(el.placeholder)
    })), buttons: [...form.querySelectorAll('button,input[type="submit"]')].filter(visible).slice(0, 10).map(el => clean(el.innerText || el.value))
  }));
  const ctas = [...document.querySelectorAll('a,button,input[type="submit"]')].filter(visible).slice(0, 300)
    .map(el => ({text: clean(el.innerText || el.value), href: clean(el.href, 2048), locator: locator(el)}));
  const iframeNodes = [...document.querySelectorAll('iframe')].filter(visible).slice(0, 50);
  const iframes = iframeNodes.map(el => ({src: clean(el.src, 350), title: clean(el.title), label: clean(el.getAttribute('aria-label') || el.parentElement?.innerText)}));
  const resources = [...document.querySelectorAll('script[src],link[href],iframe[src]')].slice(0, 250)
    .map(el => clean(el.src || el.href, 350));
  // Match signatures in inline scripts without returning their source or contact strings.
  const inline = [...document.scripts].filter(el => !el.src).slice(0, 100).map(el => el.textContent.slice(0, 30000)).join('\n');
  // Shared Digital Growth facts. Never return raw JSON-LD, ratings, reviews,
  // third-party widget text, script contents or an entire page text dump.
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(visible);
  const images = [...document.images].filter(visible);
  const schemas = []; let schemaInvalid = 0, schemaLimited = false, schemaNodes = 0, schemaBytes = 0;
  const scalar = value => typeof value === 'string' || typeof value === 'number' ? clean(value, 160) : '';
  const visitSchema = (value, depth = 0) => {
    if (depth > 10 || ++schemaNodes > 600) { schemaLimited = true; return; }
    if (Array.isArray(value)) { if (value.length > 100) schemaLimited = true; value.slice(0, 100).forEach(v => visitSchema(v, depth + 1)); return; }
    if (!value || typeof value !== 'object') return;
    if (value['@type']) {
      const types = (Array.isArray(value['@type']) ? value['@type'] : [value['@type']])
        .filter(t => typeof t === 'string').slice(0, 8).map(t => clean(t, 120).replace(/^https?:\/\/schema.org\//, ''));
      const address = value.address && typeof value.address === 'object' && !Array.isArray(value.address) ? value.address : {};
      schemas.push({types, name: scalar(value.name), url: scalar(value.url), id: scalar(value['@id']),
        phone: scalar(value.telephone), address: Object.fromEntries(['streetAddress','addressLocality','addressRegion','postalCode','addressCountry']
          .map(k => [k, scalar(address[k])]).filter(([, v]) => v)),
        geo_present: !!(value.geo?.latitude && value.geo?.longitude), hours_present: !!(value.openingHours || value.openingHoursSpecification),
        areas: (Array.isArray(value.areaServed) ? value.areaServed : [value.areaServed]).slice(0, 12)
          .map(a => scalar(typeof a === 'object' && a ? a.name : a)).filter(Boolean)});
    }
    // Whitelisted entity relationships only; never walk reviews, ratings, offers or arbitrary payloads.
    for (const key of ['@graph', 'mainEntity', 'department', 'subOrganization', 'location', 'publisher', 'provider'])
      if (value[key]) visitSchema(value[key], depth + 1);
  };
  const ld = [...document.querySelectorAll('script[type="application/ld+json"]')];
  for (const script of ld.slice(0, 24)) {
    schemaBytes += script.textContent.length;
    if (schemaBytes > 128000 || script.textContent.length > 64000) { schemaLimited = true; continue; }
    try { visitSchema(JSON.parse(script.textContent)); } catch { schemaInvalid++; }
  }
  if (ld.length > 24) schemaLimited = true;
  const microdataElements = [...document.querySelectorAll('[itemscope][itemtype]')];
  if (microdataElements.length > 60) schemaLimited = true;
  const microdata = microdataElements.slice(0, 60)
    .flatMap(el => el.getAttribute('itemtype').split(/\s+/).filter(t => /^https?:\/\/schema.org\/\w+$/.test(t)).map(t => t.split('/').pop()));
  const htexts = headings.slice(0, 60).map(el => ({level: Number(el.tagName[1]), text: clean(el.innerText, 160)}));
  const paragraphs = [...document.querySelectorAll('main p,article p,section p')].filter(visible);
  const addresses = [...document.querySelectorAll('address,[itemprop="streetAddress"]')].filter(visible).slice(0, 12).map(el => clean(el.innerText, 240));
  const localityMatches = [...bodyText.matchAll(/\b([A-Z][a-z]+(?:[ -][A-Z][a-z]+){0,3}),\s*(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b/g)]
    .slice(0, 20).map(m => clean(m[0], 100));
  const seoLinks = anchors.slice(0, 250).map(el => ({href: clean(el.href, 2048), text: clean(el.innerText, 120),
    navigation: !!el.closest('nav,header'), service_context: /services?|what we do/i.test(el.closest('section,article,nav')?.querySelector('h1,h2,h3,h4')?.innerText || '')}));
  const growth = {
    version: 'digital_growth_crawl_v1', title: clean(document.title, 240),
    descriptions: [...document.querySelectorAll('meta[name="description" i]')].slice(0, 4).map(el => clean(el.content, 320)),
    robots_meta: [...document.querySelectorAll('meta[name="robots" i],meta[name="googlebot" i]')].slice(0, 8)
      .map(el => ({agent: clean(el.name, 40).toLowerCase(), content: clean(el.content, 300).toLowerCase()})),
    canonicals: [...document.head.querySelectorAll('link[rel~="canonical" i]')].slice(0, 8).map(el => clean(el.href, 2048)),
    viewport: clean(document.querySelector('meta[name="viewport"]')?.content), headings: htexts,
    heading_count: headings.length, headings_complete: headings.length <= 60,
    schema: {entities: schemas.slice(0, 100), microdata_types: [...new Set(microdata)], invalid_json_count: schemaInvalid,
      script_count: ld.length, complete: !schemaLimited && schemas.length <= 100},
    images: {count: images.length, missing_alt: images.filter(el => !el.hasAttribute('alt')).length,
      empty_alt: images.filter(el => el.hasAttribute('alt') && !el.getAttribute('alt').trim()).length,
      dimensions_missing: images.filter(el => !el.hasAttribute('width') || !el.hasAttribute('height')).length,
      lazy: images.filter(el => el.loading === 'lazy').length},
    mixed_content: [...document.querySelectorAll('script[src],img[src],iframe[src],link[rel="stylesheet"][href],video[src],audio[src]')]
      .filter(el => /^(http:)/i.test(el.src || el.href)).length,
    visible_words: bodyText.trim().split(/\s+/).length, paragraphs: paragraphs.length,
    section_count: document.querySelectorAll('main section,article section').length,
    faq: htexts.some(h => /frequently asked|\bfaq\b|common questions/i.test(h.text)),
    breadcrumbs: !![...document.querySelectorAll('nav[aria-label*="breadcrumb" i],[itemtype$="/BreadcrumbList"]')].filter(visible).length,
    testimonials: htexts.some(h => /testimonials|customer reviews|what (?:our )?customers say/i.test(h.text)),
    video: !![...document.querySelectorAll('video')].filter(visible).length || iframes.some(i => /youtube.com|youtu.be|vimeo.com/.test(i.src)),
    addresses, visible_location_context: [...new Set(localityMatches)], links: seoLinks, links_complete: anchors.length <= 250,
    body_complete: document.readyState === 'complete' && bodyText.length < 150000,
    service_area_context: /\b(?:areas? we (?:serve|cover)|service areas?|serving (?:the )?[A-Z][a-z]+(?: [A-Z][a-z]+)?(?: area| and|,))/i.test(bodyText),
    // Supporting-detail presence only, not a word-count quality verdict.
    supporting_detail: paragraphs.some(el => el.innerText.trim().length >= 80),
    h1_body_overlap: htexts.filter(h => h.level === 1).some(h => h.text.toLowerCase().split(/[^a-z0-9]+/)
      .filter(w => w.length > 3).some(w => paragraphs.some(p => p.innerText.toLowerCase().includes(w))))
  };
  return {
    url: location.href, title: clean(document.title), ready_state: document.readyState,
    viewport: clean(document.querySelector('meta[name="viewport"]')?.content), http_status: httpStatus,
    blocked, soft_error: softError, soft_error_excerpt: softError ? clean(errorText) : "",
    body_available: !!document.body, text_length: bodyText.trim().length, link_count: anchors.length,
    limits_reached: count >= 10000 || anchors.length > 250 || allForms.length > 30 || contacts.length >= 150 || bodyText.length >= 150000,
    links, contacts: contacts.slice(0, 150), forms, ctas, resources, iframes, growth,
    generator: clean(document.querySelector('meta[name="generator"]')?.content),
    tracking: {ga: /gtag\(\s*['"]config['"]\s*,\s*['"]G-|google-analytics\.com|analytics\.js/.test(inline),
      gtm: /GTM-[A-Z0-9]+/.test(inline), meta_pixel: /fbq\(\s*['"]init['"]/.test(inline)},
    complete: document.readyState === 'complete' && count < 10000 && anchors.length <= 250 &&
      allForms.length <= 30 && contacts.length < 150 && bodyText.length < 150000,
    login_wall: !!document.querySelector('input[type="password"]') && /sign in|log in/i.test(document.title + ' ' + (document.querySelector('h1')?.innerText || ''))
  };
})()
