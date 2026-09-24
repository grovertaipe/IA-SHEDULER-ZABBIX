"""Schema tests for the optional ``once`` ``start_date`` field (Req 29, 3.2).

A recurrence object validates against :data:`ai.schema.EXTRACTED_REQUEST_SCHEMA`
with ``start_date`` as a string OR null (both accepted), and a non-string /
non-null ``start_date`` is rejected on that field's path.
"""

from __future__ import annotations

import pytest

from ai.schema import validate_against_schema


def test_recurrence_with_start_date_string_validates() -> None:
    ok, fields = validate_against_schema(
        {
            "intent": "maintenance_request",
            "recurrence": {
                "recurrence_type": "once",
                "start_date": "2026-06-15",
                "start_hour": 22,
                "duration_hours": 1,
            },
        }
    )
    assert ok is True
    assert fields == []


def test_recurrence_with_start_date_null_validates() -> None:
    ok, fields = validate_against_schema(
        {
            "intent": "maintenance_request",
            "recurrence": {"recurrence_type": "once", "start_date": None},
        }
    )
    assert ok is True
    assert fields == []


def test_recurrence_with_non_string_start_date_rejected() -> None:
    ok, fields = validate_against_schema(
        {
            "intent": "maintenance_request",
            "recurrence": {"recurrence_type": "once", "start_date": 20260615},
        }
    )
    assert ok is False
    assert any("start_date" in f for f in fields)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
