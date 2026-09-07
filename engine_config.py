"""Bounded, environment-only Phase 3B configuration."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from browser.camofox import service_url


def bounded(name, default, lower, upper):
    try:
        return max(lower, min(int(os.getenv(name, str(default))), upper))
    except ValueError:
        raise ValueError(f"{name} must be an integer") from None


@dataclass(frozen=True)
class EngineConfig:
    provider: str = field(default_factory=lambda: os.getenv("BROWSER_PROVIDER", "camofox"))
    base_url: str = field(default_factory=lambda: os.getenv("CAMOFOX_BASE_URL", "http://127.0.0.1:9377"))
    access_key: str = field(default_factory=lambda: os.getenv("CAMOFOX_ACCESS_KEY", ""), repr=False)
    timeout: int = field(default_factory=lambda: bounded("CAMOFOX_REQUEST_TIMEOUT_SEC", 35, 1, 60))
    concurrency: int = field(default_factory=lambda: bounded("CAMOFOX_MAX_BROWSER_CONCURRENCY", 2, 1, 2))
    pages: int = field(default_factory=lambda: bounded("CAMOFOX_MAX_PAGES_PER_BUSINESS", 3, 1, 4))
    settle_ms: int = field(default_factory=lambda: bounded("CAMOFOX_PAGE_SETTLE_MS", 1200, 0, 3000))
    readiness_ms: int = field(default_factory=lambda: bounded("CAMOFOX_READINESS_TIMEOUT_MS", 4000, 500, 5000))
    screenshots: bool = field(default_factory=lambda: os.getenv("AUDIT_SCREENSHOTS_ENABLED", "false").lower() == "true")
    discovery_pages: int = field(default_factory=lambda: bounded("DISCOVERY_MAX_PAGES_PER_PROVIDER", 3, 1, 5))
    artifacts: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "audit_artifacts")

    def __post_init__(self):
        if self.provider != "camofox":
            raise ValueError("BROWSER_PROVIDER must be camofox; mock providers are test injection only")
        service_url(self.base_url, self.access_key)

    def browser(self):
        from browser.camofox import CamoFoxProvider
        return CamoFoxProvider(self.base_url, self.access_key, self.timeout, self.settle_ms)
