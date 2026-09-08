'use strict';
// Render the server's qualification view using safe DOM properties only.
let selectedSearch = '';
let displayedSearch = '';
let leadsGeneration = 0;
let detailGeneration = 0;
let detailTrigger = null;
let displayedQuery = new URLSearchParams();

function safeLink(value, label) {
  const fallback = textElement('span', label || value || 'Website not verified');
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f\\]/.test(value)) return fallback;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port) return fallback;
    const link = textElement('a', label || value);
    link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    return link;
  } catch { return fallback; }
}

function small(text) { const node = textElement('small', text); node.className = 'secondary'; return node; }

function searchLabel(job) {
  const date = new Date(job.created_at);
  return `${job.category} · ${[job.city, job.state].filter(Boolean).join(', ')} · ${Number.isNaN(date.getTime()) ? '' : date.toLocaleString()} · ${job.discovered_count} businesses`;
}

function leadQuery() {
  const params = new URLSearchParams();
  if (selectedSearch) params.set('job_id', selectedSearch);
  for (const [id, key] of [['filter-audit', 'audit_status'], ['filter-opportunity', 'primary_opportunity'],
    ['filter-evidence', 'min_evidence'], ['filter-score', 'min_opportunity'], ['sort-leads', 'sort']]) {
    if ($(id).value !== '') params.set(key, $(id).value);
  }
  for (const [id, key] of [['filter-phone', 'has_phone'], ['filter-email', 'has_email'], ['filter-contact', 'has_contact']]) {
    if ($(id).checked) params.set(key, 'true');
  }
  return params;
}

async function loadLeads() {
  const generation = ++leadsGeneration;
  const params = leadQuery(); params.set('limit', '50'); params.set('offset', String(offset));
  $('lead-count').textContent = 'Loading this search…';
  $('export-leads').disabled = true;
  $('lead-results').setAttribute('aria-busy', 'true');
  let data, jobs;
  try {
    [data, jobs] = await Promise.all([
      api('/api/leads?' + params).then(response => response.json()),
      api('/api/leadgen/jobs').then(response => response.json())]);
  } catch (error) {
    if (generation === leadsGeneration) {
      $('lead-results').removeAttribute('aria-busy'); $('lead-rows').replaceChildren();
      $('lead-count').textContent = 'Results unavailable. Refresh to try again.';
      displayedSearch = ''; detailGeneration++;
    }
    throw error;
  }
  if (!signedIn || generation !== leadsGeneration) return;
  const options = [new Option('Latest search (automatic)', '')];
  for (const job of jobs) options.push(new Option(searchLabel(job), job.id));
  $('search-selector').replaceChildren(...options);
  $('search-selector').value = selectedSearch;
  displayedSearch = data.job?.id || '';
  displayedQuery = new URLSearchParams(params); displayedQuery.delete('limit'); displayedQuery.delete('offset');
  if (displayedSearch) displayedQuery.set('job_id', displayedSearch);
  $('current-search').textContent = data.job ? `Showing results from: ${searchLabel(data.job)}` : 'No search yet. Start a search to build your list.';
  renderLeads(data);
  $('export-leads').disabled = !data.job;
  $('lead-results').removeAttribute('aria-busy');
}

function renderLeads(data) {
  const rows = data.leads.map(lead => {
    const s = lead.summary, score = s.score_summary;
    const row = document.createElement('tr');
    const cell = (label, ...children) => {
      const td = document.createElement('td'); td.dataset.label = label; td.append(...children); return td;
    };
    const business = cell('Business', textElement('strong', s.business_name));
    if (s.commercially_usable_v2) {
      const usable = textElement('span', 'Usable lead'); usable.className = 'usable-label';
      usable.title = 'Enough website evidence and a public contact path to review. This does not indicate purchase intent.';
      business.append(usable);
    }
    const opportunity = cell('Opportunity', textElement('span', score.opportunity_display));
    if (score.opportunity_note && score.opportunity_display !== 'No confirmed gap') opportunity.append(small(score.opportunity_note));
    opportunity.title = score.tooltips.opportunity_score;
    const evidence = cell('Evidence', textElement('span', score.evidence_confidence == null ? 'Not assessed' : `${Math.round(score.evidence_confidence)} / 100`));
    evidence.title = score.tooltips.evidence_confidence;
    const contact = cell('Contact', textElement('span', s.contact_paths.join(' · ') || 'No path confirmed'),
      small(score.contact_confidence == null ? 'Confidence not assessed' : `${Math.round(score.contact_confidence)} / 100 confidence`));
    contact.title = score.tooltips.contact_confidence;
    const button = textElement('button', 'View evidence'); button.type = 'button'; button.className = 'btn btn-outline';
    button.addEventListener('click', () => showDetail(lead.id, button).catch(showError));
    row.append(business, cell('Location', textElement('span', s.location)),
      cell('Website', safeLink(s.website, s.website_display)), cell('Primary opportunity', textElement('span', s.primary_opportunity)),
      opportunity, evidence, contact, cell('Audit status', textElement('span', s.audit_summary.label)), cell('Details', button));
    return row;
  });
  $('lead-rows').replaceChildren(...rows);
  $('lead-empty').hidden = rows.length > 0;
  $('lead-empty').textContent = data.job ? 'No businesses match these filters in this search. Clear filters or choose another search.' : 'Your results will appear here after a search.';
  $('lead-count').textContent = `${data.total} businesses · ${offset + (rows.length ? 1 : 0)}–${offset + rows.length} shown`;
  $('previous-page').disabled = offset === 0;
  $('next-page').disabled = offset + rows.length >= data.total;
}

