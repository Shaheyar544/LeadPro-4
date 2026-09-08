"""New profiles round-trip through the existing production JSONB boundary."""
from contextlib import contextmanager
from datetime import timedelta
import os
import json
import pytest
from sqlalchemy import select
from tests.test_fixture_postgres import mixed
from production_models import SearchJob, SearchJobItem, LeadScore, AuditEvidence, AuditRun, utcnow, uid

pytestmark = pytest.mark.skipif(os.getenv('RUN_POSTGRES_TESTS') != '1', reason='Opt-in isolated PostgreSQL')


def test_growth_profiles_saved_with_conversion_and_scoped_read_model(mixed, monkeypatch):
    from production_repository import ProductionRepository
    from production_views import detail_view, leads_view, export_csv
    from production_scoring import score_browser_evidence
    from tests.test_digital_growth import collected
    from audit_engine.detectors import evidence
    m = mixed
    job = SearchJob(user_id=m.user.id, run_mode='live', status='running', lease_token=uid(),
        lease_until=utcnow() + timedelta(seconds=60), payload=dict(category='Plumbing', city='Austin', state='TX'))
    m.db.add(job); m.db.flush()
    item = SearchJobItem(job_id=job.id, business_id=m.real.id, status='running')
    m.db.add(item); m.db.flush()
    growth, rows = collected('technical')
    # This is an isolated DB transaction. Use a non-fixture-shaped observed URL
    # to exercise LIVE persistence without weakening its .test rejection guard.
    growth = json.loads(json.dumps(growth).replace('growth-business.test', 'observed-business.example.com'))
    rows = json.loads(json.dumps(rows).replace('growth-business.test', 'observed-business.example.com'))
    page_map = {o['page_id']:uid() for o in growth['observations']}
    for row in rows:
        row['page_id'] = page_map[row['page_id']]
    pages = [dict(id=page_map[o['page_id']], final_url=o['url'], title=o['title'],
                  page_type='homepage' if n == 0 else o['kind'], status='completed') for n, o in enumerate(growth['observations'])]
    for o in growth['observations']: o['page_id'] = page_map[o['page_id']]
    core = [evidence(k, 'present', page_id=pages[0]['id'], url=pages[0]['final_url']) for k in ('contact_form','quote_form','booking_form','contact_page','primary_cta','click_to_call','mobile_layout')]
    audit = dict(status='completed', pages=pages, evidence=core + rows, contacts=[], final_url=pages[0]['final_url'],
        growth_assessed=True, growth_observations=growth['observations'], growth_page_analysis=growth['page_analysis'],
        provider_name='GOOGLE_NAME_CANARY', rating='GOOGLE_RATING_CANARY', raw_response={'secret':'MUST_NOT_PERSIST'})
    original = score_browser_evidence(audit)
    @contextmanager
    def transaction():
        yield m.db
        m.db.flush()
    monkeypatch.setattr('production_repository.transaction', transaction)
    ProductionRepository().save_audit(job.id, job.lease_token, item.id, audit)
    run = m.db.scalar(select(AuditRun).where(AuditRun.item_id == item.id))
    score = m.db.scalar(select(LeadScore).where(LeadScore.audit_id == run.id))
    assert score.profile_version == 'website_conversion_v2'
    assert {k:v for k,v in score.breakdown.items() if k != 'digital_growth'} == original
    assert score.breakdown['digital_growth']['profiles']['technical_seo_v1']['opportunity_score'] > 40
    assert 'observations' not in score.breakdown['digital_growth']
    persisted = json.dumps(score.breakdown) + json.dumps([e.evidence for e in m.db.scalars(select(AuditEvidence).where(AuditEvidence.audit_id == run.id))])
    for forbidden in ('GOOGLE_NAME_CANARY','GOOGLE_RATING_CANARY','MUST_NOT_PERSIST'):
        assert forbidden not in persisted
    selected = detail_view(m.db, m.real, m.user.id, job.id)
    assert selected['digital_growth']['profiles']['technical_seo_v1']['sufficient']
    assert leads_view(m.db, m.user.id, job_id=job.id, min_technical=40)['total'] == 1
    assert leads_view(m.db, m.user.id, job_id=m.live_job.id, min_technical=1)['total'] == 0
    exported = export_csv(m.db, m.user.id, job_id=job.id, min_technical=40)
    assert 'technical_seo_opportunity' in exported and 'Schema Implementation' in exported
    assert 'GOOGLE_RATING_CANARY' not in exported
    from lead_engine.reprocess_growth import reprocess
    from copy import deepcopy
    job.status = 'completed'; m.db.flush()
    topic = next(e for e in m.db.scalars(select(AuditEvidence).where(AuditEvidence.audit_id == run.id)) if e.evidence['detector_key']=='growth.page_topic')
    bad = deepcopy(topic.evidence); bad['value']['outcome'] = 'gap'; bad['status'] = 'absent'
    topic.evidence = bad; m.db.flush()
    before = deepcopy(topic.evidence)
    report = reprocess(m.db, job.id)
    assert report['dry_run'] and report['new_browser_requests'] == 0
    assert report['changes'][0]['corrected_topic_gaps'] >= 1
    assert topic.evidence == before
    applied = reprocess(m.db, job.id, apply=True)
    m.db.flush()
    assert not applied['dry_run'] and topic.evidence['status'] == 'present'
    assert {k:v for k,v in score.breakdown.items() if k != 'digital_growth'} == original
    job.status = 'running'
    with pytest.raises(ValueError): reprocess(m.db, job.id, apply=True)
