"""Failover de proveedores de IA (Req 26, 29).

La **decisión** de qué proveedor debe atender una solicitud es una función pura
y determinista (:func:`select_provider`); no realiza E/S y no depende de Flask,
del proveedor de IA ni de la red. La **ejecución** con efectos
(:class:`FailoverAIProvider`: reintentos acotados, tiempo límite best-effort,
validación de esquema y logging) es una capa de orquestación / frontera de E/S:
delega en los proveedores concretos (que envuelven sus propios SDK) y consume la
decisión pura de :func:`select_provider` para conmutar del primario al
secundario.

Contenido del módulo:
    * :data:`Selection` — alias de tipo del resultado de la decisión;
    * :func:`select_provider` — decisión pura de failover según la tabla de
      disponibilidad (Req 26.1, 26.3, 26.4);
    * :class:`FailoverAIProvider` — orquestador con reintentos, validación de
      esquema y degradación localizada (Req 26.1-26.5, 29.2, 29.3).

Principio de diseño (Req 29.3): cuando la respuesta de IA no supera la
validación de esquema tras agotar los reintentos, se lanza
:class:`~ai.provider.AIProviderError` con el mensaje "invalid AI response" y
**nunca** se invoca ``build_timeperiod`` (este módulo no lo importa).
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Literal

from core.domain import ConversationTurn, ExtractedRequest, PromptContext
from observability.logger import SecureLogger

from .provider import AIProvider, AIProviderError
from .schema import validate_against_schema

Selection = Literal["primary", "secondary", "unavailable"]


def select_provider(
    primary_ok: bool, has_secondary: bool, secondary_ok: bool
) -> Selection:
    """Decide qué proveedor debe atender la solicitud (Req 26.1, 26.3, 26.4).

    Función pura y determinista según la tabla de disponibilidad:

    * ``primary_ok`` -> ``"primary"``
    * ``not primary_ok and has_secondary and secondary_ok`` -> ``"secondary"``
    * en cualquier otro caso -> ``"unavailable"``

    No realiza E/S; describe únicamente cuál proveedor debe atender la
    solicitud.
    """
    if primary_ok:
        return "primary"
    if has_secondary and secondary_ok:
        return "secondary"
    return "unavailable"


# --------------------------------------------------------------------------- #
# Localized unavailability message (Req 26.3)                                 #
# --------------------------------------------------------------------------- #
#: Plain fallback used when the i18n catalog / ``get_message`` is not available
#: yet (Task 18.3 may not have run). Matches the intent of the ``es`` catalog's
#: ``error.ai_unavailable`` key.
_UNAVAILABLE_FALLBACK = (
    "El asistente de IA no está disponible en este momento. "
    "Inténtalo de nuevo más tarde."
)

#: Message key looked up in the i18n catalog when available (Req 21.4).
_UNAVAILABLE_MESSAGE_KEY = "error.ai_unavailable"


def _unavailable_message(locale: str) -> str:
    """Return the localized AI-unavailability message (Req 26.3).

    Uses :func:`i18n.messages.get_message` when that module is available;
    otherwise degrades to the plain Spanish fallback. The i18n module is
    imported defensively because it may not be implemented yet (Task 18.3), so
    this orchestrator never hard-fails on a missing localization layer.
    """
    try:
        from i18n.messages import get_message
    except (ImportError, AttributeError):
        return _UNAVAILABLE_FALLBACK
    try:
        return get_message(_UNAVAILABLE_MESSAGE_KEY, locale)
    except Exception:  # pragma: no cover - defensive: never fail on i18n lookup
        return _UNAVAILABLE_FALLBACK


class FailoverAIProvider(AIProvider):
    """Orchestrating :class:`AIProvider` with retries, failover and schema checks.

    This is a boundary / orchestration component (its effects come from the
    wrapped providers' SDK calls); the *decision* of which provider to use is
    delegated to the pure :func:`select_provider`.

    Behaviour of :meth:`extract` (Req 26, 29):

    1. Attempt the **primary** provider, retrying transient
       :class:`~ai.provider.AIProviderError` failures up to ``max_retries``
       additional times (``1 + max_retries`` attempts total). ``timeout_s`` is
       a best-effort budget across those attempts — see the note below.
    2. Each successful extraction is validated against the AI JSON schema
       (:func:`~ai.schema.validate_against_schema`). An invalid response is
       retried up to ``schema_max_attempts`` times; if every attempt is invalid
       the method raises ``AIProviderError("invalid AI response: ...")`` and
       **never** invokes ``build_timeperiod`` (Req 29.2, 29.3).
    3. If the primary is exhausted (unavailable, repeated errors or
       repeatedly schema-invalid), :func:`select_provider` decides whether to
       switch to the **secondary**. When the decision is ``"secondary"`` the
       secondary is attempted with the same retry + schema-validation loop.
    4. When neither provider can serve the request the decision is
       ``"unavailable"`` and the method raises ``AIProviderError`` carrying the
       **localized** unavailability message (Req 26.3), so the service layer
       degrades gracefully instead of leaking a raw SDK/parse error.

    Every failover-relevant event (primary failure, schema exhaustion, switch to
    secondary, final unavailability) is logged via :class:`SecureLogger`, which
    masks any sensitive field — no secrets are ever logged (Req 26.5).

    Note on ``timeout_s``:
        The concrete providers wrap **synchronous** SDK calls, so a hard
        interrupt of an in-flight request is not portable to enforce here.
        ``timeout_s`` is therefore treated as a best-effort *budget*: before
        each attempt the elapsed wall-clock time is compared against it, and no
        further attempt is started once the budget is exceeded. A single call
        already in progress is allowed to finish. This is documented and
        deliberate rather than a hard per-call deadline.
    """

    def __init__(
        self,
        primary: AIProvider,
        secondary: AIProvider | None = None,
        max_retries: int = 1,
        timeout_s: float = 30.0,
        schema_max_attempts: int = 2,
        logger: SecureLogger | None = None,
    ) -> None:
        """Configure the failover orchestrator.

        Args:
            primary: The preferred provider (tried first).
            secondary: Optional fallback provider used when the primary is
                unavailable or keeps failing (Req 26.1).
            max_retries: Number of *additional* attempts on a provider after the
                first one (``1 + max_retries`` attempts total per provider).
                Negative values are clamped to ``0``.
            timeout_s: Best-effort wall-clock budget (seconds) across the
                attempts of a single :meth:`extract` call. See the class note.
            schema_max_attempts: Maximum number of extractions validated against
                the schema per provider before giving up on it (Req 29.2).
                Values below ``1`` are clamped to ``1``.
            logger: :class:`SecureLogger` used to record failover events without
                secrets (Req 26.5). A default instance is created when omitted.
        """
        self._primary = primary
        self._secondary = secondary
        self._max_retries = max(0, max_retries)
        self._timeout_s = float(timeout_s)
        self._schema_max_attempts = max(1, schema_max_attempts)
        self._logger = logger or SecureLogger()

    # ------------------------------------------------------------------ #
    # AIProvider interface                                               #
    # ------------------------------------------------------------------ #
    def is_available(self) -> bool:
        """Return ``True`` if the primary or the secondary is available (Req 26.4)."""
        if self._primary.is_available():
            return True
        return self._secondary is not None and self._secondary.is_available()

    def extract(
        self,
        message: str,
        ctx: PromptContext,
        history: list[ConversationTurn] | None = None,
        locale: str = "es",
    ) -> ExtractedRequest:
        """Extract with retries, schema validation and failover (Req 26, 29).

        ``history`` (optional) are the prior turns of the same maintenance
        conversation; they are forwarded verbatim to whichever wrapped provider
        serves the request so the model can merge fields across turns.

        ``locale`` selects the language of the degradation message raised when
        no provider can serve the request (Req 26.3); it defaults to the product
        default (``"es"``) so the base :class:`AIProvider` signature stays
        satisfiable.

        Raises:
            AIProviderError: with the localized unavailability message when both
                providers are exhausted (Req 26.3), or with ``"invalid AI
                response"`` when the schema never validates (Req 29.3). In
                neither case is ``build_timeperiod`` invoked.
        """
        started = time.monotonic()

        primary_ok = self._primary.is_available()
        has_secondary = self._secondary is not None
        secondary_ok = has_secondary and self._secondary is not None and (
            self._secondary.is_available()
        )

        # --- Attempt the primary when it is available -------------------- #
        if primary_ok:
            result = self._run_provider(
                self._primary, "primary", message, ctx, started, history
            )
            if result is not None:
                return result
            # Primary attempted but could not produce a valid response.
            primary_ok = False

        # --- Decide whether to fail over to the secondary --------------- #
        selection = select_provider(primary_ok, has_secondary, secondary_ok)
        if selection == "secondary" and self._secondary is not None:
            self._logger.info(
                "ai_failover_switch",
                from_provider="primary",
                to_provider="secondary",
            )
            result = self._run_provider(
                self._secondary, "secondary", message, ctx, started, history
            )
            if result is not None:
                return result

        # --- Nothing could serve the request: degrade (Req 26.3) -------- #
        self._logger.error(
            "ai_failover_unavailable",
            primary_available=self._primary.is_available(),
            has_secondary=has_secondary,
            secondary_available=secondary_ok,
        )
        raise AIProviderError(_unavailable_message(locale))

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _run_provider(
        self,
        provider: AIProvider,
        label: str,
        message: str,
        ctx: PromptContext,
        started: float,
        history: list[ConversationTurn] | None = None,
    ) -> ExtractedRequest | None:
        """Run one provider with the retry + schema-validation loop.

        Returns the validated :class:`ExtractedRequest` on success, or ``None``
        when this provider could not produce a schema-valid response within its
        retry / attempt budget (the caller then decides on failover). Never
        raises the raw provider/parse error to the caller and never invokes
        ``build_timeperiod`` on a schema failure (Req 29.3).

        The two budgets compose as follows: at most ``schema_max_attempts``
        extractions are validated against the schema; independently, a single
        extraction is retried up to ``1 + max_retries`` times when the provider
        raises :class:`AIProviderError` (transient SDK/parse failure).
        """
        last_schema_fields: list[str] = []
        for schema_attempt in range(1, self._schema_max_attempts + 1):
            if self._budget_exceeded(started):
                self._logger.error(
                    "ai_failover_timeout",
                    provider=label,
                    timeout_s=self._timeout_s,
                    schema_attempt=schema_attempt,
                )
                return None

            extracted = self._extract_with_retries(
                provider, label, message, ctx, started, history
            )
            if extracted is None:
                # The provider kept raising errors across all retries.
                return None

            valid, offending_fields = validate_against_schema(_to_schema_dict(extracted))
            if valid:
                return extracted

            last_schema_fields = offending_fields
            self._logger.info(
                "ai_schema_invalid",
                provider=label,
                schema_attempt=schema_attempt,
                offending_fields=offending_fields,
            )

        # Schema never validated across all attempts (Req 29.2, 29.3): report an
        # error WITHOUT invoking build_timeperiod. Returning None lets the caller
        # try the secondary; when this is the last provider the caller degrades.
        self._logger.error(
            "ai_schema_exhausted",
            provider=label,
            offending_fields=last_schema_fields,
        )
        return None

    def _extract_with_retries(
        self,
        provider: AIProvider,
        label: str,
        message: str,
        ctx: PromptContext,
        started: float,
        history: list[ConversationTurn] | None = None,
    ) -> ExtractedRequest | None:
        """Call ``provider.extract`` retrying transient errors (Req 26.2).

        Retries up to ``1 + max_retries`` attempts, catching
        :class:`AIProviderError`. Returns the raw (not yet schema-validated)
        :class:`ExtractedRequest`, or ``None`` when every attempt failed or the
        time budget is exhausted. Logs each failure without secrets (Req 26.5).
        """
        for attempt in range(1, self._max_retries + 2):
            if self._budget_exceeded(started):
                self._logger.error(
                    "ai_failover_timeout",
                    provider=label,
                    timeout_s=self._timeout_s,
                    attempt=attempt,
                )
                return None
            try:
                return provider.extract(message, ctx, history)
            except AIProviderError as exc:
                self._logger.error(
                    "ai_provider_error",
                    provider=label,
                    attempt=attempt,
                    error=str(exc),
                )
        return None

    def _budget_exceeded(self, started: float) -> bool:
        """Return whether the best-effort time budget has been exhausted.

        A non-positive ``timeout_s`` disables the budget (no attempt is skipped
        on time grounds); otherwise the elapsed wall-clock time since ``started``
        is compared against it. See the class note on ``timeout_s``.
        """
        if self._timeout_s <= 0:
            return False
        return (time.monotonic() - started) >= self._timeout_s


def _to_schema_dict(request: ExtractedRequest) -> dict:
    """Serialize an :class:`ExtractedRequest` to a plain dict for validation.

    Uses :func:`dataclasses.asdict` so nested dataclasses (``recurrence``,
    ``problem_tags``) become plain dicts. Enum-valued fields (e.g.
    ``recurrence_type``) are normalized to their ``value`` so the JSON-schema
    ``enum``/type checks operate on JSON-native scalars rather than enum
    objects. Pure and side-effect free.
    """
    data = asdict(request)
    recurrence = data.get("recurrence")
    if isinstance(recurrence, dict):
        rec_type = recurrence.get("recurrence_type")
        if rec_type is not None and hasattr(rec_type, "value"):
            recurrence["recurrence_type"] = rec_type.value
        # Sets are not JSON types; normalize day/month/occurrence sets to lists.
        for key in ("days", "months", "occurrences"):
            value = recurrence.get(key)
            if isinstance(value, set):
                recurrence[key] = sorted(value)
    return data
