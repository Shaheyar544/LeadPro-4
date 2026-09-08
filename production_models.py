from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, DateTime, JSON, Text, Float
from datetime import datetime
class Base(DeclarativeBase): pass
class SearchJob(Base):
 __tablename__='search_jobs'
 id:Mapped[str]=mapped_column(String(64),primary_key=True)
 status:Mapped[str]=mapped_column(String(32),index=True)
 payload:Mapped[dict]=mapped_column(JSON,default=dict)
 created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class Business(Base):
 __tablename__='businesses'
 id:Mapped[str]=mapped_column(String(64),primary_key=True)
 provider:Mapped[str]=mapped_column(String(64))
 provider_record_id:Mapped[str]=mapped_column(String(256))
 place_id:Mapped[str|None]=mapped_column(String(256),nullable=True)
 browser_observed_url:Mapped[str|None]=mapped_column(Text,nullable=True)
 created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class AuditEvidence(Base):
 __tablename__='audit_evidence'
 id:Mapped[str]=mapped_column(String(64),primary_key=True)
 business_id:Mapped[str]=mapped_column(String(64),index=True)
 evidence:Mapped[dict]=mapped_column(JSON)
 observed_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
class LeadScore(Base):
 __tablename__='lead_scores'
 id:Mapped[str]=mapped_column(String(64),primary_key=True)
 business_id:Mapped[str]=mapped_column(String(64),index=True)
 profile_version:Mapped[str]=mapped_column(String(64))
 score:Mapped[float]=mapped_column(Float)
 breakdown:Mapped[dict]=mapped_column(JSON)
