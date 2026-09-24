"""ChatService — orquestación de la interpretación conversacional (Task 10.1).

Este servicio es la **capa de orquestación** que se sitúa entre la capa HTTP y
el núcleo puro / el ``Proveedor_IA``. Su responsabilidad es interpretar el
mensaje del usuario y devolver una respuesta conversacional estructurada, sin
tomar por sí mismo ninguna decisión de cálculo de recurrencia (eso es del
``MaintenanceService`` + ``Motor_Recurrencia``, Task 10.2 / Task 4).

Responsabilidades (según design.md "services/chat_service.py"):

* Construir el :class:`~core.domain.PromptContext` (hoy / mañana en ISO 8601) e
  invocar ``provider.extract(message, ctx)`` para obtener un
  :class:`~core.domain.ExtractedRequest` **sin bitmasks** (Req 3.2).
* Completar el ``Numero_Ticket`` detectado localmente cuando el proveedor no lo
  incluyó: si ``ExtractedRequest.ticket is None`` se ejecuta
  :func:`core.domain.extract_ticket` sobre el mensaje y se incorpora el ticket
  hallado (Req 10.3).
* Producir la respuesta conversacional según la intención reconocida
  (``maintenance_request`` / ``help`` / ``clarification`` / ``off_topic``,
  Req 13.1-13.4).
* Ante una extracción **incompleta o no interpretable** de una solicitud de
  mantenimiento, degradar a una respuesta de **aclaración** identificando los
  campos faltantes, **sin** invocar ``build_timeperiod`` ni ningún cálculo de
  bitmasks, y **preservando** ``raw_message`` sin modificaciones (Req 3.8, 15.7).
* Si el proveedor no está disponible, devolver una respuesta indicando que el
  asistente de IA no está disponible (Req 12.5) sin interrumpir el servidor.

Este módulo **puede** sostener referencias a bordes (el ``AIProvider``) porque
es orquestación, pero delega toda **decisión pura** al núcleo
(``core.domain``): detección de ticket, y aquí la clasificación de completitud
se limita a inspeccionar campos ya extraídos, nunca a calcular la ventana.

* Resolver el ``Locale`` efectivo **una vez por solicitud** con
  :func:`i18n.locale.resolve_locale` contra ``cfg.supported_locales`` /
  ``cfg.default_locale`` y producir **todos** los textos conversacionales, de
  confirmación y de error a través del catálogo :func:`i18n.messages.get_message`
  (design §7, Req 21.1, 21.2, 21.4, 21.5, 21.6).

Convención de imports: ``backend/`` es la raíz de código; se usan imports
absolutos desde esa raíz (``from core.domain import ...``).

Requirements: 3.8, 10.3, 13.1, 13.2, 13.3, 13.4, 15.7, 21.1, 21.2, 21.4.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from ai.prompt import build_prompt_context
from ai.provider import AIProvider, AIProviderError
from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    RecurrenceType,
    extract_ticket,
)
from i18n.locale import DEFAULT_LOCALE, resolve_locale
from i18n.messages import get_message

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a hard runtime import
    from config import AppConfig

# ``i18n.messages`` (Task 18.3) is the primary source of localized text. A tiny
# built-in table is kept as a defensive fallback ONLY for message keys the
# catalog does not define, so the service never hard-fails while emitting text
# (Req 21.4 degradation). The catalog is always preferred.
_get_message: Callable[..., str] = get_message

logger = logging.getLogger(__name__)

# Canonical intents produced downstream (mirror ai.provider.VALID_INTENTS). Kept
# as module constants so the response shaping and the api layer agree.
INTENT_MAINTENANCE = "maintenance_request"
INTENT_HELP = "help"
INTENT_CLARIFICATION = "clarification"
INTENT_OFF_TOPIC = "off_topic"
INTENT_UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------- #
# Response object                                                             #
# --------------------------------------------------------------------------- #
@dataclass
class ChatResult:
    """Structured result of interpreting a chat message.

    This is the orchestration-level output. The ``/chat`` (and ``/parse`` alias)
    endpoint (Task 11.2) maps it to the **legacy-compatible** response dict; the
    fields here carry everything that shaping needs without this service knowing
    about Flask or the exact wire format.

    * ``intent`` — one of :data:`INTENT_MAINTENANCE`, :data:`INTENT_HELP`,
      :data:`INTENT_CLARIFICATION`, :data:`INTENT_OFF_TOPIC` or
      :data:`INTENT_UNAVAILABLE` (Req 13.1-13.4, 12.5).
    * ``message`` — the conversational text for the user, localized.
    * ``request`` — the (possibly ticket-completed) :class:`ExtractedRequest`
      for a valid ``maintenance_request``; ``None`` otherwise.
    * ``missing_fields`` — for a ``clarification``, the fields that were missing
      or invalid (Req 3.8); empty for other intents.
    * ``raw_message`` — the original user message, preserved unmodified
      (Req 3.8).
    * ``ticket`` — the effective ticket (from the AI or locally detected,
      Req 10.3); ``None`` when absent.
    * ``locale`` — the effective locale used to render ``message``.
    """

    intent: str
    message: str
    raw_message: str
    request: ExtractedRequest | None = None
    missing_fields: list[str] = field(default_factory=list)
    ticket: str | None = None
    locale: str = "es"

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain dict for the HTTP layer to reshape.

        Returns orchestration-level keys only; the api layer (Task 11.2) maps
        ``intent`` to the legacy ``type`` vocabulary and adds any endpoint
        specific fields it must preserve for the widget (Req 15.3).
        """
        data: dict[str, object] = {
            "intent": self.intent,
            "message": self.message,
            "raw_message": self.raw_message,
            "locale": self.locale,
        }
        if self.ticket is not None:
            data["ticket"] = self.ticket
        if self.missing_fields:
            data["missing_fields"] = list(self.missing_fields)
        return data


