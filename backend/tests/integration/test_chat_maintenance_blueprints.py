"""Integration tests for the chat + maintenance blueprints (Task 11.2).

Builds a tiny Flask app registering both blueprints with **fake** services and a
fake Zabbix client, then exercises the HTTP contract with Flask's test client:

* ``/chat`` and ``/parse`` return identical-shaped responses (Req 15.2).
* ``/create_maintenance`` returns the ``maintenance_created`` confirmation shape
  (Req 11.4).
* an unauthorized user yields HTTP 401 on both acting endpoints (Req 11).
* ``/maintenance/templates`` and ``/test/routine`` return their legacy shapes.

These use fakes only for the boundaries (AI provider / Zabbix client); the
blueprints, services shaping and the recurrence engine run for real.
"""

from __future__ import annotations

from typing import Any

import pytest
from flask import Flask

from api.chat import make_chat_blueprint
from api.maintenance import make_maintenance_blueprint
from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    RecurrenceType,
    UserInfo,
)
from services.chat_service import ChatResult
from services.maintenance_service import (
    MaintenanceConfirmation,
    ResolvedResources,
)


# --------------------------------------------------------------------------- #
# Fakes                                                                       #
# --------------------------------------------------------------------------- #
class FakeClient:
    """Minimal fake ZabbixClient: ``check_authentication`` drives the auth edge.

    ``sessions`` maps a valid session id → the VERIFIED user object Zabbix would
    return for it. Unknown session ids yield ``None`` (invalid/expired), so a
    request without a known session fails closed (401).
    """

    def __init__(self, sessions: dict[str, dict[str, Any]]) -> None:
        self._sessions = sessions

    def check_authentication(self, sessionid: str) -> dict[str, Any] | None:
        return self._sessions.get(sessionid)

    def list_maintenance(self) -> list[dict[str, Any]]:
        return []


class FakeChatService:
    """Fake ChatService returning a preset :class:`ChatResult`."""

    def __init__(self, result: ChatResult) -> None:
        self._result = result

    def interpret(self, message: str, *, locale: str = "es", **_: Any) -> ChatResult:
        # Preserve the original message like the real service.
        self._result.raw_message = message
        self._result.locale = locale
        return self._result


class FakeMaintenanceService:
    """Fake MaintenanceService with canned resolution + confirmation."""

    def __init__(
        self,
        resolved: ResolvedResources,
        confirmation: MaintenanceConfirmation | None = None,
    ) -> None:
        self._resolved = resolved
        self._confirmation = confirmation

    def resolve_resources(self, **_: Any) -> ResolvedResources:
        return self._resolved

    def create(self, request: ExtractedRequest, user: UserInfo) -> MaintenanceConfirmation:
        assert self._confirmation is not None
        return self._confirmation


class FakeConfig:
    """Minimal AppConfig stand-in for locale resolution."""

    supported_locales = ["es", "en"]
    default_locale = "es"
    version = "test"
    ai_provider = "gemini"


# --------------------------------------------------------------------------- #
# App builders                                                                #
# --------------------------------------------------------------------------- #
def _maintenance_request_result() -> ChatResult:
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.DAILY,
        start_hour=2,
        duration_hours=2.0,
    )
    req = ExtractedRequest(
        intent="maintenance_request",
        hosts=["srv-web01"],
        recurrence=rec,
        raw_message="",
    )
    return ChatResult(
        intent="maintenance_request",
        message="listo",
        raw_message="",
        request=req,
        ticket="100-178306",
    )


#: The verified user Zabbix returns for the valid session below.
_VERIFIED_USER = {
    "userid": "42",
    "username": "operator",
    "name": "Op",
    "surname": "Erator",
}
#: A valid frontend session id the widget would send.
_SESSION_ID = "sid-valid"


def _build_app(
    chat_result: ChatResult,
    resolved: ResolvedResources,
    confirmation: MaintenanceConfirmation | None = None,
    *,
    authenticated: bool = True,
) -> Flask:
    sessions = {_SESSION_ID: _VERIFIED_USER} if authenticated else {}
    client = FakeClient(sessions)
    chat_service = FakeChatService(chat_result)
    maint_service = FakeMaintenanceService(resolved, confirmation)
    config = FakeConfig()

    app = Flask(__name__)
    app.register_blueprint(
        make_chat_blueprint(chat_service, maint_service, client, config)  # type: ignore[arg-type]
    )
    app.register_blueprint(
        make_maintenance_blueprint(maint_service, client, config)  # type: ignore[arg-type]
    )
    return app


