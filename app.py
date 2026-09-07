"""
LeadPro v4 — Web Server
FastAPI: REST + SSE + tracking + audit pages.
"""
from __future__ import annotations
import asyncio, json, uuid, base64, os, aiohttp, time, logging, re
from urllib.parse import urlparse
from pathlib import Path
from typing import AsyncGenerator, Optional, List, AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from functools import lru_cache
from fastapi import FastAPI, APIRouter, HTTPException, Request, Depends, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, Response, FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
import config
from jose import JWTError, jwt
import bcrypt
from product_models import LeadGenRequest
from jobs import JobManager, CapacityExceeded
from engine_store import EngineStore
from engine_config import EngineConfig
from engine_worker import PersistentWorker
from engine_views import summary as business_summary, csv_export
from dataclasses import asdict
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize local storage and resume durable searches; no outreach scheduler."""
    from database import init_db
    init_db()
    _ensure_default_admin()
    evidence_worker.start()
    try:
        yield
    finally:
        await evidence_worker.shutdown()
        await job_manager.shutdown()


app = FastAPI(title="Local Business Lead Intelligence Engine", lifespan=lifespan)
# Source retained for attribution/future removal, but never mounted in V0.1.
legacy_routes = APIRouter()
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS,
                   allow_methods=["GET", "POST", "PUT"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    )
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Validation errors must not echo input values (particularly passwords/API keys).
from fastapi.exceptions import RequestValidationError

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]})


# Request logging middleware
_logger = logging.getLogger("request")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    _logger.info(
        f"{request.method} {request.url.path} {response.status_code} {process_time:.3f}s"
    )
    return response

def _rate_limit_key(request: Request) -> str:
    """Use the peer address; do not trust arbitrary forwarding headers."""
    return request.client.host if request.client else "unknown"


# Rate limiting
limiter = Limiter(key_func=_rate_limit_key)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# JWT authentication (non-auto-error so optional auth works; enforced in dependency)
security = HTTPBearer(auto_error=False)
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, config.JWT_SECRET, algorithm=JWT_ALGORITHM)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    if credentials is None:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, config.JWT_SECRET,
                             algorithms=[JWT_ALGORITHM], options={"require_exp": True})
        username = payload.get("sub")
        if not isinstance(username, str) or not username:
            raise HTTPException(401, "Invalid token")
        from database import get_user
        if get_user(username) is None:
            raise HTTPException(401, "Invalid token")
        return username
    except JWTError:
        raise HTTPException(401, "Invalid token") from None


async def get_current_user_role(user: str = Depends(get_current_user)) -> tuple[str, str]:
    from database import get_user
    row = get_user(user)
    if row is None:
        raise HTTPException(401, "Invalid token")
    # A signed but stale/forged role claim never grants administrator access.
    return user, row["role"]


async def require_admin(user_role: tuple[str, str] = Depends(get_current_user_role)):
    _, role = user_role
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _ensure_default_admin():
    """Bootstrap only from a supplied password, never log credential material."""
    from database import count_users, create_user
    if count_users() > 0:
        return
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "")
    if not password:
        logging.getLogger("auth").warning(
            "No users exist. Set INITIAL_ADMIN_PASSWORD securely and restart to create admin.")
        return
    if len(password) < 12 or len(password.encode("utf-8")) > 72:
        raise RuntimeError("INITIAL_ADMIN_PASSWORD must be 12+ characters and at most 72 UTF-8 bytes")
    create_user("admin", _hash_password(password), role="admin")


_PIXEL = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
job_manager = JobManager(config.MAX_CONCURRENT_TASKS)  # Unmounted legacy handlers only.
engine_store = EngineStore(config.DB_PATH)
engine_settings = EngineConfig()
evidence_worker = PersistentWorker(engine_store, engine_settings)
# These objects belong exclusively to unmounted legacy handlers.
_background_tasks: set = set()
_audit_email_sem = asyncio.Semaphore(10)


def _new_job():
    raise HTTPException(404, "Not found")  # Unmounted legacy handlers must not start work.


def owned_job(jid, user):
    job = job_manager.get(jid, user)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


async def _sse_stream(job):
    sequence = 0
    while True:
        snapshot = job.snapshot(sequence)
        for event in snapshot["events"]:
            yield f"data: {json.dumps(event)}\n\n"
        sequence = snapshot["sequence"]
        if snapshot["status"] != "running":
            yield f"data: {json.dumps({'type': 'done', 'status': snapshot['status']})}\n\n"
            return
        yield ": keepalive\n\n"
        await asyncio.sleep(1)


def _sse(job):
    return StreamingResponse(_sse_stream(job), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ── Authentication ──
class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@app.post("/api/auth/login")
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest):
    from database import get_user, update_user_last_login
    row = get_user(body.username)
    if not row or not _verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    update_user_last_login(row["id"])
    token = create_access_token(data={"sub": row["username"], "role": row["role"]})
    return {"access_token": token, "token_type": "bearer"}


@app.post("/api/auth/change-password")
@limiter.limit("5/minute")
async def change_password(request: Request, body: ChangePasswordRequest,
                           user: str = Depends(get_current_user)):
    from database import get_user, get_conn
    row = get_user(user)
    if not row or not _verify_password(body.old_password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Old password incorrect")
    if len(body.new_password.encode("utf-8")) > 72:
        raise HTTPException(400, "Password must be at most 72 UTF-8 bytes")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not any(c.isupper() for c in body.new_password):
        raise HTTPException(status_code=400, detail="Password must contain an uppercase letter")
    if not any(c.islower() for c in body.new_password):
        raise HTTPException(status_code=400, detail="Password must contain a lowercase letter")
    if not any(c.isdigit() for c in body.new_password):
        raise HTTPException(status_code=400, detail="Password must contain a digit")
    new_hash = _hash_password(body.new_password)
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_hash, row["id"]))
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(user: str = Depends(get_current_user)):
    from database import get_user
    row = get_user(user)
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": row["username"], "role": row["role"]}


# ── UI (cached in memory) ──
@lru_cache(maxsize=2)
def _read_ui_html(name: str) -> str:
    p = Path(__file__).parent / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    html = _read_ui_html("index.html")
    if not html:
        raise HTTPException(404)
    return HTMLResponse(html)


@legacy_routes.get("/landing", response_class=HTMLResponse)
async def serve_landing():
    html = _read_ui_html("landing.html")
    if not html:
        raise HTTPException(404)
    return HTMLResponse(html)

@app.get("/new_style.css", response_class=FileResponse)
async def serve_css():
    p = Path(__file__).parent / "new_style.css"
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(str(p), media_type="text/css")

# ── Tracking ──
_track_log = logging.getLogger("tracking")


@legacy_routes.get("/t/o/{oid}.gif")
@limiter.limit("60/minute")
async def track_open(oid: int, request: Request):
    from database import get_conn
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO tracking_events (outreach_id,event_type,ip,user_agent) VALUES (?,?,?,?)",
                (oid, "open", request.client.host if request.client else "",
                 request.headers.get("user-agent", "")),
            )
            conn.execute(
                "UPDATE outreach SET open_tracked=1, opened_at=? WHERE id=? AND open_tracked=0",
                (datetime.now(timezone.utc).isoformat(), oid),
            )
    except Exception as e:
        _track_log.warning("open-track failed for oid=%s: %s", oid, e)
    return Response(content=_PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})


@legacy_routes.get("/t/c/{oid}/{url_b64}")
@limiter.limit("30/minute")
async def track_click(oid: int, url_b64: str, request: Request):
    from database import get_conn
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO tracking_events (outreach_id,event_type,ip,user_agent) VALUES (?,?,?,?)",
                (oid, "click", request.client.host if request.client else "",
                 request.headers.get("user-agent", "")),
            )
            conn.execute(
                "UPDATE outreach SET clicked_at=? WHERE id=? AND clicked_at IS NULL",
                (datetime.now(timezone.utc).isoformat(), oid),
            )
    except Exception as e:
        _track_log.warning("click-track failed for oid=%s: %s", oid, e)
    try:
        target = base64.urlsafe_b64decode(url_b64).decode()
    except Exception:
        target = "/"
    # Validate target URL — only allow http/https and the tracking domain or /
    if target not in ("/", ""):
        try:
            parsed = urlparse(target)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                target = "/"
        except Exception:
            target = "/"
    return RedirectResponse(url=target, status_code=302)


# ── Audit page tracking pixel ──
@legacy_routes.get("/t/audit/{token}.gif")
@limiter.limit("60/minute")
async def track_audit_view(token: str, request: Request):
    from database import get_conn
    try:
        with get_conn() as conn:
            lead = conn.execute(
                "SELECT id FROM leads WHERE audit_page_token=?", (token,)
            ).fetchone()
            if lead:
                conn.execute(
                    "INSERT INTO events (lead_id,event_type,note) VALUES (?,?,?)",
                    (lead["id"], "audit_viewed",
                     f"ip={request.client.host if request.client else ''}"),
                )
    except Exception as e:
        _track_log.warning("audit-view track failed for token=%s: %s", token, e)
    return Response(content=_PIXEL, media_type="image/gif", headers={"Cache-Control": "no-store"})

# ── Serve audit pages ──
_SAFE_TOKEN_RE = re.compile(r"^[a-zA-Z0-9_-]{6,64}$")


@legacy_routes.get("/audit/{token}")
async def serve_audit_page(token: str):
    if not _SAFE_TOKEN_RE.match(token):
        raise HTTPException(400, "Invalid token")
    safe_path = Path(f"audits/{token}.html").resolve()
    audits_dir = Path("audits").resolve()
    if not str(safe_path).startswith(str(audits_dir)):
        raise HTTPException(400, "Invalid token")
    if not safe_path.exists():
        raise HTTPException(404, "Audit page not found")
    return HTMLResponse(safe_path.read_text(encoding="utf-8"))

@app.get("/foundation.js")
async def serve_foundation_js():
    return FileResponse(Path(__file__).parent / "foundation.js", media_type="text/javascript")


@app.get("/base_style.css")
async def serve_base_css():
    return FileResponse(Path(__file__).parent / "base_style.css", media_type="text/css")


# ── Stats ──
@app.get("/health")
def health_check():
    from database import get_conn
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})


@app.get("/api/stats")
def api_stats(user: str = Depends(get_current_user)):
    with engine_store.transaction() as conn:
        row = conn.execute("SELECT count(DISTINCT b.id) total, count(DISTINCT CASE WHEN b.website_url!='' THEN b.id END) with_website FROM businesses b JOIN search_job_items i ON i.business_id=b.id JOIN search_jobs j ON j.id=i.job_id WHERE j.user_id=?", (user,)).fetchone()
        emails = conn.execute("SELECT count(DISTINCT c.business_id) FROM business_contacts c JOIN audit_runs r ON r.id=c.audit_run_id JOIN search_job_items i ON i.id=r.job_item_id JOIN search_jobs j ON j.id=i.job_id WHERE j.user_id=? AND c.contact_type='email'", (user,)).fetchone()[0]
        active = conn.execute("SELECT count(*) FROM search_jobs WHERE user_id=? AND status IN ('queued','running')", (user,)).fetchone()[0]
    return {"total": row["total"], "with_email": emails, "with_website": row["with_website"], "active_jobs": active}


@legacy_routes.get("/api/smtp/test")
async def api_smtp_test(user: str = Depends(get_current_user)):
    from outreach import test_smtp
    return {"ok": await asyncio.get_running_loop().run_in_executor(None, test_smtp)}

@legacy_routes.get("/api/brevo/test")
async def api_brevo_test(user: str = Depends(get_current_user)):
    from outreach import test_brevo_smtp
    return {"ok": await asyncio.get_running_loop().run_in_executor(None, test_brevo_smtp)}

@legacy_routes.post("/api/audit/cleanup")
async def api_audit_cleanup(user: str = Depends(get_current_user)):
    deleted = delete_expired_audit_pages()
    return {"deleted": deleted, "message": f"Removed {deleted} expired audit pages"}

# ── Analytics ──
@legacy_routes.get("/api/analytics")
async def api_analytics(user: str = Depends(get_current_user)):
    from analytics import get_full_analytics; return get_full_analytics()

# ── Campaigns ──
@legacy_routes.get("/api/campaigns")
async def api_campaigns(user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute("SELECT id,name,country,status,created_at,(SELECT COUNT(*) FROM leads WHERE leads.campaign_id = campaigns.id) + (SELECT COUNT(DISTINCT lead_id) FROM outreach WHERE outreach.campaign_id = campaigns.id AND lead_id NOT IN (SELECT id FROM leads WHERE leads.campaign_id = campaigns.id)) as lead_count FROM campaigns ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]

class CreateCampaignBody(BaseModel):
    name: str; country: str; lead_ids: Optional[List[int]] = None; lead_batch: Optional[str] = None

@legacy_routes.post("/api/campaigns")
async def api_create_campaign(body: CreateCampaignBody, user: str = Depends(get_current_user)):
    from database import create_campaign, get_conn
    cid = create_campaign(body.name, body.country)
    with get_conn() as conn:
        if body.lead_ids:
            placeholders = ','.join('?' * len(body.lead_ids))
            conn.execute(f"UPDATE leads SET campaign_id = ? WHERE id IN ({placeholders})", [cid] + body.lead_ids)
        elif body.lead_batch:
            if body.lead_batch == '__all_unassigned__':
                conn.execute("UPDATE leads SET campaign_id = ? WHERE campaign_id IS NULL", [cid])
            else:
                conn.execute("UPDATE leads SET campaign_id = ? WHERE source_query = ? AND campaign_id IS NULL", [cid, body.lead_batch])
    return {"id":cid,"name":body.name,"country":body.country,"status":"active"}

@legacy_routes.patch("/api/campaigns/{cid}/status")
async def api_campaign_status(cid: int, status: str, user: str = Depends(get_current_user)):
    """Update campaign status. Accepts ?status=... query param for backwards compat."""
    ALLOWED_STATUSES = {"active", "paused", "archived", "completed"}
    if status not in ALLOWED_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {sorted(ALLOWED_STATUSES)}")
    from database import get_conn
    with get_conn() as conn:
        cur = conn.execute("UPDATE campaigns SET status=? WHERE id=?", (status, cid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Campaign not found")
    return {"ok": True}

@legacy_routes.delete("/api/campaigns/{cid}")
async def api_delete_campaign(cid: int, user: str = Depends(get_current_user)):
    """Delete a campaign and unlink associated outreach and leads."""
    from database import get_conn
    with get_conn() as conn:
        cur = conn.execute("SELECT id FROM campaigns WHERE id=?", (cid,))
        if cur.fetchone() is None:
            raise HTTPException(404, "Campaign not found")
        conn.execute("UPDATE outreach SET campaign_id = NULL WHERE campaign_id = ?", (cid,))
        conn.execute("UPDATE leads SET campaign_id = NULL WHERE campaign_id = ?", (cid,))
        conn.execute("DELETE FROM campaigns WHERE id = ?", (cid,))
    return {"ok": True}

@legacy_routes.get("/api/lead-batches")
async def api_lead_batches(user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COALESCE(NULLIF(source_query,''),'Unassigned') as batch, "
            "COUNT(*) as count, GROUP_CONCAT(id) as lead_ids "
            "FROM leads GROUP BY source_query ORDER BY count DESC"
        ).fetchall()
    return [dict(r) for r in rows]

# ── Leads ──
@app.get("/api/leads")
async def api_leads(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0),
                    user: str = Depends(get_current_user)):
    ids, total = engine_store.result_ids(user, limit, offset)
    return {"leads": [business_summary(engine_store.detail(bid, user)) for bid in ids], "total": total}


@app.get("/api/leads/filters")
async def api_lead_filters(user: str = Depends(get_current_user)):
    return {"profiles": ["website_conversion_v1"]}


@legacy_routes.get("/api/leads/{lead_id}/preview-email")
async def api_preview_email(lead_id: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from ai_engine import generate_email
    from audit_pages import generate_audit_preview
    from config import BASE_URL
    with get_conn() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?",(lead_id,)).fetchone()
    if not lead: raise HTTPException(404)
    lead = dict(lead)
    audit_url = None
    audit_preview = None
    token = lead.get("audit_page_token")
    if token:
        audit_url = f"{BASE_URL}/audit/{token}"
        audit_preview = generate_audit_preview(lead, token)
    loop = asyncio.get_running_loop()
    content = await loop.run_in_executor(None, lambda: generate_email(
        business_name=lead.get("business_name") or "",pain_points_json=lead.get("pain_points") or "[]",
        source_query=lead.get("source_query") or "",country=lead.get("country") or "",sequence_step=1,
        decision_maker=lead.get("decision_maker", None),
        estimated_monthly_loss=lead.get("estimated_monthly_loss") or 0,
        ops_pain_points_json=lead.get("ops_pain_points"),
        audit_page_url=audit_url,
        audit_preview=audit_preview,
        niche=lead.get("niche"),
    ))
    return content or {"error":"AI generation failed"}

# ── Generate audit page for a lead ──
@legacy_routes.post("/api/leads/{lead_id}/audit-page")
async def api_gen_audit_page(lead_id: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from audit_pages import generate_audit_page
    from audit import estimate_revenue_impact
    with get_conn() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?",(lead_id,)).fetchone()
        if not lead: raise HTTPException(404)
        lead = dict(lead)
        seo = [dict(r) for r in conn.execute("SELECT * FROM seo_rankings WHERE lead_id=? ORDER BY checked_at DESC LIMIT 10",(lead_id,)).fetchall()]
        comps = [dict(r) for r in conn.execute("SELECT * FROM competitors WHERE lead_id=?",(lead_id,)).fetchall()]
    pains = json.loads(lead.get("pain_points","[]") or "[]")
    ops = json.loads(lead.get("ops_pain_points","[]") or "[]")
    roi = estimate_revenue_impact(lead.get("niche",""), pains, ops, lead.get("country",""))
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(None, lambda: generate_audit_page(lead_id, lead, seo, comps, roi))
    from config import BASE_URL
    return {"path": path, "url": f"{BASE_URL}{path}"}

# ── Lead Gen ──
@app.post("/api/leadgen/start", status_code=202)
async def api_start_leadgen(req: LeadGenRequest, user: str = Depends(get_current_user)):
    from discovery import configured_sources
    if not (evidence_worker.sources if evidence_worker.sources is not None else configured_sources()):
        raise HTTPException(503, "Configure a discovery provider API key and restart before starting a search")
    try:
        job = engine_store.create_job(user, req)
    except ValueError:
        raise HTTPException(429, "Job queue capacity reached", headers={"Retry-After": "10"}) from None
    evidence_worker.notify()
    return {"job_id": job["id"], "status": job["status"]}


def persistent_job(jid, user):
    job = engine_store.job(jid, user)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


@app.get("/api/leadgen/jobs")
async def api_jobs(user: str = Depends(get_current_user)):
    return engine_store.list_jobs(user)


@app.get("/api/leadgen/jobs/{jid}")
@app.get("/api/leadgen/status/{jid}")
async def api_lg_status(jid: str, after: int = Query(0, ge=0), user: str = Depends(get_current_user)):
    return persistent_job(jid, user)


@app.get("/api/leadgen/jobs/{jid}/items")
async def api_job_items(jid: str, limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0), user: str = Depends(get_current_user)):
    persistent_job(jid, user)
    return engine_store.items(jid, user, limit, offset)


@app.post("/api/leadgen/jobs/{jid}/cancel")
async def api_job_cancel(jid: str, user: str = Depends(get_current_user)):
    job = engine_store.cancel(jid, user)
    if job is None:
        raise HTTPException(404, "Job not found")
    evidence_worker.notify()
    return job


@app.get("/api/leadgen/stream/{jid}")
async def api_lg_stream(jid: str, user: str = Depends(get_current_user)):
    persistent_job(jid, user)
    async def updates():
        previous = None
        while True:
            job = engine_store.job(jid, user)
            if job != previous:
                yield f"data: {json.dumps(job)}\n\n"
                previous = job
            if job["status"] not in {"queued", "running"}:
                return
            yield ": keepalive\n\n"
            await asyncio.sleep(1)
    return StreamingResponse(updates(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.get("/api/discovery/readiness")
async def api_discovery_readiness(user: str = Depends(get_current_user)):
    from discovery import provider_readiness
    return provider_readiness()


@app.get("/api/browser/health")
async def api_browser_health(user: str = Depends(get_current_user)):
    return asdict(await evidence_worker.browser.health())


@app.get("/api/businesses/{bid}")
async def api_business_detail(bid: str, user: str = Depends(get_current_user)):
    detail = engine_store.detail(bid, user)
    if detail is None:
        raise HTTPException(404, "Business not found")
    return detail


# ── Outreach ──
@legacy_routes.get("/api/outreach/preview/{cid}")
async def api_outreach_preview(cid:int,min_score:int=40, user: str = Depends(get_current_user)):
    from database import get_leads_for_outreach, get_opted_out_emails, get_hard_bounce_emails
    oo=get_opted_out_emails();hb=get_hard_bounce_emails()
    leads=get_leads_for_outreach(cid,step=1,min_score=min_score)
    result=[]
    for l in leads[:200]:
        d=dict(l);d["_skipped"]=(l["email"] in oo or l["email"] in hb or not l["email"] or "@" not in str(l["email"]))
        result.append(d)
    return result

class OutreachRequest(BaseModel):
    campaign_id:int;min_score:int=40;lead_ids:list[int]=[]

@legacy_routes.post("/api/outreach/start")
async def api_start_outreach(req:OutreachRequest, user: str = Depends(get_current_user)):
    jid,q=_new_job()
    async def _run():
        from outreach import run_initial_outreach_web
        try: await run_initial_outreach_web(req.campaign_id,req.min_score,req.lead_ids,q)
        except Exception as e: await q.put({"type":"error","message":str(e)})
        finally: await q.put(None)
    t = asyncio.create_task(_run()); _background_tasks.add(t); t.add_done_callback(_background_tasks.discard); return {"job_id":jid}

@legacy_routes.post("/api/followups/start")
async def api_start_followups(user: str = Depends(get_current_user)):
    jid,q=_new_job()
    async def _run():
        from outreach import run_followups_web
        from outreach import check_replies
        try:
            await q.put({"type":"info","message":"Scanning inbox for replies…"})
            stats = await asyncio.get_running_loop().run_in_executor(None,check_replies)
            await q.put({"type":"info","message":f"Inbox scanned — {stats.get('replies',0)} replies, {stats.get('opt_outs',0)} opt-outs"})
            await run_followups_web(q)
        except Exception as e: await q.put({"type":"error","message":str(e)})
        finally: await q.put(None)
    t = asyncio.create_task(_run()); _background_tasks.add(t); t.add_done_callback(_background_tasks.discard); return {"job_id":jid}

@legacy_routes.get("/api/outreach/stream/{jid}")
async def api_out_stream(jid:str): return _sse(jid)

# ── Replies ──
@legacy_routes.post("/api/replies/scan")
async def api_scan_replies(user: str = Depends(get_current_user)):
    jid,q=_new_job()
    async def _run():
        from outreach import check_replies
        try:
            await q.put({"type":"info","message":"Connecting to IMAP…"})
            stats = await asyncio.get_running_loop().run_in_executor(None,check_replies)
            await q.put({"type":"stats","message":"Complete","data":stats})
        except Exception as e: await q.put({"type":"error","message":str(e)})
        finally: await q.put(None)
    t = asyncio.create_task(_run()); _background_tasks.add(t); t.add_done_callback(_background_tasks.discard); return {"job_id":jid}

@legacy_routes.get("/api/replies/stream/{jid}")
async def api_rep_stream(jid:str): return _sse(jid)

# ── Intelligence ──
class IntelRequest(BaseModel):
    lead_ids:list[int]|None=None;min_score:int=50;country:str|None=None;service:str|None=None

@legacy_routes.post("/api/intel/start")
async def api_start_intel(req:IntelRequest, user: str = Depends(get_current_user)):
    jid,q=_new_job()
    async def _run():
        from intel import run_intel_batch
        try: await run_intel_batch(lead_ids=req.lead_ids,min_score=req.min_score,country=req.country,service=req.service,queue=q)
        except Exception as e: await q.put({"type":"error","message":str(e)})
        finally: await q.put(None)
    t = asyncio.create_task(_run()); _background_tasks.add(t); t.add_done_callback(_background_tasks.discard); return {"job_id":jid}

@legacy_routes.get("/api/intel/stream/{jid}")
async def api_intel_stream(jid:str): return _sse(jid)

# ── Proposals ──
@legacy_routes.post("/api/proposals/generate/{lead_id}")
async def api_gen_proposal(lead_id:int, user: str = Depends(get_current_user)):
    from proposal_engine import generate_proposal
    path = await asyncio.get_running_loop().run_in_executor(None,generate_proposal,lead_id)
    return {"path":path,"lead_id":lead_id}

@legacy_routes.post("/api/proposals/batch")
async def api_batch_proposals(data:dict, user: str = Depends(get_current_user)):
    from proposal_engine import generate_proposal
    from database import get_conn
    ms=data.get("min_score",60);lim=data.get("limit",20)
    with get_conn() as conn:
        leads=conn.execute("SELECT id FROM leads WHERE lead_score>=? AND website IS NOT NULL AND website!='' ORDER BY lead_score DESC LIMIT ?",(ms,lim)).fetchall()
    loop=asyncio.get_running_loop(); paths=[]
    for l in leads:
        try: p=await loop.run_in_executor(None,generate_proposal,l["id"]); paths.append({"lead_id":l["id"],"path":p})
        except: pass
    return {"generated":len(paths),"proposals":paths}

@legacy_routes.get("/api/proposals/{lead_id}/download")
async def api_download_proposal(lead_id:int, user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        row=conn.execute("SELECT pdf_path FROM proposals WHERE lead_id=? AND pdf_path IS NOT NULL ORDER BY created_at DESC LIMIT 1",(lead_id,)).fetchone()
    if not row or not os.path.exists(row["pdf_path"]): raise HTTPException(404)
    return FileResponse(row["pdf_path"],media_type="application/pdf",filename=row["pdf_path"].split("/")[-1])

# ── Warmup ──
@legacy_routes.post("/api/warmup/run")
async def api_warmup_run(user: str = Depends(get_current_user)):
    jid,q=_new_job()
    async def _run():
        from outreach import run_warmup_cycle
        try: await run_warmup_cycle(q)
        except Exception as e: await q.put({"type":"error","message":str(e)})
        finally: await q.put(None)
    t = asyncio.create_task(_run()); _background_tasks.add(t); t.add_done_callback(_background_tasks.discard); return {"job_id":jid}

@legacy_routes.get("/api/warmup/stream/{jid}")
async def api_wu_stream(jid:str): return _sse(jid)

@legacy_routes.get("/api/warmup/accounts")
async def api_warmup_accounts(user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("SELECT id,email,domain,role,current_day,status,daily_limit,smtp_host,smtp_port,imap_host FROM warmup_accounts ORDER BY role,domain").fetchall()]

class WarmupAccountBody(BaseModel):
    email:str;password:str;domain:str;role:str="sender";smtp_host:str="smtp.gmail.com";smtp_port:int=587;imap_host:str="imap.gmail.com"

class WarmupAccountUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    domain: Optional[str] = None
    role: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    imap_host: Optional[str] = None
    daily_limit: Optional[int] = None
    current_day: Optional[int] = None
    status: Optional[str] = None

@legacy_routes.post("/api/warmup/accounts")
async def api_add_wu(body:WarmupAccountBody, _=Depends(require_admin)):
    from database import get_conn
    from config import encrypt_password
    with get_conn() as conn:
        conn.execute("INSERT OR IGNORE INTO warmup_accounts (email,password,smtp_host,smtp_port,imap_host,domain,role) VALUES (?,?,?,?,?,?,?)",
                     (body.email, encrypt_password(body.password or ""), body.smtp_host, body.smtp_port, body.imap_host, body.domain, body.role))
    return {"ok":True}

@legacy_routes.get("/api/warmup/accounts/{aid}")
async def api_get_wu(aid:int, user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        row = conn.execute("SELECT id, email, password, domain, role, current_day, status, daily_limit, smtp_host, smtp_port, imap_host FROM warmup_accounts WHERE id=?", (aid,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Account not found")
        return dict(row)

@legacy_routes.put("/api/warmup/accounts/{aid}")
async def api_update_wu(aid:int, body:WarmupAccountUpdate, user: str = Depends(get_current_user)):
    from database import get_conn
    from config import encrypt_password
    with get_conn() as conn:
        # Build update dynamically
        updates = []
        params = []
        if body.email is not None: updates.append("email=?"); params.append(body.email)
        if body.password is not None: updates.append("password=?"); params.append(encrypt_password(body.password))
        if body.domain is not None: updates.append("domain=?"); params.append(body.domain)
        if body.role is not None: updates.append("role=?"); params.append(body.role)
        if body.smtp_host is not None: updates.append("smtp_host=?"); params.append(body.smtp_host)
        if body.smtp_port is not None: updates.append("smtp_port=?"); params.append(body.smtp_port)
        if body.imap_host is not None: updates.append("imap_host=?"); params.append(body.imap_host)
        if body.daily_limit is not None: updates.append("daily_limit=?"); params.append(body.daily_limit)
        if body.current_day is not None: updates.append("current_day=?"); params.append(body.current_day)
        if body.status is not None: updates.append("status=?"); params.append(body.status)
        if not updates:
            return {"ok": True}
        params.append(aid)
        query = f"UPDATE warmup_accounts SET {', '.join(updates)} WHERE id=?"
        conn.execute(query, params)
    return {"ok":True}

@legacy_routes.delete("/api/warmup/accounts/{aid}")
async def api_del_wu(aid:int, user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn: conn.execute("DELETE FROM warmup_accounts WHERE id=?",(aid,))
    return {"ok":True}

class WhatsAppGenerateRequest(BaseModel):
    lead_id: int

@legacy_routes.post("/api/whatsapp/generate")
async def api_whatsapp_generate(body: WhatsAppGenerateRequest, user: str = Depends(get_current_user)):
    from database import get_conn
    from ai_engine import generate_whatsapp
    with get_conn() as conn:
        row = conn.execute("SELECT business_name, pain_points, country, phone FROM leads WHERE id=?", (body.lead_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Lead not found")
        message = await asyncio.get_running_loop().run_in_executor(
            None, lambda: generate_whatsapp(row.get("business_name", ""), row.get("pain_points", ""), row.get("country", ""))
        )
        return {"message": message, "phone": row.get("phone", ""), "business_name": row.get("business_name", "")}

@legacy_routes.get("/api/whatsapp/leads")
async def api_whatsapp_leads(limit: int = 200, min_score: int = 0, user: str = Depends(get_current_user)):
    """Get leads with phone numbers for WhatsApp outreach."""
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, business_name, phone, email, country, lead_score, intent_score, "
            "pain_points, decision_maker, estimated_monthly_loss, ideal_service "
            "FROM leads WHERE phone IS NOT NULL AND phone != '' AND phone != 'N/A' "
            "AND LENGTH(phone) >= 7 AND lead_score >= ? "
            "ORDER BY lead_score DESC LIMIT ?",
            (min_score, limit)
        ).fetchall()
    return [dict(r) for r in rows]

# ── Warmup Placement & Rescue ──
@legacy_routes.post("/api/warmup/accounts/{aid}/placement")
async def api_check_placement(aid: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from outreach import check_placement
    from config import decrypt_password
    with get_conn() as conn:
        acct = conn.execute("SELECT * FROM warmup_accounts WHERE id=?", (aid,)).fetchone()
        if not acct:
            raise HTTPException(404, "Account not found")
        senders = [dict(r) for r in conn.execute(
            "SELECT domain FROM warmup_accounts WHERE role='sender'"
        ).fetchall()]
    sender_domains = list(set(s["domain"] for s in senders))
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: check_placement(acct["imap_host"], acct["email"], decrypt_password(acct["password"]), sender_domains)
    )
    return result

@legacy_routes.post("/api/warmup/accounts/{aid}/rescue")
async def api_rescue_spam(aid: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from outreach import rescue_from_spam
    from config import decrypt_password
    with get_conn() as conn:
        acct = conn.execute("SELECT * FROM warmup_accounts WHERE id=?", (aid,)).fetchone()
        if not acct:
            raise HTTPException(404, "Account not found")
        senders = [dict(r) for r in conn.execute(
            "SELECT domain FROM warmup_accounts WHERE role='sender'"
        ).fetchall()]
    sender_domains = list(set(s["domain"] for s in senders))
    loop = asyncio.get_running_loop()
    rescued = await loop.run_in_executor(
        None, lambda: rescue_from_spam(acct["imap_host"], acct["email"], decrypt_password(acct["password"]), sender_domains)
    )
    return {"rescued": rescued, "account": acct["email"]}

@legacy_routes.post("/api/warmup/rescue-all")
async def api_rescue_all(user: str = Depends(get_current_user)):
    """Run spam rescue on all receiver accounts."""
    from database import get_conn
    from outreach import rescue_from_spam
    from config import decrypt_password
    with get_conn() as conn:
        receivers = [dict(r) for r in conn.execute(
            "SELECT * FROM warmup_accounts WHERE role='receiver'"
        ).fetchall()]
        senders = [dict(r) for r in conn.execute(
            "SELECT domain FROM warmup_accounts WHERE role='sender'"
        ).fetchall()]
    if not receivers:
        return {"rescued": 0, "message": "No receiver accounts found"}
    sender_domains = list(set(s["domain"] for s in senders))
    loop = asyncio.get_running_loop()
    total = 0
    for recv in receivers:
        r = await loop.run_in_executor(
            None, lambda rv=recv: rescue_from_spam(rv["imap_host"], rv["email"], decrypt_password(rv["password"]), sender_domains)
        )
        total += r
    return {"rescued": total, "accounts_checked": len(receivers)}

@legacy_routes.get("/api/warmup/logs")
async def api_warmup_logs(limit: int = 100, offset: int = 0, user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT wl.id, wl.subject, wl.sent_at, wl.landed_in, wl.rescued, "
            "sa.email as from_email, sa.domain as from_domain, "
            "ra.email as to_email "
            "FROM warmup_log wl "
            "LEFT JOIN warmup_accounts sa ON sa.id = wl.from_account "
            "LEFT JOIN warmup_accounts ra ON ra.id = wl.to_account "
            "ORDER BY wl.sent_at DESC LIMIT ? OFFSET ?",
            (limit, offset)
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM warmup_log").fetchone()[0]
    return {"logs": [dict(r) for r in rows], "total": total}

@legacy_routes.get("/api/warmup/placement-summary")
async def api_warmup_placement_summary(user: str = Depends(get_current_user)):
    """Get placement stats summary from warmup logs."""
    from database import get_conn
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM warmup_log").fetchone()[0]
        rescued = conn.execute("SELECT COUNT(*) FROM warmup_log WHERE rescued=1").fetchone()[0]
        by_domain = [dict(r) for r in conn.execute(
            "SELECT sa.domain, COUNT(*) as sent, SUM(wl.rescued) as rescued "
            "FROM warmup_log wl JOIN warmup_accounts sa ON sa.id=wl.from_account "
            "GROUP BY sa.domain ORDER BY sent DESC"
        ).fetchall()]
        accounts_status = [dict(r) for r in conn.execute(
            "SELECT email, domain, role, current_day, status, daily_limit FROM warmup_accounts ORDER BY role, domain"
        ).fetchall()]
    return {
        "total_sent": total,
        "total_rescued": rescued,
        "by_domain": by_domain,
        "accounts": accounts_status
    }

# ── AI: Executive Summary & Recommendations ──
@legacy_routes.post("/api/leads/{lead_id}/executive-summary")
async def api_exec_summary(lead_id: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from ai_engine import generate_executive_summary
    with get_conn() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")
        lead = dict(lead)
        seo = [dict(r) for r in conn.execute(
            "SELECT * FROM seo_rankings WHERE lead_id=? ORDER BY checked_at DESC LIMIT 10", (lead_id,)
        ).fetchall()]
        comps = [dict(r) for r in conn.execute(
            "SELECT * FROM competitors WHERE lead_id=?", (lead_id,)
        ).fetchall()]
    # Build gaps list from tech stack
    gaps = []
    try:
        ts = json.loads(lead.get("tech_stack_json") or "{}")
        gaps = [{"category": k, "gap": v[0]} for k, v in ts.items() if v and v[0] == "none"]
    except Exception:
        pass
    loop = asyncio.get_running_loop()
    summary = await loop.run_in_executor(
        None, lambda: generate_executive_summary(lead, seo, comps, gaps)
    )
    return {"summary": summary, "business_name": lead["business_name"]}

@legacy_routes.post("/api/leads/{lead_id}/recommendations")
async def api_recommendations(lead_id: int, user: str = Depends(get_current_user)):
    from database import get_conn
    from ai_engine import generate_recommendations
    with get_conn() as conn:
        lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        if not lead:
            raise HTTPException(404, "Lead not found")
        lead = dict(lead)
    gaps = []
    try:
        ts = json.loads(lead.get("tech_stack_json") or "{}")
        gaps = [{"category": k, "gap": v[0]} for k, v in ts.items() if v and v[0] == "none"]
    except Exception:
        pass
    loop = asyncio.get_running_loop()
    recs = await loop.run_in_executor(
        None, lambda: generate_recommendations(lead, gaps)
    )
    return {"recommendations": recs, "business_name": lead["business_name"]}

# ── Warmup SMTP Test per account ──
@legacy_routes.post("/api/warmup/accounts/{aid}/test")
async def api_test_wu_account(aid: int, user: str = Depends(get_current_user)):
    from database import get_conn
    import smtplib
    from config import decrypt_password
    with get_conn() as conn:
        acct = conn.execute("SELECT * FROM warmup_accounts WHERE id=?", (aid,)).fetchone()
        if not acct:
            raise HTTPException(404, "Account not found")
    smtp_host = acct["smtp_host"]
    smtp_port = acct["smtp_port"]
    email_addr = acct["email"]
    password = decrypt_password(acct["password"])
    def _test():
        try:
            s = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            s.starttls()
            s.login(email_addr, password)
            s.quit()
            return True, None
        except Exception as e:
            return False, str(e)
    loop = asyncio.get_running_loop()
    ok, err = await loop.run_in_executor(None, _test)
    return {"ok": ok, "error": err, "email": email_addr}

# ── Outreach Accounts (multi-account primary sending) ──
class OutreachAccountBody(BaseModel):
    email: str
    password: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    imap_host: str = "imap.gmail.com"
    display_name: Optional[str] = None
    daily_limit: int = 150
    sending_mode: str = "smtp_password"
    signature: Optional[str] = None

class OutreachAccountUpdate(BaseModel):
    password: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    imap_host: Optional[str] = None
    display_name: Optional[str] = None
    daily_limit: Optional[int] = None
    active: Optional[int] = None
    sending_mode: Optional[str] = None
    signature: Optional[str] = None

@legacy_routes.get("/api/outreach-accounts")
async def api_list_outreach_accounts(user: str = Depends(get_current_user)):
    from database import get_outreach_accounts
    return get_outreach_accounts()

@legacy_routes.post("/api/outreach-accounts")
async def api_add_outreach_account(body: OutreachAccountBody, _=Depends(require_admin)):
    from database import get_conn
    from config import encrypt_password
    encrypted_pw = encrypt_password(body.password or "")
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO outreach_accounts (email,password,smtp_host,smtp_port,imap_host,display_name,daily_limit,sending_mode,signature) VALUES (?,?,?,?,?,?,?,?,?)",
            (body.email, encrypted_pw, body.smtp_host, body.smtp_port, body.imap_host, body.display_name, body.daily_limit, body.sending_mode, body.signature)
        )
    return {"ok": True}

@legacy_routes.put("/api/outreach-accounts/{aid}")
async def api_update_outreach_account(aid: int, body: OutreachAccountUpdate, user: str = Depends(get_current_user)):
    from database import get_conn
    from config import encrypt_password
    with get_conn() as conn:
        updates, params = [], []
        if body.password is not None:     updates.append("password=?");     params.append(encrypt_password(body.password))
        if body.smtp_host is not None:    updates.append("smtp_host=?");    params.append(body.smtp_host)
        if body.smtp_port is not None:    updates.append("smtp_port=?");    params.append(body.smtp_port)
        if body.imap_host is not None:    updates.append("imap_host=?");    params.append(body.imap_host)
        if body.display_name is not None: updates.append("display_name=?"); params.append(body.display_name)
        if body.daily_limit is not None:  updates.append("daily_limit=?");  params.append(body.daily_limit)
        if body.active is not None:       updates.append("active=?");       params.append(body.active)
        if body.sending_mode is not None: updates.append("sending_mode=?"); params.append(body.sending_mode)
        if body.signature is not None:    updates.append("signature=?");    params.append(body.signature)
        if not updates:
            return {"ok": True}
        params.append(aid)
        conn.execute(f"UPDATE outreach_accounts SET {', '.join(updates)} WHERE id=?", params)
    return {"ok": True}

@legacy_routes.delete("/api/outreach-accounts/{aid}")
async def api_delete_outreach_account(aid: int, _=Depends(require_admin)):
    from database import get_conn
    with get_conn() as conn:
        conn.execute("DELETE FROM outreach_accounts WHERE id=?", (aid,))
    return {"ok": True}

@legacy_routes.post("/api/outreach-accounts/{aid}/test")
async def api_test_outreach_account(aid: int, user: str = Depends(get_current_user)):
    import smtplib
    from database import get_conn
    with get_conn() as conn:
        acct = conn.execute("SELECT * FROM outreach_accounts WHERE id=?", (aid,)).fetchone()
        if not acct:
            raise HTTPException(404, "Account not found")
    acct = dict(acct)
    acct.setdefault("sending_mode", "smtp_password")
    if acct["sending_mode"] == "brevo_relay":
        from outreach import test_brevo_smtp
        ok = await asyncio.get_running_loop().run_in_executor(None, test_brevo_smtp)
        return {"ok": ok, "error": None if ok else "Brevo SMTP failed", "email": acct["email"], "mode": "brevo_relay"}
    smtp_host = acct["smtp_host"]
    smtp_port = acct["smtp_port"]
    email_addr = acct["email"]
    password = acct["password"]
    def _test():
        try:
            s = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            s.starttls()
            s.login(email_addr, password)
            s.quit()
            return True, None
        except Exception as e:
            return False, str(e)
    ok, err = await asyncio.get_running_loop().run_in_executor(None, _test)
    return {"ok": ok, "error": err, "email": email_addr, "mode": "smtp_password"}

# ── Config ──
_PROVIDER_KEYS = {"SERPER_API_KEY", "GOOGLE_PLACES_API_KEY", "YELP_API_KEY",
                  "PAGESPEED_API_KEY", "OPENROUTER_API_KEY"}


@app.get("/api/config")
async def api_get_config(_=Depends(require_admin)):
    from dotenv import dotenv_values
    pending = dotenv_values(Path(__file__).parent / ".env", interpolate=False)
    return {"providers": {key: bool(pending.get(key, getattr(config, key, "")))
                          for key in sorted(_PROVIDER_KEYS)},
            "max_concurrent_tasks": 1,
            "outreach_enabled": config.OUTREACH_ENABLED,
            "public_audit_enabled": config.PUBLIC_AUDIT_ENABLED,
            "scheduler_enabled": config.SCHEDULER_ENABLED}


@app.put("/api/config")
async def api_update_config(updates: dict, _=Depends(require_admin)):
    import unicodedata
    from dotenv import set_key
    for key, value in updates.items():
        if key not in _PROVIDER_KEYS:
            raise HTTPException(400, "Only discovery, audit and optional AI API keys can be updated")
        if (not isinstance(value, str) or len(value) > 512 or
                any(unicodedata.category(c).startswith("C") for c in value)):
            raise HTTPException(400, "API keys must be text without control characters (maximum 512)")
    path = Path(__file__).parent / ".env"
    for key, value in updates.items():
        set_key(path, key, value.strip(), quote_mode="always")
    if path.exists() and os.name != "nt":
        path.chmod(0o600)
    return {"ok": True, "message": "Saved. Restart the server to apply API key changes."}


# ── Activity ──
@app.get("/api/activity")
async def api_activity(limit:int=20, user: str = Depends(get_current_user)):
    from database import get_conn
    with get_conn() as conn:
        rows=conn.execute("SELECT e.event_type,e.note,e.created_at,l.business_name,l.email FROM events e JOIN leads l ON l.id=e.lead_id ORDER BY e.created_at DESC LIMIT ?",(limit,)).fetchall()
    return [dict(r) for r in rows]


# ── v4 New Endpoints ──
@legacy_routes.get("/api/leads/search")
@limiter.limit("60/minute")
async def search_leads(request: Request, q: str, limit: int = 50, _=Depends(get_current_user)):
    from database import search_leads_fulltext
    rows = search_leads_fulltext(q, limit)
    return [dict(r) for r in rows]


@app.get("/api/leads/export/csv")
async def export_leads_csv(user: str = Depends(get_current_user)):
    return StreamingResponse(csv_export(engine_store, user), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="lead-engine-businesses.csv"'})


class BulkLeadRequest(BaseModel):
    operation: str
    lead_ids: List[int]
    value: Optional[str] = None


@legacy_routes.post("/api/leads/bulk")
@limiter.limit("30/minute")
async def bulk_lead_operation(request: Request, body: BulkLeadRequest, _=Depends(get_current_user)):
    from database import get_conn
    if not body.lead_ids:
        return {"updated": 0}
    op = body.operation
    ids = body.lead_ids
    placeholders = ",".join("?" * len(ids))

    if op == "assign":
        if body.value is None:
            raise HTTPException(400, "Missing 'value' (assignee)")
        with get_conn() as conn:
            cur = conn.execute(
                f"UPDATE leads SET assigned_to=?, last_activity_at=datetime('now') WHERE id IN ({placeholders})",
                [body.value, *ids],
            )
            return {"updated": cur.rowcount}

    if op == "pipeline":
        if not body.value:
            raise HTTPException(400, "Missing 'value' (pipeline stage)")
        with get_conn() as conn:
            cur = conn.execute(
                f"UPDATE leads SET pipeline_stage=?, last_activity_at=datetime('now') WHERE id IN ({placeholders})",
                [body.value, *ids],
            )
            return {"updated": cur.rowcount}

    if op == "tag":
        if not body.value:
            raise HTTPException(400, "Missing 'value' (tag)")
        with get_conn() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO lead_tags (lead_id, tag) VALUES (?,?)",
                [(lid, body.value) for lid in ids],
            )
        return {"updated": len(ids)}

    if op == "untag":
        if not body.value:
            raise HTTPException(400, "Missing 'value' (tag)")
        with get_conn() as conn:
            cur = conn.execute(
                f"DELETE FROM lead_tags WHERE tag=? AND lead_id IN ({placeholders})",
                [body.value, *ids],
            )
            return {"updated": cur.rowcount}

    if op == "delete":
        with get_conn() as conn:
            cur = conn.execute(f"DELETE FROM leads WHERE id IN ({placeholders})", ids)
            return {"updated": cur.rowcount}

    raise HTTPException(400, f"Unknown operation: {op}")


# ── Public Audit Request (landing page form) ──
class AuditRequestBody(BaseModel):
    business_name: str
    website: str
    email: str
    phone: Optional[str] = ""
    industry: Optional[str] = ""
    country: Optional[str] = ""


@legacy_routes.post("/api/public/audit-request")
@limiter.limit("5/minute")
async def public_audit_request(request: Request, body: AuditRequestBody):
    from database import get_conn, upsert_leads
    from audit import audit_lead, estimate_revenue_impact
    from audit_pages import generate_audit_page
    import hashlib

    website = body.website.strip()
    if not website.startswith("http"):
        website = "https://" + website

    place_id = f"audit-{hashlib.md5(website.encode()).hexdigest()[:12]}"

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id, audit_page_token FROM leads WHERE place_id=?", (place_id,)
        ).fetchone()

    if existing and existing["audit_page_token"]:
        from config import BASE_URL
        existing_url = f"{BASE_URL}/audit/{existing['audit_page_token']}"
        return {"ok": True, "status": "existing", "audit_url": existing_url, "message": "Your audit is ready!"}

    raw = {
        "title": body.business_name,
        "placeId": place_id,
        "website": website,
        "phoneNumber": body.phone or "",
        "email": body.email,
        "rating": 0,
        "userRatingCount": 0,
        "address": "",
        "category": body.industry or "",
        "_niche": body.industry or "",
        "_city": "",
        "_country": body.country or "",
        "_query": "landing-page-audit",
        "_source": "landing_page",
    }

    loop = asyncio.get_running_loop()
    connector = aiohttp.TCPConnector(ssl=config.VERIFY_SSL, ttl_dns_cache=300)
    timeout_cfg = aiohttp.ClientTimeout(total=30)

    try:
        async with aiohttp.ClientSession(connector=connector, timeout=timeout_cfg) as audit_session:
            audited = await audit_lead(raw, audit_session, skip_competitor_filter=True)
    except Exception as e:
        audited = None

    if not audited or not isinstance(audited, dict):
        audited = {
            "place_id": place_id,
            "business_name": body.business_name,
            "phone": body.phone or "N/A",
            "email": body.email,
            "website": website,
            "niche": body.industry or "",
            "country": body.country or "",
            "lead_score": 0,
            "pain_points": "[]",
            "ops_pain_points": "[]",
            "tech_stack_json": "{}",
            "estimated_monthly_loss": 0,
            "ideal_service": "",
            "source_query": "landing-page-audit",
            "has_website": 0, "has_ssl": 0, "is_mobile_friendly": 0,
            "has_tracking_pixel": 0, "site_dead": 0, "uses_free_email": 0,
            "pagespeed_score": -1, "rating": 0, "review_count": 0,
            "address": "", "city": "",
            "has_facebook": 0, "has_instagram": 0, "has_linkedin": 0,
            "ops_score": 0, "intent_score": 0, "intent_reasons": "[]",
            "decision_maker": None, "decision_maker_title": None, "dm_source": None,
        }
    else:
        audited["email"] = body.email
        audited["phone"] = body.phone or audited.get("phone", "N/A")
        if not audited.get("niche") and body.industry:
            audited["niche"] = body.industry
        if not audited.get("country") and body.country:
            audited["country"] = body.country

    upsert_leads([audited])

    with get_conn() as conn:
        lead_row = conn.execute("SELECT id FROM leads WHERE place_id=?", (place_id,)).fetchone()
    lead_id = lead_row["id"]

    pains = json.loads(audited.get("pain_points", "[]") or "[]")
    ops = json.loads(audited.get("ops_pain_points", "[]") or "[]")
    roi = estimate_revenue_impact(
        audited.get("niche", ""), pains, ops, audited.get("country", "")
    )

    seo = []
    comps = []
    audit_path = await loop.run_in_executor(
        None, lambda: generate_audit_page(lead_id, audited, seo, comps, roi)
    )

    from config import BASE_URL
    audit_url = f"{BASE_URL}{audit_path}"

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO lead_notes (lead_id, note, author) VALUES (?,?,?)",
            (lead_id, f"Audit requested from landing page. Website: {website}", "landing_page"),
        )
        conn.execute(
            "INSERT INTO events (lead_id, event_type, note) VALUES (?,?,?)",
            (lead_id, "audit_requested", f"email={body.email} website={website}"),
        )

    async def _send_audit_email():
        async with _audit_email_sem:
            from outreach import SMTPSession
            from config import YOUR_NAME, YOUR_COMPANY
            try:
                smtp = SMTPSession(None)
                subject = f"Your Free Digital Audit — {body.business_name}"
                body_text = (
                    f"Hi there,\n\n"
                    f"Here's your complimentary Digital Presence Audit for {body.business_name}.\n\n"
                    f"Your personalized audit page is ready:\n{audit_url}\n\n"
                    f"This page includes:\n"
                    f"- Your digital health score\n"
                    f"- Revenue impact of each gap found\n"
                    f"- Technology stack analysis\n"
                    f"- Prioritized fix list\n\n"
                    f"This link expires in 48 hours.\n\n"
                    f"If you'd like to discuss the results or need help fixing any of the issues, "
                    f"just reply to this email — we'd be happy to help.\n\n"
                    f"Best,\n{YOUR_NAME}\n{YOUR_COMPANY}"
                )
                ok, err = smtp.send(body.email, subject, body_text)
                smtp.quit()
                if ok:
                    with get_conn() as conn:
                        conn.execute(
                            "INSERT INTO events (lead_id, event_type, note) VALUES (?,?,?)",
                            (lead_id, "audit_email_sent", f"Audit page emailed to {body.email}"),
                        )
                else:
                    with get_conn() as conn:
                        conn.execute(
                            "INSERT INTO events (lead_id, event_type, note) VALUES (?,?,?)",
                            (lead_id, "audit_email_failed", f"SMTP error: {err}"),
                        )
            except Exception as e:
                with get_conn() as conn:
                    conn.execute(
                        "INSERT INTO events (lead_id, event_type, note) VALUES (?,?,?)",
                        (lead_id, "audit_email_error", str(e)),
                    )

    t = asyncio.create_task(_send_audit_email())
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)

    return {"ok": True, "status": "created", "audit_url": audit_url, "message": "Your audit is being prepared! Check your email within a few minutes."}


@legacy_routes.post("/api/webhook/capture")
@limiter.limit("30/minute")
async def capture_webhook(request: Request):
    """Capture email from audit page form (public, no auth)."""
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    email = (data.get("email") or "").strip()
    token = (data.get("token") or "").strip()
    if not email or not token:
        raise HTTPException(400, "Missing email/token")
    from database import get_conn
    with get_conn() as conn:
        lead = conn.execute(
            "SELECT id, business_name FROM leads WHERE audit_page_token=?",
            (token,),
        ).fetchone()
        if not lead:
            raise HTTPException(404, "Audit token not found")
        conn.execute(
            "INSERT INTO events (lead_id, event_type, note) VALUES (?,?,?)",
            (lead["id"], "captured_email", email),
        )
        # Also record as a note for CRM visibility
        conn.execute(
            "INSERT INTO lead_notes (lead_id, note, author) VALUES (?,?,?)",
            (lead["id"], f"Captured email from audit page: {email}", "system"),
        )
    return {"ok": True, "message": "Email captured"}


@legacy_routes.get("/api/analytics/cohort")
@limiter.limit("30/minute")
async def analytics_cohort(request: Request, days_back: int = 30, _=Depends(get_current_user)):
    from analytics import get_cohort_analysis
    return get_cohort_analysis(days_back)


@legacy_routes.get("/api/analytics/ab")
@limiter.limit("30/minute")
async def analytics_ab(request: Request, _=Depends(get_current_user)):
    from analytics import get_ab_test_results
    return get_ab_test_results()


@legacy_routes.get("/api/analytics/sendtime")
@limiter.limit("30/minute")
async def analytics_sendtime(request: Request, _=Depends(get_current_user)):
    from analytics import get_best_send_time
    return get_best_send_time()


class NotifyBody(BaseModel):
    message: str


@legacy_routes.post("/api/notify/slack")
@limiter.limit("10/hour")
async def notify_slack(request: Request, body: NotifyBody, _=Depends(get_current_user)):
    from analytics import send_slack_notification
    success = await send_slack_notification(body.message)
    return {"ok": success}


@legacy_routes.post("/api/notify/discord")
@limiter.limit("10/hour")
async def notify_discord(request: Request, body: NotifyBody, _=Depends(get_current_user)):
    from analytics import send_discord_notification
    success = await send_discord_notification(body.message)
    return {"ok": success}


if __name__ == "__main__":
    import uvicorn; uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)