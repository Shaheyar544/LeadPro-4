"""Production API: PostgreSQL cookie sessions, CSRF, no in-process workers."""
import os
import hmac
import hashlib
import logging
import secrets
import socket
from datetime import timedelta
from contextlib import asynccontextmanager
from pathlib import Path
import bcrypt
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, delete, func
from sqlalchemy.exc import SQLAlchemyError
import redis
from production_models import User, Session, SearchJob, Business, BusinessContact, utcnow
from production_db import transaction, check_database
from production_config import validate_production_config
from production_logging import configure_logging
from production_repository import event
from production_views import job_view, detail_view, leads_view, export_csv
from qualification_params import qualification_params
from auth_sessions import fingerprint
from health import liveness, readiness
from redis_coordination import login_attempt, wake_worker
from product_models import LeadGenRequest
from local_modes import run_mode, visible_business
from live_preflight import preflight

COOKIE = '__Host-leadpro_offline_session' if run_mode() == 'offline_test' else '__Host-leadpro_session'
log = logging.getLogger('leadpro.api')
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt()).decode()

@asynccontextmanager
async def lifespan(app):
    validate_production_config()
    configure_logging()
    if not check_database():
        raise RuntimeError('PostgreSQL schema is not at Alembic head')
    log.info('api_started database=postgresql worker=external')
    yield

app = FastAPI(title='LeadPro production API', lifespan=lifespan, docs_url=None, redoc_url=None)

@app.middleware('http')
async def security_headers(request, call_next):
    if request.url.path.startswith('/api/') and request.method not in ('GET', 'HEAD', 'OPTIONS'):
        if request.headers.get('origin') != os.getenv('APP_ORIGIN'):
            return JSONResponse({'detail': 'Origin rejected'}, status_code=403)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({'detail': [dict(loc=e['loc'], msg='Invalid value', type=e['type']) for e in exc.errors()]}, status_code=422)

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    log.error('database_operation_failed')
    return JSONResponse({'detail': 'Database temporarily unavailable'}, status_code=503)

@app.exception_handler(redis.RedisError)
async def coordination_error(request, exc):
    log.warning('redis_unavailable')
    return JSONResponse({'detail': 'Coordination temporarily unavailable'}, status_code=503)

def csrf_for(sid):
    return hmac.new(os.environ['SESSION_SECRET'].encode(), sid.encode(), hashlib.sha256).hexdigest()

def authenticated(request: Request):
    sid = request.cookies.get(COOKIE, '')
    if not sid or len(sid) > 100:
        raise HTTPException(401, 'Sign in required')
    with transaction() as db:
        session = db.get(Session, fingerprint(sid))
        if session is None or session.expires_at <= utcnow():
            raise HTTPException(401, 'Session expired')
        user = db.get(User, session.user_id)
        if not user:
            raise HTTPException(401, 'Sign in required')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            token = request.headers.get('X-CSRF-Token', '')
            if len(token) != 64 or not token.isascii() or not hmac.compare_digest(csrf_for(sid), token):
                raise HTTPException(403, 'CSRF token rejected')
        return user, sid

def client_ip(request):
    peer = request.client.host
    # Uvicorn proxy-header processing is disabled. Only Caddy can supply the
    # dedicated header; it overwrites all client-supplied values.
    try:
        caddy_ips = {x[4][0] for x in socket.getaddrinfo('caddy', None)}
    except OSError:
        caddy_ips = set()
    return request.headers.get('x-leadpro-client-ip', peer) if peer in caddy_ips else peer

class Login(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=72)

class ChangePassword(BaseModel):
    model_config = ConfigDict(extra='forbid')
    old_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=12, max_length=72)

def password_ok(value, stored):
    return len(value.encode()) <= 72 and bcrypt.checkpw(value.encode(), stored.encode())

@app.get('/api/auth/mode')
def auth_mode():
    return {'mode': 'cookie', 'production': True, 'run_mode': run_mode()}

