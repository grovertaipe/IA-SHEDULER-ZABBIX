"""Tests for :class:`ai.openai_provider.OpenAIProvider` (Req 12.2).

No live OpenAI API calls are made: the SDK client is stubbed onto the provider.
Focus here is the robustness fix — the per-request NETWORK timeout is passed to
``chat.completions.create`` and SDK/timeout exceptions map to ``AIProviderError``.
"""

from __future__ import annotations

from typing import Any

import pytest

from ai.openai_provider import _MAX_TOKENS, _TEMPERATURE, OpenAIProvider
from ai.provider import AIProviderError
from core.domain import PromptContext

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")
_JSON_RESPONSE = (
    '{"intent": "maintenance_request", "hosts": ["web01"], '
    '"assistant_message": "Done, I prepared the maintenance for web01."}'
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content
        self.captured: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.captured = kwargs
        return _FakeResponse(self._content)


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.completions = _FakeCompletions(content)


class _FakeClient:
    def __init__(self, content: str) -> None:
        self.chat = _FakeChat(content)


def _make_available_provider(
    content: str = _JSON_RESPONSE, request_timeout: float = 20.0
) -> OpenAIProvider:
    provider = OpenAIProvider("dummy-key", "gpt-4o-mini", request_timeout=request_timeout)
    provider._client = _FakeClient(content)  # type: ignore[attr-defined]
    return provider


def test_provider_available_with_key_and_client() -> None:
    """A provider with a stubbed client reports available."""
    provider = _make_available_provider()
    assert provider.is_available() is True


def test_no_api_key_is_unavailable() -> None:
    """A missing key -> unavailable and extract() raises."""
    provider = OpenAIProvider(None, "gpt-4o-mini")
    assert provider.is_available() is False
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_extract_returns_parsed_request_and_passes_timeout() -> None:
    """extract() parses the text and passes the per-request timeout + params."""
    provider = _make_available_provider(request_timeout=9.0)
    result = provider.extract("apaga web01 manana", CTX)

    assert result.intent == "maintenance_request"
    assert result.hosts == ["web01"]
    assert result.assistant_message == "Done, I prepared the maintenance for web01."
    assert result.raw_message == "apaga web01 manana"

    captured = provider._client.chat.completions.captured  # type: ignore[attr-defined]
    assert captured["model"] == "gpt-4o-mini"
    assert captured["temperature"] == _TEMPERATURE
    assert captured["max_tokens"] == _MAX_TOKENS
    assert captured["timeout"] == 9.0


def test_extract_maps_timeout_exception_to_provider_error() -> None:
    """A timeout-like SDK exception surfaces as AIProviderError (no hang)."""
    provider = OpenAIProvider("dummy-key", "gpt-4o-mini", request_timeout=1.0)

    class _BoomChat:
        class completions:  # noqa: N801 - mimic SDK attribute shape
            @staticmethod
            def create(**_kwargs: Any) -> _FakeResponse:
                raise TimeoutError("read timed out")

    class _BoomClient:
        chat = _BoomChat()

    provider._client = _BoomClient()  # type: ignore[attr-defined]
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_generation_parameters() -> None:
    """Low-temperature / bounded-output params match the other providers."""
    assert _TEMPERATURE == 0.2
    assert _MAX_TOKENS == 1200
