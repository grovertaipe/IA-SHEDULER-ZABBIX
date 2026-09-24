"""Unit tests for the ``/chat`` response reshaper (api/chat.py).

Focus on the ``maintenance_request`` shaping path that derives the confirmation
preview fields the widget consumes (Req 14.6, 15.3). Specifically: for a
one-time (``once``) maintenance the response must carry the ``start_time`` /
``end_time`` display strings (``"%Y-%m-%d %H:%M"``) the widget renders as the
period, while recurring types must NOT carry them (the widget renders those
from ``recurrence_config``).

Design principle "AI extrae, backend calcula" (Req 3.2): the AI only supplies
the structured recurrence; the backend derives the display strings here
deterministically. These tests mock the AI boundary (fake ChatService) and the
Zabbix boundary (fake client + fake maintenance service) exactly like the
integration suite, so the real blueprint shaping runs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from flask import Flask

from api.chat import make_chat_blueprint
from core.domain import ExtractedRecurrence, ExtractedRequest, RecurrenceType
from core.recurrence import build_timeperiod, once_window_from_date
from services.chat_service import ChatResult
from services.maintenance_service import ResolvedResources, recurrence_config_from


# --------------------------------------------------------------------------- #
# Fakes (mirror tests/integration/test_chat_maintenance_blueprints.py)        #
# --------------------------------------------------------------------------- #
class FakeClient:
    """Minimal fake ZabbixClient: only ``user_exists`` is used by the auth edge."""

    def __init__(self, known_users: set[str]) -> None:
        self._known = known_users

    def user_exists(self, userid: str) -> bool:
        return userid in self._known


class FakeChatService:
    """Fake ChatService returning a preset :class:`ChatResult`."""

    def __init__(self, result: ChatResult) -> None:
        self._result = result

    def interpret(self, message: str, *, locale: str = "es", **_: Any) -> ChatResult:
        self._result.raw_message = message
        self._result.locale = locale
        return self._result


class FakeMaintenanceService:
    """Fake MaintenanceService returning a canned resolution."""

    def __init__(self, resolved: ResolvedResources) -> None:
        self._resolved = resolved

    def resolve_resources(self, **_: Any) -> ResolvedResources:
        return self._resolved


class FakeConfig:
    """Minimal AppConfig stand-in for locale resolution."""

    supported_locales = ["es", "en"]
    default_locale = "es"
    version = "test"
    ai_provider = "gemini"


_USER = {"userid": "42", "username": "operator", "name": "Op", "surname": "Erator"}


def _resolved_one_host() -> ResolvedResources:
    return ResolvedResources(
        hosts=[{"hostid": "1", "host": "srv-web01", "name": "srv-web01"}],
        host_ids=["1"],
    )


def _build_app(chat_result: ChatResult, resolved: ResolvedResources) -> Flask:
    client = FakeClient({"42"})
    chat_service = FakeChatService(chat_result)
    maint_service = FakeMaintenanceService(resolved)
    config = FakeConfig()

    app = Flask(__name__)
    app.register_blueprint(
        make_chat_blueprint(chat_service, maint_service, client, config)  # type: ignore[arg-type]
    )
    return app


def _maintenance_result(rec: ExtractedRecurrence) -> ChatResult:
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
    )


def _post_chat(app: Flask) -> dict[str, Any]:
    client = app.test_client()
    resp = client.post("/chat", json={"message": "mantenimiento", "user": _USER})
    assert resp.status_code == 200
    return resp.get_json()


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #
def test_once_from_structured_date_sets_display_window() -> None:
    """A ``once`` request from start_date+hour+duration → start_time/end_time.

    The strings must match the LOCAL window the recurrence engine computes from
    the same inputs, formatted as ``"%Y-%m-%d %H:%M"`` (Req 14.6, 3.2).
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2025-03-15",
        start_hour=2,
        duration_hours=3.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    start_ts, end_ts = once_window_from_date("2025-03-15", 2, 3.0)
    fmt = "%Y-%m-%d %H:%M"
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "once"
    assert data["start_time"] == datetime.fromtimestamp(start_ts).strftime(fmt)
    assert data["end_time"] == datetime.fromtimestamp(end_ts).strftime(fmt)


def test_once_from_explicit_epochs_uses_those() -> None:
    """A ``once`` request with explicit start_ts/end_ts → response uses those."""
    start_ts = int(datetime(2025, 6, 1, 8, 0, 0).timestamp())
    end_ts = int(datetime(2025, 6, 1, 10, 0, 0).timestamp())
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.ONCE,
        start_ts=start_ts,
        end_ts=end_ts,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    assert data["recurrence_type"] == "once"
    assert data["start_time"] == "2025-06-01 08:00"
    assert data["end_time"] == "2025-06-01 10:00"


def test_recurring_weekly_has_no_display_window() -> None:
    """A recurring (weekly) request → no top-level window; ``recurrence_config`` set.

    The widget renders recurring periods from ``recurrence_config`` (Req 14.6),
    so the reshaper must NOT add the once-only display strings at the top level;
    instead it emits ``recurrence_config`` with the engine-computed ``dayofweek``
    bitmask, ``every`` and ``start_time`` (seconds from midnight).
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.WEEKLY,
        days={"monday", "friday"},
        start_hour=1,
        duration_hours=2.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "weekly"
    # Top-level once-only display strings must remain absent.
    assert "start_time" not in data
    assert "end_time" not in data
    # The schedule now lives inside recurrence_config (a different key).
    config = data["recurrence_config"]
    assert config["dayofweek"] == tp.dayofweek
    assert config["every"] == tp.every
    assert config["start_time"] == tp.start_time


def test_recurring_daily_sets_recurrence_config() -> None:
    """A recurring (daily) request → ``recurrence_config`` with every + start_time.

    Expected values are computed via the engine so the test stays in lock-step
    with :func:`build_timeperiod` rather than hard-coding derived fields.
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.DAILY,
        every=1,
        start_hour=2,
        duration_hours=1.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "daily"
    assert "start_time" not in data
    assert "end_time" not in data
    config = data["recurrence_config"]
    assert config["every"] == tp.every
    assert config["start_time"] == tp.start_time


def test_recurring_monthly_by_day_of_month_sets_recurrence_config() -> None:
    """A monthly-by-day-of-month request → ``recurrence_config`` with day + start_time."""
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.MONTHLY,
        day_of_month=15,
        start_hour=3,
        duration_hours=2.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "monthly"
    assert "start_time" not in data
    assert "end_time" not in data
    config = data["recurrence_config"]
    assert config["day"] == tp.day
    assert config["start_time"] == tp.start_time


def test_once_has_no_recurrence_config() -> None:
    """A ``once`` request → top-level start_time/end_time and NO recurrence_config."""
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2025-03-15",
        start_hour=2,
        duration_hours=3.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    assert data["recurrence_type"] == "once"
    assert "start_time" in data
    assert "end_time" in data
    assert "recurrence_config" not in data


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
