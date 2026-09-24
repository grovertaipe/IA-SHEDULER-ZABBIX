"""Schema tests for the optional ``assistant_message`` field (Req 29).

A response validates against :data:`ai.schema.EXTRACTED_REQUEST_SCHEMA` both WITH
and WITHOUT ``assistant_message`` (it is optional; only ``intent`` is required),
and a non-string ``assistant_message`` is rejected.
"""

from __future__ import annotations

import pytest

from ai.schema import validate_against_schema


def test_validates_without_assistant_message() -> None:
    ok, fields = validate_against_schema({"intent": "help"})
    assert ok is True
    assert fields == []


def test_validates_with_assistant_message() -> None:
    ok, fields = validate_against_schema(
        {"intent": "help", "assistant_message": "Hola, ¿qué necesitas?"}
    )
    assert ok is True
    assert fields == []


def test_assistant_message_must_be_string() -> None:
    ok, fields = validate_against_schema(
        {"intent": "help", "assistant_message": 123}
    )
    assert ok is False
    assert "assistant_message" in fields


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
