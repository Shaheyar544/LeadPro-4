"""Mode boundaries without external discovery calls."""
import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import pytest
from local_modes import validate_mode, validate_reference, fixture_url, LIVE_ERROR

ROOT = Path(__file__).resolve().parents[1]


def live_env(monkeypatch):
    for key, value in dict(LOCAL_RUN_MODE='live', DISCOVERY_MODE='google_places_new',
        GOOGLE_PLACES_API_VERSION='new', GOOGLE_PLACES_NEW_API_KEY='fake-unit-key', LOCAL_INTEGRATION_TEST='false').items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize('key,value', [('GOOGLE_PLACES_NEW_API_KEY', ''), ('DISCOVERY_MODE', 'offline'),
    ('LOCAL_INTEGRATION_TEST', 'true'), ('GOOGLE_PLACES_API_VERSION', 'legacy')])
def test_live_configuration_rejects_missing_provider_and_fixture_switch(monkeypatch, key, value):
    live_env(monkeypatch)
    validate_mode()
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        validate_mode()


def test_missing_google_stops_before_database_or_browser(monkeypatch):
    import live_preflight
    live_env(monkeypatch)
    monkeypatch.setenv('GOOGLE_PLACES_NEW_API_KEY', '')
    db = MagicMock(side_effect=AssertionError('must not check dependencies'))
    monkeypatch.setattr(live_preflight, 'check_database', db)
    assert live_preflight.preflight() == LIVE_ERROR
    db.assert_not_called()


def test_browser_not_ready_prevents_job_creation(monkeypatch):
    import live_preflight
    live_env(monkeypatch)
    monkeypatch.setattr(live_preflight, 'check_database', lambda: True)
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.ping.return_value = True
    connection.get.return_value = None
    monkeypatch.setattr(live_preflight, 'client', lambda: connection)
    assert 'discovery was not started' in live_preflight.preflight()


@pytest.mark.parametrize('provider,identifier', [('fixture','fixture:1'),
    ('google_places_new','google_places_new:phase4a2-place-1'), ('serper_maps','serper:1')])
def test_live_rejects_fixture_references(provider, identifier):
    with pytest.raises(ValueError):
        validate_reference(provider, identifier, 'live')
    assert fixture_url('https://fixture-business.test/')


def test_offline_provider_has_explicit_provenance():
    from lead_engine.offline import OfflineGoogle
    page = asyncio.run(OfflineGoogle().fetch_page(dict(category='HVAC', city='Phoenix', state='AZ'), limit=5))
    assert len(page.records) == 5
    for row in page.records:
        validate_reference(row['provider'], row['provider_record_id'], 'offline_test')
        assert fixture_url(row['website_url'])


@pytest.mark.parametrize('failure', ['google_new_unauthorized', 'google_new_forbidden', 'google_new_transport_timeout'])
def test_provider_failure_is_terminal_without_fixture_fallback(monkeypatch, failure):
    import lead_engine.worker as worker
    from discovery import DiscoveryError
    live_env(monkeypatch)
    source = SimpleNamespace(fetch_page=AsyncMock(side_effect=DiscoveryError(failure)))
    monkeypatch.setattr(worker, 'ProviderDiscovery', lambda *a: source)
    repo = MagicMock()
    repo.cancelled.return_value = False
    browser = SimpleNamespace(health=AsyncMock(return_value=SimpleNamespace(available=True)))
    job = SimpleNamespace(id='job', lease_token='lease', payload={'target_count':5})
    asyncio.run(worker.process_job(repo, job, browser, [], MagicMock()))
    source.fetch_page.assert_awaited_once()
    repo.add_reference.assert_not_called()
    repo.finish.assert_called_once_with('job', 'lease', error='live_discovery_unavailable')


def test_google_new_requests_only_the_requested_five(monkeypatch):
    from discovery import ProviderDiscovery
    source = ProviderDiscovery('google_places_new', 'fake-key-not-sent')
    source._json = AsyncMock(return_value={'places': []})
    asyncio.run(source.fetch_page(dict(category='HVAC', city='Phoenix', state='AZ'), limit=5))
    assert source._json.await_args.kwargs['json']['pageSize'] == 5


def test_live_worker_rejects_fixture_url_before_persistence(monkeypatch):
    import lead_engine.worker as worker
    from discovery import DiscoveryPage
    live_env(monkeypatch)
    source = SimpleNamespace(fetch_page=AsyncMock(return_value=DiscoveryPage(records=[
        {'provider':'google_places_new', 'provider_record_id':'google_places_new:actual-id',
         'website_url':'https://fixture-business.test/'}])))
    monkeypatch.setattr(worker,'ProviderDiscovery',lambda *a:source)
    repo=MagicMock(); repo.cancelled.return_value=False
    browser=SimpleNamespace(health=AsyncMock(return_value=SimpleNamespace(available=True)))
    asyncio.run(worker.process_job(repo,SimpleNamespace(id='job',lease_token='lease',payload={'target_count':5}),browser,[],MagicMock()))
    repo.add_reference.assert_not_called()
    repo.save_audit.assert_not_called()
    repo.finish.assert_called_once_with('job','lease',error='live_configuration_or_data_rejected')


def test_compose_and_launcher_mode_contracts():
    live = (ROOT / 'compose.production.yaml').read_text()
    offline = (ROOT / 'compose.test.yaml').read_text()
    assert 'name: leadpro-live' in live and 'name: leadpro-offline-test' in offline
    assert 'LOCAL_RUN_MODE: live' in live and 'DISCOVERY_MODE: google_places_new' in live
    assert 'DISCOVERY_MODE: ${' not in live and 'LOCAL_INTEGRATION_TEST: "false"' in live
    assert 'LOCAL_RUN_MODE: offline_test' in offline and 'DISCOVERY_MODE: offline' in offline
    assert 'GOOGLE_PLACES_NEW_API_KEY: ""' in offline
    assert 'name: leadpro-phase4a2_pgdata' in live and 'name: leadpro-offline-test_pgdata' in offline
    assert 'ports: !override ["127.0.0.1:8444:443"]' in offline
    shared = (ROOT / 'scripts/local_stack.ps1').read_text()
    assert "if ($offline) { $script:ComposeFiles += Join-Path $script:RepoRoot 'compose.test.yaml' }" in shared
    for action in ('start', 'stop', 'status'):
        script = (ROOT / f'scripts/{action}_local.ps1').read_text()
        assert '-Mode Live' in script and '$Mode' not in script
    assert "@('down')" in (ROOT / 'scripts/stop_stack.ps1').read_text()
    assert 'DELETE FIXTURES' in (ROOT / 'scripts/clean_fixture_data.ps1').read_text()


def test_banner_is_textual_accessible_and_only_offline():
    html = (ROOT / 'index.html').read_text(encoding='utf-8')
    assert 'role="status" hidden>OFFLINE TEST MODE — fixture data' in html
    assert "$('run-mode-banner').hidden = mode.run_mode !== 'offline_test'" in (ROOT / 'foundation.js').read_text()
