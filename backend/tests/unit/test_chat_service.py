"""Tests for :class:`services.chat_service.ChatService` assistant_message flow.

Focus: the service prefers the AI's same-language ``assistant_message`` for the
conversational reply, falls back to the localized i18n catalog when it is empty,
and keeps the catalog ``error.ai_unavailable`` message (browser locale) on the
provider-unavailable fallback path. No real AI/network calls: a tiny in-memory
fake provider returns preset :class:`ExtractedRequest` values.
"""

from __future__ import annotations

from datetime import date

import pytest

from ai.provider import AIProvider, AIProviderError
from core.domain import (
    ConversationTurn,
    ExtractedRecurrence,
    ExtractedRequest,
    PromptContext,
    RecurrenceType,
)
from i18n.messages import get_message
from services.chat_service import (
    INTENT_CLARIFICATION,
    INTENT_HELP,
    INTENT_MAINTENANCE,
    INTENT_OFF_TOPIC,
    INTENT_UNAVAILABLE,
    ChatService,
)

_BASE = date(2024, 1, 1)


class _FakeProvider(AIProvider):
    """Returns a preset ExtractedRequest, or raises AIProviderError.

    Records the ``history`` it received on the last :meth:`extract` call so
    tests can assert the service forwards the conversation history.
    """

    def __init__(
        self, result: ExtractedRequest | None, *, raise_error: bool = False
    ) -> None:
        self._result = result
        self._raise = raise_error
        self.received_history: list[ConversationTurn] | None = None
        self.history_calls: list[list[ConversationTurn] | None] = []

    def extract(
        self,
        message: str,
        ctx: PromptContext,
        history: list[ConversationTurn] | None = None,
    ) -> ExtractedRequest:
        self.received_history = history
        self.history_calls.append(history)
        if self._raise:
            raise AIProviderError("unavailable")
        assert self._result is not None
        return self._result

    def is_available(self) -> bool:
        return not self._raise


class _FakeConfig:
    """Minimal config exposing the locale-resolution attributes only."""

    supported_locales = ["es", "en", "pt"]
    default_locale = "es"


def _service(result: ExtractedRequest | None, *, raise_error: bool = False) -> ChatService:
    # A config supporting es/en/pt so requested locales resolve as-is (otherwise
    # an unsupported locale degrades to the default and the catalog text differs).
    return ChatService(
        _FakeProvider(result, raise_error=raise_error),
        _FakeConfig(),  # type: ignore[arg-type]
    )


def _complete_maintenance(assistant_message: str = "") -> ExtractedRequest:
    return ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.DAILY,
            start_hour=2,
            duration_hours=2.0,
        ),
        assistant_message=assistant_message,
    )


# --------------------------------------------------------------------------- #
# AI assistant_message preferred                                              #
# --------------------------------------------------------------------------- #
def test_help_uses_ai_assistant_message() -> None:
    ai_text = "Hola, ¿qué mantenimiento quieres crear?"
    svc = _service(ExtractedRequest(intent="help", assistant_message=ai_text))
    result = svc.interpret("hola", locale="es", base_date=_BASE)
    assert result.intent == INTENT_HELP
    assert result.message == ai_text


def test_off_topic_uses_ai_assistant_message() -> None:
    ai_text = "I only help with Zabbix maintenance windows."
    svc = _service(ExtractedRequest(intent="off_topic", assistant_message=ai_text))
    result = svc.interpret("weather?", locale="en", base_date=_BASE)
    assert result.intent == INTENT_OFF_TOPIC
    assert result.message == ai_text


def test_maintenance_ready_uses_ai_assistant_message() -> None:
    ai_text = "Listo, preparé el mantenimiento diario para web01."
    svc = _service(_complete_maintenance(ai_text))
    result = svc.interpret("backup diario web01 2-4am", locale="es", base_date=_BASE)
    assert result.intent == INTENT_MAINTENANCE
    assert result.message == ai_text
    assert result.request is not None


def test_clarification_uses_ai_assistant_message() -> None:
    ai_text = "¿Sobre qué hosts aplico el mantenimiento?"
    # maintenance intent but no target -> clarification path with AI text.
    req = ExtractedRequest(
        intent="maintenance_request",
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.DAILY,
            start_hour=2,
            duration_hours=2.0,
        ),
        assistant_message=ai_text,
    )
    svc = _service(req)
    result = svc.interpret("mantenimiento diario 2-4am", locale="es", base_date=_BASE)
    assert result.intent == INTENT_CLARIFICATION
    assert result.message == ai_text
    assert result.missing_fields  # target still reported as missing


