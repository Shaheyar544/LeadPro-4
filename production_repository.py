"""Short PostgreSQL transactions; browser I/O never runs inside them."""
from datetime import timedelta
from sqlalchemy import select, func, or_, and_
from production_models import *
from production_db import transaction
from production_scoring import score_browser_evidence
from local_modes import run_mode, validate_reference, fixture_url

LEASE_SECONDS = 12

class LeaseLost(Exception):
    pass

def event(db, action, user_id=None, subject_id=None):
    db.add(SecurityEvent(action=action, user_id=user_id, subject_id=subject_id))

class ProductionRepository:
    def claim_job(self):
        with transaction() as db:
            job = db.scalar(select(SearchJob).where(or_(
                SearchJob.status == 'queued',
                and_(SearchJob.status == 'running', SearchJob.lease_until < utcnow())
            ), SearchJob.run_mode == run_mode()).order_by(SearchJob.created_at).with_for_update(skip_locked=True).limit(1))
            if job is None:
                return None
            if job.cancel_requested:
                job.status = 'cancelled'
                job.finished_at = utcnow()
                return None
            job.status = 'running'
            job.lease_token = uid()
            job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
            job.heartbeat_at = utcnow()
            job.attempts += 1
            return job

    def owned(self, db, job_id, token):
        job = db.scalar(select(SearchJob).where(SearchJob.id == job_id).with_for_update())
        if not job or job.run_mode != run_mode() or job.status != 'running' or job.lease_token != token or job.lease_until <= utcnow():
            raise LeaseLost()
        return job

    def heartbeat(self, job_id, token):
        with transaction() as db:
            job = self.owned(db, job_id, token)
            job.heartbeat_at = utcnow()
            job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
            return job.cancel_requested

    def cancelled(self, job_id, token):
        with transaction() as db:
            return self.owned(db, job_id, token).cancel_requested

    def add_reference(self, job_id, token, provider, record_id):
        validate_reference(provider, record_id)
        with transaction() as db:
            job = self.owned(db, job_id, token)
            ref = db.scalar(select(ProviderRef).where(ProviderRef.user_id == job.user_id,
                ProviderRef.provider == provider, ProviderRef.provider_record_id == record_id))
            if ref is None:
                business = Business(user_id=job.user_id, run_mode=job.run_mode)
                db.add(business)
                db.flush()
                ref = ProviderRef(user_id=job.user_id, business_id=business.id,
                                  provider=provider, provider_record_id=record_id)
                db.add(ref)
                db.flush()
            if db.get(Business, ref.business_id).run_mode != job.run_mode:
                raise ValueError('Business run mode mismatch')
            item = db.scalar(select(SearchJobItem).where(SearchJobItem.job_id == job_id,
                                                        SearchJobItem.business_id == ref.business_id))
            if item is None:
                item = SearchJobItem(job_id=job_id, business_id=ref.business_id)
                db.add(item)
                db.flush()
            return item

    def begin_item(self, job_id, token, item_id):
        with transaction() as db:
            job = self.owned(db, job_id, token)
            item = db.get(SearchJobItem, item_id)
            if not item or item.job_id != job_id:
                raise LeaseLost()
            if item.status == 'completed' or job.cancel_requested:
                return False
            item.status = 'running'
            return True

    def register_cleanup(self, job_id, token, handle):
        with transaction() as db:
            self.owned(db, job_id, token)
            row = BrowserCleanup(job_id=job_id, user_handle=handle)
            db.add(row)
            db.flush()
            return row.id

    def cleanup_done(self, cleanup_id):
        with transaction() as db:
            db.get(BrowserCleanup, cleanup_id).pending = False

    def cleanup_pending(self):
        with transaction() as db:
            return list(db.scalars(select(BrowserCleanup).join(SearchJob).where(
                BrowserCleanup.pending, SearchJob.run_mode == run_mode())))

    def save_audit(self, job_id, token, item_id, audit):
        """Only the BrowserProvider/AuditEngine result enters this boundary."""
        score = score_browser_evidence(audit)
        with transaction() as db:
            job = self.owned(db, job_id, token)
            item = db.get(SearchJobItem, item_id)
            if not item or item.job_id != job_id:
                raise LeaseLost()
            if item.status == 'completed':
                return
            if job.cancel_requested:
                raise LeaseLost()
            business = db.get(Business, item.business_id)
            if business.run_mode != job.run_mode:
                raise ValueError('Business run mode mismatch')
            if job.run_mode == 'live' and (fixture_url(audit.get('final_url')) or any(
                fixture_url(p.get('final_url')) or p.get('title') == 'Independently observed business'
                for p in audit['pages'])):
                raise ValueError('Fixture browser output rejected in LIVE')
            # Provider input is never passed here. Only successfully observed pages.
            observed = [p for p in audit['pages'] if p.get('status') in ('completed', 'partial')]
            if observed:
                business.browser_observed_url = audit.get('final_url')
                business.browser_observed_name = observed[0].get('title')
            run = AuditRun(item_id=item.id, business_id=business.id, status=audit['status'], error_code=audit.get('error_code'))
            db.add(run)
            db.flush()
            page_ids = set()
            for page in observed:
                # Discard failed-navigation URLs: they may still be provider input.
                data = {k: v for k, v in page.items() if k in ('page_type', 'status', 'final_url', 'title', 'navigation_ms')}
                db.add(AuditPage(id=page['id'], audit_id=run.id, data=data))
                page_ids.add(page['id'])
            db.flush()
            for evidence in audit['evidence']:
                if evidence.get('page_id') not in page_ids:
                    continue
                data = {k: v for k, v in evidence.items() if k in ('detector_key', 'status', 'value', 'source_url', 'page_type', 'excerpt', 'locator', 'confidence', 'detector_version', 'observed_at')}
                db.add(AuditEvidence(audit_id=run.id, page_id=evidence['page_id'], business_id=business.id, evidence=data))
            seen = set()
            for contact in audit['contacts']:
                if contact.get('evidence_type') == 'provider_public' or not observed:
                    continue
                key = (contact['type'], contact['normalized'])
                if key in seen:
                    continue
                seen.add(key)
                data = {k: v for k, v in contact.items() if k in ('source_url', 'evidence_type', 'confidence', 'excerpt', 'locator')}
                db.add(BusinessContact(audit_id=run.id, business_id=business.id, kind=key[0], normalized_value=key[1], data=data))
            db.add(LeadScore(audit_id=run.id, business_id=business.id, profile_version=score['profile_version'],
                             score=score['opportunity_score'], breakdown=score))
            item.status = 'completed'

    def finish(self, job_id, token, error=None):
        with transaction() as db:
            job = self.owned(db, job_id, token)
            job.status = 'cancelled' if job.cancel_requested else 'failed' if error else 'completed'
            job.error_code = error
            job.finished_at = utcnow()
            job.lease_until = None
            job.lease_token = None
            if job.cancel_requested:
                for item in db.scalars(select(SearchJobItem).where(SearchJobItem.job_id == job_id, SearchJobItem.status != 'completed')):
                    item.status = 'cancelled'
