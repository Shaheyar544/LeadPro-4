"""Owner-scoped projections used by API, detail and CSV."""
import csv
import io
import json
from sqlalchemy import select, func
from production_models import *
from local_modes import run_mode, visible_business, LIVE_ERROR

def job_view(db, job):
    items = list(db.scalars(select(SearchJobItem).join(Business).where(
        SearchJobItem.job_id == job.id, visible_business(job.run_mode))))
    done = sum(i.status == 'completed' for i in items)
    return dict(id=job.id, **job.payload, run_mode=job.run_mode, status=job.status, cancel_requested=job.cancel_requested,
                discovered_count=len(items), processed_count=done, qualified_count=done,
                error_message=LIVE_ERROR if job.error_code == 'live_discovery_unavailable' else job.error_code,
                created_at=job.created_at.isoformat())

def detail_view(db, business, owner, job_id=None):
    query = select(SearchJobItem).join(SearchJob).where(
        SearchJobItem.business_id == business.id, SearchJob.user_id == owner, SearchJob.run_mode == run_mode())
    if job_id:
        query = query.where(SearchJob.id == job_id)
    item = db.scalar(query.order_by(SearchJob.created_at.desc()).limit(1))
    context = db.get(SearchJob, item.job_id).payload if item else {}
    audit_query = select(AuditRun).join(SearchJobItem).join(SearchJob).where(
        AuditRun.business_id == business.id, SearchJob.user_id == owner, SearchJob.run_mode == run_mode())
    if job_id:
        audit_query = audit_query.where(SearchJob.id == job_id)
    runs = list(db.scalars(audit_query.order_by(AuditRun.created_at.desc())))
    run = runs[0] if runs else None
    score = db.scalar(select(LeadScore).where(LeadScore.audit_id == run.id)) if run else None
    return dict(
        business=dict(id=business.id, canonical_name=business.browser_observed_name or 'Unverified business',
                      website_url=business.browser_observed_url, category=context.get('category'),
                      city=context.get('city'), state=context.get('state')),
        sources=[dict(provider=r.provider, provider_record_id=r.provider_record_id, observed_at=r.created_at.isoformat())
                 for r in db.scalars(select(ProviderRef).where(ProviderRef.business_id == business.id))],
        score=score.breakdown if score else None,
        audit=dict(status=run.status, finished_at=run.finished_at.isoformat(), error_message=run.error_code) if run else None,
        pages=[dict(id=p.id, **p.data) for p in db.scalars(select(AuditPage).where(AuditPage.audit_id == run.id))] if run else [],
        evidence=[dict(id=e.id, provenance=e.provenance, **e.evidence) for e in db.scalars(select(AuditEvidence).where(AuditEvidence.audit_id == run.id))] if run else [],
        contacts=[dict(normalized_value=c.normalized_value, type=c.kind, provenance=c.provenance, **c.data)
                  for c in db.scalars(select(BusinessContact).where(BusinessContact.audit_id == run.id))] if run else [],
        history=[dict(id=r.id, status=r.status) for r in runs])

def leads_view(db, owner, limit=50, offset=0, job_id=None):
    query = select(Business).where(Business.user_id == owner, visible_business())
    if job_id:
        query = query.join(SearchJobItem).join(SearchJob).where(
            SearchJobItem.job_id == job_id, SearchJob.user_id == owner, SearchJob.run_mode == run_mode())
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    leads = []
    for business in db.scalars(query.order_by(Business.created_at.desc()).offset(offset).limit(limit)):
        detail = detail_view(db, business, owner, job_id=job_id)
        b, score = detail['business'], detail['score'] or {}
        leads.append(dict(id=b['id'], business_name=b['canonical_name'], city=b['city'], state=b['state'],
                          website=b['website_url'], opportunity_score=score.get('opportunity_score'),
                          digital_gap=score.get('digital_gap'), evidence_confidence=score.get('evidence_confidence'),
                          contact_confidence=score.get('contact_confidence'), primary_opportunity=None,
                          audit_status=(detail['audit'] or {}).get('status', 'pending')))
    return dict(leads=leads, total=total)

def safe_cell(value):
    value = '' if value is None else str(value)
    if value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n')):
        return "'" + value
    return value

def export_csv(db, owner):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['business_name', 'website', 'phone', 'email', 'evidence', 'opportunity_v2',
                     'confidence', 'provider_identifier', 'search_category', 'search_city', 'search_state'])
    for b in db.scalars(select(Business).where(Business.user_id == owner, visible_business()).order_by(Business.created_at)):
        detail = detail_view(db, b, owner)
        context, score = detail['business'], detail['score'] or {}
        row = [b.browser_observed_name, b.browser_observed_url,
               '; '.join(c['normalized_value'] for c in detail['contacts'] if c['type'] == 'phone'),
               '; '.join(c['normalized_value'] for c in detail['contacts'] if c['type'] == 'email'),
               json.dumps(detail['evidence']), score.get('opportunity_score'), score.get('evidence_confidence'),
               '; '.join(r['provider_record_id'] for r in detail['sources']), context['category'], context['city'], context['state']]
        writer.writerow([safe_cell(x) for x in row])
    return output.getvalue()
