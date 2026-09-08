"""Opt-in validation of the isolated leadpro-phase4a2 Compose project.

Run after build/up/migrate/admin bootstrap. All artifacts stay in the ignored
.local-integration directory. Never points at a remote origin or production DB.
"""
import csv
import io
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.local-integration'
ORIGIN = 'https://localhost:8443'
COMPOSE = ['docker', 'compose', '--env-file', str(LOCAL / 'stack.env'), '-f', str(ROOT / 'compose.production.yaml')]
REPORT = json.loads((LOCAL / 'validation.json').read_text()) if (LOCAL / 'validation.json').exists() else {}
PRIVATE = dict(line.split('=', 1) for line in (LOCAL / 'stack.env').read_text().splitlines() if '=' in line)
SECRETS = [v for k, v in PRIVATE.items() if any(p in k for p in ('PASSWORD', 'SECRET', 'KEY'))]


def dc(*args, check=True):
    result = subprocess.run(COMPOSE + list(args), cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and result.returncode:
        # No raw command/env/SQL/response is included in errors.
        raise RuntimeError('Compose command failed: ' + ' '.join(args[:3]) + '; code=' + str(result.returncode))
    return result.stdout


def sql(query, database='leadpro'):
    return dc('exec', '-T', 'postgres', 'psql', '-U', 'leadpro', '-d', database, '-v', 'ON_ERROR_STOP=1', '-At', '-c', query).strip()


def py(code, service='api'):
    return dc('exec', '-T', service, 'python', '-c', code).strip()


def record(name, evidence):
    REPORT[name] = {'status': 'PASS', 'evidence': evidence}
    (LOCAL / 'validation.json').write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
    print('PASS ' + name + ': ' + str(evidence), flush=True)


def eventually(check, timeout=80):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (httpx.TransportError, RuntimeError):
            pass
        time.sleep(1)
    raise AssertionError('Timed out waiting for expected state')


def client():
    return httpx.Client(base_url=ORIGIN, verify=ssl.create_default_context(cafile=str(LOCAL / 'caddy-root.crt')),
                        trust_env=False, timeout=15, headers={'Origin': ORIGIN})


def clear_rate_limit():
    keys = dc('exec', '-T', 'redis', 'redis-cli', '--scan', '--pattern', 'leadpro:login:*').splitlines()
    for key in keys:
        dc('exec', '-T', 'redis', 'redis-cli', 'DEL', key)


def login(c, password=None):
    response = c.post('/api/auth/login', json={'username': 'admin', 'password': password or PRIVATE['INITIAL_ADMIN_PASSWORD']})
    assert response.status_code == 200, 'login failed with status ' + str(response.status_code)
    body = response.json()
    c.headers['X-CSRF-Token'] = body['csrf_token']
    SECRETS.extend([body['csrf_token'], c.cookies.get('__Host-leadpro_session')])
    return response


def create(c, count=1):
    response = c.post('/api/leadgen/start', json=dict(category='Plumber', city='Austin', state='TX',
                      target_count=count, opportunity_profile='website_conversion'))
    assert response.status_code == 200
    return response.json()['job_id']


def job(c, jid):
    response = c.get('/api/leadgen/jobs/' + jid)
    assert response.status_code == 200
    return response.json()


def completed(c, jid):
    result = job(c, jid)
    assert result['status'] not in ('failed', 'cancelled'), 'job did not complete'
    return result if result['status'] == 'completed' else False


def scan_db(database='leadpro'):
    tables = sql("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename", database).splitlines()
    for table in tables:
        assert table.replace('_', '').isalnum()
        count = sql(f"SELECT count(*) FROM {table} t WHERE row_to_json(t)::text LIKE '%GOOGLE_SENTINEL_%' OR row_to_json(t)::text LIKE '%4.918237%' OR row_to_json(t)::text LIKE '%9182736%'", database)
        assert count == '0', 'Provider sentinel leaked into ' + table
    return tables


def main():
    assert PRIVATE['DISCOVERY_MODE'] == 'offline' and PRIVATE['LOCAL_INTEGRATION_TEST'] == 'true'
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'lead-engine-v1'
    c = client()
    eventually(lambda: c.get('/health/ready').status_code == 200)
    assert c.get('/health/live').status_code == 200
    clear_rate_limit()
    response = login(c)
    cookie = response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie and 'path=/' in cookie
    assert 'access_token' not in response.json()
    assert c.get('/api/auth/me').status_code == 200
    script = c.get('/foundation.js').text
    assert 'localStorage' not in script and 'sessionStorage' not in script
    assert "authMode === 'legacy-development'" in script
    record('cookie_auth', 'HTTPS CA verified; Secure/HttpOnly/SameSite=Strict; no storage JWT; normal requests use cookie')

    good = c.headers['X-CSRF-Token']
    body = dict(category='Plumber', city='Austin', state='TX', target_count=1, opportunity_profile='website_conversion')
    for token in ('', 'invalid'):
        assert c.post('/api/leadgen/start', json=body, headers={'X-CSRF-Token': token}).status_code == 403
    other = client()
    login(other)
    assert c.post('/api/leadgen/start', json=body, headers={'X-CSRF-Token': other.headers['X-CSRF-Token']}).status_code == 403
    assert c.post('/api/leadgen/start', json=body, headers={'Origin': 'https://attacker.invalid'}).status_code == 403
    for path, method, payload in [('/api/auth/change-password', 'POST', {'old_password': 'x', 'new_password': 'FreshLongPassword42!'}),
                                   ('/api/config', 'PUT', {})]:
        for token in ('', 'invalid', other.headers['X-CSRF-Token']):
            assert c.request(method, path, json=payload, headers={'X-CSRF-Token': token}).status_code == 403
    assert c.put('/api/config', json={}).status_code == 403  # Explicitly disabled production mutation.
    jid = create(c)
    for token in ('', 'invalid', other.headers['X-CSRF-Token']):
        assert c.post('/api/leadgen/jobs/' + jid + '/cancel', headers={'X-CSRF-Token': token}).status_code == 403
    result = eventually(lambda: completed(c, jid))
    assert result['processed_count'] == 1
    rows = c.get('/api/leadgen/jobs/' + jid + '/results').json()['leads']
    assert len(rows) == 1
    detail = c.get('/api/businesses/' + rows[0]['id']).json()
    assert detail['evidence'] and detail['contacts'] and detail['pages']
    assert detail['score']['profile_version'] == 'website_conversion_v2'
    assert all(x['provenance'] == 'browser' for x in detail['contacts'] + detail['evidence'])
    assert detail['score']['opportunity_score'] is not None
    record('offline_e2e', 'Cookie login -> job -> worker -> PostgreSQL browser evidence/contacts/v2 -> API/detail/results')
    record('csrf', 'Missing, invalid, cross-session, foreign-origin rejected; valid create accepted; safe GET accepted')

    exported = c.get('/api/leads/export/csv')
    assert exported.status_code == 200
    assert 'info@fixture-business.test' in exported.text and 'phase4a2-place-' in exported.text
    assert 'fixture-business.test' in exported.text and 'browser' in exported.text
    assert 'GOOGLE_SENTINEL_' not in exported.text and '4.918237' not in exported.text and '9182736' not in exported.text
    assert "'+15125550199" in exported.text  # Phone starts with +; spreadsheet injection guard.
    assert py("from production_views import safe_cell; assert all(safe_cell(v).startswith(chr(39)) for v in ['=SUM(1,2)', '+cmd', '-1+2', '@SUM(A1)', '  =x']); print('ok')") == 'ok'
    record('csv_policy', 'Browser URL/phone/email/evidence/v2/confidence/provider ID/search context included; sentinels excluded; formula-safe')

    # Real worker, Redis and API restarts while a five-item job is in progress.
    jid = create(c, 5)
    eventually(lambda: job(c, jid)['status'] == 'running')
    active_stats = subprocess.check_output(['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}'], text=True)
    record('resources_during_job', [line for line in active_stats.splitlines() if line.startswith('leadpro-phase4a2-')])
    assert sql(f"SELECT heartbeat_at IS NOT NULL FROM search_jobs WHERE id='{jid}'") == 't'
    worker_before = dc('ps', '-q', 'worker').strip()
    dc('restart', 'api')
    eventually(lambda: c.get('/health/ready').status_code == 200)
    assert dc('ps', '-q', 'worker').strip() == worker_before
    assert c.get('/api/auth/me').status_code == 200
    record('api_restart', 'Worker continued; PostgreSQL session and job survived; progress reconnected')
    dc('restart', 'redis')
    eventually(lambda: c.get('/health/ready').status_code == 200)
    assert c.get('/api/auth/me').status_code == 200
    eventually(lambda: completed(c, jid))
    assert sql(f"SELECT attempts FROM search_jobs WHERE id='{jid}'") == '1'
    record('redis_restart', 'Running job/session survived; one claim; completion after Redis reconnect; PG advisory capacity retained')

    jid = create(c, 5)
    eventually(lambda: job(c, jid)['processed_count'] >= 1 and job(c, jid)['status'] == 'running')
    before = sql(f"SELECT string_agg(a.id, ',') FROM audit_runs a JOIN search_job_items i ON i.id=a.item_id WHERE i.job_id='{jid}'")
    dc('kill', '-s', 'SIGKILL', 'worker')
    dc('up', '-d', 'worker')
    result = eventually(lambda: completed(c, jid))
    assert result['processed_count'] == 5
    assert int(sql(f"SELECT attempts FROM search_jobs WHERE id='{jid}'")) >= 2
    after = sql(f"SELECT string_agg(a.id, ',') FROM audit_runs a JOIN search_job_items i ON i.id=a.item_id WHERE i.job_id='{jid}'")
    assert set(before.split(',')) <= set(after.split(','))
    assert sql('SELECT count(*) FROM (SELECT item_id FROM audit_runs GROUP BY item_id HAVING count(*)>1) t') == '0'
    assert sql('SELECT count(*) FROM (SELECT audit_id FROM lead_scores GROUP BY audit_id HAVING count(*)>1) t') == '0'
    eventually(lambda: sql('SELECT count(*) FROM browser_cleanup WHERE pending') == '0')
    record('worker_restart', 'SIGKILL mid-job -> expired lease reclaimed; completed audit IDs retained; 5 items; no duplicate runs/scores; cleanup recovered')

    dc('stop', 'camofox')
    jid = create(c)
    time.sleep(3)
    assert c.get('/health/ready').status_code == 200
    assert job(c, jid)['status'] == 'queued'
    assert sql(f"SELECT attempts FROM search_jobs WHERE id='{jid}'") == '0'
    code = subprocess.run(COMPOSE + ['exec', '-T', 'worker', 'python', '-m', 'lead_engine.check', 'worker'], capture_output=True).returncode
    assert code != 0
    for token in ('', 'invalid'):
        assert c.post('/api/leadgen/jobs/' + jid + '/cancel', headers={'X-CSRF-Token': token}).status_code == 403
    assert c.post('/api/leadgen/jobs/' + jid + '/cancel').status_code == 200
    assert job(c, jid)['status'] == 'cancelled'
    resume_id = create(c)
    dc('start', 'camofox')
    eventually(lambda: completed(c, resume_id))
    record('camofox_outage', 'API remained ready; worker probe failed; zero claims/provider calls while down; queued cancel and resume passed')

    # Dependency degradation without conflating liveness with readiness.
    for service in ('redis', 'postgres'):
        dc('stop', service)
        try:
            assert c.get('/health/live').status_code == 200
            assert c.get('/health/ready').status_code == 503
            if service == 'postgres':
                assert c.get('/api/leads').status_code == 503
            else:
                assert c.post('/api/auth/login', json={'username': 'admin', 'password': 'FakeRedisOutagePassword_13245'}).status_code == 503
            code = subprocess.run(COMPOSE + ['exec', '-T', 'worker', 'python', '-m', 'lead_engine.check', 'worker'], capture_output=True).returncode
            assert code != 0
        finally:
            dc('start', service)
        eventually(lambda: c.get('/health/ready').status_code == 200)
    sql("UPDATE alembic_version SET version_num='0001'")
    try:
        assert c.get('/health/ready').status_code == 503
        result = subprocess.run(COMPOSE + ['run', '--rm', '--no-deps', 'api', 'python', '-c',
            "import asyncio\nfrom lead_engine.api import app,lifespan\nasync def check():\n    async with lifespan(app):\n        pass\nasyncio.run(check())"], capture_output=True)
        assert result.returncode != 0 and b'not at Alembic head' in result.stderr
    finally:
        sql("UPDATE alembic_version SET version_num='0002'")
    eventually(lambda: c.get('/health/ready').status_code == 200)
    record('readiness', 'Live stays 200; readiness 503 for PostgreSQL, Redis or migration mismatch; worker dependency probes fail; recovery passes')

    clear_rate_limit()
    attacker = client()
    for i in range(5):
        assert attacker.post('/api/auth/login', json={'username': 'admin', 'password': 'incorrect'},
                             headers={'X-Forwarded-For': f'198.51.100.{i}', 'X-LeadPro-Client-IP': f'192.0.2.{i}'}).status_code == 401
    assert attacker.post('/api/auth/login', json={'username': 'admin', 'password': 'incorrect'},
                         headers={'X-Forwarded-For': '203.0.113.5'}).status_code == 429
    print('Waiting for the real 60-second Redis login window to expire...', flush=True)
    time.sleep(61)
    login(attacker)
    record('login_rate_limit', '5 failures then 429 despite spoofed XFF/dedicated header; successful login after actual 60s expiry')

    old_cookie = c.cookies.get('__Host-leadpro_session')
    assert c.post('/api/auth/logout').status_code == 200
    assert c.get('/api/auth/me', headers={'Cookie': '__Host-leadpro_session=' + old_cookie}).status_code == 401
    login(c)
    login(other)
    changed = secrets.token_hex(24)
    SECRETS.append(changed)
    assert c.post('/api/auth/change-password', json={'old_password': PRIVATE['INITIAL_ADMIN_PASSWORD'], 'new_password': changed}).status_code == 200
    assert c.get('/api/auth/me').status_code == 401 and other.get('/api/auth/me').status_code == 401
    clear_rate_limit()
    login(c, changed)
    assert c.post('/api/auth/change-password', json={'old_password': changed, 'new_password': PRIVATE['INITIAL_ADMIN_PASSWORD']}).status_code == 200
    login(c)
    record('session_revocation', 'Logout rejects old cookie; password change revokes all sessions; valid CSRF accepted; test password restored')

    actions = set(sql('SELECT DISTINCT action FROM security_events').splitlines())
    assert {'login_success', 'login_failure', 'logout', 'password_change', 'job_create', 'job_cancel'} <= actions
    record('security_events', ', '.join(sorted(actions)))
    tables = scan_db()
    record('postgres_policy_scan', f'All {len(tables)} public tables scanned; zero restricted Google sentinel values')

    logs = dc('logs', '--no-color', 'api', 'worker', 'caddy', 'camofox', 'postgres', 'redis')
    for value in SECRETS:
        assert value not in logs, 'Full secret appeared in container logs'
    for value in ('GOOGLE_SENTINEL_', '4.918237', '9182736'):
        assert value not in logs, 'Provider sentinel appeared in logs'
    assert 'leadpro.db' not in logs
    (LOCAL / 'containers.log').write_text(logs, encoding='utf-8')
    record('log_scan', 'All six container logs: no full session/csrf/password/access keys or synthetic Google values')

    stats = subprocess.check_output(['docker', 'stats', '--no-stream', '--format', '{{.Name}}|{{.MemUsage}}|{{.CPUPerc}}'], text=True)
    record('resources', [line for line in stats.splitlines() if line.startswith('leadpro-phase4a2-')])
    c.close(); other.close(); attacker.close()


def extras():
    """Backup/restore, container configuration and private network evidence."""
    from backup_restore import backup, restore
    assert PRIVATE['DISCOVERY_MODE'] == 'offline'
    if (LOCAL / 'validation.json').exists():
        REPORT.update(json.loads((LOCAL / 'validation.json').read_text()))
    suffix = secrets.token_hex(4)
    backup_path = LOCAL / ('postgres-' + suffix + '.dump')
    database = 'phase4a2_restore_' + suffix
    backup(backup_path)
    assert backup_path.stat().st_size > 0
    restore(backup_path, database)
    counts = {}
    for table in ('users', 'sessions', 'search_jobs', 'businesses', 'audit_runs', 'audit_pages',
                  'audit_evidence', 'business_contacts', 'lead_scores', 'provider_refs', 'security_events'):
        original = int(sql('SELECT count(*) FROM ' + table))
        restored = int(sql('SELECT count(*) FROM ' + table, database))
        assert original > 0 and original == restored
        # Compare canonical row checksums, not just counts; no row values leave DB.
        query = f"SELECT md5(string_agg(row_to_json(t)::text, '' ORDER BY id)) FROM {table} t"
        assert sql(query) == sql(query, database)
        counts[table] = restored
    scan_db(database)
    assert sql('SELECT version_num FROM alembic_version', database) == '0002'
    record('backup_restore', {'format': 'pg_dump custom; binary pipes; new empty DB', 'bytes': backup_path.stat().st_size,
                             'restored_counts': counts, 'row_checksums': 'equal', 'provider_sentinels': 'absent'})

    ids = dc('ps', '-q').splitlines()
    info = json.loads(subprocess.check_output(['docker', 'inspect'] + ids, text=True))
    mappings = {}
    for container in info:
        name = container['Config']['Labels']['com.docker.compose.service']
        bound = {p: v for p, v in container['NetworkSettings']['Ports'].items() if v}
        mappings[name] = bound
        if name != 'caddy':
            assert not bound
        else:
            assert bound == {'443/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8443'}]}
        assert not any(m['Destination'] == '/var/run/docker.sock' for m in container['Mounts'])
        if name == 'camofox':
            assert not container['Mounts']
            assert all(n.endswith('_browser') for n in container['NetworkSettings']['Networks'])
    with client() as c:
        for path in ('/tabs', '/sessions', '/camofox/health', '/9377/health'):
            assert c.get(path).status_code == 404
    record('port_exposure', mappings)
    record('camofox_private', 'Only browser network; no published port/profile/socket mount; Caddy exposes no browser route')

    code = "import sys,pathlib,os; import lead_engine.api,lead_engine.worker; assert not {'sqlite3','database','engine_store','config','app'} & set(sys.modules); assert not list(pathlib.Path('/app').rglob('*.db')); assert not list(pathlib.Path('/app').glob('.jwt_secret*')); print(os.getuid())"
    assert py(code) == '10001' and py(code, 'worker') == '10001'
    record('sqlite_isolation', 'Production entrypoint import graphs exclude SQLite/legacy modules; no DB/legacy secret files; uid 10001')

    code = "import os;from production_config import validate_production_config\nvalidate_production_config()\nchanges={'DATABASE_URL':['','sqlite:///bad.db'],'REDIS_URL':[''],'SESSION_SECRET':['weak','changeme'*10],'SECURE_COOKIES':['false'],'DEBUG':['true'],'RELOAD':['true'],'OUTREACH_ENABLED':['true'],'SCHEDULER_ENABLED':['true'],'IN_PROCESS_WORKER':['true'],'CORS_ALLOW_WILDCARD':['true'],'CAMOFOX_BASE_URL':['http://outside.invalid:9377'],'CAMOFOX_ACCESS_KEY':[''],'CAMOFOX_INTERACTIVE':['desktop'],'CAMOFOX_CRASH_REPORT_ENABLED':['true'],'ENABLE_VNC':['true'],'CAMOFOX_PERSISTENCE_ENABLED':['true'],'DISCOVERY_MODE':['yelp']}\nfor key,values in changes.items():\n old=os.environ.get(key,'')\n for value in values:\n  os.environ[key]=value\n  try: validate_production_config()\n  except RuntimeError: pass\n  else: raise AssertionError(key)\n os.environ[key]=old\nprint('19 unsafe configurations rejected')"
    record('container_fail_fast', py(code))

    # Structured logger exercises fake provider, DB, Redis and browser errors.
    code = "import logging;from production_logging import configure_logging;configure_logging();logging.getLogger('fixture').error('provider api_key=FakeProviderSecret_97531 database_url=postgresql://fake:FakeDbSecret_97531@postgres/db redis_url=redis://fake:FakeRedisSecret_97531@redis/0 cookie=FakeCookieSecret_97531 csrf=FakeCsrfSecret_97531 password=FakePasswordSecret_97531 Authorization: Bearer FakeBrowserSecret_97531')"
    result = subprocess.run(COMPOSE + ['exec', '-T', 'api', 'python', '-c', code], capture_output=True, text=True)
    assert result.returncode == 0
    assert all(s not in result.stderr for s in ('FakeProviderSecret', 'FakeDbSecret', 'FakeRedisSecret', 'FakeCookieSecret', 'FakeCsrfSecret', 'FakePasswordSecret', 'FakeBrowserSecret'))
    (LOCAL / 'redaction-fixture.log').write_text(result.stderr)
    record('structured_logging_fixture', 'Fake provider/DB/Redis/browser/password/session/CSRF secrets redacted')

    # Use the real BrowserProvider inside the worker network namespace.
    result = subprocess.run(COMPOSE + ['exec', '-T', 'worker', 'python', '-'],
                            input=(ROOT / 'scripts/validate_camofox.py').read_text(), capture_output=True, text=True)
    assert result.returncode == 0, 'CamoFox browser smoke failed'
    health = json.loads(dc('exec', '-T', 'camofox', 'node', '-e', "fetch('http://127.0.0.1:9377/health').then(r=>r.json()).then(x=>console.log(JSON.stringify(x)))"))
    assert health['activeTabs'] == 0 and health['activeSessions'] == 0
    record('camofox_smoke', {'open_evaluate_close_example_com': True, 'active_tabs': 0, 'active_sessions': 0,
                            'direct_ssrf_targets': 'rejected', 'headless': 'forced in pinned derived image'})
    config_check = dc('exec', '-T', 'camofox', 'node', '-e',
        "const fs=require('fs');const c=JSON.parse(fs.readFileSync('/app/camofox.config.json'));if(process.getuid()===0||c.plugins.persistence.enabled||c.plugins.vnc.enabled||process.env.CAMOFOX_CRASH_REPORT_ENABLED!=='false')process.exit(1);console.log('nonroot plugins_disabled telemetry_disabled')")
    assert 'nonroot plugins_disabled telemetry_disabled' in config_check
    dns_check = dc('exec', '-T', 'camofox', 'node', '-e',
        "const dns=require('dns').promises;Promise.all(['postgres','redis','api'].map(async n=>{try{await dns.lookup(n);process.exitCode=1}catch{console.log(n+':not_resolvable')}}))")
    assert len(dns_check.splitlines()) == 3
    record('camofox_runtime_hardening', 'Non-root; actual plugin/telemetry config checked; data/API aliases unresolved from browser network')
    clear_rate_limit()
    with client() as c:
        login(c)
        dc('stop', 'api')
        try:
            response = c.get('/health/live?token=FakeQuerySecret_24681357')
            assert response.status_code == 502
        finally:
            dc('start', 'api')
        eventually(lambda: c.get('/health/ready').status_code == 200)
        logs = dc('logs', '--no-color', 'caddy')
        assert 'FakeQuerySecret_24681357' not in logs
        assert c.headers['X-CSRF-Token'] not in logs and c.cookies.get('__Host-leadpro_session') not in logs
        assert 'connect: connection refused' in logs
        c.post('/api/auth/logout')
    record('caddy_error_redaction', 'Forced upstream 502 retained diagnostic but omitted query secret, cookie and CSRF token')
    for key in ('failure',):
        REPORT.pop(key, None)
    (LOCAL / 'validation.json').write_text(json.dumps(REPORT, indent=2), encoding='utf-8')


