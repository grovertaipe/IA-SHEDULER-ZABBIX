"""Integration/smoke tests for the ``GET /metrics`` blueprint (Req 30.1).

Registers :func:`api.metrics.make_metrics_blueprint` on a bare Flask app and
exercises it via the test client, verifying the scrape endpoint returns 200 in
the Prometheus text format and never leaks sensitive configuration values.
"""

from __future__ import annotations

import pytest
from flask import Flask

from api.metrics import make_metrics_blueprint
from observability.metrics import Metrics


@pytest.fixture
def metrics() -> Metrics:
    """Return an isolated metrics collector (own registry)."""
    return Metrics()


@pytest.fixture
def client(metrics: Metrics):  # type: ignore[no-untyped-def]
    """Return a Flask test client with the metrics blueprint registered."""
    app = Flask(__name__)
    app.register_blueprint(make_metrics_blueprint(metrics))
    return app.test_client()


@pytest.mark.integration
def test_metrics_returns_200_prometheus_content_type(client, metrics: Metrics) -> None:  # type: ignore[no-untyped-def]
    """``GET /metrics`` responds 200 with the Prometheus exposition content type."""
    metrics.record_request(endpoint="chat", status=200, latency_seconds=0.01)
    metrics.record_failover(outcome="secondary")

    resp = client.get("/metrics")

    assert resp.status_code == 200
    assert "text/plain" in resp.content_type
    assert "version=0.0.4" in resp.content_type

    body = resp.get_data(as_text=True)
    assert "http_requests_total" in body
    assert "ai_failover_events_total" in body


@pytest.mark.integration
def test_metrics_does_not_expose_secrets(client) -> None:  # type: ignore[no-untyped-def]
    """The exposition text contains no secret / sensitive configuration values."""
    resp = client.get("/metrics")
    body = resp.get_data(as_text=True).lower()

    for needle in ("token", "api_key", "apikey", "password", "secret", "authorization"):
        assert needle not in body
