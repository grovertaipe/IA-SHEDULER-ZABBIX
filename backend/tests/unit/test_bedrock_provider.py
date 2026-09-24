"""Tests for :class:`ai.bedrock_provider.BedrockProvider` (Amazon Bedrock, Req 12.7).

No live AWS calls are made: the ``bedrock-runtime`` client is monkeypatched. The
suite also exercises the factory wiring so that Bedrock works both as the PRIMARY
provider (``AI_PROVIDER=bedrock``) and as the SECONDARY/failover provider
(``AI_SECONDARY_PROVIDER=bedrock``).
"""

from __future__ import annotations

import builtins
import importlib
from typing import Any

import pytest

import ai.bedrock_provider as bp
from ai.bedrock_provider import _MAX_TOKENS, _TEMPERATURE, BedrockProvider
from ai.factory import build_provider, build_single_provider
from ai.failover import FailoverAIProvider
from ai.provider import AIProviderError
from config import AppConfig
from core.domain import PromptContext
from observability.logger import SecureLogger

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")
_JSON_RESPONSE = (
    '{"intent": "maintenance_request", "hosts": ["web01"], '
    '"groups": ["Linux servers"], '
    '"assistant_message": "Ready — I set up the maintenance for web01."}'
)


def _converse_response(text: str) -> dict[str, Any]:
    """Build a Bedrock Converse-shaped response wrapping ``text``."""
    return {"output": {"message": {"content": [{"text": text}]}}}


