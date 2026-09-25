"""Integration/smoke tests for the ``GET /metrics`` blueprint (Req 30.1).

Registers :func:`api.metrics.make_metrics_blueprint` on a bare Flask app and
exercises it via the test client, verifying the scrape endpoint returns 200 in
the Prometheus text format and never leaks sensitive configuration values.
"""

from __future__ import annotations

import pytest
from flask import Flask

import app as app_module
from api.metrics import make_metrics_blueprint
from config import AppConfig
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


# --------------------------------------------------------------------------- #
# End-to-end wiring through the app factory: requests must produce real        #
# ``http_requests_total`` samples (not just HELP/TYPE) and never leak the raw   #
# ``sessionid`` query parameter into the exposition text (Req 30.1).            #
# --------------------------------------------------------------------------- #
def _factory_config(**overrides: object) -> AppConfig:
    """Build a fully-populated :class:`AppConfig` for factory-based tests."""
    base: dict[str, object] = {
        "zabbix_url": "https://zabbix.example.com/api_jsonrpc.php",
        "zabbix_token": "test-token",
        "zabbix_verify_tls": True,
        "zabbix_ca_bundle": None,
        "ai_provider": "gemini",
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.0-flash",
        "openai_api_key": None,
        "openai_model": "gpt-4o-mini",
        "bedrock_model": "amazon.nova-lite-v1:0",
        "aws_region": "us-east-1",
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "aws_session_token": None,
        "aws_bearer_token_bedrock": None,
        "cors_allowed_origins": ["https://widget.example.com"],
        "version": "test",
        "supported_locales": ["es", "en"],
        "default_locale": "es",
        "ai_secondary_provider": None,
        "ai_failover_max_retries": 1,
        "ai_failover_timeout_seconds": 30.0,
        "ai_request_timeout_seconds": 20.0,
        "user_cache_ttl_seconds": 300,
        "rate_limit_max_requests": 60,
        "rate_limit_window_seconds": 60,
        "ai_schema_max_attempts": 2,
    }
    base.update(overrides)
    return AppConfig(**base)  # type: ignore[arg-type]


class _FakeClient:
    """Fake ZabbixClient so the factory needs no network access."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def is_connected(self) -> bool:
        return True

    def check_authentication(self, sessionid: str) -> dict[str, object] | None:
        return {"userid": "1", "username": "admin"}


@pytest.mark.integration
def test_requests_produce_real_samples_via_factory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """After real requests, ``/metrics`` exposes a counted ``http_requests_total``
    sample for the ``/health`` route (a line with a value, not just HELP/TYPE).
    """
    monkeypatch.setattr(app_module, "ZabbixClient", _FakeClient)
    application = app_module.create_app(_factory_config())
    client = application.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200

    body = application.test_client().get("/metrics").get_data(as_text=True)

    # A real sample line for the /health route with a count >= 1 (not HELP/TYPE).
    sample_lines = [
        line
        for line in body.splitlines()
        if line.startswith("http_requests_total{")
        and 'endpoint="/health"' in line
    ]
    assert sample_lines, f"no http_requests_total sample for /health in:\n{body}"

    # The counted value is the trailing number on the sample line; must be >= 1.
    value = float(sample_lines[0].rsplit(" ", 1)[1])
    assert value >= 1.0


@pytest.mark.integration
def test_metrics_do_not_leak_sessionid_query_param(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A request carrying ``?sessionid=<secret>`` must not surface that value in
    the metrics exposition text: the endpoint label is the ROUTE, not the URL.
    """
    monkeypatch.setattr(app_module, "ZabbixClient", _FakeClient)
    application = app_module.create_app(_factory_config())
    client = application.test_client()

    secret = "SUPERSECRETSESSION123"
    client.get(f"/maintenance/list?sessionid={secret}")

    body = application.test_client().get("/metrics").get_data(as_text=True)
    assert secret not in body
    assert "sessionid" not in body