function disclosure(label, ...children) {
  const details = document.createElement('details'); details.append(textElement('summary', label), ...children); return details;
}

function section(title, ...children) {
  const node = document.createElement('section'); node.className = 'qualification-section';
  node.append(textElement('h3', title), ...children); return node;
}

function contactCard(contact, label, linked = false) {
  const node = document.createElement('div'); node.className = 'contact-card';
  node.append(small(label), linked ? safeLink(contact.value, contact.display) : textElement('strong', contact.display),
    small(`Observed on ${contact.observed_pages} ${contact.observed_pages === 1 ? 'page' : 'pages'} · ${contact.confidence_label} confidence`));
  const sources = document.createElement('ul');
  for (const url of contact.source_urls) { const item = document.createElement('li'); item.append(safeLink(url, cleanDisplayURL(url))); sources.append(item); }
  node.append(disclosure('Observation sources', sources));
  return node;
}

function cleanDisplayURL(value) {
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) if (['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid'].includes(key.toLowerCase())) url.searchParams.delete(key);
    return url.host + url.pathname + url.search + url.hash;
  } catch { return value || 'No page loaded'; }
}

function findingList(findings, empty, unknown = false) {
  if (!findings.length) return textElement('p', empty);
  const list = document.createElement('ul'); list.className = 'finding-list';
  for (const finding of findings) {
    const item = textElement('li', finding.label);
    if (unknown) item.append(' ', statusBadge(finding.status));
    list.append(item);
  }
  return list;
}

function scoreCards(score) {
  const cards = document.createElement('div'); cards.className = 'qualification-scores';
  for (const [key, label] of [['opportunity_score', 'Opportunity'], ['digital_gap', 'Digital Gap'], ['evidence_confidence', 'Evidence Confidence'], ['contact_confidence', 'Contact Confidence']]) {
    const card = document.createElement('div'); card.className = 'qualification-score';
    const value = key === 'opportunity_score' ? score.opportunity_display + (score.sufficient && score.opportunity_score > 0 ? ' / 100' : '')
      : key === 'digital_gap' && !score.sufficient ? 'Not enough evidence'
      : score[key] == null ? 'Not assessed' : `${Math.round(score[key])} / 100`;
    card.append(small(label), textElement('strong', value));
    const tooltip = score.tooltips[key] || 'Digital Gap is the stored conversion-gap score for the assessed checks.';
    card.append(disclosure(`About ${label}`, textElement('p', tooltip)));
    if (key === 'opportunity_score' && score.opportunity_note && score.opportunity_display !== 'No confirmed gap') card.append(small(score.opportunity_note));
    cards.append(card);
  }
  return cards;
}

function technicalEvidence(detail) {
  const list = document.createElement('div'); list.className = 'evidence-list';
  for (const e of detail.evidence) {
    const card = document.createElement('section'); card.className = 'evidence-card';
    const heading = textElement('h4', e.detector_key); heading.append(' ', statusBadge(e.status));
    card.append(heading, textElement('p', `Value: ${e.value == null ? 'No measured value' : typeof e.value === 'object' ? JSON.stringify(e.value) : e.value}`),
      safeLink(e.source_url, e.source_url || 'No page loaded'),
      textElement('p', `Evidence ID: ${e.id} · ${e.page_type || 'audit'} · ${e.observed_at || 'No timestamp'}`),
      textElement('p', `${Math.round((e.confidence || 0) * 100)}% confidence · ${e.detector_version || 'No version'} · ${e.locator || 'No locator'}`));
    if (e.excerpt) card.append(textElement('blockquote', e.excerpt));
    list.append(card);
  }
  const contacts = textElement('pre', JSON.stringify(detail.contacts, null, 2));
  return disclosure('Show technical evidence', textElement('p', `${detail.evidence.length} evidence observations · ${detail.history.length} audit run(s) in this search. Raw values and source URLs are preserved.`),
    list, disclosure('Raw contact observations', contacts), disclosure('Stored score breakdown', textElement('pre', JSON.stringify(detail.score, null, 2))));
}