@app.post('/api/auth/login')
def login(body: Login, request: Request, response: Response):
    if not login_attempt(client_ip(request)):
        raise HTTPException(429, 'Too many login attempts; retry after 60 seconds', headers={'Retry-After': '60'})
    with transaction() as db:
        user = db.scalar(select(User).where(User.username == body.username).with_for_update())
        valid = password_ok(body.password, user.password_hash if user else DUMMY_HASH)
        if not valid:
            event(db, 'login_failure', user.id if user else None)
        else:
            sid = secrets.token_urlsafe(32)
            db.add(Session(id=fingerprint(sid), user_id=user.id, expires_at=utcnow() + timedelta(hours=8)))
            event(db, 'login_success', user.id)
    if not valid:
        log.info('login_failure')
        raise HTTPException(401, 'Invalid credentials')
    response.set_cookie(COOKIE, sid, max_age=28800, secure=True, httponly=True, samesite='strict', path='/')
    log.info('login_success')
    return {'username': user.username, 'csrf_token': csrf_for(sid)}

@app.get('/api/auth/me')
def me(auth=Depends(authenticated)):
    return {'username': auth[0].username, 'csrf_token': csrf_for(auth[1])}

@app.post('/api/auth/logout')
def logout(response: Response, auth=Depends(authenticated)):
    with transaction() as db:
        db.execute(delete(Session).where(Session.id == fingerprint(auth[1])))
        event(db, 'logout', auth[0].id)
    response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
    log.info('logout')
    return {'message': 'Signed out'}

@app.post('/api/auth/change-password')
def change_password(body: ChangePassword, response: Response, auth=Depends(authenticated)):
    if len(body.new_password.encode()) > 72:
        raise HTTPException(422, 'Password exceeds 72 UTF-8 bytes')
    with transaction() as db:
        user = db.scalar(select(User).where(User.id == auth[0].id).with_for_update())
        if not password_ok(body.old_password, user.password_hash):
            raise HTTPException(400, 'Current password is incorrect')
        user.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
        db.execute(delete(Session).where(Session.user_id == user.id))
        event(db, 'password_change', user.id)
    response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
    return {'message': 'Password updated; sign in again'}

@app.post('/api/leadgen/start')
def start(body: LeadGenRequest, auth=Depends(authenticated)):
    error = preflight()
    if error:
        raise HTTPException(503, error)
    with transaction() as db:
        db.scalar(select(User).where(User.id == auth[0].id).with_for_update())
        count = db.scalar(select(func.count()).select_from(SearchJob).where(
            SearchJob.user_id == auth[0].id, SearchJob.run_mode == run_mode(), SearchJob.status.in_(['queued', 'running'])))
        if count >= 10:
            raise HTTPException(429, 'Job queue capacity reached')
        job = SearchJob(user_id=auth[0].id, run_mode=run_mode(), payload=body.model_dump())
        db.add(job)
        db.flush()
        event(db, 'job_create', auth[0].id, job.id)
    wake_worker()
    return {'job_id': job.id}

def owned_job(db, jid, owner):
    job = db.get(SearchJob, jid)
    if job is None or job.user_id != owner or job.run_mode != run_mode():
        raise HTTPException(404, 'Job not found')
    return job

@app.get('/api/leadgen/jobs')
def jobs(auth=Depends(authenticated)):
    with transaction() as db:
        return [job_view(db, j) for j in db.scalars(select(SearchJob).where(SearchJob.user_id == auth[0].id,
            SearchJob.run_mode == run_mode()).order_by(SearchJob.created_at.desc()).limit(50))]

@app.get('/api/leadgen/jobs/{jid}')
def job_status(jid: str, auth=Depends(authenticated)):
    with transaction() as db:
        return job_view(db, owned_job(db, jid, auth[0].id))

