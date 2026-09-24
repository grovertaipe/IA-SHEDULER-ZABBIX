"""Amazon Bedrock implementation of :class:`~backend.ai.provider.AIProvider` (Req 12.7).

Wraps the AWS ``boto3`` SDK (``bedrock-runtime`` client) and calls the Bedrock
**Converse API**, which offers a provider-agnostic message shape across the
foundation models Bedrock hosts (the default model is Amazon Nova Lite,
``amazon.nova-lite-v1:0``). ``boto3``/``botocore`` are imported **lazily** inside
the constructor (mirroring the Gemini/OpenAI providers) so importing this module
never hard-fails when the library is absent — only *constructing* and *using*
the provider needs it.

Credentials follow the standard AWS resolution model: explicit static keys may
be passed in, but the recommended path leaves them unset so boto3's default
credential chain resolves them (environment variables, ``~/.aws`` config/profile,
or an IAM role / instance profile). Because an IAM role is a valid credential
source, :meth:`is_available` requires only that the client was built — not that
explicit keys were provided. When the SDK is missing, the client cannot be
built, or the model call fails, :meth:`is_available` returns ``False`` /
:meth:`extract` raises :class:`~backend.ai.provider.AIProviderError`; the
failover / service layer handles graceful degradation (Task 21.3).

Parsing reuses the shared :func:`~backend.ai.provider.parse_response_text`
helper: this provider computes no bitmasks (Req 3.2) and preserves ``raw_message``
(Req 3.8).

Requirements: 3.2, 3.8, 12.5, 12.7, 13.1-13.5.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domain import ExtractedRequest, PromptContext

from .provider import AIProvider, AIProviderError, parse_response_text

logger = logging.getLogger(__name__)

# Generation parameters mirror the other providers (low temperature for
# deterministic structured extraction).
_TEMPERATURE = 0.2
_MAX_TOKENS = 1200

#: Default per-attempt network timeout (seconds) if the factory does not pass one.
_DEFAULT_REQUEST_TIMEOUT_SECONDS = 20.0


def _build_prompt(message: str, ctx: PromptContext) -> str:
    """Build the AI prompt, importing the prompt module defensively.

    The prompt builder lives in :mod:`backend.ai.prompt`. It is imported lazily
    and tolerantly: if the exact ``build_prompt`` symbol is not available, a
    minimal inline fallback is used so this provider still imports and functions.
    The prompt contains no bitmask arithmetic (Req 3.2).
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


def _extract_converse_text(resp: Any) -> str:
    """Concatenate all ``text`` parts of a Bedrock Converse response.

    Defensive against missing keys / unexpected shapes: walks
    ``resp["output"]["message"]["content"]`` and joins every part that carries a
    ``"text"`` key, returning an empty string when nothing usable is present.
    Pure and side-effect free.
    """
    if not isinstance(resp, dict):
        return ""
    output = resp.get("output")
    if not isinstance(output, dict):
        return ""
    message = output.get("message")
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


class BedrockProvider(AIProvider):
    """AI provider backed by Amazon Bedrock (``boto3`` Converse API)."""

    def __init__(
        self,
        model: str,
        region: str | None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        request_timeout: float = _DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        """Configure the provider and build the ``bedrock-runtime`` client.

        ``boto3`` is loaded lazily and the client is created eagerly when
        possible. When explicit ``access_key_id``/``secret_access_key`` are
        supplied they are passed to boto3 (with ``session_token`` when set);
        otherwise boto3's default credential chain (env vars, ``~/.aws``, IAM
        role / instance profile) resolves the credentials — the recommended
        path. Any failure (missing library, bad region, SDK error) leaves the
        provider unavailable rather than raising, so callers can query
        :meth:`is_available` and degrade gracefully (Req 12.5).
        """
        self._model_name = model
        self._region = region or None
        self._access_key_id = access_key_id or None
        self._secret_access_key = secret_access_key or None
        self._session_token = session_token or None
        self._request_timeout = request_timeout
        self._client: Any | None = None

        try:
            import boto3  # lazy import (Req: no hard import)
            from botocore.config import Config as BotoConfig
        except Exception as exc:  # pragma: no cover - env without the SDK
            logger.error("boto3 is not available: %s", exc)
            return

        # Per-attempt NETWORK timeout applied at the transport layer: a hung
        # connect/read raises promptly (as an AIProviderError) instead of
        # stalling the worker. Keep botocore's own retries bounded.
        boto_cfg = BotoConfig(
            connect_timeout=self._request_timeout,
            read_timeout=self._request_timeout,
            retries={"max_attempts": 2},
        )

        try:
            if self._access_key_id and self._secret_access_key:
                kwargs: dict[str, Any] = {
                    "region_name": self._region,
                    "aws_access_key_id": self._access_key_id,
                    "aws_secret_access_key": self._secret_access_key,
                    "config": boto_cfg,
                }
                if self._session_token:
                    kwargs["aws_session_token"] = self._session_token
                self._client = boto3.client("bedrock-runtime", **kwargs)
            else:
                # Recommended path: let boto3's default credential chain resolve
                # env vars / ~/.aws / IAM role / instance profile.
                self._client = boto3.client(
                    "bedrock-runtime", region_name=self._region, config=boto_cfg
                )
            logger.info("Bedrock provider configured (model=%s)", self._model_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to initialize Bedrock provider: %s", exc)
            self._client = None

    def is_available(self) -> bool:
        """Return whether the ``bedrock-runtime`` client was built (Req 12.5).

        Explicit keys are NOT required (an IAM role / instance profile is a
        valid credential source). A missing region with no resolvable default
        causes the client build to fail, which correctly yields unavailable.
        """
        return self._client is not None

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        """Call Bedrock (Converse API) and parse into an :class:`ExtractedRequest`.

        Raises :class:`AIProviderError` when the provider is unavailable
        (Req 12.5) or the Converse request fails. Parsing computes no bitmasks
        (Req 3.2) and preserves ``raw_message`` (Req 3.8).
        """
        if not self.is_available():
            raise AIProviderError("Bedrock provider is not available")

        prompt = _build_prompt(message, ctx)
        try:
            resp = self._client.converse(  # type: ignore[union-attr]
                modelId=self._model_name,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={
                    "temperature": _TEMPERATURE,
                    "maxTokens": _MAX_TOKENS,
                },
            )
        except Exception as exc:
            raise AIProviderError(f"Bedrock request failed: {exc}") from exc

        text = _extract_converse_text(resp)
        return parse_response_text(text, message)
