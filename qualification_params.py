"""Shared validated query parameters for the table and matching CSV export."""
from typing import Literal
from fastapi import Query


def qualification_params(
    job_id: str | None = Query(None, max_length=100),
    audit_status: Literal['completed', 'partial', 'failed', 'blocked', 'unverified'] | None = None,
    primary_opportunity: str | None = Query(None, max_length=80),
    min_evidence: float = Query(0, ge=0, le=100),
    has_phone: bool = False, has_email: bool = False, has_contact: bool = False,
    min_opportunity: float | None = Query(None, ge=0, le=100),
    top_opportunity: str | None = Query(None, max_length=80),
    recommended_service: str | None = Query(None, max_length=80),
    min_technical: float | None = Query(None, ge=0, le=100),
    min_on_page: float | None = Query(None, ge=0, le=100),
    min_local: float | None = Query(None, ge=0, le=100),
    min_growth_evidence: float = Query(0, ge=0, le=100),
    sort: Literal['useful', 'opportunity', 'evidence', 'contact', 'business', 'audit', 'top_opportunity', 'technical', 'on_page', 'local', 'growth_evidence'] = 'useful',
):
    return dict(job_id=job_id, audit_status=audit_status, primary_opportunity=primary_opportunity,
                min_evidence=min_evidence, has_phone=has_phone, has_email=has_email,
                has_contact=has_contact, min_opportunity=min_opportunity, sort=sort,
                top_opportunity=top_opportunity, recommended_service=recommended_service, min_technical=min_technical,
                min_on_page=min_on_page, min_local=min_local, min_growth_evidence=min_growth_evidence)
