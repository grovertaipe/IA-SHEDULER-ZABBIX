"""Provider factory: build the configured AI provider stack (Req 12, 26).

:func:`build_provider` reads the :class:`~config.AppConfig`, constructs the
**primary** provider selected by ``cfg.ai_provider`` (``gemini`` / ``openai`` /
``bedrock``),
optionally constructs a **secondary** provider from ``cfg.ai_secondary_provider``
(when set and different), and wraps both in a :class:`~ai.failover.FailoverAIProvider`
so callers always get a single :class:`~ai.provider.AIProvider` that transparently
fails over and validates responses against the AI schema (Req 12.1, 26.1).

An unsupported provider value is logged as "unsupported provider" via the
:class:`~observability.logger.SecureLogger` (no secrets) and yields an
unavailable provider for that slot; a missing API key leaves the concrete
provider unavailable (handled inside the providers, Req 12.5/12.6).

Failover / schema-validation tuning fields (``ai_secondary_provider``,
``ai_failover_max_retries``, ``ai_failover_timeout_seconds``,
``ai_schema_max_attempts``) are added to :class:`AppConfig` in a later task
(17.1); they are read **defensively** with :func:`getattr` and safe defaults so
this factory works whether or not that task has run.

Requirements: 12.1, 12.2, 12.3, 12.6, 26.1.
"""

from __future__ import annotations

from config import AppConfig
from core.domain import ExtractedRequest, PromptContext
from observability.logger import SecureLogger

from .bedrock_provider import BedrockProvider
from .failover import FailoverAIProvider
from .gemini_provider import GeminiProvider
from .openai_provider import OpenAIProvider
from .provider import AIProvider, AIProviderError

__all__ = ["build_provider", "build_single_provider"]

#: Recognized provider identifiers (Req 12.1).
_VALID_PROVIDERS = ("gemini", "openai", "bedrock")

# Defaults applied when the extended failover/schema config fields are absent
# (Task 17.1 not yet run). Kept conservative: one retry, a 30s best-effort
# budget and two schema attempts (Req 26.2, 26.4, 29.2).
_DEFAULT_MAX_RETRIES = 1
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_SCHEMA_MAX_ATTEMPTS = 2


def build_single_provider(
    name: str | None, cfg: AppConfig, logger: SecureLogger
) -> AIProvider | None:
    """Build one concrete provider by name, or ``None`` when unusable.

    Returns a :class:`GeminiProvider` / :class:`OpenAIProvider` /
    :class:`BedrockProvider` for a recognized ``name``. An empty/``None`` name
    yields ``None`` (no provider configured for that slot). An unrecognized name
    is logged as "unsupported provider" and yields ``None`` (Req 12.6). The
    concrete providers stay *unavailable* when their credentials are missing
    (Req 12.5); the factory does not raise.
    """
    if not name:
        return None
    key = name.strip().lower()
    if key == "gemini":
        return GeminiProvider(cfg.gemini_api_key, cfg.gemini_model)
    if key == "openai":
        return OpenAIProvider(cfg.openai_api_key, cfg.openai_model)
    if key == "bedrock":
        return BedrockProvider(
            cfg.bedrock_model,
            cfg.aws_region,
            cfg.aws_access_key_id,
            cfg.aws_secret_access_key,
            cfg.aws_session_token,
        )
    logger.error("unsupported provider", provider=key, expected=list(_VALID_PROVIDERS))
    return None


class _UnavailableProvider(AIProvider):
    """Null-object provider used when no primary can be built (Req 12.6).

    Always unavailable; :meth:`extract` raises so the failover layer degrades
    gracefully with its localized message rather than crashing on import.
    """

    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        """Always fail: no usable provider is configured."""
        raise AIProviderError("no AI provider configured")

    def is_available(self) -> bool:
        """Always ``False``: this slot has no usable provider."""
        return False


def build_provider(cfg: AppConfig, logger: SecureLogger | None = None) -> AIProvider:
    """Build the primary + optional secondary and wrap them in failover (Req 12.1, 26.1).

    The primary is selected by ``cfg.ai_provider``; the optional secondary by
    ``cfg.ai_secondary_provider`` (read defensively; ignored when unset or equal
    to the primary). Both are wrapped in a :class:`FailoverAIProvider` tuned by
    the failover/schema config fields (also read defensively with safe
    defaults). Always returns a single usable :class:`AIProvider`; unsupported
    values are logged (Req 12.6) and never raise here.
    """
    secure_logger = logger or SecureLogger()

    primary = build_single_provider(cfg.ai_provider, cfg, secure_logger)
    if primary is None:
        # No usable primary (unsupported value or empty): degrade to a null
        # provider so the wrapper still yields the localized unavailability
        # message instead of failing (Req 12.6).
        primary = _UnavailableProvider()

    secondary_name = getattr(cfg, "ai_secondary_provider", None)
    secondary: AIProvider | None = None
    if secondary_name and secondary_name.strip().lower() != cfg.ai_provider.strip().lower():
        secondary = build_single_provider(secondary_name, cfg, secure_logger)

    max_retries = int(getattr(cfg, "ai_failover_max_retries", _DEFAULT_MAX_RETRIES))
    timeout_s = float(
        getattr(cfg, "ai_failover_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    )
    schema_max_attempts = int(
        getattr(cfg, "ai_schema_max_attempts", _DEFAULT_SCHEMA_MAX_ATTEMPTS)
    )

    return FailoverAIProvider(
        primary=primary,
        secondary=secondary,
        max_retries=max_retries,
        timeout_s=timeout_s,
        schema_max_attempts=schema_max_attempts,
        logger=secure_logger,
    )