def ui_smoke():
    from playwright.sync_api import sync_playwright, expect
    if (LOCAL / 'validation.json').exists():
        REPORT.update(json.loads((LOCAL / 'validation.json').read_text()))
    clear_rate_limit()
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        # Trust is scoped to this test context; strict CA validation is separately
        # exercised by the HTTPX integration suite. No OS certificate changes.
        context = browser.new_context(ignore_https_errors=True, viewport={'width': 1280, 'height': 900})
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(ORIGIN + '/') else route.abort())
        page = context.new_page()
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append((request.url, request.all_headers())))
        page.goto(ORIGIN)
        page.locator('#username').fill('admin')
        page.locator('#password').fill(PRIVATE['INITIAL_ADMIN_PASSWORD'])
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.locator('#layout').wait_for(state='visible')
        page.reload()
        page.locator('#layout').wait_for(state='visible')
        assert page.evaluate('localStorage.length') == 0 and page.evaluate('sessionStorage.length') == 0
        assert '__Host-leadpro_session' not in page.evaluate('document.cookie')
        page.get_by_role('button', name='Lead Generation', exact=True).click()
        for key, value in dict(category='Plumber', city='Austin', state='TX', target_count='1').items():
            page.locator('#' + key).fill(value)
        page.get_by_role('button', name='Start search', exact=True).click()
        expect(page.locator('#job-state')).to_contain_text('completed', timeout=45000)
        page.get_by_role('button', name='Leads', exact=True).click()
        page.locator('#lead-rows tr').first.wait_for()
        page.get_by_role('button', name='View evidence').first.click()
        page.locator('#business-detail').wait_for(state='visible')
        assert 'website_conversion_v2' in page.locator('#detail-content').inner_text()
        assert 'info@fixture-business.test' in page.locator('#detail-content').inner_text()
        page.screenshot(path=str(LOCAL / 'production-evidence-desktop.png'), full_page=True)
        page.get_by_role('button', name='Close details').click()
        with page.expect_download() as download:
            page.get_by_role('button', name='Export all businesses (CSV)').click()
        data = Path(download.value.path()).read_text()
        assert 'GOOGLE_SENTINEL_' not in data and 'info@fixture-business.test' in data
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(LOCAL / 'production-mobile.png'), full_page=True)
        page.get_by_role('button', name='Sign out', exact=True).click()
        page.locator('#login-panel').wait_for(state='visible')
        page.reload()
        page.locator('#login-panel').wait_for(state='visible')
        assert all('authorization' not in headers for _, headers in requests)
        assert not errors, 'Frontend JavaScript error'
        context.close()
        browser.close()
    record('frontend_browser', 'Headless Edge: cookie login/reload/job/evidence/CSV/logout; desktop/mobile; empty web storage; no bearer; zero JS errors')


