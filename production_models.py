"""PostgreSQL records. Schema changes belong in Alembic revisions."""
from datetime import datetime, timezone
import uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, Text, Float, Integer, Boolean, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import JSONB

def utcnow():
    return datetime.now(timezone.utc)

def uid():
    return utcnow().strftime('%Y%m%d%H%M%S%f') + uuid.uuid4().hex

class Base(DeclarativeBase):
    pass

class Record:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class User(Record, Base):
    __tablename__ = 'users'
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)

class Session(Record, Base):
    __tablename__ = 'sessions'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

class SecurityEvent(Record, Base):
    __tablename__ = 'security_events'
    user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    subject_id: Mapped[str | None] = mapped_column(String(64))

class SearchJob(Record, Base):
    __tablename__ = 'search_jobs'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class Business(Record, Base):
    __tablename__ = 'businesses'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    browser_observed_url: Mapped[str | None] = mapped_column(Text)
    browser_observed_name: Mapped[str | None] = mapped_column(Text)

class ProviderRef(Record, Base):
    __tablename__ = 'provider_refs'
    __table_args__ = (UniqueConstraint('user_id', 'provider', 'provider_record_id'),)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    provider_record_id: Mapped[str] = mapped_column(String(300))
    # No raw response or arbitrary provider JSON column.

class SearchJobItem(Record, Base):
    __tablename__ = 'search_job_items'
    __table_args__ = (UniqueConstraint('job_id', 'business_id'),)
    job_id: Mapped[str] = mapped_column(ForeignKey('search_jobs.id'), index=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)

class AuditRun(Record, Base):
    __tablename__ = 'audit_runs'
    item_id: Mapped[str] = mapped_column(ForeignKey('search_job_items.id'), unique=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    status: Mapped[str] = mapped_column(String(32))
    error_code: Mapped[str | None] = mapped_column(String(64))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditPage(Record, Base):
    __tablename__ = 'audit_pages'
    audit_id: Mapped[str] = mapped_column(ForeignKey('audit_runs.id'), index=True)
    data: Mapped[dict] = mapped_column(JSONB)

class AuditEvidence(Record, Base):
    __tablename__ = 'audit_evidence'
    audit_id: Mapped[str] = mapped_column(ForeignKey('audit_runs.id'), index=True)
    page_id: Mapped[str | None] = mapped_column(ForeignKey('audit_pages.id'), index=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    provenance: Mapped[str] = mapped_column(String(32), default='browser')
    evidence: Mapped[dict] = mapped_column(JSONB)

class BusinessContact(Record, Base):
    __tablename__ = 'business_contacts'
    __table_args__ = (UniqueConstraint('audit_id', 'kind', 'normalized_value'),)
    audit_id: Mapped[str] = mapped_column(ForeignKey('audit_runs.id'), index=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    normalized_value: Mapped[str] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(32), default='browser')
    data: Mapped[dict] = mapped_column(JSONB)

class LeadScore(Record, Base):
    __tablename__ = 'lead_scores'
    audit_id: Mapped[str] = mapped_column(ForeignKey('audit_runs.id'), unique=True)
    business_id: Mapped[str] = mapped_column(ForeignKey('businesses.id'), index=True)
    profile_version: Mapped[str] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float)
    breakdown: Mapped[dict] = mapped_column(JSONB)

class BrowserCleanup(Record, Base):
    __tablename__ = 'browser_cleanup'
    job_id: Mapped[str] = mapped_column(ForeignKey('search_jobs.id'), index=True)
    user_handle: Mapped[str] = mapped_column(String(100), unique=True)
    pending: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

Index('ix_jobs_claim', SearchJob.status, SearchJob.created_at)
