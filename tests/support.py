"""Import the app under isolated configuration, never the user's .env/DB."""
import atexit
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEMP = tempfile.TemporaryDirectory(prefix="leadpro-phase3a-tests-")
TEST_ENV = {
    "JWT_SECRET": "offline-test-signing-secret-" + "x" * 40,
    "DB_PATH": str(Path(TEMP.name) / "test.db"),
    "OUTREACH_ENABLED": "false", "PUBLIC_AUDIT_ENABLED": "false",
    "SCHEDULER_ENABLED": "false", "VERIFY_SSL": "true",
    "MAX_CONCURRENT_TASKS": "1", "SCRAPE_THREADS": "2",
    "INITIAL_ADMIN_PASSWORD": "", "OPENROUTER_API_KEY": "",
    "SERPER_API_KEY": "", "GOOGLE_PLACES_API_KEY": "", "YELP_API_KEY": "",
    "PAGESPEED_API_KEY": "", "HUNTER_API_KEY": "", "CLEARBIT_API_KEY": "",
}
with patch.dict(os.environ, TEST_ENV), patch("dotenv.load_dotenv"):
    import config
    import app
    import database


def close_pool():
    if database._pool is not None:
        while not database._pool.empty():
            database._pool.get_nowait().close()
        database._pool = None


def cleanup():
    close_pool()
    TEMP.cleanup()


atexit.register(cleanup)
