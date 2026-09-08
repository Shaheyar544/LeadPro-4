"""Mixed real/fixture invariants in the opt-in isolated PostgreSQL test DB."""
import os
from types import SimpleNamespace
import pytest
from sqlalchemy import select, func
from production_models import *

pytestmark = pytest.mark.skipif(os.getenv('RUN_POSTGRES_TESTS') != '1', reason='Opt-in isolated PostgreSQL')


@pytest.fixture
def mixed(monkeypatch):
    from sqlalchemy.orm import Session as DBSession
    from production_db import engine
    monkeypatch.setenv('LOCAL_RUN_MODE', 'live')
    with DBSession(engine()) as db:
        db.begin()
        try:
            user = User(username=uid(), password_hash='test-only')
            db.add(user); db.flush()
            real = Business(user_id=user.id, run_mode='live', browser_observed_name='Real website observation', browser_observed_url='https://example.com/')
            fixture = Business(user_id=user.id, run_mode='offline_test', browser_observed_name='Independently observed business', browser_observed_url='https://fixture-business.test/')
            # Unclassified historical data and a fixture-looking LIVE record
            # must both survive cleanup, even though neither belongs in the UI.
            legacy = Business(user_id=user.id, run_mode='legacy', browser_observed_name='Historical benchmark')
            lookalike = Business(user_id=user.id, run_mode='live', browser_observed_url='https://fixture-business.test/')
            db.add_all([real, fixture, legacy, lookalike]); db.flush()
            live_job = SearchJob(user_id=user.id, run_mode='live', status='completed', payload={'category':'Roofing','city':'Dallas','state':'TX'})
            test_job = SearchJob(user_id=user.id, run_mode='offline_test', status='completed', payload={'category':'Fixture'})
            db.add_all([live_job,test_job]); db.flush()
            db.add_all([ProviderRef(user_id=user.id,business_id=real.id,provider='google_places_new',provider_record_id='google_places_new:'+uid()),
                ProviderRef(user_id=user.id,business_id=fixture.id,provider='fixture',provider_record_id='fixture:'+uid())])
            live_item = SearchJobItem(job_id=live_job.id,business_id=real.id,status='completed')
            test_item = SearchJobItem(job_id=test_job.id,business_id=fixture.id,status='completed')
            db.add_all([live_item,test_item]); db.flush()
            for item in (live_item,test_item):
                run = AuditRun(item_id=item.id,business_id=item.business_id,status='completed')
                db.add(run); db.flush()
                page = AuditPage(audit_id=run.id,data={})
                db.add(page); db.flush()
                db.add_all([AuditEvidence(audit_id=run.id,page_id=page.id,business_id=item.business_id,evidence={}),
                    BusinessContact(audit_id=run.id,business_id=item.business_id,kind='email',normalized_value='test-only',data={}),
                    LeadScore(audit_id=run.id,business_id=item.business_id,profile_version='website_conversion_v2',score=10,breakdown={'opportunity_score':10})])
            db.add_all([Session(user_id=user.id,expires_at=utcnow()), SecurityEvent(user_id=user.id,action='test'),
                        BrowserCleanup(job_id=test_job.id,user_handle=uid(),pending=False)])
            db.flush()
            yield SimpleNamespace(**locals())
        finally:
            db.rollback()  # No test records survive, even after cleanup executes.


def test_live_ui_csv_job_counts_and_detail_scope(mixed):
    from production_views import leads_view, export_csv, job_view
    m = mixed
    result = leads_view(m.db,m.user.id)
    assert result['total'] == 1 and result['leads'][0]['id'] == m.real.id
    assert 'fixture-business.test' not in export_csv(m.db,m.user.id)
    assert leads_view(m.db,m.user.id,job_id=m.test_job.id)['total'] == 0
    assert job_view(m.db,m.live_job)['discovered_count'] == 1
    # Deliberate malformed cross-mode item must not contaminate live job counts.
    m.db.add(SearchJobItem(job_id=m.live_job.id,business_id=m.fixture.id)); m.db.flush()
    assert job_view(m.db,m.live_job)['discovered_count'] == 1


def test_results_use_requested_jobs_audit_and_context(mixed):
    from production_views import leads_view
    m=mixed
    newer=SearchJob(user_id=m.user.id,run_mode='live',status='completed',payload={'category':'HVAC','city':'Phoenix','state':'AZ'})
    m.db.add(newer);m.db.flush()
    item=SearchJobItem(job_id=newer.id,business_id=m.real.id,status='completed')
    m.db.add(item);m.db.flush()
    audit=AuditRun(item_id=item.id,business_id=m.real.id,status='partial')
    m.db.add(audit);m.db.flush()
    m.db.add(LeadScore(audit_id=audit.id,business_id=m.real.id,profile_version='website_conversion_v2',score=90,breakdown={'opportunity_score':90}))
    old_page = m.db.scalar(select(AuditPage).join(AuditRun).where(AuditRun.item_id == m.live_item.id))
    old_page.data = {'page_type':'homepage','title':'Earlier observed name','final_url':'https://example.com/earlier'}
    m.db.add(AuditPage(audit_id=audit.id,data={'page_type':'homepage','title':'New observed name','final_url':'https://example.com/new'}))
    m.real.browser_observed_name = 'New observed name'
    m.real.browser_observed_url = 'https://example.com/new'
    m.db.flush()
    old=leads_view(m.db,m.user.id,job_id=m.live_job.id)['leads'][0]
    new=leads_view(m.db,m.user.id,job_id=newer.id)['leads'][0]
    assert (old['city'],old['opportunity_score'],old['audit_status']) == ('Dallas',10,'completed')
    assert (new['city'],new['opportunity_score'],new['audit_status']) == ('Phoenix',90,'partial')
    assert old['business_name'] == 'Earlier observed name' and old['website'] == 'https://example.com/earlier'
    assert new['business_name'] == 'New observed name' and new['website'] == 'https://example.com/new'
    assert leads_view(m.db,m.user.id)['job']['id'] == newer.id
    assert leads_view(m.db,m.user.id)['leads'][0]['city'] == 'Phoenix'


