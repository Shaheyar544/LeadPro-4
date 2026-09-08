"""Disabled contracts for future licensed data sources. No network implementation."""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class RankRequest:
    keyword: str
    location: str
    device: str
    domain: str


class RankTrackingProvider(ABC):
    profile_version = 'serp_rank_tracking_v1'
    configured = False
    fields = ('keyword', 'location', 'device', 'domain', 'rank', 'serp_features', 'checked_at', 'provider')

    @abstractmethod
    async def measure(self, request: RankRequest):
        """Return real, licensed observations; unavailable rank is None."""


class OffPageProvider(ABC):
    profile_version = 'off_page_seo_v1'
    configured = False
    fields = ('referring_domains', 'backlinks', 'domain_metrics', 'competitor_gap', 'anchor_text', 'new_links', 'lost_links', 'checked_at', 'provider')

    @abstractmethod
    async def measure(self, domain: str):
        """Return source-attributed measurements, never inferred metrics."""


class SocialMediaProvider(ABC):
    profile_version = 'social_media_audit_v1'
    configured = False
    platforms = ('facebook', 'instagram', 'linkedin', 'youtube', 'tiktok')

    @abstractmethod
    async def measure(self, public_profile_url: str):
        """Public authorized evidence only; no credential or bypass flow."""


class PagePerformanceProvider(ABC):
    profile_version = 'page_performance_v1'
    configured = False
    fields = ('provider', 'checked_at', 'strategy', 'lab_score', 'lcp', 'cls', 'inp', 'field_data_available')

    @abstractmethod
    async def measure(self, public_page_url: str):
        """Provider measurements only. Navigation duration is not Core Web Vitals."""
