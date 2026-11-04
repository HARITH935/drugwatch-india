"""PoliteFetcher: etiquette rules from ADR 0003, tested against a local scripted HTTP server."""

import json
import socket

import pytest

from drugwatch_ingestion.fetcher import (
    USER_AGENT,
    BlockedError,
    FetchError,
    HostRateLimiter,
    PoliteFetcher,
)


def make_fetcher(clock, **settings) -> PoliteFetcher:
    return PoliteFetcher(clock=clock.time, sleep=clock.sleep, **settings)


def test_returns_bytes_and_sends_honest_user_agent(http_server, fake_clock):
    http_server.scripts["/ok"] = [(200, b"hello")]

    result = make_fetcher(fake_clock).fetch(
        f"{http_server.base_url}/ok", params={"month": "Sep-2026"}
    )

    assert result.status == 200
    assert result.content == b"hello"
    assert result.url.endswith("/ok?month=Sep-2026")
    assert http_server.requests[0]["headers"]["User-Agent"] == USER_AGENT
    assert "github.com/HARITH935/drugwatch-india" in USER_AGENT


def test_provenance_never_contains_request_headers(http_server, fake_clock):
    http_server.scripts["/api"] = [(200, b"{}")]

    result = make_fetcher(fake_clock).fetch(
        f"{http_server.base_url}/api", headers={"Authorization": "Bearer guest-jwt-123"}
    )

    assert http_server.requests[0]["headers"]["Authorization"] == "Bearer guest-jwt-123"  # was sent
    assert "guest-jwt-123" not in json.dumps(result.provenance())  # but is never stored


def test_post_sends_json_body(http_server, fake_clock):
    http_server.scripts["/list"] = [(200, b"[]")]

    make_fetcher(fake_clock).fetch(
        f"{http_server.base_url}/list", http_method="POST", json={"pageIndex": 0}
    )

    assert json.loads(http_server.bodies[0]) == {"pageIndex": 0}


def test_waits_min_interval_between_requests_to_same_host(http_server, fake_clock):
    http_server.scripts["/ok"] = [(200, b"x")]
    fetcher = make_fetcher(fake_clock)

    fetcher.fetch(f"{http_server.base_url}/ok")
    fetcher.fetch(f"{http_server.base_url}/ok")

    assert fake_clock.sleeps == [3.0]  # fake time stood still, so the full 3 s was waited


def test_retries_temporary_errors_with_exponential_backoff(http_server, fake_clock):
    http_server.scripts["/flaky"] = [(503, b""), (503, b""), (200, b"finally")]

    result = make_fetcher(fake_clock).fetch(f"{http_server.base_url}/flaky")

    assert result.content == b"finally"
    assert len(http_server.requests) == 3
    assert fake_clock.sleeps == [5.0, 10.0]


def test_gives_up_after_max_attempts(http_server, fake_clock):
    http_server.scripts["/down"] = [(503, b"")]

    with pytest.raises(FetchError, match="gave up after 4 attempts") as error:
        make_fetcher(fake_clock).fetch(f"{http_server.base_url}/down")

    assert not isinstance(error.value, BlockedError)
    assert len(http_server.requests) == 4
    assert fake_clock.sleeps == [5.0, 10.0, 20.0]


def test_backoff_is_capped(fake_clock):
    fetcher = make_fetcher(fake_clock, backoff_cap=60.0)

    assert [fetcher._backoff(n) for n in (2, 3, 4, 5, 6)] == [5.0, 10.0, 20.0, 40.0, 60.0]


@pytest.mark.parametrize("status", [403, 429])
def test_stops_at_once_when_blocked(http_server, fake_clock, status):
    http_server.scripts["/blocked"] = [(status, b"go away")]

    with pytest.raises(BlockedError, match=str(status)):
        make_fetcher(fake_clock).fetch(f"{http_server.base_url}/blocked")

    assert len(http_server.requests) == 1  # never retried
    assert fake_clock.sleeps == []


def test_does_not_retry_not_found(http_server, fake_clock):
    with pytest.raises(FetchError, match="404") as error:
        make_fetcher(fake_clock).fetch(f"{http_server.base_url}/missing")

    assert not isinstance(error.value, BlockedError)
    assert len(http_server.requests) == 1


def test_retries_network_errors(fake_clock):
    with socket.socket() as s:  # find a free port, then close it: nothing is listening there
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    with pytest.raises(FetchError, match="ConnectionError"):
        make_fetcher(fake_clock, max_attempts=2).fetch(f"http://127.0.0.1:{port}/")

    assert fake_clock.sleeps == [5.0]


def test_refuses_oversized_body(http_server, fake_clock):
    http_server.scripts["/big"] = [(200, b"x" * 100)]

    with pytest.raises(FetchError, match="larger than 10 bytes"):
        make_fetcher(fake_clock, max_bytes=10).fetch(f"{http_server.base_url}/big")


def test_rate_limiter_tracks_each_host_separately(fake_clock):
    limiter = HostRateLimiter(3.0, fake_clock.time, fake_clock.sleep)

    limiter.wait("cdsco.gov.in")
    limiter.wait("nppa.gov.in")  # different host: no wait
    fake_clock.now += 1.0
    limiter.wait("cdsco.gov.in")  # 1 s since its last request: waits the other 2 s
    fake_clock.now += 5.0
    limiter.wait("nppa.gov.in")  # 8 s since its last request: no wait

    assert fake_clock.sleeps == [2.0]