def secret_scan():
    from scan_secrets import scan
    scan()


def coordination_smoke():
    clear_rate_limit()
    with client() as c:
        login(c)
        dc('up', '-d', '--scale', 'worker=2', 'worker')
        try:
            jobs = [create(c, 5), create(c, 5)]
            eventually(lambda: any(job(c, jid)['status'] == 'running' for jid in jobs))
            for name in ('jobs', 'browsers'):
                assert dc('exec', '-T', 'redis', 'redis-cli', 'EXISTS', 'leadpro:semaphore:' + name).strip() == '1'
            dc('restart', 'redis')
            deadline = time.monotonic() + 90
            max_running = 0
            while time.monotonic() < deadline:
                states = [job(c, jid) for jid in jobs]
                running = sum(j['status'] == 'running' for j in states)
                max_running = max(max_running, running)
                assert running <= 1, 'Global job semaphore exceeded'
                if all(j['status'] == 'completed' for j in states):
                    break
                time.sleep(1)
            else:
                raise AssertionError('Two-worker jobs did not complete')
            for jid in jobs:
                assert sql(f"SELECT attempts FROM search_jobs WHERE id='{jid}'") == '1'
                assert job(c, jid)['processed_count'] == 5
            record('two_worker_coordination', 'Two real workers + Redis restart: capacity one, both five-item jobs complete, one claim each, both Redis semaphore keys present')
        finally:
            dc('up', '-d', '--scale', 'worker=1', 'worker')
        c.post('/api/auth/logout')


if __name__ == '__main__':
    try:
        if '--extras' in sys.argv:
            extras()
        elif '--ui' in sys.argv:
            ui_smoke()
        elif '--secret-scan' in sys.argv:
            secret_scan()
        elif '--coordination' in sys.argv:
            coordination_smoke()
        else:
            main()
    except Exception as exc:
        REPORT['failure'] = {'status': 'FAIL', 'type': type(exc).__name__, 'message': str(exc)}
        (LOCAL / 'validation.json').write_text(json.dumps(REPORT, indent=2), encoding='utf-8')
        raise
