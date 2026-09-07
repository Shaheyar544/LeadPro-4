"""Small offline business fixtures shared by persistence, scoring and API tests."""
import copy
import sqlite3
from pathlib import Path
import tempfile
from engine_schema import SCHEMA
from engine_store import EngineStore
from discovery import DiscoveryPage
from product_models import LeadGenRequest

REQUEST = dict(category="Plumber", city="Austin", state="TX", target_count=1, opportunity_profile="website_conversion")


def facts(url="https://business.test/", **updates):
    result = dict(url=url, title="Public business", ready_state="complete", complete=True,
                  viewport="width=device-width,initial-scale=1", links=[], contacts=[], forms=[],
                  ctas=[], resources=[], generator="", tracking={}, blocked=False)
    result.update(updates)
    return result


def business(index=1, **updates):
    result = dict(provider="fixture", provider_record_id=str(index), canonical_name=f"Business {index}",
                  website_url="https://business.test/", provider_phone="", address=f"{index} Oak Street",
                  category="Plumber", city="Austin", state="TX", rating=4.8, review_count=200,
                  source_url="https://provider.test/business/" + str(index))
    result.update(updates)
    return result


class FixtureStore:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lead-engine-test-")
        self.path = Path(self.temp.name) / "engine.db"
        conn = sqlite3.connect(self.path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE users(username TEXT PRIMARY KEY)")
            conn.executemany("INSERT INTO users VALUES(?)", [("alice",), ("bob",), ("admin",)])
            conn.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()
        self.store = EngineStore(self.path)

    def job(self, user="alice", **updates):
        return self.store.create_job(user, LeadGenRequest(**{**REQUEST, **updates}))

    def close(self):
        self.temp.cleanup()


class FixtureSource:
    name = "fixture"
    def __init__(self, pages=None):
        self.pages = pages or [DiscoveryPage([business()], terminal_reason="discovery_exhausted")]
        self.calls = []

    async def fetch_page(self, job, cursor=None, limit=20, cancelled=lambda: False):
        self.calls.append(cursor)
        page = self.pages[int(cursor or 0)]
        return copy.deepcopy(page)