# --------------------------------------------------------------------------- #
# Localized message fallback                                                  #
# --------------------------------------------------------------------------- #
# Canonical catalog keys this service renders (all defined in ``i18n/catalogs``,
# Task 18.3). Kept as constants so the intent dispatch and the catalog stay in
# lock-step; :func:`i18n.messages.get_message` falls back to the ``es`` catalog
# for any key/locale it cannot resolve (Req 21.4).
MSG_MAINTENANCE_READY = "conversational.maintenance_ready"
MSG_HELP = "conversational.help"
MSG_OFF_TOPIC = "conversational.off_topic"
MSG_CLARIFICATION = "conversational.clarification"
MSG_AI_UNAVAILABLE = "error.ai_unavailable"


def _message(key: str, locale: str, **params: object) -> str:
    """Resolve a localized message from the i18n catalog (Req 21.4, 21.5).

    Thin wrapper over :func:`i18n.messages.get_message`: the catalog is the
    single source of localized text. ``get_message`` already resolves the
    effective locale, falls back to the default (``es``) catalog for missing
    keys and never raises, so this service always produces sensible text.
    """
    return _get_message(key, locale, **params)


# --------------------------------------------------------------------------- #
# Completeness inspection (pure, no bitmask computation)                       #
# --------------------------------------------------------------------------- #
def _missing_recurrence_fields(rec: ExtractedRecurrence | None) -> list[str]:
    """Identify missing/invalid recurrence fields WITHOUT computing anything.

    Pure inspection of the already-extracted :class:`ExtractedRecurrence`: it
    only reports which fields are absent so the service can ask for them; it
    never calls ``build_timeperiod`` nor computes bitmasks (Req 3.8, 15.7).

    The checks mirror the recurrence engine's *required inputs* per type without
    duplicating its validation logic:

    * every type needs ``start_hour`` and ``duration_hours`` (except ``once``,
      which uses ``start_ts`` / ``end_ts``);
    * ``once`` needs both ``start_ts`` and ``end_ts``;
    * ``weekly`` / monthly-by-weekday need at least one ``days`` name;
    * ``monthly`` needs either ``day_of_month`` or (``days`` + ``occurrences``).
    """
    if rec is None:
        return ["recurrence_type", "timing", "duration"]

    missing: list[str] = []
    rec_type = rec.recurrence_type

    if rec_type == RecurrenceType.ONCE:
        if rec.start_ts is None:
            missing.append("start_ts")
        if rec.end_ts is None:
            missing.append("end_ts")
        return missing

    # Recurrent types (daily/weekly/monthly) share start_hour + duration_hours.
    if rec.start_hour is None:
        missing.append("start_time")
    if rec.duration_hours is None:
        missing.append("duration")

    if rec_type == RecurrenceType.WEEKLY:
        if not rec.days:
            missing.append("days")
    elif rec_type == RecurrenceType.MONTHLY:
        has_dom = rec.day_of_month is not None
        has_dow = bool(rec.days)
        if not has_dom and not has_dow:
            # Neither day-of-month nor day-of-week configuration provided.
            missing.append("monthly_schedule")

    return missing


