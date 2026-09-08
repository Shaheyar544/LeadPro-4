"""Container health probes; no database mutations."""
import asyncio
import json
import sys
import urllib.request
from health import readiness

if sys.argv[1] == 'api':
    try:
        with urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3) as response:
            sys.exit(0 if response.status == 200 else 1)
    except Exception:
        sys.exit(1)
else:
    from engine_config import EngineConfig
    async def check():
        browser = EngineConfig().browser()
        try:
            return readiness()['status'] == 'ok' and (await browser.health()).available
        finally:
            await browser.shutdown()
    sys.exit(0 if asyncio.run(check()) else 1)