async function showDetail(bid, trigger) {
  const generation = ++detailGeneration, search = displayedSearch, user = currentUser;
  const query = search ? '?job_id=' + encodeURIComponent(search) : '';
  trigger.disabled = true;
  let detail;
  try { detail = await (await api(`/api/businesses/${encodeURIComponent(bid)}${query}`)).json(); }
  finally { trigger.disabled = false; }
  if (!signedIn || currentUser !== user || generation !== detailGeneration || search !== displayedSearch) return;
  detailTrigger = trigger;
  const s = detail.summary, score = s.score_summary;
  $('detail-title').textContent = s.business_name;
  const identity = document.createElement('div'); identity.className = 'business-identity';
  identity.append(textElement('p', s.location ? `${s.location} · Search location` : 'Location not verified'), safeLink(s.website, s.website_display));
  const audit = section('Audit summary', textElement('strong', s.audit_summary.label), textElement('p', s.audit_summary.explanation));
  if (s.audit_summary.observed_at) audit.append(small('Last observed: ' + new Date(s.audit_summary.observed_at).toLocaleString()));
  audit.append(scoreCards(score));
  const primary = section('Primary opportunity', textElement('strong', s.primary_opportunity)); primary.classList.add('primary-opportunity');
  const contacts = document.createElement('div'); contacts.className = 'contact-grid';
  if (s.primary_phone) contacts.append(contactCard(s.primary_phone, 'Primary phone'));
  if (s.primary_email) contacts.append(contactCard(s.primary_email, 'Email'));
  if (s.contact_page) contacts.append(contactCard(s.contact_page, 'Contact page', true));
  const contactSection = section('Public contact', contacts, textElement('p', s.contact_paths.length ? `Contact paths: ${s.contact_paths.join(' · ')}` : 'No public contact path confirmed. No contacts were guessed.'));
  if (s.phone_selection) contactSection.append(small(s.phone_selection));
  if (s.other_phones.length) contactSection.append(disclosure(`Other public numbers (${s.other_phones.length})`, ...s.other_phones.map(c => contactCard(c, c.label))));
  if (s.other_emails.length) contactSection.append(disclosure(`Other public emails (${s.other_emails.length})`, ...s.other_emails.map(c => contactCard(c, 'Additional public email'))));
  if (s.socials.length) contactSection.append(disclosure(`Public social profiles (${s.socials.length})`, ...s.socials.map(c => contactCard(c, friendly(c.platform), true))));
  const pageCards = document.createElement('div'); pageCards.className = 'page-cards';
  for (const p of s.pages) {
    const card = document.createElement('div'); card.className = 'page-card';
    card.append(textElement('strong', p.label), small(friendly(p.status)), safeLink(p.url, p.display_url)); pageCards.append(card);
  }
  const why = section('Why this score', textElement('h4', 'Confirmed conversion gaps'), findingList(score.gaps, 'No confirmed conversion gap in the scored checks.'),
    textElement('h4', 'Confirmed strengths'), findingList(score.strengths, 'No scored strength could be confirmed.'),
    textElement('p', 'Unknown checks were excluded from scoring. Gaps describe the pages assessed.'),
    small(score.profile_version || 'Scoring not available'));
  $('detail-content').replaceChildren(identity, audit, primary, contactSection,
    section('Confirmed strengths', findingList(s.confirmed_strengths, 'No strengths could be confirmed.')),
    section('Confirmed gaps', findingList(s.confirmed_gaps, 'No conversion gaps were confirmed.')),
    section('Could not confirm', textElement('p', 'These checks could not be assessed reliably and are not treated as missing features.'), findingList(s.unknown_checks, 'All displayed checks were assessed.', true)),
    section('Pages inspected', pageCards), why, technicalEvidence(detail));
  $('business-detail').showModal(); $('business-detail').scrollTop = 0; $('close-detail').focus();
}

function resetQualification() {
  leadsGeneration++; detailGeneration++; selectedSearch = ''; displayedSearch = ''; detailTrigger = null; offset = 0;
  displayedQuery = new URLSearchParams();
  $('lead-filters').reset(); $('search-selector').replaceChildren(new Option('Latest search (automatic)', ''));
  $('current-search').textContent = ''; $('lead-count').textContent = '';
}

function initializeQualification() {
  $('search-selector').addEventListener('change', () => {
    selectedSearch = $('search-selector').value; offset = 0; detailGeneration++; loadLeads().catch(showError);
  });
  $('lead-filters').addEventListener('submit', event => { event.preventDefault(); offset = 0; loadLeads().catch(showError); });
  $('clear-lead-filters').addEventListener('click', () => { $('lead-filters').reset(); offset = 0; loadLeads().catch(showError); });
  $('business-detail').addEventListener('close', () => { detailGeneration++; if (detailTrigger?.isConnected && signedIn) detailTrigger.focus(); });
}
