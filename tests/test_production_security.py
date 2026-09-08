import importlib
import os
import secrets
import pytest


def safe_env(monkeypatch):
    values = dict(APP_ENV='production', DATABASE_URL='postgresql+psycopg://user:fixture@postgres/db',
        REDIS_URL='redis://redis:6379/0', SESSION_SECRET=secrets.token_hex(32),
        CAMOFOX_ACCESS_KEY=secrets.token_hex(24), INITIAL_ADMIN_PASSWORD=secrets.token_hex(24),
        SECURE_COOKIES='true', DEBUG='false', IN_PROCESS_WORKER='false', SCHEDULER_ENABLED='false',
        OUTREACH_ENABLED='false', CORS_ALLOW_WILDCARD='false', RELOAD='false',
        APP_ORIGIN='https://localhost:8443', CAMOFOX_BASE_URL='http://camofox:9377',
        CAMOFOX_INTERACTIVE='off', CAMOFOX_CRASH_REPORT_ENABLED='false', ENABLE_VNC='false',
        CAMOFOX_PERSISTENCE_ENABLED='false', DISCOVERY_MODE='google_places_new', LOCAL_RUN_MODE='live', LOCAL_INTEGRATION_TEST='false',
        GOOGLE_PLACES_API_VERSION='new', GOOGLE_PLACES_NEW_API_KEY='unit-test-not-sent')
    for key, value in values.items():
        monkeypatch.setenv(key, value)


@pytest.mark.parametrize('key,value', [
    ('DATABASE_URL', 'sqlite:///leak.db'), ('DATABASE_URL', ''), ('REDIS_URL', ''),
    ('SESSION_SECRET', 'weak'), ('SESSION_SECRET', 'changeme' * 9),
    ('CORS_ALLOW_WILDCARD', 'true'), ('SECURE_COOKIES', 'false'), ('DEBUG', 'true'),
    ('RELOAD', 'true'), ('IN_PROCESS_WORKER', 'true'), ('OUTREACH_ENABLED', 'true'),
    ('SCHEDULER_ENABLED', 'true'), ('CAMOFOX_BASE_URL', 'http://public.example:9377'),
    ('CAMOFOX_ACCESS_KEY', ''), ('CAMOFOX_INTERACTIVE', 'desktop'),
    ('CAMOFOX_CRASH_REPORT_ENABLED', 'true'), ('ENABLE_VNC', 'true'),
    ('CAMOFOX_PERSISTENCE_ENABLED', 'true'), ('DISCOVERY_MODE', 'serper_maps')])
def test_fail_fast(monkeypatch, key, value):
    from production_config import validate_production_config
    safe_env(monkeypatch)
    assert validate_production_config()
    monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        validate_production_config()


def test_v2_ignores_all_transient_google_fields_and_unknown_is_not_absent():
    from production_scoring import score_browser_evidence
    audit = {'findings': {'contact_form': {'status': 'present'}, 'booking_form': {'status': 'absent'},
                          'primary_cta': {'status': 'present'}}}
    before = score_browser_evidence(audit)
    dirty = dict(audit, displayName='GOOGLE_SENTINEL_NAME', formattedAddress='GOOGLE_SENTINEL_ADDRESS',
                 websiteUri='GOOGLE_SENTINEL_WEBSITE', nationalPhoneNumber='GOOGLE_SENTINEL_PHONE',
                 rating=4.918237, userRatingCount=9182736, primaryType='sentinel', businessStatus='sentinel')
    assert score_browser_evidence(dirty) == before
    assert score_browser_evidence({})['opportunity_score'] is None
    assert score_browser_evidence({})['evidence_confidence'] == 0
    assert before['opportunity_score'] == 33.33


def test_formatter_redacts_values_and_exception_payloads(monkeypatch):
    import logging
    from production_logging import JsonFormatter
    monkeypatch.setenv('CAMOFOX_ACCESS_KEY', 'FakeBrowserSecret_13579')
    monkeypatch.setenv('INITIAL_ADMIN_PASSWORD', 'FakePasswordSecret_24680')
    message = 'Authorization: Bearer FakeBrowserSecret_13579 password=FakePasswordSecret_24680 database_url=postgresql://u:pass@db/x csrf=FakeCsrfSecret_97531 cookie=FakeCookieSecret_98765'
    record = logging.LogRecord('fixture', logging.ERROR, '', 0, message, (), None)
    rendered = JsonFormatter().format(record)
    assert all(x not in rendered for x in ('FakeBrowserSecret', 'FakePasswordSecret', 'FakeCsrfSecret', 'FakeCookieSecret', 'u:pass'))
