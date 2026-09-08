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
  return {
    url: location.href, title: clean(document.title), ready_state: document.readyState,
    viewport: clean(document.querySelector('meta[name="viewport"]')?.content), http_status: httpStatus,
    blocked, soft_error: softError, soft_error_excerpt: softError ? clean(errorText) : "",
    body_available: !!document.body, text_length: bodyText.trim().length, link_count: anchors.length,
    limits_reached: count >= 10000 || anchors.length > 250 || allForms.length > 30 || contacts.length >= 150 || bodyText.length >= 150000,
    links, contacts: contacts.slice(0, 150), forms, ctas, resources, iframes,
    generator: clean(document.querySelector('meta[name="generator"]')?.content),
    tracking: {ga: /gtag\(\s*['"]config['"]\s*,\s*['"]G-|google-analytics\.com|analytics\.js/.test(inline),
      gtm: /GTM-[A-Z0-9]+/.test(inline), meta_pixel: /fbq\(\s*['"]init['"]/.test(inline)},
    complete: document.readyState === 'complete' && count < 10000 && anchors.length <= 250 &&
      allForms.length <= 30 && contacts.length < 150 && bodyText.length < 150000,
    login_wall: !!document.querySelector('input[type="password"]') && /sign in|log in/i.test(document.title + ' ' + (document.querySelector('h1')?.innerText || ''))
  };
})()
