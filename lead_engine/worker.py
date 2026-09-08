"""Durable PostgreSQL worker. Fenced writes and recoverable browser cleanup."""
import asyncio
import logging
import os
import signal
import time
from contextlib import contextmanager
from sqlalchemy import text
import redis
from browser.base import BrowserSession, BrowserError
from engine_config import EngineConfig
from audit_engine.runner import AuditEngine
from production_db import engine, check_database
from production_config import validate_production_config
from production_logging import configure_logging
from production_repository import ProductionRepository, LeaseLost
from redis_coordination import CoordinationLease, redis_ready, wait_for_work
from discovery import ProviderDiscovery

log = logging.getLogger('leadpro.worker')

@contextmanager
def global_capacity():
    """Postgres advisory fencing prevents Redis restart from doubling capacity."""
    with engine().connect().execution_options(isolation_level='AUTOCOMMIT') as guard:
        job_lock = bool(guard.execute(text('SELECT pg_try_advisory_lock(41002)')).scalar())
        browser_lock = job_lock and bool(guard.execute(text('SELECT pg_try_advisory_lock(41003)')).scalar())
        try:
            yield guard if job_lock and browser_lock else None
        finally:
            if browser_lock:
                guard.execute(text('SELECT pg_advisory_unlock(41003)'))
            if job_lock:
                guard.execute(text('SELECT pg_advisory_unlock(41002)'))

async def cleanup_orphans(repo, browser):
    for row in repo.cleanup_pending():
        try:
            await browser.close_session(BrowserSession(row.user_handle, ''))
            repo.cleanup_done(row.id)
        except BrowserError:
            return False
    return True

async def process_job(repo, job, real_browser, leases, guard):
    token = job.lease_token
    stopping = asyncio.Event()
    lost = asyncio.Event()
    async def heartbeat():
        while not stopping.is_set():
            await asyncio.sleep(1)
            try:
                guard.execute(text('SELECT 1'))
                repo.heartbeat(job.id, token)
                for lease in leases:
                    # Reacquisition is safe only while this process holds both
                    # PostgreSQL advisory locks across the Redis restart.
                    if not lease.renew() and not lease.acquire():
                        lost.set()
                        return
            except redis.RedisError:
                log.warning('redis_reconnecting postgres_lease_retained')
            except Exception:
                lost.set()
                return

    pulse = asyncio.create_task(heartbeat())
    cancelled = lambda: lost.is_set() or repo.cancelled(job.id, token)
    browser = real_browser
    try:
        offline = os.getenv('DISCOVERY_MODE') == 'offline'
        if offline:
            from .offline import OfflineGoogle, browser_fixture, validate_fixture
            source = OfflineGoogle()
            browser = browser_fixture()
            runner = AuditEngine(browser, EngineConfig(settle_ms=0, readiness_ms=500), validate=validate_fixture)
        else:
            source = ProviderDiscovery('google_places_new', os.getenv('GOOGLE_PLACES_NEW_API_KEY', ''))
            runner = AuditEngine(browser, EngineConfig())
        cursor = None
        processed = set()
        for _ in range(3):
            if cancelled():
                break
            if not (await real_browser.health()).available:
                return  # Keep unfinished work leased for recovery; never mark complete.
            page = await source.fetch_page(job.payload, cursor=cursor, limit=min(job.payload['target_count'], 20), cancelled=cancelled)
            log.info('provider_page_received transient_payload_discarded')
            for row in page.records:
                if cancelled() or len(processed) >= job.payload['target_count']:
                    break
                if row['provider_record_id'] in processed:
                    continue
                processed.add(row['provider_record_id'])
                item = repo.add_reference(job.id, token, row['provider'], row['provider_record_id'])
                if not repo.begin_item(job.id, token, item.id):
                    continue
                if not (await real_browser.health()).available:
                    # Leave lease to expire; no more discovery until browser ready.
                    return
                session = await browser.open_session()
                cleanup_id = repo.register_cleanup(job.id, token, session.user_id)
                try:
                    if offline:
                        await asyncio.sleep(min(float(os.getenv('OFFLINE_ITEM_DELAY', '0')), 10))
                    if cancelled():
                        break
                    # Only the transient navigation hint crosses into the browser.
                    # Provider phone/name/address/rating never enter AuditEngine.
                    result = await runner.run({'website_url': row.get('website_url', '')}, session, cancelled=cancelled)
                    if not cancelled():
                        repo.save_audit(job.id, token, item.id, result)
                        log.info('item_completed database=postgresql score=website_conversion_v2')
                finally:
                    try:
                        await browser.close_session(session)
                        repo.cleanup_done(cleanup_id)
                    except BrowserError:
                        log.warning('browser_cleanup_pending')
            if not page.cursor or len(processed) >= job.payload['target_count']:
                break
            cursor = page.cursor
        if not lost.is_set():
            repo.finish(job.id, token)
            log.info('job_finished database=postgresql')
    except LeaseLost:
        log.warning('job_lease_lost stale_write_rejected')
    except asyncio.CancelledError:
        log.info('worker_shutdown lease_recovery_pending')
        raise
    except Exception:
        log.error('worker_operation_failed')
        # Durable records remain recoverable after the bounded lease expires.
    finally:
        stopping.set()
        pulse.cancel()
        await asyncio.gather(pulse, return_exceptions=True)
        if browser is not real_browser:
            await browser.shutdown()

async def run():
    validate_production_config()
    configure_logging()
    if not check_database():
        raise RuntimeError('PostgreSQL schema is not at Alembic head')
    repo = ProductionRepository()
    browser = EngineConfig().browser()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    log.info('worker_started database=postgresql')
    try:
        while not stop.is_set():
            try:
                if not check_database() or not redis_ready() or not (await browser.health()).available:
                    await asyncio.sleep(1)
                    continue
                with global_capacity() as guard:
                    if guard is None:
                        await asyncio.sleep(.5)
                        continue
                    leases = [CoordinationLease('jobs'), CoordinationLease('browsers')]
                    try:
                        if not all(lease.acquire() for lease in leases):
                            await asyncio.sleep(.5)
                            continue
                        if not await cleanup_orphans(repo, browser):
                            await asyncio.sleep(1)
                            continue
                        job = repo.claim_job()
                        if job:
                            log.info('job_claimed database=postgresql')
                            task = asyncio.create_task(process_job(repo, job, browser, leases, guard))
                            waiter = asyncio.create_task(stop.wait())
                            await asyncio.wait([task, waiter], return_when=asyncio.FIRST_COMPLETED)
                            if stop.is_set() and not task.done():
                                task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
                            waiter.cancel()
                            await asyncio.gather(waiter, return_exceptions=True)
                    finally:
                        for lease in leases:
                            lease.release()
                await asyncio.to_thread(wait_for_work)
            except Exception:
                log.warning('worker_dependencies_reconnecting')
                await asyncio.sleep(1)
    finally:
        await browser.shutdown()

if __name__ == '__main__':
    asyncio.run(run())