#: A cosmetic user payload the widget still sends for display. The backend does
#: NOT trust it for identity — authentication is the ``sessionid`` below.
_USER = {"userid": "42", "username": "operator", "name": "Op", "surname": "Erator"}


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
def test_chat_and_parse_return_identical_shape() -> None:
    """/chat and /parse must return byte-for-byte identical responses (Req 15.2)."""
    resolved = ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )
    app = _build_app(_maintenance_request_result(), resolved)
    client = app.test_client()

    body = {
        "message": "backup diario 2-4am srv-web01",
        "sessionid": _SESSION_ID,
        "user": _USER,
    }
    chat_resp = client.post("/chat", json=body)
    parse_resp = client.post("/parse", json=body)

    assert chat_resp.status_code == 200
    assert parse_resp.status_code == 200
    assert chat_resp.get_json() == parse_resp.get_json()
    assert chat_resp.get_json()["type"] == "maintenance_request"
    assert chat_resp.get_json()["found_hosts"]


def test_chat_message_is_ai_assistant_text() -> None:
    """The /chat response ``message`` is the ChatResult text (AI assistant_message)."""
    ai_text = "Listo, preparé el mantenimiento diario para srv-web01."
    resolved = ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )
    result = _maintenance_request_result()
    result.message = ai_text
    app = _build_app(result, resolved)
    client = app.test_client()

    resp = client.post(
        "/chat",
        json={
            "message": "backup diario 2-4am srv-web01",
            "sessionid": _SESSION_ID,
            "user": _USER,
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["message"] == ai_text


def test_create_maintenance_confirmation_localized_en() -> None:
    """The creation confirmation ``message`` is localized via the i18n catalog."""
    resolved = ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )
    confirmation = MaintenanceConfirmation(
        maintenanceid="777",
        name="100-178306 - backup",
        description="desc",
        user=UserInfo(userid="42", username="operator", name="Op", surname="Erator"),
        resolved=resolved,
    )
    app = _build_app(_maintenance_request_result(), resolved, confirmation)
    client = app.test_client()

    body = {
        "message": "backup diario",
        "sessionid": _SESSION_ID,
        "user": _USER,
        "locale": "en",
        "hosts": ["srv-web01"],
        "recurrence_type": "daily",
        "recurrence": {"start_hour": 2, "duration_hours": 2.0},
        "ticket": "100-178306",
    }
    resp = client.post("/create_maintenance", json=body)
    assert resp.status_code == 200
    message = resp.get_json()["message"]
    # English catalog wording (Req 21.1) rather than the previous fixed Spanish.
    assert "Maintenance created successfully!" in message
    assert "Requested by: Op Erator" in message
    assert "Ticket: 100-178306" in message


def test_chat_missing_message_is_400_no_state_change() -> None:
    """A missing message yields 400 error without acting (Req 15.7)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    resp = client.post("/chat", json={"sessionid": _SESSION_ID, "user": _USER})
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


def test_chat_invalid_session_yields_401() -> None:
    """An invalid/expired session yields 401 (Req 11)."""
    app = _build_app(
        _maintenance_request_result(), ResolvedResources(), authenticated=False
    )
    client = app.test_client()

    resp = client.post(
        "/chat", json={"message": "hola", "sessionid": _SESSION_ID, "user": _USER}
    )
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_chat_missing_session_yields_401() -> None:
    """A request with no sessionid at all yields 401 (Req 11)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    # A client-claimed user without a session is NOT authenticated.
    resp = client.post("/chat", json={"message": "hola", "user": _USER})
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_chat_ignores_client_userid_uses_verified_identity() -> None:
    """The echoed identity comes from Zabbix's verified session, not the client.

    The client claims a different userid; the maintenance confirmation uses the
    VERIFIED user (42/operator) that Zabbix returned for the session.
    """
    resolved = ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )
    confirmation = MaintenanceConfirmation(
        maintenanceid="777",
        name="100-178306 - backup",
        description="desc",
        user=UserInfo(userid="42", username="operator", name="Op", surname="Erator"),
        resolved=resolved,
    )
    app = _build_app(_maintenance_request_result(), resolved, confirmation)
    client = app.test_client()

    resp = client.post(
        "/create_maintenance",
        json={
            "message": "backup diario",
            "sessionid": _SESSION_ID,
            # Attacker-claimed identity — must be ignored.
            "user": {"userid": "1", "username": "admin"},
            "hosts": ["srv-web01"],
            "recurrence_type": "daily",
            "recurrence": {"start_hour": 2, "duration_hours": 2.0},
        },
    )
    assert resp.status_code == 200
    assert resp.get_json()["user_info"]["userid"] == "42"
    assert resp.get_json()["user_info"]["username"] == "operator"


