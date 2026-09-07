"""Local UI smoke check using installed Edge, not a business browser worker.

Run explicitly: python tests/browser_smoke.py --artifact-dir <temporary folder>
Uses only localhost, an isolated database, and generated temporary credentials.
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    args.artifact_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="leadpro-ui-smoke-") as temporary:
        data = Path(temporary)
        password = secrets.token_urlsafe(24)
        env = {**os.environ, "PYTHONPATH": str(ROOT), "DB_PATH": str(data / "smoke.db"),
               "JWT_SECRET": secrets.token_urlsafe(64), "INITIAL_ADMIN_PASSWORD": password,
               "SERPER_API_KEY": "", "GOOGLE_PLACES_API_KEY": "", "YELP_API_KEY": "",
               "OPENROUTER_API_KEY": "", "PAGESPEED_API_KEY": "", "HUNTER_API_KEY": "", "CLEARBIT_API_KEY": "",
               "OUTREACH_ENABLED": "false", "PUBLIC_AUDIT_ENABLED": "false",
               "SCHEDULER_ENABLED": "false", "VERIFY_SSL": "true", "MAX_CONCURRENT_TASKS": "1",
               "BROWSER_PROVIDER": "camofox", "CAMOFOX_BASE_URL": "http://127.0.0.1:9377", "CAMOFOX_ACCESS_KEY": "",
               "CAMOFOX_PAGE_SETTLE_MS": "0", "AUDIT_SCREENSHOTS_ENABLED": "false"}
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        with (data / "server.log").open("w+", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "tests.smoke_app:app", "--host", "127.0.0.1",
                                        "--port", str(port), "--no-proxy-headers"], cwd=data, env=env,
                                       stdout=log, stderr=log,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                for attempt in range(100):
                    if process.poll() is not None:
                        raise AssertionError("Local server exited during startup")
                    try:
                        with urllib.request.urlopen(base + "/health", timeout=1) as response:
                            assert response.status == 200
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    raise AssertionError("Local startup timed out")

                payload = '=SUM(1,2) <img src=x onerror="window.__xss=1"> Fixture Business'

                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="msedge", headless=True)
                    context = browser.new_context(viewport={"width": 1280, "height": 900}, reduced_motion="reduce")
                    context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base + "/") else route.abort())
                    page = context.new_page()
                    errors, requests = [], []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.on("request", lambda request: requests.append(request.url))
                    page.goto(base)
                    page.locator("#username").fill("admin")
                    page.locator("#password").fill(password)
                    page.get_by_role("button", name="Sign in", exact=True).click()
                    page.locator("#layout").wait_for(state="visible")
                    assert page.locator("nav [data-page]").count() == 4
                    page.get_by_role("button", name="Lead Generation", exact=True).click()
                    page.locator("#category").fill("Plumber")
                    page.locator("#city").fill("Austin")
                    page.locator("#state").fill("ZZ")
                    page.locator("#target_count").fill("2")
                    page.get_by_role("button", name="Start search", exact=True).click()
                    page.wait_for_function("() => document.getElementById('state').getAttribute('aria-invalid') === 'true'")
                    assert page.locator("#lg-errors").evaluate("node => node === document.activeElement")
                    page.locator("#state").fill("Texas")
                    with page.expect_response(lambda response: response.url.endswith('/api/leadgen/start') and response.status == 202) as start:
                        page.get_by_role("button", name="Start search", exact=True).click()
                    jid = start.value.json()["job_id"]
                    page.reload()
                    page.locator("#layout").wait_for(state="visible")
                    page.get_by_role("button", name="Lead Generation", exact=True).click()
                    page.wait_for_function("() => document.getElementById('job-state').textContent.includes('partial')", timeout=30000)
                    assert 'Discovered 2 / 2' in page.locator('#job-log').inner_text()
                    page.get_by_role("button", name="Leads", exact=True).click()
                    page.locator("#lead-rows tr").first.wait_for()
                    row = page.locator('#lead-rows tr').filter(has_text=payload)
                    assert row.count() == 1
                    assert page.locator('#lead-rows img').count() == 0
                    assert page.evaluate("typeof window.__xss") == "undefined"
                    row.get_by_role('button', name='View evidence').click()
                    page.locator('#business-detail').wait_for(state='visible')
                    assert 'office@public-business.test' in page.locator('#detail-content').inner_text()
                    assert page.locator('#detail-content img').count() == 0
                    assert page.locator('#detail-content .status-unknown').count() > 0
                    page.screenshot(path=str(args.artifact_dir / 'business-evidence.png'), full_page=True)
                    page.get_by_role('button', name='Close details').click()
                    blocked = page.locator('#lead-rows tr').filter(has_text='Blocked business')
                    blocked.get_by_role('button', name='View evidence').click()
                    page.locator('#business-detail').wait_for(state='visible')
                    assert page.locator('#detail-content .status-blocked').count() > 0
                    assert 'Unknown' in page.locator('#detail-content').inner_text()
                    page.get_by_role('button', name='Close details').click()
                    with page.expect_download() as download:
                        page.get_by_role("button", name="Export all businesses (CSV)").click()
                    downloaded = Path(download.value.path()).read_text(encoding='utf-8')
                    assert "'=SUM(1,2)" in downloaded and "'+15125551234" in downloaded
                    page.get_by_role("button", name="Lead Generation", exact=True).click()
                    page.locator('#category').fill('Plumber')
                    page.locator('#city').fill('Austin'); page.locator('#state').fill('TX'); page.locator('#target_count').fill('2')
                    page.get_by_role('button', name='Start search', exact=True).click()
                    page.locator('#cancel-job:not([disabled])').wait_for()
                    page.get_by_role('button', name='Cancel job', exact=True).click()
                    page.wait_for_function("() => document.getElementById('job-state').textContent.includes('cancelled')", timeout=30000)
                    # Cancellation survives a full page reload; selecting its
                    # saved history entry must reconnect without starting work.
                    searches_before_reload = sum(url.endswith('/api/leadgen/start') for url in requests)
                    page.reload()
                    page.locator('#layout').wait_for(state='visible')
                    page.get_by_role('button', name='Lead Generation', exact=True).click()
                    page.locator('#recent-jobs button').filter(has_text='cancelled').first.click()
                    page.wait_for_function("() => document.getElementById('job-state').textContent.includes('cancelled')")
                    assert page.locator('#cancel-job').is_disabled()
                    assert sum(url.endswith('/api/leadgen/start') for url in requests) == searches_before_reload
                    page.locator('#category').fill('Offline')
                    page.locator('#city').fill('Austin'); page.locator('#state').fill('TX')
                    page.locator('#target_count').fill('1')
                    page.get_by_role('button', name='Start search', exact=True).click()
                    page.wait_for_function("() => document.getElementById('job-state').textContent.includes('Offline') && document.getElementById('job-state').textContent.includes('partial')", timeout=30000)
                    page.get_by_role('button', name='Leads', exact=True).click()
                    page.locator('#lead-rows tr').filter(has_text=payload).get_by_role('button', name='View evidence').click()
                    page.locator('#business-detail').wait_for(state='visible')
                    assert 'Browser service is unavailable' in page.locator('#detail-content').inner_text()
                    assert page.locator('#detail-content .status-failed').count() > 0
                    page.get_by_role('button', name='Close details').click()
                    page.get_by_role("button", name="Lead Generation", exact=True).click()
                    page.screenshot(path=str(args.artifact_dir / "leadgen-desktop.png"), full_page=True)
                    page.set_viewport_size({"width": 375, "height": 812})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    assert page.locator("#lg-btn").is_visible()
                    page.screenshot(path=str(args.artifact_dir / "leadgen-mobile.png"), full_page=True)
                    page.get_by_role("button", name="Settings", exact=True).click()
                    page.locator("#settings-form").wait_for(state="visible")
                    assert page.locator("#provider-fields input").count() == 5
                    assert not any(page.locator("#provider-fields input").nth(i).input_value() for i in range(5))
                    page.get_by_role("button", name="Toggle theme").click()
                    page.screenshot(path=str(args.artifact_dir / "settings-mobile-light.png"), full_page=True)
                    # A response arriving after logout must not reopen sensitive details.
                    page.get_by_role("button", name="Leads", exact=True).click()
                    page.locator('#lead-rows tr').first.wait_for()
                    pending_detail = []
                    page.route('**/api/businesses/*', lambda route: pending_detail.append(route))
                    page.locator('#lead-rows tr').first.get_by_role('button', name='View evidence').click()
                    page.get_by_role("button", name="Sign out", exact=True).click()
                    page.locator("#login-panel").wait_for(state="visible")
                    assert len(pending_detail) == 1
                    pending_detail[0].continue_()
                    page.wait_for_timeout(200)
                    assert not page.locator('#business-detail').is_visible()
                    assert not errors, errors
                    forbidden = ("/api/outreach", "/api/warmup", "/api/whatsapp", "/api/smtp", "/api/brevo", "/api/intel", "/api/campaigns", "/api/proposals")
                    assert not any(any(path in url for path in forbidden) for url in requests)
                    browser.close()
                log.flush()
                log.seek(0)
                output = log.read()
                assert password not in output and env["JWT_SECRET"] not in output
                print("PASS: Windows startup and real login; persistent search, refresh recovery, cancellation, blocked/offline evidence, detailed scores, stored-XSS fixtures, CSV download, validation, mobile layout, settings and logout; no retired API calls or JS errors.")
            finally:
                if os.name == "nt" and process.poll() is None:
                    # Windows venv redirectors can have a Python child; stop only
                    # this harness's recorded process tree before closing fixtures.
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   capture_output=True, check=False,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
                elif process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    main()
