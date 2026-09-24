"""Integration tests for the per-client rate-limit middleware (Req 28.1-28.3).

Installs the ``before_request`` hook produced by
:func:`api.rate_limit.install_rate_limit` on a tiny Flask app (a single view)
and drives it through the test client with a **fake clock** so time is fully
controlled. Verifies that:

* requests within the configured limit pass through (non-429),
* the request that exceeds the limit is rejected with **429** and the
  ``{"type": "error", "message": ...}`` body, without executing the view, and
* after the window advances the per-client counter resets and requests are
  allowed again.
"""

from __future__ import annotations

import pytest
from flask import Flask

from api.rate_limit import RateLimiter, install_rate_limit


class _FakeClock:
    """A controllable monotonic clock for deterministic window tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_app(limiter: RateLimiter) -> Flask:
    """Build a tiny Flask app with the rate-limit hook and a counted view."""
    app = Flask(__name__)
    app.config["EXECUTIONS"] = 0

    install_rate_limit(app, limiter)

    @app.post("/action")
    def action():  # type: ignore[no-untyped-def]
        app.config["EXECUTIONS"] += 1
        return {"type": "success", "message": "ok"}

    return app


@pytest.mark.integration
def test_requests_within_limit_pass() -> None:
    """Every request up to the limit is allowed and executes the view."""
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=3, window_seconds=60, clock=clock)
    app = _make_app(limiter)
    client = app.test_client()

    for _ in range(3):
        resp = client.post("/action")
        assert resp.status_code == 200

    assert app.config["EXECUTIONS"] == 3


@pytest.mark.integration
def test_request_exceeding_limit_gets_429_without_executing() -> None:
    """The over-limit request is rejected with 429 and never runs the view."""
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=2, window_seconds=60, clock=clock)
    app = _make_app(limiter)
    client = app.test_client()

    assert client.post("/action").status_code == 200
    assert client.post("/action").status_code == 200

    resp = client.post("/action")
    assert resp.status_code == 429
    body = resp.get_json()
    assert body == {"type": "error", "message": body["message"]}
    assert body["type"] == "error"
    assert "message" in body

    # The blocked request must NOT have executed the action (Req 28.2).
    assert app.config["EXECUTIONS"] == 2


@pytest.mark.integration
def test_counter_resets_after_window_advances() -> None:
    """Once the window advances, the per-client counter resets (Req 28.1)."""
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
    app = _make_app(limiter)
    client = app.test_client()

    assert client.post("/action").status_code == 200
    # Same window: second request is over the limit.
    assert client.post("/action").status_code == 429

    # Advance into the next fixed window: the counter resets.
    clock.advance(60)
    assert client.post("/action").status_code == 200
    # And the limit applies again within the new window.
    assert client.post("/action").status_code == 429

    assert app.config["EXECUTIONS"] == 2


@pytest.mark.integration
def test_limit_is_per_client() -> None:
    """Distinct clients (via X-Forwarded-For) keep independent counters."""
    clock = _FakeClock()
    limiter = RateLimiter(max_requests=1, window_seconds=60, clock=clock)
    app = _make_app(limiter)
    client = app.test_client()

    a = {"X-Forwarded-For": "10.0.0.1"}
    b = {"X-Forwarded-For": "10.0.0.2"}

    assert client.post("/action", headers=a).status_code == 200
    assert client.post("/action", headers=a).status_code == 429
    # A different client is unaffected by the first client's usage.
    assert client.post("/action", headers=b).status_code == 200
