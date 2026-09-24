"""Tests for the structured ``once`` window in :mod:`core.recurrence`.

Focus: the ``once`` resolution order in :func:`core.recurrence.build_timeperiod`
(via :func:`_build_once`) — a structured ISO ``start_date`` + ``start_hour`` +
``duration_hours`` is converted to the correct local epoch window by the backend
("AI extrae, backend calcula", Req 3.2), explicit ``start_ts`` / ``end_ts`` keep
working, a malformed ``start_date`` raises, and missing all ``once`` data raises.
No I/O, no network.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from core.domain import RecurrenceConfig, RecurrenceError, RecurrenceType
from core.recurrence import build_timeperiod, once_window_from_date


def _floor_minute(seconds: int) -> int:
    return seconds - seconds % 60


def test_once_from_structured_date_computes_local_epoch() -> None:
    cfg = RecurrenceConfig(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2026-06-15",
        start_hour=22,
        duration_hours=1,
    )
    tp = build_timeperiod(cfg)

    expected_start = int(datetime(2026, 6, 15, 22, 0, 0).timestamp())
    assert tp.timeperiod_type == 0
    assert tp.period == 3600
    assert tp.start_date == _floor_minute(expected_start)


def test_once_window_from_date_helper() -> None:
    start_ts, end_ts = once_window_from_date("2026-06-15", 22, 1)
    expected_start = int(datetime(2026, 6, 15, 22, 0, 0).timestamp())
    assert start_ts == expected_start
    assert end_ts == expected_start + 3600


def test_once_explicit_epochs_still_work() -> None:
    start = int(datetime(2026, 1, 2, 10, 0, 0).timestamp())
    end = start + 7200
    cfg = RecurrenceConfig(
        recurrence_type=RecurrenceType.ONCE,
        start_ts=start,
        end_ts=end,
    )
    tp = build_timeperiod(cfg)
    assert tp.timeperiod_type == 0
    assert tp.period == 7200
    assert tp.start_date == _floor_minute(start)


def test_once_explicit_epochs_take_precedence_over_structured_date() -> None:
    # When both are present, the explicit epochs win (unchanged legacy path).
    start = int(datetime(2026, 3, 1, 8, 0, 0).timestamp())
    end = start + 3600
    cfg = RecurrenceConfig(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2099-12-31",
        start_hour=5,
        duration_hours=9,
        start_ts=start,
        end_ts=end,
    )
    tp = build_timeperiod(cfg)
    assert tp.period == 3600
    assert tp.start_date == _floor_minute(start)


def test_once_malformed_start_date_raises() -> None:
    cfg = RecurrenceConfig(
        recurrence_type=RecurrenceType.ONCE,
        start_date="15/06/2026",
        start_hour=22,
        duration_hours=1,
    )
    with pytest.raises(RecurrenceError) as exc:
        build_timeperiod(cfg)
    assert exc.value.field == "start_date"


def test_once_missing_everything_raises() -> None:
    cfg = RecurrenceConfig(recurrence_type=RecurrenceType.ONCE)
    with pytest.raises(RecurrenceError) as exc:
        build_timeperiod(cfg)
    assert exc.value.field in {"start_ts", "end_ts"}


def test_once_structured_missing_hour_raises() -> None:
    # start_date present but no hour/duration -> falls through to missing error.
    cfg = RecurrenceConfig(
        recurrence_type=RecurrenceType.ONCE,
        start_date="2026-06-15",
    )
    with pytest.raises(RecurrenceError):
        build_timeperiod(cfg)


def test_once_from_date_invalid_hour_raises() -> None:
    with pytest.raises(RecurrenceError) as exc:
        once_window_from_date("2026-06-15", 24, 1)
    assert exc.value.field == "start_hour"


def test_once_from_date_invalid_duration_raises() -> None:
    with pytest.raises(RecurrenceError) as exc:
        once_window_from_date("2026-06-15", 22, 0)
    assert exc.value.field == "duration_hours"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
