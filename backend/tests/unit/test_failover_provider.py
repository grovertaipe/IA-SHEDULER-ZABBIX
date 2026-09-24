"""Unit tests for :class:`ai.failover.FailoverAIProvider` and ``ai.factory`` (Task 21.3).

Covers the orchestration behaviour required by Req 26 / 29 with fake providers:

* (a) primary fails, secondary ok  -> secondary is used;
* (b) both fail                     -> localized unavailability, no raw leak;
* (c) primary returns schema-invalid responses repeatedly -> retries then errors
      WITHOUT invoking ``build_timeperiod`` (Req 29.2, 29.3);
* failover events are recorded through a fake :class:`SecureLogger`-like sink.

The tests use fakes (no network, no SDKs) so they validate real orchestration
logic rather than mocked internals.
"""

from __future__ import annotations

import pytest

from ai import factory, failover  # noqa: F401  (import smoke: `from ai import failover, factory`)
from ai.failover import FailoverAIProvider, select_provider
from ai.provider import AIProvider, AIProviderError
from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    PromptContext,
    RecurrenceType,
)

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")


# --------------------------------------------------------------------------- #
# Test doubles                                                                #
# --------------------------------------------------------------------------- #
class RecordingLogger:
    """Minimal SecureLogger-compatible sink that records events (no secrets)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def info(self, event: str, **fields: object) -> None:
        self.events.append(("info", event, dict(fields)))

    def error(self, event: str, **fields: object) -> None:
        self.events.append(("error", event, dict(fields)))

    def event_names(self) -> list[str]:
        return [name for _, name, _ in self.events]


class FakeProvider(AIProvider):
    """Configurable fake provider driving the failover orchestration paths."""

    def __init__(
        self,
        *,
        available: bool = True,
        result: ExtractedRequest | None = None,
        error: bool = False,
    ) -> None:
        self._available = available
        self._result = result
        self._error = error
        self.calls = 0

    def is_available(self) -> bool:
        return self._available

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        self.calls += 1
        if self._error or self._result is None:
            raise AIProviderError("fake provider failure")
        return self._result


def _valid_request(message: str = "hi") -> ExtractedRequest:
    """A schema-valid ExtractedRequest (intent present, recurrence enum valid)."""
    return ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.DAILY,
            start_hour=22,
            duration_hours=1.0,
        ),
        raw_message=message,
    )


class SchemaInvalidProvider(AIProvider):
    """Provider that returns a structurally-broken ExtractedRequest.

    Sets ``intent`` to a non-string (via object.__setattr__ to bypass the type
    hint) so ``validate_against_schema`` reports the ``intent`` field as
    offending — driving the schema-retry-then-error path (Req 29.2, 29.3).
    """

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        self.calls += 1
        req = _valid_request(message)
        # Break the required 'intent' field's type so schema validation fails.
        object.__setattr__(req, "intent", 123)
        return req


# --------------------------------------------------------------------------- #
# select_provider sanity (unchanged pure function still importable)           #
# --------------------------------------------------------------------------- #
def test_select_provider_table() -> None:
    assert select_provider(True, True, True) == "primary"
    assert select_provider(True, False, False) == "primary"
    assert select_provider(False, True, True) == "secondary"
    assert select_provider(False, True, False) == "unavailable"
    assert select_provider(False, False, False) == "unavailable"


# --------------------------------------------------------------------------- #
# (a) primary fails, secondary ok -> secondary used                           #
# --------------------------------------------------------------------------- #
def test_primary_fails_secondary_used() -> None:
    expected = _valid_request()
    primary = FakeProvider(available=True, error=True)
    secondary = FakeProvider(available=True, result=expected)
    logger = RecordingLogger()

    fp = FailoverAIProvider(
        primary=primary,
        secondary=secondary,
        max_retries=1,
        timeout_s=30.0,
        schema_max_attempts=2,
        logger=logger,  # type: ignore[arg-type]
    )

    result = fp.extract("do maintenance", CTX)

    assert result is expected
    assert primary.calls >= 1  # primary was attempted (with retries)
    assert secondary.calls == 1  # secondary served the request
    assert "ai_failover_switch" in logger.event_names()


def test_primary_unavailable_secondary_used() -> None:
    expected = _valid_request()
    primary = FakeProvider(available=False)
    secondary = FakeProvider(available=True, result=expected)
    logger = RecordingLogger()

    fp = FailoverAIProvider(
        primary=primary, secondary=secondary, logger=logger  # type: ignore[arg-type]
    )

    result = fp.extract("do maintenance", CTX)

    assert result is expected
    assert primary.calls == 0  # unavailable primary is never called
    assert secondary.calls == 1


# --------------------------------------------------------------------------- #
# (b) both fail -> unavailable/degraded, no raw exception leaks               #
# --------------------------------------------------------------------------- #
def test_both_fail_degrades_localized() -> None:
    primary = FakeProvider(available=True, error=True)
    secondary = FakeProvider(available=True, error=True)
    logger = RecordingLogger()

    fp = FailoverAIProvider(
        primary=primary,
        secondary=secondary,
        max_retries=1,
        logger=logger,  # type: ignore[arg-type]
    )

    with pytest.raises(AIProviderError) as excinfo:
        fp.extract("do maintenance", CTX)

    # The degraded message is the localized unavailability text, NOT the raw
    # "fake provider failure" from the SDK/parse layer (Req 26.3).
    assert "fake provider failure" not in str(excinfo.value)
    assert "no está disponible" in str(excinfo.value)
    assert "ai_failover_unavailable" in logger.event_names()


def test_no_providers_available_degrades() -> None:
    primary = FakeProvider(available=False)
    logger = RecordingLogger()

    fp = FailoverAIProvider(primary=primary, secondary=None, logger=logger)  # type: ignore[arg-type]

    assert fp.is_available() is False
    with pytest.raises(AIProviderError) as excinfo:
        fp.extract("do maintenance", CTX)
    assert "no está disponible" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# (c) schema-invalid repeatedly -> retries then errors, no build_timeperiod   #
# --------------------------------------------------------------------------- #
def test_schema_invalid_retries_then_degrades_without_build_timeperiod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Trip a flag if build_timeperiod is ever called during the schema failure
    # path; it must NOT be (Req 29.3).
    called = {"build_timeperiod": False}
    import core.recurrence as recurrence

    def _tripwire(*args: object, **kwargs: object) -> object:
        called["build_timeperiod"] = True
        raise AssertionError("build_timeperiod must not be invoked on schema failure")

    monkeypatch.setattr(recurrence, "build_timeperiod", _tripwire, raising=False)

    primary = SchemaInvalidProvider()
    logger = RecordingLogger()

    fp = FailoverAIProvider(
        primary=primary,
        secondary=None,
        max_retries=0,
        schema_max_attempts=3,
        logger=logger,  # type: ignore[arg-type]
    )

    with pytest.raises(AIProviderError):
        fp.extract("do maintenance", CTX)

    # Validated the schema exactly schema_max_attempts times before giving up.
    assert primary.calls == 3
    assert called["build_timeperiod"] is False
    names = logger.event_names()
    assert "ai_schema_invalid" in names
    assert "ai_schema_exhausted" in names


def test_schema_valid_returns_immediately() -> None:
    expected = _valid_request()
    primary = FakeProvider(available=True, result=expected)
    logger = RecordingLogger()

    fp = FailoverAIProvider(
        primary=primary, schema_max_attempts=2, logger=logger  # type: ignore[arg-type]
    )

    result = fp.extract("do maintenance", CTX)
    assert result is expected
    assert primary.calls == 1  # no unnecessary retries when the first is valid


# --------------------------------------------------------------------------- #
# factory.build_provider                                                      #
# --------------------------------------------------------------------------- #
def _cfg(**overrides: object):
    """Build an AppConfig with sensible test defaults, overridable per test."""
    from config import AppConfig

    base = dict(
        zabbix_url="https://zbx.example/api_jsonrpc.php",
        zabbix_token="tok",  # noqa: S106 - test placeholder, not a real secret
        ai_provider="gemini",
        gemini_api_key=None,
        gemini_model="gemini-2.0-flash",
        openai_api_key=None,
        openai_model="gpt-4o-mini",
        bedrock_model="amazon.nova-lite-v1:0",
        aws_region="us-east-1",
        aws_access_key_id=None,
        aws_secret_access_key=None,
        aws_session_token=None,
        cors_allowed_origins=["https://ui.example"],
        version="test",
        supported_locales=["es", "en"],
        default_locale="es",
        ai_secondary_provider=None,
        ai_failover_max_retries=1,
        ai_failover_timeout_seconds=30.0,
        ai_request_timeout_seconds=20.0,
        user_cache_ttl_seconds=300,
        rate_limit_max_requests=60,
        rate_limit_window_seconds=60,
        ai_schema_max_attempts=2,
    )
    base.update(overrides)
    return AppConfig(**base)  # type: ignore[arg-type]


def test_build_provider_wraps_in_failover() -> None:
    provider = factory.build_provider(_cfg(ai_provider="gemini"))
    assert isinstance(provider, FailoverAIProvider)


def test_build_provider_unsupported_logs_and_degrades() -> None:
    logger = RecordingLogger()
    provider = factory.build_provider(
        _cfg(ai_provider="not-a-provider"), logger=logger  # type: ignore[arg-type]
    )
    assert isinstance(provider, FailoverAIProvider)
    assert provider.is_available() is False
    assert "unsupported provider" in logger.event_names()
