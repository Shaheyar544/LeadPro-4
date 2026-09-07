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


class BrowserError(Exception):
    def __init__(self, code: str):
        self.code = code if code in ERROR_MESSAGES else "browser_protocol_error"
        super().__init__(ERROR_MESSAGES[self.code])


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
