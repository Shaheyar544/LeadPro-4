"""Explicit runtime mode and fail-closed live data boundaries."""
import os
from urllib.parse import urlsplit
from sqlalchemy import and_, or_, exists, select

LEGACY_FIXTURE_IDS = tuple('google_places_new:phase4a2-place-' + str(i) for i in range(1, 6))
LIVE_ERROR = 'Live discovery is not configured or unavailable. Google Places API (New) could not be used.'


def run_mode():
    value = os.getenv('LOCAL_RUN_MODE', 'live')
    if value not in {'live', 'offline_test'}:
        raise RuntimeError('LOCAL_RUN_MODE must be live or offline_test')
    return value


def validate_mode():
    offline = run_mode() == 'offline_test'
    expected = 'offline' if offline else 'google_places_new'
    if os.getenv('DISCOVERY_MODE') != expected:
        raise RuntimeError('Discovery does not match the selected local run mode')
    if os.getenv('LOCAL_INTEGRATION_TEST', 'false') != ('true' if offline else 'false'):
        raise RuntimeError('Fixture configuration does not match local run mode')
    if not offline and (os.getenv('GOOGLE_PLACES_API_VERSION') != 'new' or not os.getenv('GOOGLE_PLACES_NEW_API_KEY')):
        raise RuntimeError(LIVE_ERROR)
    if offline and os.getenv('GOOGLE_PLACES_NEW_API_KEY'):
        raise RuntimeError('Offline test mode must not receive a paid discovery key')


def fixture_url(value):
    host = (urlsplit(value or '').hostname or '').lower()
    return host.endswith('.test') or host == 'fixture-business.test'


def validate_reference(provider, record_id, mode=None):
    mode = mode or run_mode()
    if not record_id or len(record_id) > 300:
        raise ValueError('Disallowed provider reference')
    if mode == 'live':
        if provider != 'google_places_new' or record_id in LEGACY_FIXTURE_IDS or not record_id.startswith('google_places_new:'):
            raise ValueError('Fixture or unsupported reference rejected in LIVE')
    elif provider != 'fixture' or not record_id.startswith('fixture:'):
        raise ValueError('Offline test requires fixture provenance')


def visible_business(mode=None):
    from production_models import Business, ProviderRef
    mode = mode or run_mode()
    allowed = Business.run_mode == mode
    if mode == 'live':
        fixture_ref = exists(select(ProviderRef.id).where(ProviderRef.business_id == Business.id,
            or_(ProviderRef.provider == 'fixture', ProviderRef.provider_record_id.in_(LEGACY_FIXTURE_IDS))))
        allowed = and_(allowed, ~fixture_ref,
            or_(Business.browser_observed_url.is_(None), ~Business.browser_observed_url.ilike('%fixture-business.test%')),
            or_(Business.browser_observed_name.is_(None), Business.browser_observed_name != 'Independently observed business'))
    return allowed
