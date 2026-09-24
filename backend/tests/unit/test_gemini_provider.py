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
from ai.gemini_provider import _MAX_OUTPUT_TOKENS, _TEMPERATURE, GeminiProvider
from ai.provider import AIProviderError
from core.domain import PromptContext

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")
_JSON_RESPONSE = '{"intent": "maintenance_request", "hosts": ["web01"]}'


class _FakeResponse:
    """Mimics the google-genai response object exposing ``.text``."""

    def __init__(self, text: str) -> None:
        self.text = text


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
