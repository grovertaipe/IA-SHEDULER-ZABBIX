"""Integration tests for the search blueprint (Req 11, 14.2, 14.3, 15.1).

Builds a tiny Flask app registering the search blueprint with a **fake** Zabbix
client, then exercises the HTTP contract with Flask's test client:

* ``/search_hosts`` and ``/search_groups`` require a validated logged-in Zabbix
  user and return HTTP 401 without one (Req 11).
* with a valid user they return the legacy ``search_results`` shape (Req 15.3).
* a missing/blank ``search`` term still yields HTTP 400 (Req 15.7).

Only the Zabbix boundary is faked; the blueprint and the auth edge run for real.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from api.search import make_search_blueprint


class FakeClient:
    """Minimal fake ZabbixClient for the search + auth edges."""

    def __init__(self, known_users: set[str]) -> None:
        self._known = known_users

    def user_exists(self, userid: str) -> bool:
        return userid in self._known

    def search_hosts(self, term: str) -> list[dict[str, Any]]:
        return [{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}]

    def search_groups(self, term: str) -> list[dict[str, Any]]:
        return [{"groupid": "10", "name": "Linux servers"}]


_USER = {"userid": "42", "username": "operator", "name": "Op", "surname": "Erator"}


def _build_app(known_users: set[str] | None = None) -> Flask:
    client = FakeClient(known_users if known_users is not None else {"42"})
    app = Flask(__name__)
    app.register_blueprint(make_search_blueprint(client))  # type: ignore[arg-type]
    return app


# --------------------------------------------------------------------------- #
# search_hosts                                                                #
# --------------------------------------------------------------------------- #
def test_search_hosts_requires_user() -> None:
    """/search_hosts without a valid user yields 401 (Req 11)."""
    app = _build_app(known_users=set())
    client = app.test_client()

    resp = client.post("/search_hosts", json={"search": "srv", "user": _USER})
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_hosts_missing_user_yields_401() -> None:
    """/search_hosts with no user payload at all yields 401 (Req 11)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_hosts", json={"search": "srv"})
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_hosts_valid_user_returns_results() -> None:
    """/search_hosts with a valid user returns the legacy search_results shape."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_hosts", json={"search": "srv", "user": _USER})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "search_results"
    assert data["search_term"] == "srv"
    assert data["hosts_found"] == 1
    assert data["hosts"]


def test_search_hosts_accepts_legacy_user_info_key() -> None:
    """The legacy ``user_info`` key is accepted like ``user`` (Req 15.6)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_hosts", json={"search": "srv", "user_info": _USER})
    assert resp.status_code == 200
    assert resp.get_json()["type"] == "search_results"


def test_search_hosts_missing_term_is_400() -> None:
    """A blank term yields 400 even for a valid user (Req 15.7)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_hosts", json={"search": "  ", "user": _USER})
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


# --------------------------------------------------------------------------- #
# search_groups                                                               #
# --------------------------------------------------------------------------- #
def test_search_groups_requires_user() -> None:
    """/search_groups without a valid user yields 401 (Req 11)."""
    app = _build_app(known_users=set())
    client = app.test_client()

    resp = client.post("/search_groups", json={"search": "linux", "user": _USER})
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_groups_valid_user_returns_results() -> None:
    """/search_groups with a valid user returns the legacy search_results shape."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_groups", json={"search": "linux", "user": _USER})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "search_results"
    assert data["groups_found"] == 1
    assert data["groups"]


def test_search_groups_missing_term_is_400() -> None:
    """A blank term yields 400 even for a valid user (Req 15.7)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_groups", json={"user": _USER})
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
