'use strict';
// All untrusted content is rendered as text or assigned through DOM properties.
const $ = id => document.getElementById(id);
const fields = ['category', 'city', 'state', 'target_count', 'opportunity_profile'];
const pages = {dashboard: 'Dashboard', leadgen: 'Lead Generation', leads: 'Leads', settings: 'Settings'};
// Compatibility is enabled only by the legacy development server's mode route.
let authMode = 'cookie';
let token = ''; // Development-only, memory-only legacy credential.
let csrfToken = '';
let signedIn = false;
let offset = 0;
let pollGeneration = 0;
let currentUser = '';
let activeJob = '';

function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text == null || text === '' ? '—' : String(text);
  return element;
}

function showError(error) { $('app-error').textContent = error.message || 'Request failed.'; }

async function api(path, options = {}) {
  const headers = {...(options.headers || {})};
  if (authMode === 'legacy-development' && token) headers.Authorization = `Bearer ${token}`;
  if (authMode === 'cookie' && !['GET', 'HEAD'].includes(options.method || 'GET')) headers['X-CSRF-Token'] = csrfToken;
  if (options.body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {...options, headers, credentials: 'same-origin'});
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Generic fallback */ }
    const error = new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`);
    error.detail = detail;
    error.status = response.status;
    if (response.status === 401) clearSession();
    throw error;
  }
  return response;
}

function clearSession() {
  pollGeneration++;
  token = '';
  currentUser = '';
  csrfToken = '';
  signedIn = false;
  $('layout').hidden = true;
  $('login-panel').hidden = false;
  $('lead-rows').replaceChildren();
  $('job-log').replaceChildren();
  $('recent-jobs').replaceChildren();
  $('detail-content').replaceChildren();
  $('business-detail').close();
  activeJob = '';
}

async function showPage(page) {
  if (!Object.hasOwn(pages, page)) return;
  $('app-error').textContent = '';
  for (const name of Object.keys(pages)) $('page-' + name).classList.toggle('active', name === page);
  for (const button of document.querySelectorAll('[data-page]')) {
    const active = button.dataset.page === page;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  $('page-title').textContent = pages[page];
  try {
    if (page === 'dashboard') await loadStats();
    if (page === 'leads') await loadLeads();
    if (page === 'settings') await loadSettings();
    if (page === 'leadgen') await loadJobs();
  } catch (error) { showError(error); }
}

async function loadStats() {
  const data = await (await api('/api/stats')).json();
  for (const [id, key] of [['s-total', 'total'], ['s-email', 'with_email'], ['s-website', 'with_website'], ['s-jobs', 'active_jobs']]) {
    $(id).textContent = data[key];
  }
}

function websiteCell(value) {
  const cell = textElement('td', value);
  if (typeof value !== 'string' || /[\u0000-\u0020\u007f\\]/.test(value)) return cell;
  try {
    const url = new URL(value);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.port) return cell;
    const link = textElement('a', value);
    link.href = url.href;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    cell.replaceChildren(link);
  } catch { /* Malformed and scheme-less URLs remain plain text. */ }
  return cell;
}

function renderLeads(data) {
  const rows = [];
  for (const lead of data.leads) {
    const row = document.createElement('tr');
    const detailButton = textElement('button', 'View evidence');
    detailButton.type = 'button'; detailButton.className = 'btn btn-outline';
    detailButton.addEventListener('click', () => showDetail(lead.id).catch(showError));
    const detailCell = document.createElement('td'); detailCell.append(detailButton);
    row.append(textElement('td', lead.business_name), textElement('td', [lead.city, lead.state].filter(Boolean).join(', ')),
      websiteCell(lead.website), textElement('td', lead.opportunity_score), textElement('td', lead.digital_gap),
      textElement('td', lead.evidence_confidence), textElement('td', lead.contact_confidence),
      textElement('td', friendly(lead.primary_opportunity)), textElement('td', lead.audit_status), detailCell);
    rows.push(row);
  }
  $('lead-rows').replaceChildren(...rows);
  $('lead-count').textContent = `${data.total} businesses · ${offset + (data.leads.length ? 1 : 0)}–${offset + data.leads.length} shown`;
  $('previous-page').disabled = offset === 0;
  $('next-page').disabled = offset + data.leads.length >= data.total;
}

async function loadLeads() {
  renderLeads(await (await api(`/api/leads?limit=50&offset=${offset}`)).json());
}

function clearValidation() {
  $('lg-errors').hidden = true;
  $('lg-errors').replaceChildren();
  for (const field of fields) {
    $(field).removeAttribute('aria-invalid');
    $(field + '-error').textContent = '';
  }
}

function validationErrors(errors) {
  const summary = $('lg-errors');
  summary.replaceChildren(textElement('h3', 'Please check these fields'));
  const list = document.createElement('ul');
  for (const error of errors) {
    const field = error.loc && error.loc[error.loc.length - 1];
    const item = document.createElement('li');
    if (fields.includes(field)) {
      $(field).setAttribute('aria-invalid', 'true');
      $(field + '-error').textContent = error.msg;
      const link = textElement('a', `${$(field).labels[0].textContent}: ${error.msg}`);
      link.href = '#' + field;
      link.addEventListener('click', () => $(field).focus());
      item.append(link);
    } else item.textContent = error.msg;
    list.append(item);
  }
  summary.append(list);
  summary.hidden = false;
  summary.focus();
}

async function loadJobs() {
  const jobs = await (await api('/api/leadgen/jobs')).json();
  $('recent-jobs').replaceChildren(...jobs.map(job => {
    const item = document.createElement('li');
    const button = textElement('button', `${job.category} · ${job.city}, ${job.state} · ${job.status}`);
    button.type = 'button'; button.className = 'btn btn-outline';
    button.addEventListener('click', () => { void pollJob(job.id); }); item.append(button); return item;
  }));
  return jobs;
}

async function pollJob(jid) {
  const generation = ++pollGeneration;
  activeJob = jid;
  $('lg-btn').disabled = true;
  while (generation === pollGeneration && signedIn) {
    try {
      const data = await (await api(`/api/leadgen/jobs/${encodeURIComponent(jid)}`)).json();
      if (generation !== pollGeneration) return;
      const active = ['queued', 'running'].includes(data.status);
      $('job-state').textContent = `${data.category} in ${data.city}, ${data.state}: ${data.status}${data.cancel_requested && active ? ' · cancellation requested' : ''}`;
      $('job-log').replaceChildren(
        textElement('li', `Discovered ${data.discovered_count} / ${data.target_count} target`),
        textElement('li', `Processed ${data.processed_count} · Assessable businesses ${data.qualified_count}`),
        textElement('li', data.error_message || 'Progress is saved to the database.'));
      $('cancel-job').disabled = !active || Boolean(data.cancel_requested);
      if (!active) {
        $('lg-btn').disabled = false;
        await loadJobs();
        return;
      }
    } catch (error) {
      $('job-state').textContent = 'Progress unavailable. Reload to reconnect to the saved job.';
      if (error.status === 404) {
        $('lg-btn').disabled = false;
        $('cancel-job').disabled = true;
        return;
      }
      showError(error);
    }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

function friendly(value) { return value ? String(value).replaceAll('_', ' ') : 'Not assessed'; }

function statusBadge(value) {
  const allowed = ['present', 'absent', 'unknown', 'blocked', 'failed', 'not_applicable'];
  const status = allowed.includes(value) ? value : 'unknown';
  const span = textElement('span', friendly(status)); span.className = 'evidence-status status-' + status; return span;
}

async function showDetail(bid) {
  const sessionUser = currentUser;
  const detail = await (await api(`/api/businesses/${encodeURIComponent(bid)}`)).json();
  if (!signedIn || currentUser !== sessionUser) return;
  const business = detail.business, score = detail.score;
  $('detail-title').textContent = business.canonical_name;
  const nodes = [textElement('p', [business.category, business.city, business.state, business.address].filter(Boolean).join(' · ')),
    textElement('p', `Audit: ${detail.audit?.status || 'pending'} · Observed: ${detail.audit?.finished_at || 'not yet'} · ${detail.audit?.error_message || ''}`)];
  nodes.push(textElement('h3', 'Sources and website'));
  const sources = document.createElement('ul');
  for (const source of detail.sources) {
    const item = textElement('li', `${source.provider} · ${source.provider_record_id} · ${source.source_url || 'No source URL'} · ${source.observed_at}`); sources.append(item);
  }
  nodes.push(sources, textElement('p', business.website_url || 'No authoritative website supplied.'));
  nodes.push(textElement('h3', 'Scores and confidence'));
  if (score) {
    const scores = document.createElement('dl'); scores.className = 'score-grid';
    for (const key of ['opportunity_score', 'digital_gap', 'business_strength', 'evidence_confidence', 'contact_confidence']) {
      scores.append(textElement('dt', friendly(key)), textElement('dd', score[key] == null ? 'Unknown' : `${score[key]} / 100`));
    }
    nodes.push(scores, textElement('p', `${score.profile_version}: ${score.breakdown.formula}. ${score.breakdown.fallback ? 'Fallback: ' + friendly(score.breakdown.fallback) + '.' : ''}`));
    nodes.push(textElement('p', 'Unknown, blocked and failed checks do not count as missing features. Absence refers only to the pages assessed. Mobile layout is a Firefox overflow check.'));
  } else nodes.push(textElement('p', 'Scoring has not finished.'));
  nodes.push(textElement('h3', 'Public business contacts'));
  const contacts = document.createElement('ul');
  for (const c of detail.contacts) contacts.append(textElement('li', `${c.normalized_value} · ${friendly(c.evidence_type)} · ${Math.round(c.confidence * 100)}% confidence · ${c.source_url || 'Provider source unavailable'} · ${c.excerpt || ''}`));
  if (!detail.contacts.length) contacts.append(textElement('li', 'No public contacts observed. No contacts were guessed.'));
  nodes.push(contacts, textElement('h3', 'Pages inspected'));
  const pageList = document.createElement('ul');
  for (const page of detail.pages) pageList.append(textElement('li', `${page.page_type}: ${page.status} · ${page.final_url || page.url} · ${page.title || ''} · ${page.navigation_ms ?? 'unknown'} ms navigation (diagnostic only)`));
  nodes.push(pageList, textElement('h3', 'Evidence and score explanation'));
  const evidenceList = document.createElement('div'); evidenceList.className = 'evidence-list';
  const findingMap = score?.breakdown?.findings || {};
  for (const [key, finding] of Object.entries(findingMap)) {
    const section = document.createElement('section'); section.className = 'evidence-card';
    const heading = textElement('h4', friendly(key)); heading.append(' ', statusBadge(finding.status)); section.append(heading);
    const component = (score.breakdown.components || []).find(c => c.detector_key === key);
    if (component) section.append(textElement('p', `Scoring status: ${friendly(component.status)} · Weight ${component.weight} · Gap points: ${component.gap_points ?? 'excluded'}`));
    for (const e of detail.evidence.filter(e => e.detector_key === key)) {
      section.append(textElement('p', `${friendly(e.status)} · ${e.value == null ? 'No measured value' : typeof e.value === 'object' ? JSON.stringify(e.value) : e.value}`),
        textElement('p', `${e.source_url || 'No page loaded'} · ${e.page_type || 'audit'} · ${e.observed_at}`),
        textElement('p', `${Math.round(e.confidence * 100)}% confidence · ${e.detector_version} · ${e.locator || 'No locator'}`));
      if (e.excerpt) section.append(textElement('blockquote', e.excerpt));
    }
    evidenceList.append(section);
  }
  nodes.push(evidenceList, textElement('p', `${detail.history.length} audit run(s) retained for this business.`));
  $('detail-content').replaceChildren(...nodes);
  $('business-detail').showModal(); $('close-detail').focus();
}

$('close-detail').addEventListener('click', () => $('business-detail').close());
$('cancel-job').addEventListener('click', async () => {
  if (!activeJob) return;
  $('cancel-job').disabled = true;
  try { await api(`/api/leadgen/jobs/${encodeURIComponent(activeJob)}/cancel`, {method: 'POST'}); }
  catch (error) { showError(error); $('cancel-job').disabled = false; }
});
$('check-browser').addEventListener('click', async () => {
  $('browser-health').textContent = 'Checking browser service…';
  try {
    const health = await (await api('/api/browser/health')).json();
    $('browser-health').textContent = `${health.provider}: ${friendly(health.status)} · REST contract ${health.contract_version}`;
  } catch (error) { showError(error); }
});

async function enterWorkspace() {
  const user = await (await api('/api/auth/me')).json();
  currentUser = user.username;
  csrfToken = user.csrf_token || '';
  signedIn = true;
  $('login-panel').hidden = true;
  $('layout').hidden = false;
  $('lg-btn').disabled = false;
  await showPage('dashboard');
  const jobs = await loadJobs();
  const resume = jobs.find(job => ['queued', 'running'].includes(job.status));
  if (resume) void pollJob(resume.id);
}

async function loadSettings() {
  $('settings-form').hidden = true;
  try {
    const settings = await (await api('/api/config')).json();
    $('settings-status').textContent = `Concurrent jobs: ${settings.max_concurrent_tasks}. Outreach and public sending are disabled.`;
    if (settings.editable === false) {
      $('settings-status').textContent += ' Provider settings are managed by the operator.';
      return;
    }
    const nodes = [];
    for (const [key, configured] of Object.entries(settings.providers)) {
      const group = document.createElement('div');
      group.className = 'form-group';
      const label = textElement('label', `${key} — ${configured ? 'configured' : 'not configured'}`);
      const input = document.createElement('input');
      input.type = 'password'; input.id = 'key-' + key; input.name = key;
      input.autocomplete = 'new-password'; input.maxLength = 512;
      label.htmlFor = input.id;
      group.append(label, input); nodes.push(group);
    }
    $('provider-fields').replaceChildren(...nodes);
    $('settings-form').hidden = false;
  } catch (error) {
    if (error.status === 403) $('settings-status').textContent = 'Provider configuration requires an administrator.';
    else throw error;
  }
}

$('login-form').addEventListener('submit', async event => {
  event.preventDefault(); $('login-error').textContent = '';
  const button = event.currentTarget.querySelector('button'); button.disabled = true;
  try {
    const response = await api('/api/auth/login', {method: 'POST', body: JSON.stringify({username: $('username').value, password: $('password').value})});
    const session = await response.json();
    if (authMode === 'legacy-development') token = session.access_token;
    else csrfToken = session.csrf_token;
    $('password').value = '';
    await enterWorkspace();
  } catch (error) { $('login-error').textContent = error.message; }
  finally { button.disabled = false; }
});
$('logout-btn').addEventListener('click', logout);
$('theme-toggle').addEventListener('click', () => document.body.classList.toggle('theme-light'));
for (const button of document.querySelectorAll('[data-page]')) button.addEventListener('click', () => showPage(button.dataset.page));
$('new-search').addEventListener('click', () => showPage('leadgen'));
$('refresh-leads').addEventListener('click', () => loadLeads().catch(showError));
$('previous-page').addEventListener('click', () => { offset = Math.max(0, offset - 50); loadLeads().catch(showError); });
$('next-page').addEventListener('click', () => { offset += 50; loadLeads().catch(showError); });
$('leadgen-form').addEventListener('submit', async event => {
  event.preventDefault(); clearValidation();
  const invalid = fields.filter(field => !$(field).validity.valid).map(field => ({loc: ['body', field], msg: $(field).validationMessage}));
  if (invalid.length) return validationErrors(invalid);
  const body = Object.fromEntries(fields.map(field => [field, $(field).value]));
  body.target_count = Number(body.target_count);
  $('lg-btn').disabled = true;
  try {
    const data = await (await api('/api/leadgen/start', {method: 'POST', body: JSON.stringify(body)})).json();
    void pollJob(data.job_id);
  } catch (error) {
    $('lg-btn').disabled = false;
    validationErrors(Array.isArray(error.detail) ? error.detail : [{msg: error.message}]);
  }
});
$('export-leads').addEventListener('click', async () => {
  try {
    // One CSV implementation, on the server. No browser-side cell serialization.
    const blob = await (await api('/api/leads/export/csv')).blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = 'leads.csv';
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { showError(error); }
});
$('settings-form').addEventListener('submit', async event => {
  event.preventDefault();
  const updates = {};
  for (const input of $('provider-fields').querySelectorAll('input')) if (input.value.trim()) updates[input.name] = input.value.trim();
  try {
    const data = await (await api('/api/config', {method: 'PUT', body: JSON.stringify(updates)})).json();
    for (const input of $('provider-fields').querySelectorAll('input')) input.value = '';
    $('settings-status').textContent = data.message;
  } catch (error) { showError(error); }
});
$('password-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('/api/auth/change-password', {method: 'POST', body: JSON.stringify({old_password: $('old-password').value, new_password: $('new-password').value})});
    $('old-password').value = ''; $('new-password').value = '';
    $('password-status').textContent = 'Password updated.';
    if (authMode === 'cookie') {
      clearSession();
      $('login-error').textContent = 'Password updated. Sign in again.';
    }
  } catch (error) { $('password-status').textContent = error.message; }
});
async function logout() {
  try {
    if (authMode === 'cookie' && signedIn) await api('/api/auth/logout', {method: 'POST'});
    clearSession();
  } catch (error) { showError(error); }
}

async function initializeAuthentication() {
  const response = await fetch('/api/auth/mode', {credentials: 'same-origin'});
  if (!response.ok) throw new Error('Authentication configuration unavailable.');
  const mode = await response.json();
  $('run-mode-banner').hidden = mode.run_mode !== 'offline_test';
  authMode = mode.production === false && mode.mode === 'legacy-development' ? 'legacy-development' : 'cookie';
  if (authMode === 'cookie') {
    try { await enterWorkspace(); }
    catch (error) { clearSession(); if (error.status !== 401) $('login-error').textContent = error.message; }
  }
}
initializeAuthentication().catch(error => { $('login-error').textContent = error.message; });
