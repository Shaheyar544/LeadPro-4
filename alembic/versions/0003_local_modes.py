"""Durable run modes; preserve unclassified history, identify exact old fixtures."""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'


def upgrade():
    for table in ('businesses', 'search_jobs'):
        op.add_column(table, sa.Column('run_mode', sa.String(16), nullable=False, server_default='legacy'))
        op.create_check_constraint('ck_' + table + '_run_mode', table, "run_mode IN ('live', 'offline_test', 'legacy')")
        op.create_index('ix_' + table + '_owner_mode', table, ['user_id', 'run_mode'])
    # Frozen exact identifiers from the inspected Phase 4A.2 fixture, not a broad
    # name/hostname deletion heuristic. No rows are deleted by this migration.
    ids = tuple('google_places_new:phase4a2-place-' + str(i) for i in range(1, 6))
    op.get_bind().execute(sa.text("""
        UPDATE businesses b SET run_mode='offline_test'
        WHERE b.browser_observed_url='https://fixture-business.test/'
          AND b.browser_observed_name='Independently observed business'
          AND EXISTS (SELECT 1 FROM provider_refs r WHERE r.business_id=b.id
            AND r.provider='google_places_new' AND r.provider_record_id IN :ids)
          AND NOT EXISTS (SELECT 1 FROM provider_refs r WHERE r.business_id=b.id
            AND (r.provider!='google_places_new' OR r.provider_record_id NOT IN :ids))
    """).bindparams(sa.bindparam('ids', expanding=True)), {'ids': ids})
    op.execute("""UPDATE search_jobs j SET run_mode='offline_test'
        WHERE EXISTS (SELECT 1 FROM search_job_items i WHERE i.job_id=j.id)
          AND NOT EXISTS (SELECT 1 FROM search_job_items i JOIN businesses b ON b.id=i.business_id
              WHERE i.job_id=j.id AND b.run_mode!='offline_test')""")


def downgrade():
    for table in ('search_jobs', 'businesses'):
        op.drop_index('ix_' + table + '_owner_mode', table)
        op.drop_constraint('ck_' + table + '_run_mode', table, type_='check')
        op.drop_column(table, 'run_mode')
