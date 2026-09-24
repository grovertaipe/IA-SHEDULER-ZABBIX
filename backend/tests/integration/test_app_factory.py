"""Integration tests for the app factory (Task 11.4).

Builds the real Flask application via :func:`app.create_app` with an injected
:class:`~config.AppConfig` override (so no environment or real network access is
needed) and a monkeypatched :class:`~zabbix.client.ZabbixClient`, then exercises
the wiring with Flask's test client:

* every contract route is registered (Req 15.1).
* ``/health`` responds and reflects the injected config (Req 16).
* CORS is restricted to the configured origins and answers preflight, never
  emitting the wildcard (Req 15.5).
* the rate-limit middleware runs first and returns 429 once the window is
  exhausted (Req 28.1).
"""

from __future__ import annotations

import app as app_module
from config import AppConfig


def _config(**overrides: object) -> AppConfig:
    """Build a fully-populated :class:`AppConfig` for tests, with overrides."""
    base: dict[str, object] = {
        "zabbix_url": "https://zabbix.example.com/api_jsonrpc.php",
        "zabbix_token": "test-token",
        "ai_provider": "gemini",
        "gemini_api_key": "test-key",
        "gemini_model": "gemini-2.0-flash",
        "openai_api_key": None,
        "openai_model": "gpt-4o-mini",
        "cors_allowed_origins": ["https://widget.example.com"],
        "version": "test",
        "supported_locales": ["es", "en"],
        "default_locale": "es",
        "ai_secondary_provider": None,
        "ai_failover_max_retries": 1,
        "ai_failover_timeout_seconds": 30.0,
        "user_cache_ttl_seconds": 300,
        "rate_limit_max_requests": 60,
        "rate_limit_window_seconds": 60,
        "ai_schema_max_attempts": 2,
    }
    base.update(overrides)
    return AppConfig(**base)  # type: ignore[arg-type]


class _FakeClient:
    """Fake ZabbixClient: only connectivity/user probes are exercised here."""

    def __init__(self, *args: object, connected: bool = True, **kwargs: object) -> None:
        self._connected = connected

    def is_connected(self) -> bool:
        return self._connected

    def user_exists(self, userid: str) -> bool:
        return True


def _build(monkeypatch, **cfg_overrides: object) -> app_module.Flask:
    """Build the app with the Zabbix client patched out (no network)."""
    monkeypatch.setattr(app_module, "ZabbixClient", _FakeClient)
    return app_module.create_app(_config(**cfg_overrides))


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
_EXPECTED_ROUTES = {
    "/chat",
    "/parse",
    "/create_maintenance",
    "/health",
    "/search_hosts",
    "/search_groups",
    "/maintenance/list",
    "/maintenance/templates",
    "/test/routine",
    "/metrics",
}


def test_app_registers_all_contract_routes(monkeypatch) -> None:
    """The factory registers every contract endpoint (Req 15.1)."""
    application = _build(monkeypatch)
    rules = {str(rule) for rule in application.url_map.iter_rules()}
    assert _EXPECTED_ROUTES <= rules


def test_health_responds_healthy_when_connected(monkeypatch) -> None:
    """/health returns 200 healthy and echoes the injected config (Req 16)."""
    application = _build(monkeypatch)
    client = application.test_client()

    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "healthy"
    assert data["zabbix_connected"] is True
    assert data["ai_provider"] == "gemini"
    assert data["version"] == "test"


def test_health_degraded_when_disconnected(monkeypatch) -> None:
    """/health degrades (not error) when Zabbix is unreachable (Req 16.3)."""
    monkeypatch.setattr(
        app_module,
        "ZabbixClient",
        lambda *a, **k: _FakeClient(connected=False),
    )
    application = app_module.create_app(_config())
    resp = application.test_client().get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "degraded"


def test_cors_allows_configured_origin_and_not_wildcard(monkeypatch) -> None:
    """CORS echoes the configured origin and never the wildcard (Req 15.5)."""
    application = _build(monkeypatch)
    client = application.test_client()

    origin = "https://widget.example.com"
    resp = client.get("/health", headers={"Origin": origin})
    allow_origin = resp.headers.get("Access-Control-Allow-Origin")
    assert allow_origin in (origin, None) and allow_origin != "*"
    assert allow_origin == origin


def test_cors_preflight_is_answered(monkeypatch) -> None:
    """A CORS preflight (OPTIONS) is answered with the allowed origin (Req 15.5)."""
    application = _build(monkeypatch)
    client = application.test_client()

    resp = client.options(
        "/chat",
        headers={
            "Origin": "https://widget.example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("Access-Control-Allow-Origin") == "https://widget.example.com"


def test_disallowed_origin_is_not_echoed(monkeypatch) -> None:
    """An origin outside the allow-list is not reflected back (Req 15.5)."""
    application = _build(monkeypatch)
    client = application.test_client()

    resp = client.get("/health", headers={"Origin": "https://evil.example.com"})
    assert resp.headers.get("Access-Control-Allow-Origin") != "https://evil.example.com"
    assert resp.headers.get("Access-Control-Allow-Origin") != "*"


def test_rate_limit_runs_first_and_returns_429(monkeypatch) -> None:
    """The rate-limit middleware runs before validation and returns 429 (Req 28.1)."""
    application = _build(monkeypatch, rate_limit_max_requests=2, rate_limit_window_seconds=60)
    client = application.test_client()

    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    blocked = client.get("/health")
    assert blocked.status_code == 429
    assert blocked.get_json()["type"] == "error"


def test_create_app_builds_without_config_override() -> None:
    """create_app() builds from a (degraded) env config without raising (Req 1.2)."""
    application = app_module.create_app()
    assert application is not None
    rules = {str(rule) for rule in application.url_map.iter_rules()}
    assert _EXPECTED_ROUTES <= rules
