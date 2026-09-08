"""Fail closed before either production entrypoint accepts work."""
import os
from urllib.parse import urlsplit
from production_boundary import validate_production_settings

def validate_production_config():
    if os.getenv('APP_ENV') != 'production':
        raise RuntimeError('Dedicated entrypoints require APP_ENV=production')
    validate_production_settings()
    for name in ('SESSION_SECRET', 'CAMOFOX_ACCESS_KEY', 'INITIAL_ADMIN_PASSWORD'):
        value = os.getenv(name, '')
        if len(value) < (32 if name == 'SESSION_SECRET' else 12) or len(set(value)) < 8 or any(x in value.lower() for x in ('changeme', 'default', 'password123')):
            raise RuntimeError('Unsafe production configuration: ' + name)
    if os.getenv('RELOAD', 'false') != 'false':
        raise RuntimeError('Reload is forbidden')
    if os.getenv('APP_ORIGIN') != 'https://localhost:8443':
        raise RuntimeError('Phase 4A local origin must be https://localhost:8443')
    if os.getenv('CAMOFOX_BASE_URL') != 'http://camofox:9377':
        raise RuntimeError('Unsafe CamoFox service URL')
    required = {'CAMOFOX_INTERACTIVE': 'off', 'CAMOFOX_CRASH_REPORT_ENABLED': 'false',
                'ENABLE_VNC': 'false', 'CAMOFOX_PERSISTENCE_ENABLED': 'false'}
    if any(os.getenv(k) != v for k, v in required.items()):
        raise RuntimeError('Unsafe CamoFox configuration')
    if urlsplit(os.getenv('REDIS_URL', '')).scheme not in {'redis', 'rediss'}:
        raise RuntimeError('Invalid Redis URL')
    mode = os.getenv('DISCOVERY_MODE', 'disabled')
    if mode not in {'disabled', 'offline', 'google_places_new'}:
        raise RuntimeError('Unsupported discovery policy')
    if mode == 'offline' and os.getenv('LOCAL_INTEGRATION_TEST') != 'true':
        raise RuntimeError('Offline fixture requires explicit local integration mode')
    return True
