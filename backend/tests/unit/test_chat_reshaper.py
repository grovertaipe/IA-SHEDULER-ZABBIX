"""Unit tests for the ``/chat`` response reshaper (api/chat.py).

Focus on the ``maintenance_request`` shaping path that derives the confirmation
preview fields the widget consumes (Req 14.6, 15.3). Every maintenance type
carries the top-level ``start_time`` / ``end_time`` display strings
(``"%Y-%m-%d %H:%M"``) the widget renders as the "Period" — these are the
maintenance ACTIVE WINDOW (Zabbix ``active_since`` / ``active_till``), exactly
as the legacy v1 monolith emitted them for every type. Recurring types
ADDITIONALLY carry a ``recurrence_config`` block with the schedule detail;
``once`` carries NO ``recurrence_config``.

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
from services.maintenance_service import (
    ResolvedResources,
    active_window,
    recurrence_config_from,
)

_FMT = "%Y-%m-%d %H:%M"


def _expected_window(rec: ExtractedRecurrence) -> tuple[str, str]:
    """Compute the expected top-level display window via the engine.

    Mirrors the reshaper exactly: build the ``TimePeriod`` once, derive the
    active window and format both epochs as local ``"%Y-%m-%d %H:%M"`` strings.
    Kept engine-derived (never hard-coded) so the test stays in lock-step with
    :func:`active_window` / :func:`build_timeperiod`.
    """
    tp = build_timeperiod(recurrence_config_from(rec))
    start_ts, end_ts = active_window(rec, tp)
    return (
        datetime.fromtimestamp(start_ts).strftime(_FMT),
        datetime.fromtimestamp(end_ts).strftime(_FMT),
    )


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

    The strings must match the LOCAL active window the recurrence engine
    computes from the same inputs, formatted as ``"%Y-%m-%d %H:%M"`` (Req 14.6,
    3.2). The reshaper now unifies on the ``active_window`` path for every type;
    for ``once`` that window equals ``(start_date, start_date + period)`` — the
    same window the legacy direct ``once_window_from_date`` formula produced,
    modulo the engine's minute-flooring. Both are asserted here to prove the
    once value did not shift.
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2025-03-15",
        start_hour=2,
        duration_hours=3.0,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "once"
    # The unified active-window path (what the reshaper uses).
    expected_start, expected_end = _expected_window(rec)
    assert data["start_time"] == expected_start
    assert data["end_time"] == expected_end
    # And it still equals the legacy direct once formula (window unchanged).
    once_start, once_end = once_window_from_date("2025-03-15", 2, 3.0)
    assert data["start_time"] == datetime.fromtimestamp(once_start).strftime(_FMT)
    assert data["end_time"] == datetime.fromtimestamp(once_end).strftime(_FMT)


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


# Fixed active-window bounds for the recurring tests. ``active_window`` uses
# ``int(time.time())`` when a recurring request carries no ``start_ts``, so the
# fixtures below set explicit epochs to keep the formatted window deterministic
# WITHOUT freezing global time.
_WIN_START_TS = int(datetime(2025, 3, 1, 0, 0, 0).timestamp())
_WIN_END_TS = int(datetime(2025, 12, 31, 23, 59, 0).timestamp())


def test_recurring_weekly_has_display_window_and_config() -> None:
    """A recurring (weekly) request → top-level active window + ``recurrence_config``.

    The top-level ``start_time``/``end_time`` are the maintenance ACTIVE WINDOW
    (Zabbix ``active_since``/``active_till``) the widget renders as the "Period"
    (Req 14.6) — present for every type, exactly like the legacy v1 monolith.
    The weekly schedule detail (``dayofweek`` bitmask, ``every``, seconds-from-
    midnight ``start_time``) additionally lives inside ``recurrence_config``.
    Expected values are engine-derived, never hard-coded.
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.WEEKLY,
        days={"monday", "friday"},
        start_hour=1,
        duration_hours=2.0,
        start_ts=_WIN_START_TS,
        end_ts=_WIN_END_TS,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "weekly"
    # Top-level active window IS present for recurring types now.
    expected_start, expected_end = _expected_window(rec)
    assert data["start_time"] == expected_start
    assert data["end_time"] == expected_end
    # The schedule detail additionally lives inside recurrence_config.
    config = data["recurrence_config"]
    assert config["dayofweek"] == tp.dayofweek
    assert config["every"] == tp.every
    assert config["start_time"] == tp.start_time


def test_recurring_daily_has_display_window_and_config() -> None:
    """A recurring (daily) request → top-level active window + ``recurrence_config``.

    Expected values are computed via the engine so the test stays in lock-step
    with :func:`build_timeperiod` / :func:`active_window` rather than hard-coding
    derived fields.
    """
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.DAILY,
        every=1,
        start_hour=2,
        duration_hours=1.0,
        start_ts=_WIN_START_TS,
        end_ts=_WIN_END_TS,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "daily"
    expected_start, expected_end = _expected_window(rec)
    assert data["start_time"] == expected_start
    assert data["end_time"] == expected_end
    config = data["recurrence_config"]
    assert config["every"] == tp.every
    assert config["start_time"] == tp.start_time


def test_recurring_monthly_by_day_of_month_has_display_window_and_config() -> None:
    """A monthly-by-day-of-month request → top-level active window + ``recurrence_config``."""
    rec = ExtractedRecurrence(
        recurrence_type=RecurrenceType.MONTHLY,
        day_of_month=15,
        start_hour=3,
        duration_hours=2.0,
        start_ts=_WIN_START_TS,
        end_ts=_WIN_END_TS,
    )
    app = _build_app(_maintenance_result(rec), _resolved_one_host())
    data = _post_chat(app)

    tp = build_timeperiod(recurrence_config_from(rec))
    assert data["type"] == "maintenance_request"
    assert data["recurrence_type"] == "monthly"
    expected_start, expected_end = _expected_window(rec)
    assert data["start_time"] == expected_start
    assert data["end_time"] == expected_end
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
