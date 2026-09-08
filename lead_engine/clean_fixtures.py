"""Count first; explicitly confirmed, transactional fixture-only maintenance."""
import argparse
import hashlib
import json
from sqlalchemy import select, delete, text
from production_db import transaction
from production_models import (Business, ProviderRef, SearchJob, SearchJobItem, AuditRun,
    AuditPage, AuditEvidence, BusinessContact, LeadScore, BrowserCleanup)
from local_modes import LEGACY_FIXTURE_IDS

TABLES = (AuditEvidence, BusinessContact, LeadScore, AuditPage, AuditRun,
          SearchJobItem, BrowserCleanup, ProviderRef, Business, SearchJob)


def plan(db):
    # Name/hostname alone never authorizes deletion of live or historical rows.
    refs = list(db.scalars(select(ProviderRef)))
    items = list(db.scalars(select(SearchJobItem)))
    jobs = {j.id: j for j in db.scalars(select(SearchJob))}
    candidates = set()
    for business in db.scalars(select(Business).where(Business.run_mode == 'offline_test')):
        sources = [r for r in refs if r.business_id == business.id]
        known = sources and all((r.provider == 'fixture' and r.provider_record_id.startswith('fixture:')) or
            (r.provider == 'google_places_new' and r.provider_record_id in LEGACY_FIXTURE_IDS and
             business.browser_observed_url == 'https://fixture-business.test/' and
             business.browser_observed_name == 'Independently observed business') for r in sources)
        if known and all(jobs[i.job_id].run_mode == 'offline_test' for i in items if i.business_id == business.id):
            candidates.add(business.id)
    selected_jobs = {j.id for j in jobs.values() if j.run_mode == 'offline_test' and
        all(i.business_id in candidates for i in items if i.job_id == j.id)}
    # Preserve mixed job history in its entirety, even transitively shared rows.
    while True:
        retained = {bid for bid in candidates if all(i.job_id in selected_jobs for i in items if i.business_id == bid)}
        retained_jobs = {jid for jid in selected_jobs if all(i.business_id in retained for i in items if i.job_id == jid)}
        if retained == candidates and retained_jobs == selected_jobs:
            break
        candidates, selected_jobs = retained, retained_jobs
    selected_items = {i.id for i in items if i.job_id in selected_jobs and i.business_id in candidates}
    audits = set(db.scalars(select(AuditRun.id).where(AuditRun.item_id.in_(selected_items))))
    ids = {
        Business: candidates, SearchJob: selected_jobs, SearchJobItem: selected_items, AuditRun: audits,
        ProviderRef: {r.id for r in refs if r.business_id in candidates},
        BrowserCleanup: set(db.scalars(select(BrowserCleanup.id).where(BrowserCleanup.job_id.in_(selected_jobs))))}
    for model in (AuditEvidence, BusinessContact, LeadScore, AuditPage):
        ids[model] = set(db.scalars(select(model.id).where(model.audit_id.in_(audits))))
    active = any(jobs[jid].status in ('queued', 'running') for jid in selected_jobs)
    pending = db.scalar(select(BrowserCleanup.id).where(BrowserCleanup.id.in_(ids[BrowserCleanup]), BrowserCleanup.pending).limit(1))
    digest = hashlib.sha256(json.dumps({m.__tablename__: sorted(v) for m, v in ids.items()}, sort_keys=True).encode()).hexdigest()
    return ids, dict(counts={m.__tablename__: len(ids[m]) for m in TABLES}, plan=digest,
                     safe_to_apply=not active and pending is None)


def clean(db, expected_plan, confirmation):
    if confirmation != 'DELETE FIXTURES':
        raise ValueError('Explicit DELETE FIXTURES confirmation required')
    # Short maintenance transaction prevents changes after checking the plan.
    db.execute(text("SET LOCAL lock_timeout = '3s'"))
    for name in sorted(m.__tablename__ for m in TABLES):
        db.execute(text('LOCK TABLE ' + name + ' IN SHARE ROW EXCLUSIVE MODE'))
    ids, summary = plan(db)
    if summary['plan'] != expected_plan:
        raise ValueError('Fixture data changed; run a new dry run and confirm again')
    if not summary['safe_to_apply']:
        raise ValueError('Fixture work or browser cleanup is pending; stop work and retry')
    deleted = {}
    for model in TABLES:
        deleted[model.__tablename__] = db.execute(delete(model).where(model.id.in_(ids[model]))).rowcount
    return dict(deleted=deleted, remaining=plan(db)[1]['counts'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--confirm')
    parser.add_argument('--plan')
    args = parser.parse_args()
    try:
        with transaction() as db:
            result = clean(db, args.plan, args.confirm) if args.confirm is not None else plan(db)[1]
        print(json.dumps(result, sort_keys=True))
    except Exception:
        print('Fixture cleanup refused or rolled back. Run dry run again; ensure fixture jobs and cleanup have finished.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
