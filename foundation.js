'use strict';
// All untrusted content is rendered as text or assigned through DOM properties.
const $ = id => document.getElementById(id);
const fields = ['category', 'city', 'state', 'target_count', 'opportunity_profile'];
const pages = {dashboard: 'Dashboard', leadgen: 'Lead Generation', leads: 'Leads', settings: 'Settings'};
let token = localStorage.getItem('lead_engine_token') || '';
let offset = 0;
let pollGeneration = 0;
let currentUser = '';

function textElement(tag, text) {
  const element = document.createElement(tag);
  element.textContent = text == null || text === '' ? '—' : String(text);
  return element;
}

function showError(error) { $('app-error').textContent = error.message || 'Request failed.'; }

async function api(path, options = {}) {
  const headers = {'Authorization': `Bearer ${token}`, ...(options.headers || {})};
  if (options.body) headers['Content-Type'] = 'application/json';
  const response = await fetch(path, {...options, headers});
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Generic fallback */ }
    const error = new Error(typeof detail === 'string' ? detail : `Request failed (${response.status}).`);
    error.detail = detail;
    error.status = response.status;
    if (response.status === 401) logout();
    throw error;
  }
  return response;
}

function logout() {
  pollGeneration++;
  token = '';
  currentUser = '';
  localStorage.removeItem('lead_engine_token');
  $('layout').hidden = true;
  $('login-panel').hidden = false;
  $('lead-rows').replaceChildren();
  $('job-log').replaceChildren();
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
    let findings = lead.pain_points || '';
    try { const parsed = JSON.parse(findings); if (Array.isArray(parsed)) findings = parsed.join('; '); } catch { /* Render text. */ }
    row.append(textElement('td', lead.business_name), textElement('td', [lead.city, lead.country].filter(Boolean).join(', ')),
      websiteCell(lead.website), textElement('td', lead.email), textElement('td', lead.phone),
      textElement('td', lead.lead_score), textElement('td', findings));
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

async function pollJob(jid) {
  const generation = ++pollGeneration;
  let sequence = 0;
  $('lg-btn').disabled = true;
  $('job-log').replaceChildren();
  while (generation === pollGeneration && token) {
    try {
      const data = await (await api(`/api/leadgen/status/${encodeURIComponent(jid)}?after=${sequence}`)).json();
      if (generation !== pollGeneration) return;
      $('job-state').textContent = `Job ${data.job_id}: ${data.status}`;
      for (const event of data.events) $('job-log').append(textElement('li', event.message));
      while ($('job-log').children.length > 200) $('job-log').firstElementChild.remove();
      sequence = data.sequence;
      if (data.status !== 'running') {
        localStorage.removeItem('lead_engine_job_' + currentUser);
        $('lg-btn').disabled = false;
        return;
      }
    } catch (error) {
      $('job-state').textContent = 'Progress unavailable. Work may still be running. Reload to reconnect.';
      if (error.status === 404) {
        localStorage.removeItem('lead_engine_job_' + currentUser);
        $('job-state').textContent = 'Job no longer available. Jobs are lost after a server restart.';
        $('lg-btn').disabled = false;
        return;
      }
      showError(error);
    }
    await new Promise(resolve => setTimeout(resolve, 1500));
  }
}

async function enterWorkspace() {
  const user = await (await api('/api/auth/me')).json();
  currentUser = user.username;
  $('login-panel').hidden = true;
  $('layout').hidden = false;
  $('lg-btn').disabled = false;
  await showPage('dashboard');
  const jid = localStorage.getItem('lead_engine_job_' + currentUser);
  if (jid) void pollJob(jid);
}

async function loadSettings() {
  $('settings-form').hidden = true;
  try {
    const settings = await (await api('/api/config')).json();
    $('settings-status').textContent = `Concurrent jobs: ${settings.max_concurrent_tasks}. Outreach and public sending are disabled.`;
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
    token = (await response.json()).access_token;
    localStorage.setItem('lead_engine_token', token);
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
    localStorage.setItem('lead_engine_job_' + currentUser, data.job_id);
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
  } catch (error) { $('password-status').textContent = error.message; }
});
if (token) enterWorkspace().catch(error => { logout(); $('login-error').textContent = error.message; });
