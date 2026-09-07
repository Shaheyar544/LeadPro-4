"""Small asynchronous browser contract; no browser implementation leaks out."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


ERROR_MESSAGES = {
    "browser_unavailable": "Browser service is unavailable or access is denied.",
    "browser_timeout": "Browser operation timed out.",
    "browser_navigation_failed": "Browser could not load this page.",
    "browser_blocked": "Page access was blocked; no bypass was attempted.",
    "browser_protocol_error": "Browser service returned an unexpected response.",
    "unsafe_navigation": "Navigation was stopped by the public website safety policy.",
    "browser_session_lost": "Browser session was lost; the audit can be retried.",
}
ERROR_MESSAGES.update({
    "browser_connect_timeout": "Connection to the browser service timed out.",
    "browser_navigation_timeout": "Page navigation timed out.",
    "browser_dom_timeout": "No usable page content became available in time.",
    "browser_render_timeout": "Page content did not stabilize within the observation window.",
    "browser_evaluate_timeout": "Reading page content timed out.",
    "browser_snapshot_timeout": "Reading the page snapshot timed out.",
    "browser_cleanup_timeout": "Browser cleanup timed out; cleanup remains pending.",
    "browser_tab_timeout": "Creating a browser tab timed out.",
    "browser_connection_reset": "The connection was reset during navigation.",
    "browser_tls_error": "The target website failed TLS certificate validation.",
    "browser_maintenance": "The page reports maintenance or a hosting error.",
    "browser_parking": "The page appears to be a parked domain.",
    "browser_javascript_required": "The page requires unavailable JavaScript or cookies.",
    "external_redirect": "The page redirected outside the verified business domain.",
})
PHASES = {"session_create", "tab_create", "initial_navigation", "redirect_validation",
          "dom_ready", "render_settle", "link_extract", "evaluate", "snapshot",
          "page_select", "cleanup", "connect", "viewport"}


class BrowserError(Exception):
    def __init__(self, code: str, *, phase=None, http_status=None, retryable=False):
        self.code = code if code in ERROR_MESSAGES else "browser_protocol_error"
        self.phase = phase if phase in PHASES else None
        self.http_status = http_status if isinstance(http_status, int) else None
        self.retryable = bool(retryable)
        super().__init__(ERROR_MESSAGES[self.code])

    def diagnostic(self):
        return dict(code=self.code, phase=self.phase, http_status=self.http_status)


@dataclass
class BrowserSession:
    user_id: str
    session_key: str
    pages: set[str] = field(default_factory=set)


@dataclass
class BrowserPage:
    id: str
    session: BrowserSession
    url: str
    navigation_error: BrowserError | None = None


@dataclass
class BrowserHealth:
    provider: str
    configured: bool
    available: bool
    status: str
    contract_version: str


class BrowserProvider(ABC):
    name: str
    version: str

    @abstractmethod
    async def health(self) -> BrowserHealth: ...
    @abstractmethod
    async def open_session(self) -> BrowserSession: ...
    @abstractmethod
    async def open_page(self, session: BrowserSession, url: str) -> BrowserPage: ...
    @abstractmethod
    async def navigate(self, page: BrowserPage, url: str) -> str: ...
    @abstractmethod
    async def get_links(self, page: BrowserPage) -> list[dict]: ...
    @abstractmethod
    async def evaluate(self, page: BrowserPage, expression: str) -> Any: ...
    @abstractmethod
    async def get_snapshot(self, page: BrowserPage) -> dict: ...
    @abstractmethod
    async def screenshot(self, page: BrowserPage) -> bytes: ...
    @abstractmethod
    async def set_viewport(self, page: BrowserPage, width: int, height: int) -> bool: ...
    @abstractmethod
    async def close_page(self, page: BrowserPage) -> None: ...
    @abstractmethod
    async def close_session(self, session: BrowserSession) -> None: ...
    @abstractmethod
    async def shutdown(self) -> None: ...
