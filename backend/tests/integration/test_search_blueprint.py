"""Integration tests for the search blueprint (Req 11, 14.2, 14.3, 15.1).

Builds a tiny Flask app registering the search blueprint with a **fake** Zabbix
client, then exercises the HTTP contract with Flask's test client:

* ``/search_hosts`` and ``/search_groups`` require a valid logged-in Zabbix
  session and return HTTP 401 without one (Req 11).
* with a valid session they return the legacy ``search_results`` shape (Req 15.3).
* a missing/blank ``search`` term still yields HTTP 400 (Req 15.7).

Only the Zabbix boundary is faked; the blueprint and the auth edge run for real.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from api.search import make_search_blueprint


class FakeClient:
    """Minimal fake ZabbixClient for the search + auth edges.

    ``sessions`` maps a valid session id → the VERIFIED user object Zabbix would
    return; unknown session ids yield ``None`` (invalid/expired).
    """

    def __init__(self, sessions: dict[str, dict[str, Any]]) -> None:
        self._sessions = sessions

    def check_authentication(self, sessionid: str) -> dict[str, Any] | None:
        return self._sessions.get(sessionid)

    def search_hosts(self, term: str) -> list[dict[str, Any]]:
        return [{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}]

    def search_groups(self, term: str) -> list[dict[str, Any]]:
        return [{"groupid": "10", "name": "Linux servers"}]


#: Cosmetic display payload (not trusted for identity) + the auth credential.
_USER = {"userid": "42", "username": "operator", "name": "Op", "surname": "Erator"}
_SESSION_ID = "sid-valid"
_VERIFIED_USER = {
    "userid": "42",
    "username": "operator",
    "name": "Op",
    "surname": "Erator",
}


def _build_app(*, authenticated: bool = True) -> Flask:
    sessions = {_SESSION_ID: _VERIFIED_USER} if authenticated else {}
    client = FakeClient(sessions)
    app = Flask(__name__)
    app.register_blueprint(make_search_blueprint(client))  # type: ignore[arg-type]
    return app


# --------------------------------------------------------------------------- #
# search_hosts                                                                #
# --------------------------------------------------------------------------- #
def test_search_hosts_invalid_session_yields_401() -> None:
    """/search_hosts with an invalid session yields 401 (Req 11)."""
    app = _build_app(authenticated=False)
    client = app.test_client()

    resp = client.post(
        "/search_hosts", json={"search": "srv", "sessionid": _SESSION_ID, "user": _USER}
    )
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_hosts_missing_session_yields_401() -> None:
    """/search_hosts with no session at all yields 401 (Req 11)."""
    app = _build_app()
    client = app.test_client()

    # A client-claimed user without a session is NOT authenticated.
    resp = client.post("/search_hosts", json={"search": "srv", "user": _USER})
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_hosts_valid_session_returns_results() -> None:
    """/search_hosts with a valid session returns the legacy search_results shape."""
    app = _build_app()
    client = app.test_client()

    resp = client.post(
        "/search_hosts", json={"search": "srv", "sessionid": _SESSION_ID}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "search_results"
    assert data["search_term"] == "srv"
    assert data["hosts_found"] == 1
    assert data["hosts"]


def test_search_hosts_missing_term_is_400() -> None:
    """A blank term yields 400 even for a valid session (Req 15.7)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post(
        "/search_hosts", json={"search": "  ", "sessionid": _SESSION_ID}
    )
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


# --------------------------------------------------------------------------- #
# search_groups                                                               #
# --------------------------------------------------------------------------- #
def test_search_groups_invalid_session_yields_401() -> None:
    """/search_groups with an invalid session yields 401 (Req 11)."""
    app = _build_app(authenticated=False)
    client = app.test_client()

    resp = client.post(
        "/search_groups",
        json={"search": "linux", "sessionid": _SESSION_ID, "user": _USER},
    )
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_search_groups_valid_session_returns_results() -> None:
    """/search_groups with a valid session returns the legacy search_results shape."""
    app = _build_app()
    client = app.test_client()

    resp = client.post(
        "/search_groups", json={"search": "linux", "sessionid": _SESSION_ID}
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "search_results"
    assert data["groups_found"] == 1
    assert data["groups"]


def test_search_groups_missing_term_is_400() -> None:
    """A blank term yields 400 even for a valid session (Req 15.7)."""
    app = _build_app()
    client = app.test_client()

    resp = client.post("/search_groups", json={"sessionid": _SESSION_ID})
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
