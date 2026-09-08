"""Durable SQLite state; transactions never contain network operations."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import time
import uuid
from urllib.parse import urlsplit


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def uid():
    return uuid.uuid4().hex


def domain(url):
    try:
        return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def identity(record):
    def norm(value):
        return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())
    # Address distinguishes physical branches sharing name, phone or domain.
    # Without an address, require name + location + phone/domain, never domain alone.
    parts = [norm(record.get(k)) for k in ("canonical_name", "city", "state", "address")]
    if not parts[-1]:
        phone = re.sub(r"\D", "", str(record.get("provider_phone") or ""))
        if len(phone) == 11 and phone.startswith("1"):
            phone = phone[1:]
        parts.append(phone or domain(record.get("website_url")))
    if not any(parts[1:]):
        parts.extend([record["provider"], record["provider_record_id"]])
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


ERRORS = {
    "discovery_exhausted": "Discovery sources returned fewer unique businesses than requested.",
    "provider_limit": "The configured provider page or quota limit was reached.",
    "provider_unavailable": "A discovery provider is unavailable or denied access.",
    "provider_protocol_error": "A discovery provider returned an unexpected response.",
    "website_unverified": "No authoritative business website was supplied; no URL was guessed.",
    "worker_interrupted": "The worker was interrupted; unfinished work can resume.",
    "audit_incomplete": "Some businesses could not be fully assessed.",
    "cancelled": "Cancelled by the job owner.",
    "internal_error": "The job could not finish. Check the sanitized server log.",
}


def error_message(code):
    from browser.base import ERROR_MESSAGES
    return ERROR_MESSAGES.get(code, ERRORS.get(code, "The operation could not be completed.")) if code else None


class LeaseLost(Exception):
    pass


class EngineStore:
    def __init__(self, path):
        self.path = str(path)

    @contextmanager
    def transaction(self, write=False):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            if write:
                conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_job(self, user, request):
        jid = uid()
        with self.transaction(True) as conn:
            # Bounded backlog per owner; running jobs are managed by the worker lease.
            if conn.execute("SELECT count(*) FROM search_jobs WHERE user_id=? AND status IN ('queued','running')", (user,)).fetchone()[0] >= 10:
                raise ValueError("Job queue capacity reached")
            conn.execute("INSERT INTO search_jobs(id,user_id,category,city,state,target_count,profile,status,created_at) VALUES(?,?,?,?,?,?,?,'queued',?)",
                         (jid, user, request.category, request.city, request.state, request.target_count, request.opportunity_profile, now()))
        return self.job(jid, user)

    def owner_has_capacity(self, user):
        """Read-only capacity check used before live browser preflight."""
        with self.transaction() as conn:
            count = conn.execute("SELECT count(*) FROM search_jobs WHERE user_id=? AND status IN ('queued','running')", (user,)).fetchone()[0]
        return count < 10

    def job(self, jid, user=None):
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM search_jobs WHERE id=?" + (" AND user_id=?" if user else ""), (jid, user) if user else (jid,)).fetchone()
        if row is None:
            return None
        data = dict(row)
        # Internal cursors may contain provider tokens. They never leave this store.
        for key in ("discovery_state", "worker_id", "lease_until"):
            data.pop(key, None)
        return data

    def list_jobs(self, user):
        with self.transaction() as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM search_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user,))]
        return [self.job(jid, user) for jid in ids]

    def cancel(self, jid, user):
        with self.transaction(True) as conn:
            row = conn.execute("SELECT status FROM search_jobs WHERE id=? AND user_id=?", (jid, user)).fetchone()
            if row is None:
                return None
            if row[0] in ("queued", "running"):
                conn.execute("UPDATE search_jobs SET cancel_requested=1 WHERE id=?", (jid,))
                conn.execute("UPDATE search_job_items SET status='cancelled',completed_at=? WHERE job_id=? AND status='pending'", (now(), jid))
                if row[0] == "queued":
                    conn.execute("UPDATE search_jobs SET status='cancelled',finished_at=?,error_code='cancelled',error_message=? WHERE id=?", (now(), error_message("cancelled"), jid))
        return self.job(jid, user)

    def claim_job(self, worker, lease_seconds=60):
        with self.transaction(True) as conn:
            stamp = time.time()
            stale = conn.execute("SELECT id FROM search_jobs WHERE status='running' AND lease_until<?", (stamp,)).fetchall()
            for row in stale:
                self._recover(conn, row[0])
            # Enforce ONE active job across independent local workers.
            if conn.execute("SELECT 1 FROM search_jobs WHERE status='running' LIMIT 1").fetchone():
                return None
            row = conn.execute("SELECT id FROM search_jobs WHERE status='queued' AND cancel_requested=0 ORDER BY created_at,id LIMIT 1").fetchone()
            if row is None:
                return None
            conn.execute("UPDATE search_jobs SET status='running',worker_id=?,lease_until=?,heartbeat_at=?,started_at=COALESCE(started_at,?) WHERE id=?",
                         (worker, stamp + lease_seconds, now(), now(), row[0]))
            return row[0]

    def _recover(self, conn, jid):
        conn.execute("UPDATE audit_runs SET status='failed',error_code='worker_interrupted',error_message=?,finished_at=? WHERE status='running' AND job_item_id IN (SELECT id FROM search_job_items WHERE job_id=?)", (error_message("worker_interrupted"), now(), jid))
        conn.execute("UPDATE search_job_items SET status=CASE WHEN attempts<3 THEN 'pending' ELSE 'failed' END,error_code='worker_interrupted',error_message=? WHERE job_id=? AND status='processing'", (error_message("worker_interrupted"), jid))
        conn.execute("UPDATE search_jobs SET status='queued',worker_id=NULL,lease_until=NULL WHERE id=?", (jid,))
        if conn.execute("SELECT cancel_requested FROM search_jobs WHERE id=?", (jid,)).fetchone()[0]:
            conn.execute("UPDATE search_job_items SET status='cancelled',completed_at=? WHERE job_id=? AND status='pending'", (now(), jid))
            conn.execute("UPDATE search_jobs SET status='cancelled',finished_at=?,error_code='cancelled',error_message=? WHERE id=?", (now(), error_message("cancelled"), jid))
        self._progress(conn, jid)

    def release(self, jid, worker):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            self._recover(conn, jid)

    def _lease(self, conn, jid, worker):
        if not conn.execute("SELECT 1 FROM search_jobs WHERE id=? AND worker_id=? AND status='running' AND lease_until>?", (jid, worker, time.time())).fetchone():
            raise LeaseLost()

    def heartbeat(self, jid, worker):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            conn.execute("UPDATE search_jobs SET heartbeat_at=?,lease_until=? WHERE id=?", (now(), time.time() + 60, jid))

    def discovery_state(self, jid):
        with self.transaction() as conn:
            row = conn.execute("SELECT discovery_state,discovery_done FROM search_jobs WHERE id=?", (jid,)).fetchone()
            return json.loads(row[0]), bool(row[1])

    def save_discovery(self, jid, worker, records, state, done=False, error=None):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            job = conn.execute("SELECT * FROM search_jobs WHERE id=?", (jid,)).fetchone()
            if job["cancel_requested"]:
                return
            count = conn.execute("SELECT count(*) FROM search_job_items WHERE job_id=?", (jid,)).fetchone()[0]
            for record in records:
                if count >= job["target_count"]:
                    break
                source = conn.execute("SELECT business_id FROM business_sources WHERE provider=? AND provider_record_id=?", (record["provider"], record["provider_record_id"])).fetchone()
                match = conn.execute("SELECT id FROM businesses WHERE identity_key=?", (identity(record),)).fetchone()
                bid = source[0] if source else match[0] if match else uid()
                values = tuple(record.get(k) for k in ("canonical_name", "website_url", "provider_phone", "address", "category", "city", "state", "rating", "review_count"))
                conn.execute("INSERT INTO businesses(id,identity_key,canonical_name,website_url,provider_phone,address,category,city,state,rating,review_count,normalized_domain,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET website_url=COALESCE(NULLIF(excluded.website_url,''),businesses.website_url), normalized_domain=COALESCE(NULLIF(excluded.normalized_domain,''),businesses.normalized_domain), provider_phone=COALESCE(NULLIF(excluded.provider_phone,''),businesses.provider_phone), rating=COALESCE(excluded.rating,businesses.rating),review_count=COALESCE(excluded.review_count,businesses.review_count),updated_at=excluded.updated_at",
                             (bid, identity(record), *values, domain(record.get("website_url")), now(), now()))
                conn.execute("INSERT INTO business_sources VALUES(?,?,?,?,?,?) ON CONFLICT(provider,provider_record_id) DO UPDATE SET observed_at=excluded.observed_at", (uid(), bid, record["provider"], record["provider_record_id"], record.get("source_url"), now()))
                changed = conn.execute("INSERT OR IGNORE INTO search_job_items(id,job_id,business_id,provider,provider_record_id,source_url,status,created_at) VALUES(?,?,?,?,?,?,'pending',?)", (uid(), jid, bid, record["provider"], record["provider_record_id"], record.get("source_url"), now())).rowcount
                count += changed
            conn.execute("UPDATE search_jobs SET discovery_state=?,discovery_done=?,discovered_count=?,error_code=?,error_message=? WHERE id=?", (json.dumps(state), int(done), count, error, error_message(error), jid))

    def claim_item(self, jid, worker):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            if conn.execute("SELECT cancel_requested FROM search_jobs WHERE id=?", (jid,)).fetchone()[0]:
                return None
            row = conn.execute("SELECT * FROM search_job_items WHERE job_id=? AND status='pending' ORDER BY created_at,id LIMIT 1", (jid,)).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE search_job_items SET status='processing',attempts=attempts+1,claimed_at=? WHERE id=?", (now(), row["id"]))
            return dict(row)

    def business(self, bid):
        with self.transaction() as conn:
            row = conn.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone()
        return dict(row) if row else None

    def start_run(self, item, worker, provider, session):
        rid = uid()
        with self.transaction(True) as conn:
            self._lease(conn, item["job_id"], worker)
            business = conn.execute("SELECT website_url FROM businesses WHERE id=?", (item["business_id"],)).fetchone()
            conn.execute("INSERT INTO audit_runs(id,business_id,job_item_id,provider,provider_version,status,start_url,browser_user_id,browser_session_key,cleanup_pending,started_at) VALUES(?,?,?,?,?,'running',?,?,?,?,?)", (rid, item["business_id"], item["id"], provider.name, provider.version, business[0], session.user_id, session.session_key, 1, now()))
        return rid

    def replace_run_session(self, jid, worker, rid, session):
        # Called only after confirmed old-context cleanup; persist the new IDs
        # before the lazy provider allocates any browser state.
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            conn.execute("UPDATE audit_runs SET browser_user_id=?,browser_session_key=?,cleanup_pending=1 WHERE id=? AND status='running'", (session.user_id, session.session_key, rid))

    def record_navigation(self, jid, worker, rid, page_id, attempt, details):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            conn.execute("INSERT INTO audit_navigation_attempts VALUES(?,?,?,?) ON CONFLICT(audit_run_id,page_id,attempt) DO UPDATE SET details_json=excluded.details_json", (rid, page_id, attempt, json.dumps(details)))

    def pending_cleanup(self):
        with self.transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT id,browser_user_id,browser_session_key FROM audit_runs WHERE cleanup_pending=1 AND status!='running' LIMIT 100")]

    def cleaned(self, rid):
        with self.transaction(True) as conn:
            conn.execute("UPDATE audit_runs SET cleanup_pending=0 WHERE id=?", (rid,))

    def finish_run(self, jid, item, worker, rid, result, score):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            stamp = now()
            conn.execute("UPDATE audit_runs SET status=?,final_url=?,pages_attempted=?,pages_completed=?,error_code=?,error_message=?,finished_at=? WHERE id=? AND status='running'", (result["status"], result.get("final_url"), len(result["pages"]), sum(p["status"] == "completed" for p in result["pages"]), result.get("error_code"), error_message(result.get("error_code")), stamp, rid))
            for page in result["pages"]:
                conn.execute("INSERT INTO audit_pages VALUES(?,?,?,?,?,?,?,?,?,?,?)", (page["id"], rid, page["url"], page["page_type"], page["status"], page.get("final_url"), page.get("title"), page.get("navigation_ms"), page.get("screenshot_path"), page.get("screenshot_bytes"), page["observed_at"]))
            for evidence in result["evidence"]:
                conn.execute("INSERT INTO audit_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (evidence["id"], rid, evidence.get("page_id"), evidence["detector_key"], evidence["status"], json.dumps(evidence.get("value")), evidence.get("source_url"), evidence.get("page_type"), evidence.get("excerpt", "")[:240], evidence.get("locator", "")[:200], evidence["confidence"], evidence["detector_version"], evidence["observed_at"]))
            for contact in result["contacts"]:
                conn.execute("INSERT OR IGNORE INTO business_contacts VALUES(?,?,?,?,?,?,?,?,?,?,?)", (uid(), item["business_id"], rid, contact["type"], contact["display"], contact["normalized"], contact["source_url"], contact["evidence_type"], contact.get("excerpt", "")[:240], contact["confidence"], stamp))
            conn.execute("INSERT INTO lead_scores VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (uid(), item["business_id"], rid, "website_conversion", "website_conversion_v1", score["business_strength"], score["digital_gap"], score["opportunity_score"], score["evidence_confidence"], score["contact_confidence"], json.dumps(score["breakdown"]), stamp))
            status = "cancelled" if result["status"] == "cancelled" else "completed" if result["status"] in ("completed", "partial") else "skipped" if result["status"] == "unverified" else "failed"
            conn.execute("UPDATE search_job_items SET status=?,completed_at=?,error_code=?,error_message=? WHERE id=?", (status, stamp, result.get("error_code"), error_message(result.get("error_code")), item["id"]))
            self._progress(conn, jid)

    def _progress(self, conn, jid):
        processed = conn.execute("SELECT count(*) FROM search_job_items WHERE job_id=? AND status IN ('completed','failed','skipped','cancelled')", (jid,)).fetchone()[0]
        qualified = conn.execute("SELECT count(DISTINCT i.id) FROM search_job_items i JOIN audit_runs r ON r.job_item_id=i.id JOIN lead_scores s ON s.audit_run_id=r.id WHERE i.job_id=? AND i.status='completed' AND EXISTS (SELECT 1 FROM audit_pages p WHERE p.audit_run_id=r.id AND p.status IN ('completed','partial')) AND s.digital_gap IS NOT NULL", (jid,)).fetchone()[0]
        conn.execute("UPDATE search_jobs SET processed_count=?,qualified_count=? WHERE id=?", (processed, qualified, jid))

    def finish_job(self, jid, worker, error=None):
        with self.transaction(True) as conn:
            self._lease(conn, jid, worker)
            job = conn.execute("SELECT * FROM search_jobs WHERE id=?", (jid,)).fetchone()
            code = error or job["error_code"]
            incomplete = conn.execute("SELECT 1 FROM search_job_items WHERE job_id=? AND (status!='completed' OR error_code IS NOT NULL) LIMIT 1", (jid,)).fetchone()
            if job["cancel_requested"]:
                status, code = "cancelled", "cancelled"
            elif error:
                status = "partial" if job["processed_count"] else "failed"
            elif job["discovered_count"] < job["target_count"] or job["qualified_count"] < job["discovered_count"] or incomplete:
                status, code = "partial", code or "audit_incomplete"
            else:
                status, code = "completed", None
            conn.execute("UPDATE audit_runs SET status='failed',error_code=?,error_message=?,finished_at=? WHERE status='running' AND job_item_id IN (SELECT id FROM search_job_items WHERE job_id=?)", (code or "internal_error", error_message(code or "internal_error"), now(), jid))
            conn.execute("UPDATE search_job_items SET status=?,completed_at=? WHERE job_id=? AND status IN ('pending','processing')", ("cancelled" if status == "cancelled" else "failed", now(), jid))
            self._progress(conn, jid)
            conn.execute("UPDATE search_jobs SET status=?,error_code=?,error_message=?,finished_at=?,worker_id=NULL,lease_until=NULL WHERE id=?", (status, code, error_message(code), now(), jid))

    def items(self, jid, user, limit=100, offset=0):
        if not self.job(jid, user):
            return None
        with self.transaction() as conn:
            return [dict(r) for r in conn.execute("SELECT i.*,b.canonical_name FROM search_job_items i JOIN businesses b ON b.id=i.business_id WHERE i.job_id=? ORDER BY i.created_at,i.id LIMIT ? OFFSET ?", (jid, limit, offset))]

    def result_ids(self, user, limit=100, offset=0):
        with self.transaction() as conn:
            rows = conn.execute("SELECT b.id,MAX(r.started_at) latest FROM businesses b JOIN search_job_items i ON i.business_id=b.id JOIN search_jobs j ON j.id=i.job_id LEFT JOIN audit_runs r ON r.job_item_id=i.id WHERE j.user_id=? GROUP BY b.id ORDER BY latest DESC,b.id LIMIT ? OFFSET ?", (user, limit, offset)).fetchall()
            total = conn.execute("SELECT count(DISTINCT i.business_id) FROM search_job_items i JOIN search_jobs j ON j.id=i.job_id WHERE j.user_id=?", (user,)).fetchone()[0]
        return [r[0] for r in rows], total

    def detail(self, bid, user):
        with self.transaction() as conn:
            if not conn.execute("SELECT 1 FROM search_job_items i JOIN search_jobs j ON j.id=i.job_id WHERE i.business_id=? AND j.user_id=?", (bid, user)).fetchone():
                return None
            business = dict(conn.execute("SELECT * FROM businesses WHERE id=?", (bid,)).fetchone())
            business.pop("identity_key", None)
            sources = [dict(r) for r in conn.execute("SELECT provider,provider_record_id,source_url,observed_at FROM business_sources WHERE business_id=?", (bid,))]
            runs = [dict(r) for r in conn.execute("SELECT r.id,r.provider,r.provider_version,r.status,r.start_url,r.final_url,r.pages_attempted,r.pages_completed,r.error_code,r.error_message,r.started_at,r.finished_at FROM audit_runs r JOIN search_job_items i ON i.id=r.job_item_id JOIN search_jobs j ON j.id=i.job_id WHERE r.business_id=? AND j.user_id=? ORDER BY r.started_at DESC,r.id DESC LIMIT 100", (bid, user))]
            run = runs[0] if runs else None
            result = {"business": business, "sources": sources, "audit": run, "history": runs, "pages": [], "evidence": [], "contacts": [], "score": None}
            if run:
                rid = run["id"]
                for key, table in (("pages", "audit_pages"), ("evidence", "audit_evidence"), ("contacts", "business_contacts")):
                    result[key] = [dict(r) for r in conn.execute(f"SELECT * FROM {table} WHERE audit_run_id=?", (rid,))]
                navigation = [dict(page_id=r[0], **json.loads(r[1])) for r in conn.execute("SELECT page_id,details_json FROM audit_navigation_attempts WHERE audit_run_id=? ORDER BY page_id,attempt", (rid,))]
                result["navigation"] = navigation
                for page in result["pages"]:
                    page["attempts"] = [d for d in navigation if d["page_id"] == page["id"]]
                for evidence in result["evidence"]:
                    evidence["value"] = json.loads(evidence.pop("normalized_value"))
                row = conn.execute("SELECT * FROM lead_scores WHERE audit_run_id=? ORDER BY created_at DESC LIMIT 1", (rid,)).fetchone()
                if row:
                    result["score"] = dict(row)
                    result["score"]["breakdown"] = json.loads(result["score"].pop("breakdown_json"))
            return result
