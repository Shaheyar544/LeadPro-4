"""Complete production schema, generated and reviewed against empty PostgreSQL."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision = '0002'
down_revision = '0001'

def upgrade():
    # Explicit DDL reviewed against the production model contract.
    op.create_table('users',
    sa.Column('username', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('username')
    )
    op.create_table('businesses',
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('browser_observed_url', sa.Text(), nullable=True),
    sa.Column('browser_observed_name', sa.Text(), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_businesses_user_id'), 'businesses', ['user_id'], unique=False)
    op.create_table('search_jobs',
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('cancel_requested', sa.Boolean(), nullable=False),
    sa.Column('lease_token', sa.String(length=64), nullable=True),
    sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('heartbeat_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_jobs_claim', 'search_jobs', ['status', 'created_at'], unique=False)
    op.create_index(op.f('ix_search_jobs_lease_until'), 'search_jobs', ['lease_until'], unique=False)
    op.create_index(op.f('ix_search_jobs_status'), 'search_jobs', ['status'], unique=False)
    op.create_index(op.f('ix_search_jobs_user_id'), 'search_jobs', ['user_id'], unique=False)
    op.create_table('security_events',
    sa.Column('user_id', sa.String(length=64), nullable=True),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('subject_id', sa.String(length=64), nullable=True),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_security_events_action'), 'security_events', ['action'], unique=False)
    op.create_index(op.f('ix_security_events_user_id'), 'security_events', ['user_id'], unique=False)
    op.create_table('sessions',
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('browser_cleanup',
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('user_handle', sa.String(length=100), nullable=False),
    sa.Column('pending', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['search_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_handle')
    )
    op.create_index(op.f('ix_browser_cleanup_job_id'), 'browser_cleanup', ['job_id'], unique=False)
    op.create_index(op.f('ix_browser_cleanup_pending'), 'browser_cleanup', ['pending'], unique=False)
    op.create_table('provider_refs',
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('provider_record_id', sa.String(length=300), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'provider', 'provider_record_id')
    )
    op.create_index(op.f('ix_provider_refs_business_id'), 'provider_refs', ['business_id'], unique=False)
    op.create_index(op.f('ix_provider_refs_user_id'), 'provider_refs', ['user_id'], unique=False)
    op.create_table('search_job_items',
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.ForeignKeyConstraint(['job_id'], ['search_jobs.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('job_id', 'business_id')
    )
    op.create_index(op.f('ix_search_job_items_business_id'), 'search_job_items', ['business_id'], unique=False)
    op.create_index(op.f('ix_search_job_items_job_id'), 'search_job_items', ['job_id'], unique=False)
    op.create_index(op.f('ix_search_job_items_status'), 'search_job_items', ['status'], unique=False)
    op.create_table('audit_runs',
    sa.Column('item_id', sa.String(length=64), nullable=False),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('error_code', sa.String(length=64), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.ForeignKeyConstraint(['item_id'], ['search_job_items.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('item_id')
    )
    op.create_index(op.f('ix_audit_runs_business_id'), 'audit_runs', ['business_id'], unique=False)
    op.create_table('audit_pages',
    sa.Column('audit_id', sa.String(length=64), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audit_runs.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_pages_audit_id'), 'audit_pages', ['audit_id'], unique=False)
    op.create_table('business_contacts',
    sa.Column('audit_id', sa.String(length=64), nullable=False),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('normalized_value', sa.Text(), nullable=False),
    sa.Column('provenance', sa.String(length=32), nullable=False),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audit_runs.id'], ),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('audit_id', 'kind', 'normalized_value')
    )
    op.create_index(op.f('ix_business_contacts_audit_id'), 'business_contacts', ['audit_id'], unique=False)
    op.create_index(op.f('ix_business_contacts_business_id'), 'business_contacts', ['business_id'], unique=False)
    op.create_table('lead_scores',
    sa.Column('audit_id', sa.String(length=64), nullable=False),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('profile_version', sa.String(length=64), nullable=False),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('breakdown', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audit_runs.id'], ),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('audit_id')
    )
    op.create_index(op.f('ix_lead_scores_business_id'), 'lead_scores', ['business_id'], unique=False)
    op.create_table('audit_evidence',
    sa.Column('audit_id', sa.String(length=64), nullable=False),
    sa.Column('page_id', sa.String(length=64), nullable=True),
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('provenance', sa.String(length=32), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audit_runs.id'], ),
    sa.ForeignKeyConstraint(['business_id'], ['businesses.id'], ),
    sa.ForeignKeyConstraint(['page_id'], ['audit_pages.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_evidence_audit_id'), 'audit_evidence', ['audit_id'], unique=False)
    op.create_index(op.f('ix_audit_evidence_business_id'), 'audit_evidence', ['business_id'], unique=False)
    op.create_index(op.f('ix_audit_evidence_page_id'), 'audit_evidence', ['page_id'], unique=False)


def downgrade():
    # Explicit DDL reviewed against the production model contract.
    op.drop_index(op.f('ix_audit_evidence_page_id'), table_name='audit_evidence')
    op.drop_index(op.f('ix_audit_evidence_business_id'), table_name='audit_evidence')
    op.drop_index(op.f('ix_audit_evidence_audit_id'), table_name='audit_evidence')
    op.drop_table('audit_evidence')
    op.drop_index(op.f('ix_lead_scores_business_id'), table_name='lead_scores')
    op.drop_table('lead_scores')
    op.drop_index(op.f('ix_business_contacts_business_id'), table_name='business_contacts')
    op.drop_index(op.f('ix_business_contacts_audit_id'), table_name='business_contacts')
    op.drop_table('business_contacts')
    op.drop_index(op.f('ix_audit_pages_audit_id'), table_name='audit_pages')
    op.drop_table('audit_pages')
    op.drop_index(op.f('ix_audit_runs_business_id'), table_name='audit_runs')
    op.drop_table('audit_runs')
    op.drop_index(op.f('ix_search_job_items_status'), table_name='search_job_items')
    op.drop_index(op.f('ix_search_job_items_job_id'), table_name='search_job_items')
    op.drop_index(op.f('ix_search_job_items_business_id'), table_name='search_job_items')
    op.drop_table('search_job_items')
    op.drop_index(op.f('ix_provider_refs_user_id'), table_name='provider_refs')
    op.drop_index(op.f('ix_provider_refs_business_id'), table_name='provider_refs')
    op.drop_table('provider_refs')
    op.drop_index(op.f('ix_browser_cleanup_pending'), table_name='browser_cleanup')
    op.drop_index(op.f('ix_browser_cleanup_job_id'), table_name='browser_cleanup')
    op.drop_table('browser_cleanup')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_index(op.f('ix_security_events_user_id'), table_name='security_events')
    op.drop_index(op.f('ix_security_events_action'), table_name='security_events')
    op.drop_table('security_events')
    op.drop_index(op.f('ix_search_jobs_user_id'), table_name='search_jobs')
    op.drop_index(op.f('ix_search_jobs_status'), table_name='search_jobs')
    op.drop_index(op.f('ix_search_jobs_lease_until'), table_name='search_jobs')
    op.drop_index('ix_jobs_claim', table_name='search_jobs')
    op.drop_table('search_jobs')
    op.drop_index(op.f('ix_businesses_user_id'), table_name='businesses')
    op.drop_table('businesses')
    op.drop_table('users')
