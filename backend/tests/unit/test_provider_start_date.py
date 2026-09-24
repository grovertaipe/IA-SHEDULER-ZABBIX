"""Parser tests for the ``once`` ``start_date`` field (Req 3.2).

:func:`ai.provider.parse_extracted_request` reads a structured ``start_date``
(ISO ``YYYY-MM-DD`` string or null) from the recurrence sub-object and sets it
on :class:`core.domain.ExtractedRecurrence`, while still reading ``start_ts`` /
``end_ts`` as before. No bitmask arithmetic, no network.
"""

from __future__ import annotations

import pytest

from ai.provider import parse_extracted_request
from core.domain import RecurrenceType


def test_start_date_parsed_from_nested_recurrence() -> None:
    data = {
        "intent": "maintenance_request",
        "groups": ["Applications"],
        "recurrence": {
            "recurrence_type": "once",
            "start_hour": 22,
            "duration_hours": 1,
            "start_date": "2026-01-02",
            "start_ts": None,
            "end_ts": None,
        },
    }
    req = parse_extracted_request(data, "mensaje original")
    assert req.recurrence is not None
    assert req.recurrence.recurrence_type == RecurrenceType.ONCE
    assert req.recurrence.start_date == "2026-01-02"
    assert req.recurrence.start_hour == 22
    assert req.recurrence.duration_hours == 1.0
    assert req.recurrence.start_ts is None
    assert req.recurrence.end_ts is None


def test_start_date_null_yields_none() -> None:
    data = {
        "intent": "maintenance_request",
        "recurrence": {"recurrence_type": "once", "start_date": None},
    }
    req = parse_extracted_request(data, "x")
    assert req.recurrence is not None
    assert req.recurrence.start_date is None


def test_start_date_absent_yields_none() -> None:
    data = {
        "intent": "maintenance_request",
        "recurrence": {"recurrence_type": "daily", "start_hour": 2, "duration_hours": 2},
    }
    req = parse_extracted_request(data, "x")
    assert req.recurrence is not None
    assert req.recurrence.start_date is None


def test_start_date_blank_string_yields_none() -> None:
    data = {
        "intent": "maintenance_request",
        "recurrence": {"recurrence_type": "once", "start_date": "   "},
    }
    req = parse_extracted_request(data, "x")
    assert req.recurrence is not None
    assert req.recurrence.start_date is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