class _FakeClient:
    """Stub ``bedrock-runtime`` client capturing the ``converse`` kwargs."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.captured: dict[str, Any] = {}

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.captured = kwargs
        return _converse_response(self._text)


def _make_available_provider(text: str = _JSON_RESPONSE) -> BedrockProvider:
    """Construct a provider and force a stubbed client onto it."""
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1")
    provider._client = _FakeClient(text)  # type: ignore[attr-defined]
    return provider


def _cfg(**overrides: Any) -> AppConfig:
    """Build an AppConfig with all fields populated, applying overrides."""
    base: dict[str, Any] = {
        "zabbix_url": "http://localhost/zabbix/api_jsonrpc.php",
        "zabbix_token": "token",
        "ai_provider": "bedrock",
        "gemini_api_key": None,
        "gemini_model": "gemini-flash-lite-latest",
        "openai_api_key": None,
        "openai_model": "gpt-4o-mini",
        "bedrock_model": "amazon.nova-lite-v1:0",
        "aws_region": "us-east-1",
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "aws_session_token": None,
        "cors_allowed_origins": ["http://localhost"],
        "version": "2.0.0",
        "supported_locales": ["es", "en"],
        "default_locale": "es",
        "ai_secondary_provider": None,
        "ai_failover_max_retries": 1,
        "ai_failover_timeout_seconds": 30.0,
        "ai_request_timeout_seconds": 20.0,
        "user_cache_ttl_seconds": 300,
        "rate_limit_max_requests": 60,
        "rate_limit_window_seconds": 60,
        "ai_schema_max_attempts": 2,
    }
    base.update(overrides)
    return AppConfig(**base)


# --------------------------------------------------------------------------- #
# Availability                                                                #
# --------------------------------------------------------------------------- #
def test_provider_available_with_client() -> None:
    """A provider with a client present reports available."""
    provider = _make_available_provider()
    assert provider.is_available() is True


def test_module_import_survives_missing_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the module never hard-fails when boto3 is absent (lazy import).

    We force the ``boto3`` import to fail, reimport the module, and confirm the
    provider is simply unavailable rather than raising at import/construction,
    and that extract() raises AIProviderError.
    """
    real_import = builtins.__import__

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "boto3" or name.startswith("boto3."):
            raise ImportError("forced: no boto3 SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    reloaded = importlib.reload(bp)
    try:
        provider = reloaded.BedrockProvider("amazon.nova-lite-v1:0", "us-east-1")
        assert provider.is_available() is False
        with pytest.raises(reloaded.AIProviderError):
            provider.extract("hola", CTX)
    finally:
        monkeypatch.setattr(builtins, "__import__", real_import)
        importlib.reload(bp)


# --------------------------------------------------------------------------- #
# extract()                                                                   #
# --------------------------------------------------------------------------- #
def test_extract_returns_parsed_request_with_stubbed_client() -> None:
    """extract() calls Converse and parses the returned text.

    Asserts the parsed ExtractedRequest and that raw_message is preserved, plus
    the modelId and inferenceConfig (temperature 0.2 / maxTokens 1200) passed to
    converse.
    """
    provider = _make_available_provider()

    result = provider.extract("apaga web01 manana", CTX)

    assert result.intent == "maintenance_request"
    assert result.hosts == ["web01"]
    assert result.groups == ["Linux servers"]
    assert result.assistant_message == "Ready — I set up the maintenance for web01."
    assert result.raw_message == "apaga web01 manana"

    captured = provider._client.captured  # type: ignore[attr-defined]
    assert captured["modelId"] == "amazon.nova-lite-v1:0"
    assert captured["inferenceConfig"]["temperature"] == _TEMPERATURE
    assert captured["inferenceConfig"]["maxTokens"] == _MAX_TOKENS
    # The prompt is carried as a single user text content block.
    assert captured["messages"][0]["role"] == "user"
    assert isinstance(captured["messages"][0]["content"][0]["text"], str)


def test_extract_concatenates_multiple_text_parts() -> None:
    """Multiple content parts with ``text`` are concatenated before parsing."""
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1")

    class _MultiPartClient:
        captured: dict[str, Any] = {}

        def converse(self, **kwargs: Any) -> dict[str, Any]:
            return {
                "output": {
                    "message": {
                        "content": [
                            {"text": '{"intent": "help",'},
                            {"text": ' "hosts": []}'},
                        ]
                    }
                }
            }

    provider._client = _MultiPartClient()  # type: ignore[attr-defined]
    result = provider.extract("ayuda", CTX)
    assert result.intent == "help"


def test_extract_maps_client_exception_to_provider_error() -> None:
    """A client exception surfaces as AIProviderError."""
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1")

    class _BoomClient:
        def converse(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("bedrock endpoint unreachable")

    provider._client = _BoomClient()  # type: ignore[attr-defined]
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_unavailable_provider_extract_raises() -> None:
    """With no client, the provider is unavailable and extract() raises."""
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1")
    provider._client = None  # type: ignore[attr-defined]
    assert provider.is_available() is False
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


def test_generation_parameters_match_other_providers() -> None:
    """Low-temperature / bounded-output params mirror the other providers."""
    assert _TEMPERATURE == 0.2
    assert _MAX_TOKENS == 1200


# --------------------------------------------------------------------------- #
# Fix 1: per-request network timeout via botocore Config                      #
# --------------------------------------------------------------------------- #
def test_client_built_with_connect_and_read_timeouts() -> None:
    """The boto3 client carries connect/read timeouts from request_timeout.

    boto3 exposes the effective client config on ``client.meta.config``.
    """
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1", request_timeout=8.0)
    # The real boto3 client is built (no network call happens at construction).
    assert provider.is_available() is True
    config = provider._client.meta.config  # type: ignore[attr-defined]
    assert config.connect_timeout == 8.0
    assert config.read_timeout == 8.0


def test_extract_maps_timeout_exception_to_provider_error() -> None:
    """A timeout-like client exception surfaces as AIProviderError (no hang)."""
    provider = BedrockProvider("amazon.nova-lite-v1:0", "us-east-1", request_timeout=1.0)

    class _TimeoutClient:
        def converse(self, **_kwargs: Any) -> dict[str, Any]:
            raise TimeoutError("read timed out")

    provider._client = _TimeoutClient()  # type: ignore[attr-defined]
    with pytest.raises(AIProviderError):
        provider.extract("hola", CTX)


# --------------------------------------------------------------------------- #
# Factory wiring                                                              #
# --------------------------------------------------------------------------- #
def test_build_single_provider_returns_bedrock() -> None:
    """build_single_provider('bedrock', ...) returns a BedrockProvider."""
    provider = build_single_provider("bedrock", _cfg(), SecureLogger())
    assert isinstance(provider, BedrockProvider)


def test_build_provider_primary_bedrock_returns_failover() -> None:
    """build_provider with ai_provider='bedrock' yields a FailoverAIProvider."""
    provider = build_provider(_cfg(ai_provider="bedrock"), SecureLogger())
    assert isinstance(provider, FailoverAIProvider)


def test_build_provider_secondary_bedrock_returns_failover() -> None:
    """Bedrock is usable as the secondary/failover provider."""
    provider = build_provider(
        _cfg(ai_provider="gemini", ai_secondary_provider="bedrock"),
        SecureLogger(),
    )
    assert isinstance(provider, FailoverAIProvider)
