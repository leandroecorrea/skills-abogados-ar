"""HTTP client abstraction for MEV service.

This module provides a clean HTTP client interface with:
- Async support for FastAPI integration
- Connection pooling
- Automatic cookie handling
- Retry logic
- Configurable timeouts
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Any
import httpx

from .exceptions import NetworkError, SessionError


@dataclass
class SessionCookie:
    """MEV session cookie."""

    name: str
    value: str
    creation_date: datetime = field(default_factory=datetime.now)
    domain: str = "mev.scba.gov.ar"


@dataclass
class MEVResponse:
    """Wrapper for HTTP response with proper encoding for MEV."""

    _response: httpx.Response
    _encoding: str

    @property
    def text(self) -> str:
        """Get response text with correct encoding for Spanish characters."""
        # Decode raw bytes with the specified encoding (latin-1 for MEV)
        return self._response.content.decode(self._encoding, errors="replace")

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def content(self) -> bytes:
        return self._response.content


@dataclass
class HttpClientConfig:
    """Configuration for the HTTP client."""

    base_url: str = "https://mev.scba.gov.ar"
    timeout: float = 30.0
    max_retries: int = 3
    retry_delay: float = 1.0
    follow_redirects: bool = True
    # MEV uses Latin-1 encoding for Spanish characters (Ñ, Ó, etc.)
    response_encoding: str = "latin-1"
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )


class MEVHttpClient:
    """
    Async HTTP client for MEV operations.

    Handles all low-level HTTP operations including:
    - Session cookie management
    - Request retries
    - Error handling
    - Connection pooling

    Usage:
        async with MEVHttpClient() as client:
            response = await client.post("/loguin.asp", data={...})
    """

    DEFAULT_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self, config: Optional[HttpClientConfig] = None):
        """Initialize the HTTP client."""
        self.config = config or HttpClientConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._session_cookie: Optional[SessionCookie] = None

    async def __aenter__(self) -> "MEVHttpClient":
        """Async context manager entry."""
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def _ensure_client(self) -> None:
        """Ensure the HTTP client is initialized."""
        if self._client is None:
            headers = {
                **self.DEFAULT_HEADERS,
                "User-Agent": self.config.user_agent,
            }
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                follow_redirects=self.config.follow_redirects,
                timeout=self.config.timeout,
                headers=headers,
            )

    async def close(self) -> None:
        """Close the HTTP client and release resources."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            self._session_cookie = None

    async def get(
        self,
        path: str,
        params: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> MEVResponse:
        """Perform a GET request with retry logic."""
        await self._ensure_client()
        response = await self._request_with_retry("GET", path, params=params, headers=headers)
        return MEVResponse(_response=response, _encoding=self.config.response_encoding)

    async def post(
        self,
        path: str,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        referer: Optional[str] = None,
    ) -> MEVResponse:
        """Perform a POST request with retry logic."""
        await self._ensure_client()
        request_headers = headers or {}
        if referer:
            request_headers["Referer"] = f"{self.config.base_url}{referer}"
        response = await self._request_with_retry("POST", path, data=data, headers=request_headers)
        return MEVResponse(_response=response, _encoding=self.config.response_encoding)

    async def _request_with_retry(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, str]] = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        """Execute a request with retry logic."""
        last_error: Optional[Exception] = None

        for attempt in range(self.config.max_retries):
            try:
                if method == "GET":
                    response = await self._client.get(path, params=params, headers=headers)
                else:
                    response = await self._client.post(path, data=data, headers=headers)

                response.raise_for_status()
                return response

            except httpx.TimeoutException as e:
                last_error = NetworkError(
                    f"Request timeout after {self.config.timeout}s",
                    {"path": path, "attempt": attempt + 1},
                )
            except httpx.HTTPStatusError as e:
                # Don't retry client errors (4xx)
                if 400 <= e.response.status_code < 500:
                    raise NetworkError(
                        f"HTTP {e.response.status_code}: {e.response.reason_phrase}",
                        {"path": path, "status_code": e.response.status_code},
                    )
                last_error = NetworkError(
                    f"HTTP error: {e.response.status_code}",
                    {"path": path, "attempt": attempt + 1},
                )
            except httpx.RequestError as e:
                last_error = NetworkError(
                    f"Request failed: {str(e)}",
                    {"path": path, "attempt": attempt + 1},
                )

            # Wait before retry (except on last attempt)
            if attempt < self.config.max_retries - 1:
                await asyncio.sleep(self.config.retry_delay * (attempt + 1))

        raise last_error

    async def fetch_initial_cookie(self) -> SessionCookie:
        """Fetch the login page to obtain the initial session cookie."""
        await self._ensure_client()
        response = await self.get("/loguin.asp")

        # Extract cookie from the client's cookie jar
        for cookie in self._client.cookies.jar:
            if cookie.domain and "mev.scba.gov.ar" in cookie.domain:
                self._session_cookie = SessionCookie(
                    name=cookie.name,
                    value=cookie.value,
                    creation_date=datetime.now(),
                )
                return self._session_cookie

        # Fallback: use first available cookie
        cookies = list(self._client.cookies.jar)
        if cookies:
            c = cookies[0]
            self._session_cookie = SessionCookie(name=c.name, value=c.value)
            return self._session_cookie

        raise SessionError("Failed to obtain session cookie from MEV")

    @property
    def has_session(self) -> bool:
        """Check if client has an active session cookie."""
        return self._session_cookie is not None

    @property
    def session_cookie(self) -> Optional[SessionCookie]:
        """Get the current session cookie."""
        return self._session_cookie

    def clear_session(self) -> None:
        """Clear the current session."""
        self._session_cookie = None
        if self._client is not None:
            self._client.cookies.clear()
