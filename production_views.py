"""Owner/mode/search-scoped projections used by API, detail and CSV."""
from collections import defaultdict
from sqlalchemy import select
from production_models import *
from local_modes import run_mode, visible_business, LIVE_ERROR
from lead_summary import qualify, lead_row, filter_sort, summary_csv, safe_cell
from growth_scoring import growth_for_detail


def job_view(db, job):
    items = list(db.scalars(select(SearchJobItem).join(Business).where(
        SearchJobItem.job_id == job.id, visible_business(job.run_mode))))
    done = sum(i.status == 'completed' for i in items)
    return dict(id=job.id, **job.payload, run_mode=job.run_mode, status=job.status, cancel_requested=job.cancel_requested,
                discovered_count=len(items), processed_count=done, qualified_count=done,
                error_message=LIVE_ERROR if job.error_code == 'live_discovery_unavailable' else job.error_code,
                created_at=job.created_at.isoformat())


def selected_job(db, owner, job_id=None):
    query = select(SearchJob).where(SearchJob.user_id == owner, SearchJob.run_mode == run_mode())
    if job_id:
        query = query.where(SearchJob.id == job_id)
    return db.scalar(query.order_by(SearchJob.created_at.desc(), SearchJob.id.desc()).limit(1))


def details_for_job(db, businesses, job):
    """Batch one bounded search: query count does not grow with the number of leads."""
    if not businesses or not job:
        return []
    ids = [b.id for b in businesses]
    runs = list(db.scalars(select(AuditRun).join(SearchJobItem).where(
        SearchJobItem.job_id == job.id, AuditRun.business_id.in_(ids)).order_by(AuditRun.created_at.desc(), AuditRun.id.desc())))
    histories = defaultdict(list)
    for run in runs:
        histories[run.business_id].append(run)
    latest = {bid: history[0] for bid, history in histories.items()}
    run_ids = [r.id for r in latest.values()]
    buckets = {}
    for model in (AuditPage, AuditEvidence, BusinessContact, LeadScore):
        grouped = defaultdict(list)
        if run_ids:
            for row in db.scalars(select(model).where(model.audit_id.in_(run_ids)).order_by(model.id)):
                grouped[row.audit_id].append(row)
        buckets[model] = grouped
    sources = defaultdict(list)
    for source in db.scalars(select(ProviderRef).where(ProviderRef.business_id.in_(ids))):
        sources[source.business_id].append(dict(provider=source.provider, provider_record_id=source.provider_record_id, observed_at=source.created_at.isoformat()))
    details = []
    for business in businesses:
        run = latest.get(business.id)
        rid = run.id if run else None
        pages = [dict(p.data, id=p.id) for p in buckets[AuditPage][rid]]
        evidence = [dict(e.evidence, id=e.id, observation_id=e.evidence.get('id'), provenance=e.provenance) for e in buckets[AuditEvidence][rid]]
        homepage = next((p for p in pages if p.get('page_type') == 'homepage'), {})
        detail = dict(
            business=dict(id=business.id, canonical_name=homepage.get('title') or 'Unverified business',
                          website_url=homepage.get('final_url'),
                          category=job.payload.get('category'), city=job.payload.get('city'), state=job.payload.get('state')),
            sources=sources[business.id], score=next((s.breakdown for s in buckets[LeadScore][rid]), None),
            audit=dict(status=run.status, finished_at=run.finished_at.isoformat() if run.finished_at else None, error_message=run.error_code) if run else None,
            pages=pages, evidence=evidence,
            contacts=[dict(c.data, id=c.id, normalized_value=c.normalized_value, type=c.kind, provenance=c.provenance) for c in buckets[BusinessContact][rid]],
            history=[dict(id=r.id, status=r.status) for r in histories[business.id]])
        detail['digital_growth'] = growth_for_detail(detail)
        detail['summary'] = qualify(detail)
        details.append(detail)
    return details


def detail_view(db, business, owner, job_id=None):
    if job_id:
        job = selected_job(db, owner, job_id)
    else:
        job = db.scalar(select(SearchJob).join(SearchJobItem).where(SearchJobItem.business_id == business.id,
            SearchJob.user_id == owner, SearchJob.run_mode == run_mode()).order_by(SearchJob.created_at.desc(), SearchJob.id.desc()).limit(1))
    if not job or not db.scalar(select(SearchJobItem.id).where(SearchJobItem.job_id == job.id, SearchJobItem.business_id == business.id)):
        return None
    return details_for_job(db, [business], job)[0]


def leads_view(db, owner, limit=50, offset=0, job_id=None, **filters):
    job = selected_job(db, owner, job_id)
    if not job:
        return dict(leads=[], total=0, job=None)
    businesses = list(db.scalars(select(Business).join(SearchJobItem).where(
        Business.user_id == owner, visible_business(), SearchJobItem.job_id == job.id)))
    rows = filter_sort([lead_row(d) for d in details_for_job(db, businesses, job)], **filters)
    return dict(leads=rows[offset:offset + limit], total=len(rows), job=dict(id=job.id, **job.payload,
                created_at=job.created_at.isoformat(), status=job.status, discovered_count=len(businesses), run_mode=job.run_mode))


def export_csv(db, owner, job_id=None, **filters):
    return summary_csv(leads_view(db, owner, limit=100, job_id=job_id, **filters)['leads'])
