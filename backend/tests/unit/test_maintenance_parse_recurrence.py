"""Unit tests for ``api.maintenance._parse_recurrence`` (create-side parsing).

Covers the create-time contract: the widget resends the SAME Zabbix-format
``recurrence_config`` object the backend produced in ``/chat`` (keys among
``{start_time, duration, every, dayofweek, day, month}`` where ``start_time`` /
``duration`` are SECONDS and ``dayofweek`` / ``month`` are precomputed bitmasks).
``_parse_recurrence`` must map it into the :class:`ExtractedRecurrence` fields the
recurrence engine consumes so recurring creates no longer fail with
"Falta start_time en la configuración recurrente" (only ``once`` used to work).

Each recurring case asserts end-to-end through
``build_timeperiod(recurrence_config_from(parsed))`` so it proves the actual
create path (the same call the maintenance service makes) no longer raises a
:class:`RecurrenceError`. The ``once`` legacy string path is asserted unchanged.

A round-trip test also feeds the ``recurrence_config`` produced by
``api.chat._recurrence_config_fields`` straight back into ``_parse_recurrence``
so the two contracts stay in lock-step (the whole bug was drift between them),
plus a guard that the ``/chat`` serializer now includes ``duration``.
"""

from __future__ import annotations

from datetime import datetime

from api.chat import _recurrence_config_fields
from api.maintenance import _parse_recurrence
from core.recurrence import build_timeperiod
from services.maintenance_service import recurrence_config_from


def _build(data: dict) -> object:
    """Parse ``data`` and run the exact create-path build the service performs."""
    parsed = _parse_recurrence(data)
    return parsed, build_timeperiod(recurrence_config_from(parsed))


# --------------------------------------------------------------------------- #
# Recurring: Zabbix-format recurrence_config (the resent /chat object)        #
# --------------------------------------------------------------------------- #
def test_daily_recurrence_config_maps_and_builds() -> None:
    """daily: start_time/duration seconds → start_hour/duration_hours; type 2."""
    parsed, tp = _build(
        {
            "recurrence_type": "daily",
            "recurrence_config": {"start_time": 7200, "duration": 3600, "every": 1},
        }
    )

    assert parsed.start_hour == 2
    assert parsed.duration_hours == 1.0
    assert parsed.every == 1

    assert tp.timeperiod_type == 2
    assert tp.start_time == 7200
    assert tp.period == 3600
    assert tp.every == 1


def test_weekly_recurrence_config_builds_with_dayofweek() -> None:
    """weekly: precomputed dayofweek bitmask passes through; type 3, no error."""
    # 17 = Monday (1) + Friday (16).
    parsed, tp = _build(
        {
            "recurrence_type": "weekly",
            "recurrence_config": {
                "start_time": 3600,
                "duration": 7200,
                "dayofweek": 17,
                "every": 1,
            },
        }
    )

    assert parsed.start_hour == 1
    assert parsed.duration_hours == 2.0
    assert parsed.day_bitmask == 17

    assert tp.timeperiod_type == 3
    assert tp.start_time == 3600
    assert tp.period == 7200
    assert tp.dayofweek == 17
    assert tp.every == 1


def test_monthly_by_day_of_month_recurrence_config_builds() -> None:
    """monthly-by-dom: day passes through; type 4 with day == 15."""
    parsed, tp = _build(
        {
            "recurrence_type": "monthly",
            "recurrence_config": {
                "start_time": 10800,
                "duration": 7200,
                "day": 15,
                "every": 1,
                "month": 4095,
            },
        }
    )

    assert parsed.start_hour == 3
    assert parsed.duration_hours == 2.0
    assert parsed.day_of_month == 15

    assert tp.timeperiod_type == 4
    assert tp.start_time == 10800
    assert tp.period == 7200
    assert tp.day == 15
    assert tp.month == 4095