@app.post('/api/leadgen/jobs/{jid}/cancel')
def cancel_job(jid: str, auth=Depends(authenticated)):
    with transaction() as db:
        job = db.scalar(select(SearchJob).where(SearchJob.id == jid).with_for_update())
        if not job or job.user_id != auth[0].id or job.run_mode != run_mode():
            raise HTTPException(404, 'Job not found')
        if job.status in ('queued', 'running'):
            job.cancel_requested = True
            if job.status == 'queued':
                job.status, job.finished_at = 'cancelled', utcnow()
            event(db, 'job_cancel', auth[0].id, jid)
    wake_worker()
    return {'status': 'cancellation_requested'}

@app.get('/api/leadgen/jobs/{jid}/results')
def results(jid: str, auth=Depends(authenticated)):
    with transaction() as db:
        owned_job(db, jid, auth[0].id)
        return leads_view(db, auth[0].id, limit=100, job_id=jid)

@app.get('/api/leads/export/csv')
def csv_route(filters=Depends(qualification_params), auth=Depends(authenticated)):
    with transaction() as db:
        if filters['job_id']:
            owned_job(db, filters['job_id'], auth[0].id)
        return Response(export_csv(db, auth[0].id, **filters), media_type='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=leads.csv'})

@app.get('/api/leads')
def leads(limit: int = 50, offset: int = 0, filters=Depends(qualification_params), auth=Depends(authenticated)):
    with transaction() as db:
        if filters['job_id']:
            owned_job(db, filters['job_id'], auth[0].id)
        return leads_view(db, auth[0].id, max(1, min(limit, 100)), max(0, offset), **filters)

@app.get('/api/businesses/{bid}')
def business_detail(bid: str, job_id: str | None = None, auth=Depends(authenticated)):
    with transaction() as db:
        b = db.scalar(select(Business).where(Business.id == bid, visible_business()))
        if not b or b.user_id != auth[0].id:
            raise HTTPException(404, 'Business not found')
        detail = detail_view(db, b, auth[0].id, job_id=job_id)
        if detail is None:
            raise HTTPException(404, 'Business not found in this search')
        return detail

@app.get('/api/stats')
def stats(auth=Depends(authenticated)):
    with transaction() as db:
        businesses = list(db.scalars(select(Business).where(Business.user_id == auth[0].id, visible_business())))
        emails = db.scalar(select(func.count(func.distinct(BusinessContact.business_id))).join(Business).where(
            Business.user_id == auth[0].id, visible_business(), BusinessContact.kind == 'email'))
        jobs = db.scalar(select(func.count()).select_from(SearchJob).where(SearchJob.user_id == auth[0].id,
            SearchJob.run_mode == run_mode(), SearchJob.status.in_(['queued', 'running'])))
        return dict(total=len(businesses), with_email=emails, with_website=sum(bool(b.browser_observed_url) for b in businesses), active_jobs=jobs)

@app.get('/api/config')
def config(auth=Depends(authenticated)):
    return {'max_concurrent_tasks': 1, 'providers': {'google_places_new': bool(os.getenv('GOOGLE_PLACES_NEW_API_KEY'))},
            'editable': False}

@app.put('/api/config')
def config_mutation(auth=Depends(authenticated)):
    raise HTTPException(403, 'Production provider settings are environment-only')

@app.get('/api/browser/health')
def browser_health(auth=Depends(authenticated)):
    # API has no browser network route; browser readiness belongs to the worker.
    return {'provider': 'camofox', 'status': 'worker_managed', 'contract_version': '1.14.0'}

@app.get('/health/live')
def live():
    return liveness()

@app.get('/health/ready')
def ready(response: Response):
    result = readiness()
    response.status_code = 200 if result['status'] == 'ok' else 503
    return result

@app.get('/')
def home():
    return FileResponse('index.html')

@app.get('/{asset}')
def static_asset(asset: str):
    if asset not in {'foundation.js', 'qualification.js', 'base_style.css', 'new_style.css'}:
        raise HTTPException(404, 'Not found')
    return FileResponse(asset)
