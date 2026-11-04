"""Polite HTTP fetcher: the one way ingestion code talks to source websites (ADR 0003).

PoliteFetcher enforces the scraping etiquette in a single place, so no source adapter can forget it:
- at least `min_interval` seconds (default 3) between requests to the same host;
- an honest User-Agent that names the project and its public repo;
- a connect + read timeout on every request;
- retries with capped exponential backoff, but only for temporary failures (network errors, 5xx);
- an immediate stop on 403 / 429: a site refusing us is never retried harder.

Retries are a short loop here, not urllib3's built-in Retry: urllib3 retries the first failure with
no delay and bypasses our per-host limiter, which would break the 3-second rule.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import requests

from drugwatch_ingestion import __version__

USER_AGENT = f"DrugWatchIndia/{__version__} (+https://github.com/HARITH935/drugwatch-india)"

RETRY_STATUSES = frozenset({500, 502, 503, 504})  # temporary server-side failures: worth retrying
STOP_STATUSES = frozenset({403, 429})  # "forbidden" / "too many requests": stop (ADR 0003)
NETWORK_ERRORS = (  # temporary network problems: worth retrying
    requests.ConnectionError,  # refused / reset / DNS failure, and connect timeouts
    requests.Timeout,  # read timeout: the server stopped sending
    requests.exceptions.ChunkedEncodingError,  # connection dropped in the middle of the body
)


class FetchError(Exception):
    """The request failed for good: a status that is never retried, or retries ran out."""


class BlockedError(FetchError):
    """The site answered 403 or 429. Callers must stop all requests to that host (ADR 0003)."""


class _TemporaryError(Exception):
    """Internal: one attempt failed in a way that a later attempt might not."""


@dataclass(frozen=True)  # frozen: a result can't be changed after it's created
class FetchResult:
    http_method: str
    url: str  # the URL we asked for, including query parameters
    final_url: str  # the URL we ended up at after any HTTP redirects
    status: int
    content: bytes  # the body exactly as received, never decoded here: raw/ stores bytes
    content_type: str | None
    etag: str | None  # the server's version tag for this file, if it sends one
    last_modified: str | None
    fetched_at: datetime  # UTC

    def provenance(self) -> dict[str, Any]:
        """Request details for the raw/ metadata sidecar.

        Request headers are left out on purpose: they can hold tokens (e.g. Jan Aushadhi's guest
        JWT), and tokens must never be stored.
        """
        return {
            "http_method": self.http_method,
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "content_type": self.content_type,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "fetched_at": self.fetched_at.isoformat(timespec="seconds"),
            "user_agent": USER_AGENT,
        }


class HostRateLimiter:
    """Keeps the starts of requests to the same host at least `min_interval` seconds apart."""

    def __init__(
        self, min_interval: float, clock: Callable[[], float], sleep: Callable[[float], None]
    ):
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last_start: dict[str, float] = {}  # host -> clock time its last request started

    def wait(self, host: str) -> None:
        last = self._last_start.get(host)
        if last is not None:
            remaining = self.min_interval - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last_start[host] = self._clock()


class PoliteFetcher:
    def __init__(
        self,
        *,  # keyword-only: call sites read like settings, e.g. PoliteFetcher(max_attempts=2)
        min_interval: float = 3.0,
        max_attempts: int = 4,  # 1 try + up to 3 retries
        backoff_base: float = 5.0,  # wait 5 s, 10 s, 20 s ... before each retry
        backoff_cap: float = 60.0,  # never wait longer than this between retries
        timeout: tuple[float, float] = (10.0, 60.0),  # (connect, read) seconds
        max_bytes: int = 100 * 1024 * 1024,  # refuse bodies over 100 MB, to protect memory
        clock: Callable[[], float] = time.monotonic,  # monotonic: ignores system clock changes
        sleep: Callable[[float], None] = time.sleep,  # tests pass fakes so they never really wait
    ):
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._sleep = sleep
        self._limiter = HostRateLimiter(min_interval, clock, sleep)
        self._session = requests.Session()  # reuses connections to the same host (keep-alive)
        self._session.headers["User-Agent"] = USER_AGENT

    def fetch(
        self,
        url: str,
        *,
        http_method: str = "GET",
        params: dict[str, str] | None = None,  # query string, e.g. {"month": "Sep-2026"}
        json: Any = None,  # JSON request body (Jan Aushadhi's API is a POST)
        headers: dict[str, str] | None = None,  # extra headers, e.g. a guest-token Authorization
    ) -> FetchResult:
        """Fetch one URL politely. Raises BlockedError on 403/429, FetchError on other failures."""
        host = urlsplit(url).hostname or url  # rate-limit per host name, whatever the port
        problem = ""
        for attempt in range(1, self.max_attempts + 1):
            if attempt > 1:
                self._sleep(self._backoff(attempt))
            self._limiter.wait(host)
            try:
                return self._fetch_once(http_method, url, params, json, headers)
            except _TemporaryError as exc:
                problem = str(exc)
        raise FetchError(
            f"{http_method} {url}: gave up after {self.max_attempts} attempts ({problem})"
        )

    def _backoff(self, attempt: int) -> float:
        """Seconds to wait before attempt 2, 3, 4 ...: base, 2 x base, 4 x base ..., capped."""
        return min(self.backoff_cap, self.backoff_base * 2 ** (attempt - 2))

    def _fetch_once(
        self,
        http_method: str,
        url: str,
        params: dict[str, str] | None,
        json: Any,
        headers: dict[str, str] | None,
    ) -> FetchResult:
        try:
            with self._session.request(
                http_method,
                url,
                params=params,
                json=json,
                headers=headers,
                timeout=self.timeout,
                stream=True,  # read the body in chunks, so the size cap can stop a huge download
            ) as response:
                status = response.status_code
                if status in STOP_STATUSES:
                    raise BlockedError(
                        f"{http_method} {response.url}: HTTP {status}, stop requesting this host"
                    )
                if status in RETRY_STATUSES:
                    raise _TemporaryError(f"HTTP {status}")
                if not 200 <= status < 300:
                    raise FetchError(f"{http_method} {response.url}: HTTP {status}")
                content = self._read_body(response)
                return FetchResult(
                    http_method=http_method,
                    url=response.history[0].url if response.history else response.url,
                    final_url=response.url,
                    status=status,
                    content=content,
                    content_type=response.headers.get("Content-Type"),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                    fetched_at=datetime.now(UTC),
                )
        except NETWORK_ERRORS as exc:
            raise _TemporaryError(f"{type(exc).__name__}: {exc}") from exc

    def _read_body(self, response: requests.Response) -> bytes:
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            size += len(chunk)
            if size > self.max_bytes:
                raise FetchError(f"{response.url}: body larger than {self.max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