# --------------------------------------------------------------------------- #
# Catalog fallback when assistant_message is empty                            #
# --------------------------------------------------------------------------- #
def test_help_falls_back_to_catalog_when_empty() -> None:
    svc = _service(ExtractedRequest(intent="help", assistant_message=""))
    result = svc.interpret("hola", locale="es", base_date=_BASE)
    assert result.message == get_message("conversational.help", "es")


def test_maintenance_ready_falls_back_to_catalog_when_empty() -> None:
    svc = _service(_complete_maintenance(""))
    result = svc.interpret("backup diario web01 2-4am", locale="en", base_date=_BASE)
    assert result.message == get_message("conversational.maintenance_ready", "en")


def test_clarification_falls_back_to_catalog_when_empty() -> None:
    req = ExtractedRequest(
        intent="maintenance_request",
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.DAILY,
            start_hour=2,
            duration_hours=2.0,
        ),
        assistant_message="",
    )
    svc = _service(req)
    result = svc.interpret("mantenimiento diario 2-4am", locale="es", base_date=_BASE)
    assert result.intent == INTENT_CLARIFICATION
    assert result.message == get_message("conversational.clarification", "es")


# --------------------------------------------------------------------------- #
# Unavailable fallback path stays templated (catalog, browser locale)         #
# --------------------------------------------------------------------------- #
def test_provider_error_uses_catalog_ai_unavailable_in_browser_locale() -> None:
    svc = _service(None, raise_error=True)
    result = svc.interpret("hola", locale="en", base_date=_BASE)
    assert result.intent == INTENT_UNAVAILABLE
    assert result.message == get_message("error.ai_unavailable", "en")


# --------------------------------------------------------------------------- #
# once completeness via structured start_date (Req 3.2 — AI extracts, backend  #
# computes). "mañana 22:00-23:00" -> start_date + start_hour + duration is a    #
# COMPLETE once request (maintenance_request, no missing fields).               #
# --------------------------------------------------------------------------- #
def test_once_with_structured_date_is_complete() -> None:
    req = ExtractedRequest(
        intent="maintenance_request",
        groups=["Applications"],
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.ONCE,
            start_date="2026-01-02",
            start_hour=22,
            duration_hours=1.0,
        ),
        assistant_message="Listo para revisar.",
    )
    svc = _service(req)
    result = svc.interpret(
        "mantenimiento para el grupo Applications mañana de 22:00 a 23:00",
        locale="es",
        base_date=_BASE,
    )
    assert result.intent == INTENT_MAINTENANCE
    assert result.missing_fields == []
    assert result.request is not None


def test_once_with_explicit_epochs_is_complete() -> None:
    req = ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.ONCE,
            start_ts=1_700_000_000,
            end_ts=1_700_003_600,
        ),
    )
    svc = _service(req)
    result = svc.interpret("web01 once", locale="es", base_date=_BASE)
    assert result.intent == INTENT_MAINTENANCE
    assert result.missing_fields == []


def test_once_without_any_timing_degrades_to_clarification() -> None:
    req = ExtractedRequest(
        intent="maintenance_request",
        groups=["Applications"],
        recurrence=ExtractedRecurrence(recurrence_type=RecurrenceType.ONCE),
    )
    svc = _service(req)
    result = svc.interpret(
        "mantenimiento para el grupo Applications una vez",
        locale="es",
        base_date=_BASE,
    )
    assert result.intent == INTENT_CLARIFICATION
    # Sensible structured missing-field names (not the epoch names).
    assert "start_date" in result.missing_fields
    assert "start_hour" in result.missing_fields
    assert "duration" in result.missing_fields


# --------------------------------------------------------------------------- #
# History forwarding: ChatService passes the conversation history to the       #
# provider so extraction accumulates fields across turns (backend stateless).  #
# --------------------------------------------------------------------------- #
def test_interpret_forwards_history_to_provider() -> None:
    provider = _FakeProvider(_complete_maintenance("listo"))
    svc = ChatService(provider, _FakeConfig())  # type: ignore[arg-type]

    history = [
        ConversationTurn(role="user", content="mantenimiento para web01"),
        ConversationTurn(role="assistant", content="¿A qué hora?"),
    ]
    svc.interpret("de 2 a 4am", locale="es", base_date=_BASE, history=history)

    assert provider.received_history is history
    assert provider.received_history is not None
    assert [t.role for t in provider.received_history] == ["user", "assistant"]


def test_interpret_without_history_passes_none() -> None:
    provider = _FakeProvider(_complete_maintenance("listo"))
    svc = ChatService(provider, _FakeConfig())  # type: ignore[arg-type]

    svc.interpret("backup diario web01 2-4am", locale="es", base_date=_BASE)

    assert provider.received_history is None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
