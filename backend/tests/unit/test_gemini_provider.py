"""Tests for :class:`ai.gemini_provider.GeminiProvider` (google-genai migration).

Bugfix spec: ``.kiro/specs/gemini-sdk-migration``. Two properties are covered:

* **Property 1: Bug Condition** — on the running interpreter, constructing the
  provider with a valid API key must yield ``is_available() == True`` and a
  stubbed ``extract`` must return the parsed request. On the UNFIXED code
  (legacy ``google-generativeai`` on Python 3.14) this FAILS, proving the bug.
* **Property 2: Preservation** — non-buggy inputs (no key, missing SDK) behave
  exactly as before; generation params and the OpenAI provider are unchanged.

No live Gemini API calls are made: the SDK client is monkeypatched.
"""

from __future__ import annotations

import builtins
import importlib
from typing import Any

import pytest

import ai.gemini_provider as gp
from ai.gemini_provider import (
    _MAX_OUTPUT_TOKENS,
    _TEMPERATURE,
    GeminiProvider,
    _extract_text,
)
from ai.provider import AIProviderError
from core.domain import PromptContext

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")
_JSON_RESPONSE = '{"intent": "maintenance_request", "hosts": ["web01"]}'


class _FakeResponse:
    """Mimics the google-genai response object exposing ``.text``."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakePart:
    """A single response part; may or may not carry ``.text``.

    A ``thought_signature``-only part (Gemini 3.x "thinking" models) is modeled
    by passing ``text=None`` and a ``thought_signature`` attribute.
    """

    def __init__(self, text: str | None = None, thought_signature: bytes | None = None) -> None:
        self.text = text
        if thought_signature is not None:
            self.thought_signature = thought_signature


class _FakeContent:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.content = _FakeContent(parts)


class _FakeThinkingResponse:
    """Response whose ``.text`` is empty but exposes ``.candidates`` parts.

    Simulates a Gemini 3.x thinking response where the SDK could not build a
    clean concatenated ``.text`` (empty) but the answer lives in the parts
    alongside a non-text ``thought_signature`` part.
    """

    def __init__(self, text: str, parts: list[_FakePart]) -> None:
        self.text = text
        self.candidates = [_FakeCandidate(parts)]


# --------------------------------------------------------------------------- #
# Property 1: Bug Condition - Gemini Provider Available After SDK Migration    #
# --------------------------------------------------------------------------- #
def test_provider_available_with_api_key() -> None:
    """With a valid key the provider builds a client and is available.

    UNFIXED (google-generativeai on Python 3.14): the SDK import raises
    "Metaclasses with custom tp_new are not supported", so is_available() is
    False -> this assertion FAILS, confirming the bug.
    """
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash")
    assert provider.is_available() is True


def test_extract_returns_parsed_request_with_stubbed_sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract() delegates to the SDK and parses the returned text.

    The client's generate_content is stubbed so NO network call happens.
    """
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash")
    assert provider.is_available() is True  # precondition (fails on unfixed)

    captured: dict[str, Any] = {}

    def _fake_generate_content(*, model: str, contents: str, config: Any) -> _FakeResponse:
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return _FakeResponse(_JSON_RESPONSE)

    # Route the fixed provider's client call to the stub.
    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _fake_generate_content,
    )

    result = provider.extract("apaga web01 manana", CTX)

    assert result.intent == "maintenance_request"
    assert result.hosts == ["web01"]
    assert result.raw_message == "apaga web01 manana"
    assert captured["model"] == "gemini-2.0-flash"
    # generation parameters are carried on the config object
    assert getattr(captured["config"], "temperature", None) == _TEMPERATURE
    assert getattr(captured["config"], "max_output_tokens", None) == _MAX_OUTPUT_TOKENS


