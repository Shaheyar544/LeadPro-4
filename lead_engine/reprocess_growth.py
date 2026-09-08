"""Re-evaluate one completed, at-most-five-business growth validation from saved facts.

Dry run by default. No discovery, browsing, raw-fact changes, conversion changes,
contact changes, deletion or historical bulk re-audit. Operator CLI only.
"""
import argparse
from copy import deepcopy
import json
from sqlalchemy import select
from production_models import SearchJob, SearchJobItem, AuditRun, AuditEvidence, LeadScore, SecurityEvent
from production_db import transaction
from local_modes import run_mode
from audit_engine.growth import topic_outcome, cross_page_checks
from growth_scoring import build_growth, stored_growth


TOPIC_DETAIL = 'Topic assessed from the observed title, headings and page context; a missing H1 alone does not erase a clear topic.'


def reprocess(db, job_id, *, apply=False):
    job = db.scalar(select(SearchJob).where(SearchJob.id == job_id, SearchJob.run_mode == run_mode()).with_for_update())
    if not job or job.status != 'completed':
        raise ValueError('A completed job in the active mode is required')
    items = list(db.scalars(select(SearchJobItem).where(SearchJobItem.job_id == job.id)))
    if not 1 <= len(items) <= 5 or any(i.status != 'completed' for i in items):
        raise ValueError('Reprocessing requires one completed validation with at most five businesses')
    report = []
    for item in items:
        audit = db.scalar(select(AuditRun).where(AuditRun.item_id == item.id))
        score = db.scalar(select(LeadScore).where(LeadScore.audit_id == audit.id)) if audit else None
        if not score or not score.breakdown.get('digital_growth'):
            continue
        original = deepcopy(score.breakdown)
        previous = original['digital_growth']
        models = list(db.scalars(select(AuditEvidence).where(AuditEvidence.audit_id == audit.id).order_by(AuditEvidence.id)))
        facts = {r.page_id: deepcopy(r.evidence['value']) for r in models if r.evidence.get('detector_key') == 'growth.page_observation'
                 and r.evidence.get('detector_version') == 'digital_growth_crawl_v1'}
        evidence, corrected = [], 0
        for row in models:
            data = deepcopy(row.evidence)
            if data.get('detector_key') == 'growth.page_topic' and row.page_id in facts:
                outcome = topic_outcome(facts[row.page_id])
                corrected += data.get('value', {}).get('outcome') == 'gap' and outcome != 'gap'
                data['value'].update(outcome=outcome, detail=TOPIC_DETAIL)
                data.update(status={'pass':'present', 'gap':'absent', 'unknown':'unknown'}[outcome],
                            confidence=.9 if outcome in {'pass','gap'} else 0, excerpt=TOPIC_DETAIL)
                if apply:
                    row.evidence = data
            evidence.append(dict(data, id=data.get('id') or row.id, page_id=row.page_id))
        observations = list(facts.values())
        pages = [dict(id=o['page_id'], final_url=o['url']) for o in observations]
        _, analysis = cross_page_checks(observations, pages)
        metrics = deepcopy(previous.get('metrics', {}))
        if metrics.get('pages_attempted') == 0:
            metrics['browser_sessions'] = 0
        conversion = {k:v for k,v in original.items() if k != 'digital_growth'}
        growth = build_growth(evidence, conversion, assessed=previous['assessed'], observations=observations,
                              page_analysis=analysis, metrics=metrics)
        report.append(dict(business_id=item.business_id, corrected_topic_gaps=corrected,
            before={v:p['opportunity_score'] for v,p in previous['profiles'].items()},
            after={v:p['opportunity_score'] for v,p in growth['profiles'].items()},
            services_before=previous['recommended_services']['services'], services_after=growth['recommended_services']['services']))
        if apply:
            score.breakdown = dict(conversion, digital_growth=stored_growth(growth))
            assert {k:v for k,v in score.breakdown.items() if k != 'digital_growth'} == conversion
    if apply and report:
        db.add(SecurityEvent(user_id=job.user_id, action='growth_reprocess', subject_id=job.id))
    return dict(job_id=job_id, dry_run=not apply, new_browser_requests=0, changes=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--apply', action='store_true', help='Apply reviewed changes to this validation only')
    args = parser.parse_args()
    with transaction() as db:
        report = reprocess(db, args.job_id, apply=args.apply)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
