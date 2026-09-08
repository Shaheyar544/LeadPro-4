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
  resetQualification();
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
    selectedSearch = ''; offset = 0;
    void pollJob(data.job_id);
  } catch (error) {
    $('lg-btn').disabled = false;
    validationErrors(Array.isArray(error.detail) ? error.detail : [{msg: error.message}]);
  }
});
$('export-leads').addEventListener('click', async () => {
  try {
    // One CSV implementation, on the server. No browser-side cell serialization.
    const blob = await (await api('/api/leads/export/csv?' + displayedQuery)).blob();
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
initializeQualification();
initializeAuthentication().catch(error => { $('login-error').textContent = error.message; });