def test_create_maintenance_returns_confirmation_shape() -> None:
    """/create_maintenance returns the maintenance_created confirmation (Req 11.4)."""
    resolved = ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )
    confirmation = MaintenanceConfirmation(
        maintenanceid="777",
        name="100-178306 - backup",
        description="Ticket: 100-178306\nSolicitado por: Op Erator (operator) [userid: 42]",
        user=UserInfo(userid="42", username="operator", name="Op", surname="Erator"),
        resolved=resolved,
    )
    app = _build_app(_maintenance_request_result(), resolved, confirmation)
    client = app.test_client()

    body = {
        "message": "backup diario",
        "sessionid": _SESSION_ID,
        "user": _USER,
        "hosts": ["srv-web01"],
        "recurrence_type": "daily",
        "recurrence": {"start_hour": 2, "duration_hours": 2.0},
        "ticket": "100-178306",
    }
    resp = client.post("/create_maintenance", json=body)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "maintenance_created"
    assert data["success"] is True
    assert data["maintenance_id"] == "777"
    assert data["name"] == "100-178306 - backup"
    assert data["hosts_affected"] == 1
    assert data["ticket_number"] == "100-178306"
    assert data["user_info"]["userid"] == "42"


def test_create_maintenance_invalid_session_yields_401() -> None:
    """An invalid session cannot create a maintenance (Req 11, 15.7)."""
    app = _build_app(
        _maintenance_request_result(), ResolvedResources(), authenticated=False
    )
    client = app.test_client()

    resp = client.post(
        "/create_maintenance",
        json={
            "sessionid": _SESSION_ID,
            "user": _USER,
            "hosts": ["srv-web01"],
            "recurrence_type": "daily",
        },
    )
    assert resp.status_code == 401


def test_create_maintenance_missing_target_is_400() -> None:
    """No host/group/tag yields 400 without creating (Req 15.7)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    resp = client.post(
        "/create_maintenance",
        json={"sessionid": _SESSION_ID, "user": _USER, "recurrence_type": "daily"},
    )
    assert resp.status_code == 400
    assert resp.get_json()["type"] == "error"


def test_maintenance_templates_shape() -> None:
    """/maintenance/templates returns the legacy templates structure (Req 15.4)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    resp = client.get("/maintenance/templates")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "templates"
    assert set(data["templates"]) == {"daily", "weekly", "monthly"}


def test_maintenance_list_shape() -> None:
    """/maintenance/list returns the legacy maintenance_list shape (Req 15.4).

    The endpoint hits Zabbix, so it requires a valid session carried in the
    query string as ``?sessionid=`` (Req 11); a valid one yields the legacy shape.
    """
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    resp = client.get(f"/maintenance/list?sessionid={_SESSION_ID}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "maintenance_list"
    assert data["total"] == 0


def test_maintenance_list_without_session_yields_401() -> None:
    """/maintenance/list requires a session via ?sessionid= (Req 11)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    resp = client.get("/maintenance/list")
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_maintenance_list_invalid_session_yields_401() -> None:
    """An unknown ?sessionid= is rejected with 401 (Req 11)."""
    app = _build_app(
        _maintenance_request_result(), ResolvedResources(), authenticated=False
    )
    client = app.test_client()

    resp = client.get(f"/maintenance/list?sessionid={_SESSION_ID}")
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


def test_test_routine_valid_weekly() -> None:
    """/test/routine validates a weekly config and decodes it without creating."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    body = {
        "recurrence_type": "weekly",
        "sessionid": _SESSION_ID,
        "user": _USER,
        "recurrence": {
            "days": ["monday", "friday"],
            "start_hour": 1,
            "duration_hours": 2.0,
        },
    }
    resp = client.post("/test/routine", json=body)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["type"] == "test_result"
    assert data["valid"] is True
    assert any("Días" in d for d in data["details"])


def test_test_routine_invalid_reports_error() -> None:
    """/test/routine reports an invalid config without raising (Req 15.7)."""
    app = _build_app(_maintenance_request_result(), ResolvedResources())
    client = app.test_client()

    # weekly with no days -> recurrence engine rejects it.
    body = {
        "recurrence_type": "weekly",
        "sessionid": _SESSION_ID,
        "user": _USER,
        "recurrence": {"start_hour": 1, "duration_hours": 2.0},
    }
    resp = client.post("/test/routine", json=body)
    assert resp.status_code == 200
    assert resp.get_json()["valid"] is False


def test_test_routine_unauthorized_yields_401() -> None:
    """/test/routine requires a valid logged-in Zabbix session (Req 11)."""
    app = _build_app(
        _maintenance_request_result(), ResolvedResources(), authenticated=False
    )
    client = app.test_client()

    body = {
        "recurrence_type": "weekly",
        "sessionid": _SESSION_ID,
        "user": _USER,
        "recurrence": {"days": ["monday"], "start_hour": 1, "duration_hours": 2.0},
    }
    resp = client.post("/test/routine", json=body)
    assert resp.status_code == 401
    assert resp.get_json()["type"] == "error"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