def test_monthly_by_day_of_week_recurrence_config_builds() -> None:
    """monthly-by-dow: dayofweek bitmask passes through; type 4 with dayofweek."""
    parsed, tp = _build(
        {
            "recurrence_type": "monthly",
            "recurrence_config": {
                "start_time": 7200,
                "duration": 3600,
                "dayofweek": 1,
                "every": 1,
                "month": 4095,
            },
        }
    )

    assert parsed.start_hour == 2
    assert parsed.duration_hours == 1.0
    assert parsed.day_bitmask == 1

    assert tp.timeperiod_type == 4
    assert tp.start_time == 7200
    assert tp.period == 3600
    assert tp.dayofweek == 1
    assert tp.month == 4095


def test_start_time_integer_division_is_safe() -> None:
    """A non-whole-hour start_time floors to the hour via integer division."""
    parsed = _parse_recurrence(
        {
            "recurrence_type": "daily",
            "recurrence_config": {"start_time": 9000, "duration": 3600},
        }
    )
    # 9000s = 2h30m → floors to hour 2 (widget always sends whole hours; safe).
    assert parsed.start_hour == 2


def test_intent_format_takes_precedence_over_recurrence_config() -> None:
    """Explicit intent-format recurrence values win; config only fills gaps."""
    parsed = _parse_recurrence(
        {
            "recurrence_type": "daily",
            "recurrence": {"start_hour": 5, "duration_hours": 3.0, "every": 2},
            "recurrence_config": {"start_time": 7200, "duration": 3600, "every": 1},
        }
    )
    assert parsed.start_hour == 5
    assert parsed.duration_hours == 3.0
    assert parsed.every == 2


# --------------------------------------------------------------------------- #
# once: legacy string path stays unchanged                                    #
# --------------------------------------------------------------------------- #
def test_once_legacy_string_path_unchanged() -> None:
    """once: legacy start_time/end_time strings → start_ts/end_ts epochs; type 0."""
    parsed, tp = _build(
        {
            "recurrence_type": "once",
            "start_time": "2025-01-15 02:00",
            "end_time": "2025-01-15 04:00",
        }
    )

    expected_start = int(datetime(2025, 1, 15, 2, 0).timestamp())
    expected_end = int(datetime(2025, 1, 15, 4, 0).timestamp())
    assert parsed.start_ts == expected_start
    assert parsed.end_ts == expected_end
    # once never reads recurrence_config; no bitmasks leaked in.
    assert parsed.day_bitmask is None
    assert parsed.month_bitmask is None

    assert tp.timeperiod_type == 0
    assert tp.period == expected_end - expected_start


# --------------------------------------------------------------------------- #
# Contract lock-step: /chat serializer ↔ create-side parser                   #
# --------------------------------------------------------------------------- #
def test_recurrence_config_fields_includes_duration() -> None:
    """The /chat serializer now emits ``duration`` (seconds) for the round-trip."""
    parsed = _parse_recurrence(
        {
            "recurrence_type": "daily",
            "recurrence_config": {"start_time": 7200, "duration": 3600, "every": 1},
        }
    )
    tp = build_timeperiod(recurrence_config_from(parsed))
    fields = _recurrence_config_fields(tp)

    assert fields["duration"] == 3600
    assert fields["start_time"] == 7200


def test_chat_config_round_trips_through_create_parser() -> None:
    """Feeding the /chat recurrence_config back into create rebuilds the same tp.

    Guards against the exact contract drift that caused the bug: the serializer
    (:func:`api.chat._recurrence_config_fields`) and the parser
    (:func:`api.maintenance._parse_recurrence`) must agree on the wire keys.
    """
    # Build a weekly tp the way /chat does, serialize it, then resend it.
    seed = _parse_recurrence(
        {
            "recurrence_type": "weekly",
            "recurrence_config": {
                "start_time": 3600,
                "duration": 7200,
                "dayofweek": 17,
                "every": 1,
            },
        }
    )
    tp_from_chat = build_timeperiod(recurrence_config_from(seed))
    resent_config = _recurrence_config_fields(tp_from_chat)

    # The widget resends exactly this object under recurrence_config.
    parsed, tp = _build(
        {"recurrence_type": "weekly", "recurrence_config": resent_config}
    )

    assert tp.timeperiod_type == 3
    assert tp.start_time == tp_from_chat.start_time
    assert tp.period == tp_from_chat.period
    assert tp.dayofweek == tp_from_chat.dayofweek
    assert tp.every == tp_from_chat.every
