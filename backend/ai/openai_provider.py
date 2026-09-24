"""OpenAI implementation of :class:`~backend.ai.provider.AIProvider` (Req 12.2).

Wraps the ``openai`` SDK. The SDK is imported **lazily** inside the constructor
(mirroring the legacy monolith) so importing this module never hard-fails when
the library is absent — only *constructing* and *using* the provider needs it.
When the SDK is missing or the API key is absent, :meth:`is_available` returns
``False`` and :meth:`extract` raises
:class:`~backend.ai.provider.AIProviderError`; the failover / service layer
handles graceful degradation later (Task 21.3).

Requirements: 3.2, 3.8, 12.2, 12.5, 13.1-13.5.
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
_MAX_TOKENS = 1200

#: Default per-attempt network timeout (seconds) if the factory does not pass one.
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0

# System message keeps the assistant scoped to Zabbix maintenance extraction.
_SYSTEM_PROMPT = (
    "Eres un asistente especializado en crear mantenimientos para Zabbix. "
    "Devuelves únicamente un objeto JSON estructurado, sin calcular bitmasks."
)


def _build_prompt(message: str, ctx: PromptContext) -> str:
    """Build the AI prompt, importing the prompt module defensively.

    The prompt builder lives in :mod:`backend.ai.prompt` (sibling Task 8.1). It
    is imported lazily and tolerantly: if the exact ``build_prompt`` symbol is
    not yet available, a minimal inline fallback is used so this provider still
    imports and functions. The prompt contains no bitmask arithmetic (Req 3.2).
    """
    try:
        from .prompt import build_prompt
    except (ImportError, AttributeError):
        return _fallback_prompt(message, ctx)
    return build_prompt(message, ctx)


def _fallback_prompt(message: str, ctx: PromptContext) -> str:
    """Minimal prompt used only if :mod:`ai.prompt` cannot be imported.

    Injects today/tomorrow (Req 13.6) and requests the structured contract with
    no bitmask arithmetic (Req 3.2). Deterministic and side-effect free.
    """
    return (
        "Extract a structured maintenance request as a single JSON object. "
        "Do NOT compute bitmasks. Recognize infrastructure terms (CIs, servers, "
        "routers, switches, nodes, instances, appliances) as hosts. Use intent "
        "one of maintenance_request|help|clarification|off_topic. "
        f"today={ctx.today_iso} tomorrow={ctx.tomorrow_iso}\n"
        f"User message: {message}"
    )


class OpenAIProvider(AIProvider):
    """AI provider backed by OpenAI (``openai`` chat completions)."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the provider with an API key and model name.

        The SDK is loaded lazily and the client is created eagerly when
        possible. Any failure (missing library, missing key, SDK error) leaves
        the provider unavailable rather than raising, so callers can query
        :meth:`is_available` and degrade gracefully (Req 12.5).

        ``request_timeout`` is the per-attempt NETWORK timeout (seconds) passed
        to each ``chat.completions.create`` call so a hung read raises promptly
        (becoming an :class:`AIProviderError`) instead of stalling the worker.
        """
        self._api_key = api_key or None
        self._model_name = model
        self._request_timeout = request_timeout
        self._client: Any | None = None

        if not self._api_key:
            logger.error("Missing API key for AI provider 'openai': set OPENAI_API_KEY")
            return

        try:
            from openai import OpenAI  # lazy import (Req: no hard import)
        except Exception as exc:  # pragma: no cover - env without the SDK
            logger.error("openai SDK is not available: %s", exc)
            return

        try:
            self._client = OpenAI(api_key=self._api_key)
            logger.info("OpenAI provider configured (model=%s)", self._model_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to initialize OpenAI provider: %s", exc)
            self._client = None

    def is_available(self) -> bool:
        """Return whether the API key and client are both configured."""
        return self._api_key is not None and self._client is not None

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        """Call OpenAI and parse the response into an :class:`ExtractedRequest`.

        Raises :class:`AIProviderError` when the provider is unavailable
        (Req 12.5) or the model returns no usable text. The parsing computes no
        bitmasks (Req 3.2) and preserves ``raw_message`` (Req 3.8).
        """
        if not self.is_available():
            raise AIProviderError("OpenAI provider is not available")

        prompt = _build_prompt(message, ctx)
        try:
            response = self._client.chat.completions.create(  # type: ignore[union-attr]
                model=self._model_name,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=_TEMPERATURE,
                max_tokens=_MAX_TOKENS,
                # Per-request NETWORK timeout (seconds). A hung read raises here
                # and is mapped to AIProviderError below.
                timeout=self._request_timeout,
            )
        except Exception as exc:
            raise AIProviderError(f"OpenAI request failed: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        text = ""
        if choices:
            message_obj = getattr(choices[0], "message", None)
            text = getattr(message_obj, "content", "") or ""
        return parse_response_text(text, message)