def test_latest_empty_live_search_does_not_fall_back_to_history(mixed):
    from production_views import leads_view, export_csv, detail_view
    m = mixed
    newest = SearchJob(user_id=m.user.id,run_mode='live',payload={'category':'New search','city':'Austin','state':'TX'})
    m.db.add(newest); m.db.flush()
    assert leads_view(m.db,m.user.id)['job']['id'] == newest.id
    assert leads_view(m.db,m.user.id)['total'] == 0
    assert len(export_csv(m.db,m.user.id).splitlines()) == 1
    assert leads_view(m.db,m.user.id,job_id=m.live_job.id)['total'] == 1
    assert detail_view(m.db,m.real,m.user.id,job_id=newest.id) is None
    assert detail_view(m.db,m.real,m.user.id,job_id=m.test_job.id) is None
    assert leads_view(m.db,'different-owner',job_id=m.live_job.id)['total'] == 0


def test_offline_defaults_to_its_own_latest_search(mixed, monkeypatch):
    from production_views import leads_view
    monkeypatch.setenv('LOCAL_RUN_MODE','offline_test')
    result = leads_view(mixed.db,mixed.user.id)
    assert result['job']['id'] == mixed.test_job.id
    assert [r['id'] for r in result['leads']] == [mixed.fixture.id]


def test_batch_projection_and_csv_do_not_mutate_evidence_or_scores(mixed):
    from sqlalchemy import event
    from production_views import leads_view, export_csv
    m = mixed
    before = {model: [(r.id, repr(getattr(r, 'evidence', getattr(r, 'breakdown', getattr(r, 'data', None))))) for r in m.db.scalars(select(model))]
              for model in (AuditEvidence,LeadScore,BusinessContact,AuditPage)}
    statements = []
    def record(*args): statements.append(args[2])
    bind = m.db.get_bind(); event.listen(bind, 'before_cursor_execute', record)
    try:
        result = leads_view(m.db,m.user.id)
        assert len(statements) <= 8
    finally:
        event.remove(bind, 'before_cursor_execute', record)
    assert result['total'] == 1
    assert 'evidence' not in export_csv(m.db,m.user.id).splitlines()[0].split(',')
    assert leads_view(m.db,m.user.id,audit_status='failed')['total'] == 0
    assert leads_view(m.db,m.user.id,has_phone=True)['total'] == 0
    m.db.flush()
    after = {model: [(r.id, repr(getattr(r, 'evidence', getattr(r, 'breakdown', getattr(r, 'data', None))))) for r in m.db.scalars(select(model))]
             for model in before}
    assert before == after


def test_fixture_cleanup_dryrun_confirm_and_preservation(mixed):
    from lead_engine.clean_fixtures import plan, clean
    m = mixed
    protected = {model: list(m.db.scalars(select(model.id))) for model in (User,Session,SecurityEvent)}
    ids, summary = plan(m.db)
    assert ids[Business] == {m.fixture.id} and ids[SearchJob] == {m.test_job.id}
    assert m.db.get(Business,m.fixture.id) is not None  # Dry run made no change.
    with pytest.raises(ValueError):
        clean(m.db,summary['plan'],'yes')
    with pytest.raises(ValueError):
        clean(m.db,'stale-plan','DELETE FIXTURES')
    result = clean(m.db,summary['plan'],'DELETE FIXTURES')
    assert result['deleted']['businesses'] == 1 and result['remaining']['businesses'] == 0
    for row in (m.real,m.legacy,m.lookalike):
        assert m.db.scalar(select(Business.id).where(Business.id==row.id)) == row.id
    assert m.db.scalar(select(SearchJob.id).where(SearchJob.id==m.live_job.id)) == m.live_job.id
    for model, before in protected.items():
        assert list(m.db.scalars(select(model.id))) == before


def test_cleanup_preserves_cross_mode_references_and_pending_work(mixed):
    from lead_engine.clean_fixtures import plan, clean
    m=mixed
    m.test_job.status='running'; m.db.flush()
    summary=plan(m.db)[1]
    assert not summary['safe_to_apply']
    with pytest.raises(ValueError):
        clean(m.db,summary['plan'],'DELETE FIXTURES')
    m.test_job.status='completed'
    m.db.add(SearchJobItem(job_id=m.live_job.id,business_id=m.fixture.id)); m.db.flush()
    ids, summary=plan(m.db)
    assert not ids[Business] and not ids[SearchJob]
