"""Gemini implementation of :class:`~backend.ai.provider.AIProvider` (Req 12.3).

Wraps Google's ``google-genai`` SDK (the Google Gen AI SDK, which supports
current Python runtimes). The SDK is imported **lazily** inside the constructor
so that importing this module never hard-fails when the library is not installed
— only *constructing* and *using* the provider requires it. The new SDK is
stateless per request (the client holds only auth; the model name is passed on
each call), so the provider stores the client plus the model name. When the SDK
is missing or the API key is absent, :meth:`is_available` returns ``False`` and
:meth:`extract` raises :class:`~backend.ai.provider.AIProviderError`; the
failover / service layer handles graceful degradation later (Task 21.3).

Requirements: 3.2, 3.8, 12.3, 12.5, 13.1-13.5.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domain import ExtractedRequest, PromptContext

from .provider import AIProvider, AIProviderError, parse_response_text

logger = logging.getLogger(__name__)

# Generation parameters mirror the legacy monolith (low temperature for
# deterministic structured extraction).
_TEMPERATURE = 0.2
_MAX_OUTPUT_TOKENS = 1200


def _build_prompt(message: str, ctx: PromptContext) -> str:
    """Build the AI prompt, importing the prompt module defensively.

    The prompt builder lives in :mod:`backend.ai.prompt` (sibling Task 8.1). It
    is imported lazily and tolerantly here: if the exact ``build_prompt`` symbol
    is not yet available, we fall back to a minimal inline prompt so this
    provider still functions and imports cleanly. The prompt itself contains no
    bitmask arithmetic (Req 3.1/3.2).
    """
    try:
        from .prompt import build_prompt
    except (ImportError, AttributeError):
        return _fallback_prompt(message, ctx)
    return build_prompt(message, ctx)


def _fallback_prompt(message: str, ctx: PromptContext) -> str:
    """Minimal prompt used only if :mod:`ai.prompt` cannot be imported.

    Injects today/tomorrow (Req 13.6) and asks for the structured contract
    without any bitmask arithmetic (Req 3.2). Deterministic and side-effect free.
    """
    return (
        "Extract a structured maintenance request as a single JSON object. "
        "Do NOT compute bitmasks. Recognize infrastructure terms (CIs, servers, "
        "routers, switches, nodes, instances, appliances) as hosts. Use intent "
        "one of maintenance_request|help|clarification|off_topic. "
        f"today={ctx.today_iso} tomorrow={ctx.tomorrow_iso}\n"
        f"User message: {message}"
    )


class GeminiProvider(AIProvider):
    """AI provider backed by Google Gemini (``google-genai``)."""

    def __init__(self, api_key: str | None, model: str) -> None:
        """Configure the provider with an API key and model name.

        The SDK is loaded lazily and the client is created eagerly when
        possible. Any failure (missing library, missing key, SDK error) leaves
        the provider in an unavailable state rather than raising, so callers can
        query :meth:`is_available` and degrade gracefully (Req 12.5). The new
        SDK is stateless per request, so only the client (auth) and the model
        name are stored; the model is passed on each ``generate_content`` call.
        """
        self._api_key = api_key or None
        self._model_name = model
        self._client: Any | None = None
        self._types: Any | None = None

        if not self._api_key:
            logger.error("Missing API key for AI provider 'gemini': set GOOGLE_API_KEY")
            return

        try:
            from google import genai  # lazy import (Req: no hard import)
            from google.genai import types
        except Exception as exc:  # pragma: no cover - env without the SDK
            logger.error("google-genai is not available: %s", exc)
            return

        try:
            self._client = genai.Client(api_key=self._api_key)
            self._types = types
            logger.info("Gemini provider configured (model=%s)", self._model_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to initialize Gemini provider: %s", exc)
            self._client = None

    def is_available(self) -> bool:
        """Return whether the API key and client are both configured."""
        return self._api_key is not None and self._client is not None

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        """Call Gemini and parse the response into an :class:`ExtractedRequest`.

        Raises :class:`AIProviderError` when the provider is unavailable
        (Req 12.5) or the model returns no usable text. The parsing computes no
        bitmasks (Req 3.2) and preserves ``raw_message`` (Req 3.8).
        """
        if not self.is_available():
            raise AIProviderError("Gemini provider is not available")

        prompt = _build_prompt(message, ctx)
        try:
            response = self._client.models.generate_content(  # type: ignore[union-attr]
                model=self._model_name,
                contents=prompt,
                config=self._types.GenerateContentConfig(  # type: ignore[union-attr]
                    temperature=_TEMPERATURE,
                    max_output_tokens=_MAX_OUTPUT_TOKENS,
                ),
            )
        except Exception as exc:
            raise AIProviderError(f"Gemini request failed: {exc}") from exc

        text = getattr(response, "text", "") or ""
        return parse_response_text(text, message)