def test_extract_wraps_sdk_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK exceptions surface as AIProviderError (contract preserved)."""
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash")
    assert provider.is_available() is True

    def _boom(**_kwargs: Any) -> _FakeResponse:
        raise RuntimeError("network kaput")

    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _boom,
    )

    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


# --------------------------------------------------------------------------- #
# Property 2: Preservation - Non-Bug Inputs Behave Identically                #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", ["gemini-2.0-flash", "gemini-1.5-pro", "x"])
def test_no_api_key_is_unavailable(model: str) -> None:
    """For any model, a missing key -> unavailable and extract() raises."""
    provider = GeminiProvider(None, model)
    assert provider.is_available() is False
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_empty_api_key_is_unavailable() -> None:
    """An empty-string key is treated as no key (unchanged)."""
    provider = GeminiProvider("", "gemini-2.0-flash")
    assert provider.is_available() is False


def test_module_import_survives_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the module never hard-fails when the SDK is absent (lazy import).

    We force the ``google`` import to fail, reimport the module, and confirm the
    provider is simply unavailable rather than raising at import/construction.
    """
    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "google" or name.startswith("google."):
            raise ImportError("forced: no google SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    reloaded = importlib.reload(gp)
    try:
        provider = reloaded.GeminiProvider("dummy-key", "gemini-2.0-flash")
        assert provider.is_available() is False
        with pytest.raises(reloaded.AIProviderError):
            provider.extract("hola", CTX)
    finally:
        monkeypatch.setattr(builtins, "__import__", real_import)
        importlib.reload(gp)


def test_generation_parameters_unchanged() -> None:
    """The fixed low-temperature / bounded-output params are preserved."""
    assert _TEMPERATURE == 0.2
    assert _MAX_OUTPUT_TOKENS == 1200


# --------------------------------------------------------------------------- #
# Fix 2: Robust Gemini 3.x response text extraction (_extract_text)           #
# --------------------------------------------------------------------------- #
def test_extract_text_uses_response_text_when_present() -> None:
    """When ``response.text`` is non-empty it is returned as-is (common path)."""
    assert _extract_text(_FakeResponse(_JSON_RESPONSE)) == _JSON_RESPONSE


def test_extract_text_falls_back_to_parts_ignoring_thought_signature() -> None:
    """Empty ``.text`` -> concatenate text parts, skipping non-text parts.

    Simulates a Gemini 3.x thinking response: a ``thought_signature``-only part
    (no ``.text``) followed by the real answer text part.
    """
    resp = _FakeThinkingResponse(
        text="",
        parts=[
            _FakePart(thought_signature=b"\x01\x02"),  # non-text: must be skipped
            _FakePart(text='{"intent": "help",'),
            _FakePart(text=' "hosts": []}'),
        ],
    )
    assert _extract_text(resp) == '{"intent": "help", "hosts": []}'


def test_extract_text_returns_empty_when_no_text_anywhere() -> None:
    """A response with neither ``.text`` nor text parts yields ``""``.

    A malformed/thinking-only response must not raise inside the helper.
    """
    resp = _FakeThinkingResponse(
        text="",
        parts=[_FakePart(thought_signature=b"\xaa")],
    )
    assert _extract_text(resp) == ""


def test_extract_raises_when_response_has_no_usable_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract() raises AIProviderError when no text can be extracted.

    This lets failover try the secondary instead of parsing empty text.
    """
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash")
    assert provider.is_available() is True

    def _thinking_only(**_kwargs: Any) -> _FakeThinkingResponse:
        return _FakeThinkingResponse(text="", parts=[_FakePart(thought_signature=b"\x01")])

    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _thinking_only,
    )
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_extract_recovers_text_from_thinking_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """extract() parses text recovered from candidate parts (thinking model)."""
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash")
    assert provider.is_available() is True

    def _thinking(**_kwargs: Any) -> _FakeThinkingResponse:
        return _FakeThinkingResponse(
            text="",
            parts=[
                _FakePart(thought_signature=b"\x01"),
                _FakePart(text=_JSON_RESPONSE),
            ],
        )

    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _thinking,
    )
    result = provider.extract("apaga web01", CTX)
    assert result.intent == "maintenance_request"
    assert result.hosts == ["web01"]


# --------------------------------------------------------------------------- #
# Fix 1: per-request network timeout is wired into the SDK call               #
# --------------------------------------------------------------------------- #
def test_extract_passes_http_options_timeout_in_ms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The configured request_timeout is applied as HttpOptions timeout (ms)."""
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash", request_timeout=7.0)
    assert provider.is_available() is True

    captured: dict[str, Any] = {}

    def _fake_generate_content(*, model: str, contents: str, config: Any) -> _FakeResponse:
        captured["config"] = config
        return _FakeResponse(_JSON_RESPONSE)

    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _fake_generate_content,
    )
    provider.extract("hola", CTX)
    http_options = getattr(captured["config"], "http_options", None)
    assert http_options is not None
    # 7.0s -> 7000 ms
    assert getattr(http_options, "timeout", None) == 7000


def test_extract_maps_timeout_exception_to_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timeout-like SDK exception surfaces as AIProviderError (no hang)."""
    provider = GeminiProvider("dummy-key", "gemini-2.0-flash", request_timeout=1.0)
    assert provider.is_available() is True

    def _timeout(**_kwargs: Any) -> _FakeResponse:
        raise TimeoutError("read timed out")

    monkeypatch.setattr(
        provider._client.models,  # type: ignore[attr-defined]
        "generate_content",
        _timeout,
    )
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)
