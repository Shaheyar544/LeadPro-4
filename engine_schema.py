"""Additive Phase 3B migration. Legacy leads and their history remain intact."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS search_jobs (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(username),
 category TEXT NOT NULL, city TEXT NOT NULL, state TEXT NOT NULL,
 target_count INTEGER NOT NULL CHECK(target_count BETWEEN 1 AND 100), profile TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('queued','running','completed','partial','failed','cancelled')),
 discovered_count INTEGER NOT NULL DEFAULT 0, processed_count INTEGER NOT NULL DEFAULT 0,
 qualified_count INTEGER NOT NULL DEFAULT 0, cancel_requested INTEGER NOT NULL DEFAULT 0,
 error_code TEXT, error_message TEXT, discovery_state TEXT NOT NULL DEFAULT '{}',
 discovery_done INTEGER NOT NULL DEFAULT 0, worker_id TEXT, lease_until REAL,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, heartbeat_at TEXT
);
CREATE TABLE IF NOT EXISTS businesses (
 id TEXT PRIMARY KEY, identity_key TEXT UNIQUE NOT NULL, canonical_name TEXT NOT NULL,
 normalized_domain TEXT, website_url TEXT, provider_phone TEXT, address TEXT,
 category TEXT, city TEXT, state TEXT, rating REAL, review_count INTEGER,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_sources (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES businesses(id),
 provider TEXT NOT NULL, provider_record_id TEXT NOT NULL, source_url TEXT,
 observed_at TEXT NOT NULL, UNIQUE(provider, provider_record_id)
);
CREATE TABLE IF NOT EXISTS search_job_items (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES search_jobs(id),
 business_id TEXT NOT NULL REFERENCES businesses(id), provider TEXT NOT NULL,
 provider_record_id TEXT NOT NULL, source_url TEXT, status TEXT NOT NULL
 CHECK(status IN ('pending','processing','completed','failed','skipped','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, error_code TEXT, error_message TEXT,
 claimed_at TEXT, completed_at TEXT, created_at TEXT NOT NULL,
 UNIQUE(job_id, business_id)
);
CREATE TABLE IF NOT EXISTS audit_runs (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES businesses(id),
 job_item_id TEXT NOT NULL REFERENCES search_job_items(id), provider TEXT NOT NULL,
 provider_version TEXT NOT NULL, status TEXT NOT NULL, start_url TEXT, final_url TEXT,
 pages_attempted INTEGER NOT NULL DEFAULT 0, pages_completed INTEGER NOT NULL DEFAULT 0,
 error_code TEXT, error_message TEXT, browser_user_id TEXT, browser_session_key TEXT,
 cleanup_pending INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, finished_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_pages (
 id TEXT PRIMARY KEY, audit_run_id TEXT NOT NULL REFERENCES audit_runs(id),
 url TEXT, page_type TEXT NOT NULL, status TEXT NOT NULL, final_url TEXT, title TEXT,
 navigation_ms INTEGER, screenshot_path TEXT, screenshot_bytes INTEGER,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_evidence (
 id TEXT PRIMARY KEY, audit_run_id TEXT NOT NULL REFERENCES audit_runs(id),
 audit_page_id TEXT REFERENCES audit_pages(id), detector_key TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('present','absent','unknown','blocked','failed','not_applicable')),
 normalized_value TEXT, source_url TEXT, page_type TEXT, excerpt TEXT, locator TEXT,
 confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1), detector_version TEXT NOT NULL,
 observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS business_contacts (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES businesses(id),
 audit_run_id TEXT NOT NULL REFERENCES audit_runs(id), contact_type TEXT NOT NULL,
 display_value TEXT NOT NULL, normalized_value TEXT NOT NULL, source_url TEXT,
 evidence_type TEXT NOT NULL, excerpt TEXT, confidence REAL NOT NULL,
 observed_at TEXT NOT NULL,
 UNIQUE(audit_run_id, contact_type, normalized_value, source_url)
);
CREATE TABLE IF NOT EXISTS lead_scores (
 id TEXT PRIMARY KEY, business_id TEXT NOT NULL REFERENCES businesses(id),
 audit_run_id TEXT NOT NULL REFERENCES audit_runs(id), profile TEXT NOT NULL,
 profile_version TEXT NOT NULL, business_strength REAL, digital_gap REAL,
 opportunity_score REAL, evidence_confidence REAL NOT NULL, contact_confidence REAL NOT NULL,
 breakdown_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_claim ON search_jobs(status, lease_until, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_user ON search_jobs(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_items_claim ON search_job_items(job_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_runs_business ON audit_runs(business_id, started_at);
CREATE INDEX IF NOT EXISTS idx_evidence_run ON audit_evidence(audit_run_id, detector_key);
CREATE INDEX IF NOT EXISTS idx_contacts_business ON business_contacts(business_id, contact_type);
CREATE INDEX IF NOT EXISTS idx_scores_business ON lead_scores(business_id, created_at);
"""