def _missing_request_fields(req: ExtractedRequest) -> list[str]:
    """Return the list of missing/invalid fields for a maintenance request.

    A maintenance request needs a target (at least one host, group or a set of
    ``trigger_tags`` / ``problem_tags`` to discover them) and a valid recurrence
    specification. Pure inspection only — no bitmask computation, no time-period
    building (Req 3.8, 15.7). An empty list means the extraction is complete
    enough to proceed to the maintenance service.
    """
    missing: list[str] = []

    has_target = bool(
        req.hosts or req.groups or req.trigger_tags or req.problem_tags
    )
    if not has_target:
        missing.append("hosts_or_groups")

    missing.extend(_missing_recurrence_fields(req.recurrence))
    return missing


# --------------------------------------------------------------------------- #
# Service                                                                     #
# --------------------------------------------------------------------------- #
class ChatService:
    """Orchestrates conversational interpretation of a user message (Task 10.1).

    Holds a reference to an :class:`~ai.provider.AIProvider` (which may be the
    failover-wrapped provider). All pure decisions are delegated to the core
    (``core.domain.extract_ticket`` and the field-inspection helpers above);
    this class only sequences the boundary calls and shapes the result.
    """

    def __init__(
        self,
        provider: AIProvider,
        config: AppConfig | None = None,
    ) -> None:
        """Create the service around an AI provider (or failover wrapper).

        Args:
            provider: the AI provider (possibly failover-wrapped) used to
                extract the request.
            config: the application configuration. When provided, its
                ``supported_locales`` / ``default_locale`` drive per-request
                locale resolution (design §7, Req 21.5, 21.6). When ``None`` the
                service falls back to the product baseline (``es`` only), so the
                class stays constructible without a config in tests.
        """
        self._provider = provider
        self._config = config

    def _resolve_locale(self, requested: str | None) -> str:
        """Resolve the effective locale once per request (design §7, Req 21).

        Applies :func:`i18n.locale.resolve_locale` against the configured
        ``supported_locales`` / ``default_locale`` when a config is present;
        otherwise resolves against the guaranteed baseline (``es``). Unknown or
        unsupported values silently degrade to the default (Req 21.5, 21.6).
        """
        if self._config is not None:
            return resolve_locale(
                requested,
                self._config.supported_locales,
                self._config.default_locale,
            )
        return resolve_locale(requested, [DEFAULT_LOCALE], DEFAULT_LOCALE)

    def interpret(
        self,
        message: str,
        *,
        locale: str | None = "es",
        base_date: date | None = None,
    ) -> ChatResult:
        """Interpret ``message`` and return a structured :class:`ChatResult`.

        Steps:

        1. Detect the ticket locally up front (used to complete the AI output,
           Req 10.3) and build the prompt context (today/tomorrow, Req 13.6).
        2. Call ``provider.extract``. If the provider is unavailable or its
           output is unusable, degrade to an ``unavailable`` response (Req 12.5)
           without touching any recurrence computation and preserving the
           original ``message`` (Req 3.8).
        3. Complete the ticket when the AI did not provide one (Req 10.3).
        4. Dispatch on the recognized intent (Req 13.1-13.4). For a maintenance
           request, inspect completeness; if incomplete, return a clarification
           listing the missing fields WITHOUT invoking ``build_timeperiod``
           (Req 3.8, 15.7).

        Args:
            message: the original user message.
            locale: the requested locale for the conversational text; it is
                resolved once against the configured supported/default locales
                (design §7, Req 21.5, 21.6). ``None``/unsupported degrades to
                the default (``es``).
            base_date: injectable "today" for deterministic prompt context.

        Returns:
            A :class:`ChatResult`; ``raw_message`` always equals ``message`` and
            ``locale`` carries the effective (resolved) locale.
        """
        # Resolve the effective locale ONCE per request (design §7, Req 21).
        effective_locale = self._resolve_locale(locale)

        # Local ticket detection is a pure core decision (Req 10.3). Done before
        # the provider call so it is available regardless of the AI output.
        local_ticket = extract_ticket(message)
        ctx = build_prompt_context(base_date)

        try:
            extracted = self._provider.extract(message, ctx)
        except AIProviderError as exc:
            # Provider unavailable / unusable output: degrade gracefully without
            # any recurrence computation and preserve the original message.
            logger.warning("AI provider unavailable or unusable: %s", exc)
            return ChatResult(
                intent=INTENT_UNAVAILABLE,
                message=_message(MSG_AI_UNAVAILABLE, effective_locale),
                raw_message=message,
                ticket=local_ticket,
                locale=effective_locale,
            )

        # Preserve the original request unmodified (Req 3.8). Providers already
        # set raw_message; enforce it here so the contract holds even if a
        # provider forgot to.
        extracted.raw_message = message

        # Complete the locally-detected ticket when the AI did not include one
        # (Req 10.3). Only fills, never overrides an AI-provided ticket.
        if extracted.ticket is None and local_ticket is not None:
            extracted.ticket = local_ticket
        effective_ticket = extracted.ticket

        # Dispatch by intent (Req 13.1-13.4).
        if extracted.intent == INTENT_HELP:
            return ChatResult(
                intent=INTENT_HELP,
                message=_message(MSG_HELP, effective_locale),
                raw_message=message,
                ticket=effective_ticket,
                locale=effective_locale,
            )

        if extracted.intent == INTENT_OFF_TOPIC:
            return ChatResult(
                intent=INTENT_OFF_TOPIC,
                message=_message(MSG_OFF_TOPIC, effective_locale),
                raw_message=message,
                ticket=effective_ticket,
                locale=effective_locale,
            )

        if extracted.intent == INTENT_MAINTENANCE:
            missing = _missing_request_fields(extracted)
            if missing:
                # Incomplete extraction: DO NOT compute the time period; ask for
                # the missing details and preserve the original message
                # (Req 3.8, 15.7).
                return self._clarification(
                    message, effective_locale, effective_ticket, missing
                )
            return ChatResult(
                intent=INTENT_MAINTENANCE,
                message=_message(MSG_MAINTENANCE_READY, effective_locale),
                raw_message=message,
                request=extracted,
                ticket=effective_ticket,
                locale=effective_locale,
            )

        # Default / explicit clarification intent: ask for details. When the AI
        # already flagged clarification we still surface whatever fields we can
        # detect as missing to guide the user.
        missing = (
            _missing_request_fields(extracted)
            if extracted.recurrence is not None
            or extracted.hosts
            or extracted.groups
            else []
        )
        return self._clarification(
            message, effective_locale, effective_ticket, missing
        )

    def _clarification(
        self,
        message: str,
        locale: str,
        ticket: str | None,
        missing: list[str],
    ) -> ChatResult:
        """Build a clarification result listing the missing fields (Req 13.4).

        Never invokes any recurrence computation (Req 3.8, 15.7); it only
        formats the already-identified missing field names into the localized
        clarification message and preserves the original ``message``.
        """
        return ChatResult(
            intent=INTENT_CLARIFICATION,
            message=_message(MSG_CLARIFICATION, locale),
            raw_message=message,
            missing_fields=missing,
            ticket=ticket,
            locale=locale,
        )


__all__ = [
    "ChatService",
    "ChatResult",
    "INTENT_MAINTENANCE",
    "INTENT_HELP",
    "INTENT_CLARIFICATION",
    "INTENT_OFF_TOPIC",
    "INTENT_UNAVAILABLE",
    "MSG_MAINTENANCE_READY",
    "MSG_HELP",
    "MSG_OFF_TOPIC",
    "MSG_CLARIFICATION",
    "MSG_AI_UNAVAILABLE",
]
