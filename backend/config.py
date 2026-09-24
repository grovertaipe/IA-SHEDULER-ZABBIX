"""Single configuration module (Req 1.3).

Loads all configuration (Zabbix URL/token, AI provider and keys/models, CORS
allowed origins, version) plus the extended cross-cutting fields (localization,
AI failover, user-cache TTL, rate limiting and AI-schema validation) from
environment variables. No secrets are hard-coded here, and no secret *values*
are ever written to the logs (Req 18.4, 18.5).

Environment variables (legacy-compatible where possible):

Base configuration:

* ``ZABBIX_API_URL``          -> ``zabbix_url``
* ``ZABBIX_TOKEN``            -> ``zabbix_token``
* ``AI_PROVIDER``             -> ``ai_provider`` ("gemini" | "openai" | "bedrock")
* ``GOOGLE_API_KEY``          -> ``gemini_api_key``
* ``GEMINI_MODEL``            -> ``gemini_model``
* ``OPENAI_API_KEY``          -> ``openai_api_key``
* ``OPENAI_MODEL``            -> ``openai_model``
* ``BEDROCK_MODEL``           -> ``bedrock_model`` (Converse API model id;
  default ``amazon.nova-lite-v1:0``)
* ``AWS_REGION``              -> ``aws_region`` (``AWS_DEFAULT_REGION`` accepted
  as a fallback; where Bedrock + the model are enabled)
* ``AWS_ACCESS_KEY_ID``       -> ``aws_access_key_id`` (optional; leave unset to
  use the default AWS credential chain / IAM role)
* ``AWS_SECRET_ACCESS_KEY``   -> ``aws_secret_access_key`` (optional)
* ``AWS_SESSION_TOKEN``       -> ``aws_session_token`` (optional)
* ``AWS_BEARER_TOKEN_BEDROCK`` -> ``aws_bearer_token_bedrock`` (optional SECRET;
  the Amazon Bedrock **API key** / bearer token. When set, boto3 uses it
  automatically for the ``bedrock-runtime`` client and explicit
  ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` are NOT needed — only a
  region is still required. Read but never logged, Req 18.4)
* ``CORS_ALLOWED_ORIGINS``    -> ``cors_allowed_origins`` (comma-separated,
  explicit origins only; the wildcard ``*`` is rejected, Req 15.5)
* ``APP_VERSION``             -> ``version`` (authoritative value injected at
  image build time from the git tag; falls back to the ``APP_VERSION`` module
  constant, then ``DEFAULT_VERSION``)

Extended configuration (all non-secret; documented in ``.env.example``,
Req 18.3). Numeric values are parsed defensively and fall back to their safe
default on a malformed value (only the offending KEY name is logged):

* ``SUPPORTED_LOCALES``          -> ``supported_locales`` (comma-separated;
  default ``"es,en"``; ``"es"`` is always included, Req 21.4)
* ``DEFAULT_LOCALE``             -> ``default_locale`` (default ``"es"``;
  coerced back to ``"es"`` when unsupported, Req 21.5, 21.6)
* ``AI_SECONDARY_PROVIDER``      -> ``ai_secondary_provider`` (optional, default
  ``None``, Req 26.1, 26.4)
* ``AI_FAILOVER_MAX_RETRIES``    -> ``ai_failover_max_retries`` (int, default
  ``1``, Req 26.2)
* ``AI_FAILOVER_TIMEOUT_SECONDS`` -> ``ai_failover_timeout_seconds`` (float,
  default ``30.0``, Req 26.2)
* ``AI_REQUEST_TIMEOUT_SECONDS``  -> ``ai_request_timeout_seconds`` (float,
  default ``20.0``): per-attempt NETWORK timeout applied to a single provider
  SDK call so a hung read raises quickly instead of stalling the worker. It
  MUST be less than the gunicorn worker timeout.
* ``USER_CACHE_TTL_SECONDS``     -> ``user_cache_ttl_seconds`` (int, default
  ``300``, Req 27.1)
* ``RATE_LIMIT_MAX_REQUESTS``    -> ``rate_limit_max_requests`` (int, default
  ``60``, Req 28.1)
* ``RATE_LIMIT_WINDOW_SECONDS``  -> ``rate_limit_window_seconds`` (int, default
  ``60``, Req 28.1)
* ``AI_SCHEMA_MAX_ATTEMPTS``     -> ``ai_schema_max_attempts`` (int, default
  ``2``, Req 29.2)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

VALID_AI_PROVIDERS = ("gemini", "openai", "bedrock")

DEFAULT_GEMINI_MODEL = "gemini-flash-lite-latest"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_BEDROCK_MODEL = "amazon.nova-lite-v1:0"
DEFAULT_VERSION = "unknown"

#: Last-resort fallback for the application version (Req 16.1). The
#: AUTHORITATIVE version is injected at image build time via the ``APP_VERSION``
#: environment variable (Dockerfile ``ARG``/``ENV`` fed by the CI build-arg,
#: which uses the git tag). ``_resolve_version()`` reads env ``APP_VERSION``
#: first, so this constant only applies when neither the baked env value nor a
#: manual override is present (e.g. local runs). Kept in step with the current
#: release so a bare local run is not misleading.
APP_VERSION = "2.5.1"

# --- Extended configuration defaults (safe fallbacks) ---------------------

#: Default locale; Spanish is the guaranteed baseline (Req 21.5, 21.6).
DEFAULT_LOCALE = "es"
#: Locales supported out of the box; ``"es"`` is always kept (Req 21.4).
DEFAULT_SUPPORTED_LOCALES = ("es", "en", "pt")

#: Failover tuning (Req 26.2, 26.4). Mirrors ``ai/factory.py`` defaults.
DEFAULT_AI_FAILOVER_MAX_RETRIES = 1
DEFAULT_AI_FAILOVER_TIMEOUT_SECONDS = 30.0

#: Per-attempt NETWORK timeout for a single provider SDK call. Applied at the
#: SDK/transport layer so a hung network read raises promptly (as an
#: ``AIProviderError``) instead of stalling the gunicorn worker until it is
#: killed. MUST be well below the gunicorn worker ``--timeout``.
DEFAULT_AI_REQUEST_TIMEOUT_SECONDS = 20.0

#: User-validation cache TTL in seconds (Req 27.1).
DEFAULT_USER_CACHE_TTL_SECONDS = 300

#: Rate-limit window defaults (Req 28.1).
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60

#: AI-schema validation attempts (Req 29.2).
DEFAULT_AI_SCHEMA_MAX_ATTEMPTS = 2


def _parse_locales(raw: str) -> list[str]:
    """Parse a comma-separated locale list, lower-cased and de-duplicated.

    Whitespace is stripped and empty entries dropped. Spanish (``"es"``) is
    always present (Req 21.4). On an empty/absent value the built-in default
    list is returned. Order is preserved with ``"es"`` guaranteed first.
    """
    parsed = [loc.strip().lower() for loc in raw.split(",") if loc.strip()]
    if not parsed:
        parsed = list(DEFAULT_SUPPORTED_LOCALES)
    # Guarantee "es" is present (Req 21.4) and de-duplicate preserving order.
    ordered = [DEFAULT_LOCALE] + [loc for loc in parsed if loc != DEFAULT_LOCALE]
    seen: set[str] = set()
    result: list[str] = []
    for loc in ordered:
        if loc not in seen:
            seen.add(loc)
            result.append(loc)
    return result


def _parse_int(key: str, default: int) -> int:
    """Read an int env var defensively; fall back to ``default`` on bad input.

    Logs only the offending KEY name (never the value) so no secrets or noisy
    payloads leak into the logs (Req 18.4).
    """
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.error("Invalid integer for environment variable %s; using default", key)
        return default


def _parse_float(key: str, default: float) -> float:
    """Read a float env var defensively; fall back to ``default`` on bad input.

    Logs only the offending KEY name (never the value) (Req 18.4).
    """
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.error("Invalid float for environment variable %s; using default", key)
        return default


def _resolve_version() -> str:
    """Resolve the application version defensively.

    Prefers the ``APP_VERSION`` environment variable — the AUTHORITATIVE source
    in normal operation, baked into the image at build time from the git tag
    (Dockerfile build-arg fed by CI). Falls back to the :data:`APP_VERSION`
    module constant (a last-resort default for local runs), then to the safe
    :data:`DEFAULT_VERSION`. Never raises.
    """
    env_version = os.environ.get("APP_VERSION", "").strip()
    if env_version:
        return env_version
    return APP_VERSION or DEFAULT_VERSION


def _parse_cors_origins(raw: str) -> list[str]:
    """Parse a comma-separated list of allowed origins.

    Whitespace around each origin is stripped and empty entries are dropped.
    The wildcard ``*`` is not an allowed origin (Req 15.5); it is filtered out
    and reported by the caller.
    """
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration (Req 1.3).

    All values originate from environment variables via :meth:`from_env`. No
    secret values are stored anywhere other than these fields, and none are
    logged (Req 18.4, 18.5).
    """

    zabbix_url: str
    zabbix_token: str
    ai_provider: str  # "gemini" | "openai" | "bedrock" (Req 12.1)
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    openai_model: str
    # --- Amazon Bedrock (Req 12.7) ---
    bedrock_model: str  # Converse API model id (default amazon.nova-lite-v1:0)
    aws_region: str | None  # region where Bedrock + the model are enabled
    aws_access_key_id: str | None  # optional; default chain / IAM role otherwise
    aws_secret_access_key: str | None  # optional
    aws_session_token: str | None  # optional (temporary credentials)
    aws_bearer_token_bedrock: str | None  # optional Bedrock API key (bearer token)
    cors_allowed_origins: list[str]  # Req 15.5 (explicit origins, not wildcard)
    version: str

    # --- Localization (Req 21) ---
    supported_locales: list[str]  # e.g. ["es", "en"]; always includes "es" (Req 21.4)
    default_locale: str  # default "es" (Req 21.5, 21.6)

    # --- AI failover (Req 26) ---
    ai_secondary_provider: str | None  # optional secondary provider (Req 26.1, 26.4)
    ai_failover_max_retries: int  # bounded retries per provider (Req 26.2)
    ai_failover_timeout_seconds: float  # per-attempt time budget (Req 26.2)
    ai_request_timeout_seconds: float  # per-attempt NETWORK timeout for one SDK call

    # --- User-validation cache (Req 27) ---
    user_cache_ttl_seconds: int  # configurable TTL_Cache (Req 27.1)

    # --- Rate limiting (Req 28) ---
    rate_limit_max_requests: int  # requests allowed per window (Req 28.1)
    rate_limit_window_seconds: int  # window size in seconds (Req 28.1)

    # --- AI-schema validation (Req 29) ---
    ai_schema_max_attempts: int  # max validation attempts before failing (Req 29.2)

    @staticmethod
    def from_env() -> AppConfig:
        """Load and validate configuration from environment variables.

        Errors are logged by naming the missing/invalid environment *key* only;
        secret *values* are never written to the logs (Req 18.4). The method is
        tolerant: it always returns an :class:`AppConfig` so callers (for
        example the ``/health`` endpoint) can surface a degraded state rather
        than crash on import.
        """
        env = os.environ

        zabbix_url = env.get("ZABBIX_API_URL", "").strip()
        zabbix_token = env.get("ZABBIX_TOKEN", "").strip()

        if not zabbix_url:
            logger.error("Missing required environment variable: ZABBIX_API_URL")
        if not zabbix_token:
            logger.error("Missing required environment variable: ZABBIX_TOKEN")

        ai_provider = env.get("AI_PROVIDER", "gemini").strip().lower()
        if ai_provider not in VALID_AI_PROVIDERS:
            logger.error(
                "Unsupported AI provider in AI_PROVIDER: %r (expected one of %s)",
                ai_provider,
                ", ".join(VALID_AI_PROVIDERS),
            )

        # Secrets: read but never log the values (Req 18.4).
        gemini_api_key = env.get("GOOGLE_API_KEY", "").strip() or None
        gemini_model = env.get("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL
        openai_api_key = env.get("OPENAI_API_KEY", "").strip() or None
        openai_model = env.get("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL

        # Amazon Bedrock (Req 12.7). AWS_REGION preferred; AWS_DEFAULT_REGION is
        # accepted as a fallback. Keys/token are optional (default credential
        # chain / IAM role). Secrets are read but never logged (Req 18.4).
        bedrock_model = env.get("BEDROCK_MODEL", "").strip() or DEFAULT_BEDROCK_MODEL
        aws_region = (
            env.get("AWS_REGION", "").strip()
            or env.get("AWS_DEFAULT_REGION", "").strip()
            or None
        )
        aws_access_key_id = env.get("AWS_ACCESS_KEY_ID", "").strip() or None
        aws_secret_access_key = env.get("AWS_SECRET_ACCESS_KEY", "").strip() or None
        aws_session_token = env.get("AWS_SESSION_TOKEN", "").strip() or None
        # Bedrock API key (bearer token). SECRET: read but never logged (Req 18.4).
        # When set, boto3 uses it automatically for the bedrock-runtime client and
        # explicit AWS access keys are not required (only a region is).
        aws_bearer_token_bedrock = (
            env.get("AWS_BEARER_TOKEN_BEDROCK", "").strip() or None
        )

        # Validate that the selected provider has its API key configured. Log the
        # missing KEY name only, never the (absent) value (Req 18.4).
        if ai_provider == "gemini" and gemini_api_key is None:
            logger.error(
                "Missing API key for AI provider 'gemini': set GOOGLE_API_KEY"
            )
        elif ai_provider == "openai" and openai_api_key is None:
            logger.error(
                "Missing API key for AI provider 'openai': set OPENAI_API_KEY"
            )
        elif (
            ai_provider == "bedrock"
            and aws_bearer_token_bedrock is None
            and aws_access_key_id is None
            and aws_region is None
        ):
            # Soft validation only (no raise): boto3 may still resolve creds and
            # region from ~/.aws or an IAM role. A Bedrock API key (bearer token)
            # alone plus a region is also a fully valid setup, so this warning is
            # suppressed whenever AWS_BEARER_TOKEN_BEDROCK is present. Log the
            # missing KEY names only, never any (absent) value (Req 18.4).
            logger.error(
                "AI provider 'bedrock' has no Bedrock API key, no explicit AWS "
                "credentials nor a region; set AWS_REGION (or AWS_DEFAULT_REGION) "
                "and either AWS_BEARER_TOKEN_BEDROCK (API key) or "
                "AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY, or rely on the "
                "default AWS credential chain / IAM role"
            )

        raw_cors = env.get("CORS_ALLOWED_ORIGINS", "")
        cors_allowed_origins = _parse_cors_origins(raw_cors)
        if "*" in cors_allowed_origins:
            # The wildcard is not a valid explicit origin (Req 15.5).
            logger.error(
                "Wildcard '*' is not allowed in CORS_ALLOWED_ORIGINS; "
                "list explicit origins instead"
            )
            cors_allowed_origins = [
                origin for origin in cors_allowed_origins if origin != "*"
            ]
        if not cors_allowed_origins:
            logger.error(
                "No CORS origins configured; set CORS_ALLOWED_ORIGINS to a "
                "comma-separated list of explicit origins"
            )

        # --- Localization (Req 21.4, 21.5, 21.6) ---
        supported_locales = _parse_locales(env.get("SUPPORTED_LOCALES", ""))
        default_locale = env.get("DEFAULT_LOCALE", "").strip().lower() or DEFAULT_LOCALE
        if default_locale not in supported_locales:
            # Degrade silently to the guaranteed baseline locale (Req 21.5, 21.6).
            logger.error(
                "DEFAULT_LOCALE %r is not in SUPPORTED_LOCALES; falling back to %r",
                default_locale,
                DEFAULT_LOCALE,
            )
            default_locale = DEFAULT_LOCALE

        # --- AI failover (Req 26.1, 26.2, 26.4) ---
        ai_secondary_provider = env.get("AI_SECONDARY_PROVIDER", "").strip().lower() or None
        if (
            ai_secondary_provider is not None
            and ai_secondary_provider not in VALID_AI_PROVIDERS
        ):
            logger.error(
                "Unsupported AI provider in AI_SECONDARY_PROVIDER: %r "
                "(expected one of %s)",
                ai_secondary_provider,
                ", ".join(VALID_AI_PROVIDERS),
            )
        ai_failover_max_retries = _parse_int(
            "AI_FAILOVER_MAX_RETRIES", DEFAULT_AI_FAILOVER_MAX_RETRIES
        )
        ai_failover_timeout_seconds = _parse_float(
            "AI_FAILOVER_TIMEOUT_SECONDS", DEFAULT_AI_FAILOVER_TIMEOUT_SECONDS
        )
        ai_request_timeout_seconds = _parse_float(
            "AI_REQUEST_TIMEOUT_SECONDS", DEFAULT_AI_REQUEST_TIMEOUT_SECONDS
        )

        # --- User-validation cache (Req 27.1) ---
        user_cache_ttl_seconds = _parse_int(
            "USER_CACHE_TTL_SECONDS", DEFAULT_USER_CACHE_TTL_SECONDS
        )

        # --- Rate limiting (Req 28.1) ---
        rate_limit_max_requests = _parse_int(
            "RATE_LIMIT_MAX_REQUESTS", DEFAULT_RATE_LIMIT_MAX_REQUESTS
        )
        rate_limit_window_seconds = _parse_int(
            "RATE_LIMIT_WINDOW_SECONDS", DEFAULT_RATE_LIMIT_WINDOW_SECONDS
        )

        # --- AI-schema validation (Req 29.2) ---
        ai_schema_max_attempts = _parse_int(
            "AI_SCHEMA_MAX_ATTEMPTS", DEFAULT_AI_SCHEMA_MAX_ATTEMPTS
        )

        return AppConfig(
            zabbix_url=zabbix_url,
            zabbix_token=zabbix_token,
            ai_provider=ai_provider,
            gemini_api_key=gemini_api_key,
            gemini_model=gemini_model,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            bedrock_model=bedrock_model,
            aws_region=aws_region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
            aws_bearer_token_bedrock=aws_bearer_token_bedrock,
            cors_allowed_origins=cors_allowed_origins,
            version=_resolve_version(),
            supported_locales=supported_locales,
            default_locale=default_locale,
            ai_secondary_provider=ai_secondary_provider,
            ai_failover_max_retries=ai_failover_max_retries,
            ai_failover_timeout_seconds=ai_failover_timeout_seconds,
            ai_request_timeout_seconds=ai_request_timeout_seconds,
            user_cache_ttl_seconds=user_cache_ttl_seconds,
            rate_limit_max_requests=rate_limit_max_requests,
            rate_limit_window_seconds=rate_limit_window_seconds,
            ai_schema_max_attempts=ai_schema_max_attempts,
        )
