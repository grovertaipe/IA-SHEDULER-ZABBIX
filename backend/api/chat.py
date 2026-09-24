"""Chat blueprint: ``POST /chat`` and ``POST /parse`` (Req 15.1, 15.2, 14.6).

Thin HTTP adapter over :class:`~services.chat_service.ChatService`. It contains
no business logic (Req 1.2): it reads the request body, validates the user
(Req 11), resolves the effective locale (Req 21.3), delegates interpretation to
the :class:`ChatService` and maps the resulting :class:`ChatResult` back into the
**exact response vocabulary** the widget already consumes (Req 15.3, 15.4).

``/parse`` is a strict **alias** of ``/chat`` (Req 15.2): both routes are wired
to the *same* handler, so their request and response formats are identical byte
for byte (Property 22). This mirrors the legacy monolith where ``/parse`` simply
delegated to ``/chat``.

Legacy ``type`` vocabulary preserved so the widget keeps working (Req 15.3):

* ``maintenance_request``  -- a complete maintenance request; the response also
  carries the host/group resolution (``found_hosts``/``found_groups``/
  ``missing_hosts``/``missing_groups`` + ``search_summary``) the widget renders
  as a preview (Req 14.6).
* ``help_request``         -- a help/examples answer.
* ``clarification_needed`` -- the request was incomplete or nothing resolved;
  the widget asks the user to refine it.
* ``off_topic``            -- an unrelated question, politely redirected.
* ``error``                -- bad input / unauthorized / internal error; carries
  the appropriate HTTP status and never changes state (Req 15.7).

Auth: ``/chat`` acts on Zabbix (it resolves hosts/groups), so it validates the
``Info_Usuario`` with :func:`api.auth.validate_user` and maps a failure to HTTP
**401** (Req 11). On any missing/invalid input it returns an ``error`` response
WITHOUT changing state (Req 15.7).

Flask coupling is confined to this layer; the blueprint is built by the factory
:func:`make_chat_blueprint`, which receives the :class:`ChatService`, the
:class:`~services.maintenance_service.MaintenanceService` (for host/group
resolution), the :class:`~zabbix.client.ZabbixClient` (for user validation) and
the :class:`~config.AppConfig` (for locale resolution). The app factory
(Task 11.4) builds these and registers the blueprint.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from flask import Blueprint, jsonify, request

from api.auth import validate_user
from config import AppConfig
from core.domain import ConversationTurn, RecurrenceType, TimePeriod
from core.recurrence import RecurrenceError, build_timeperiod
from i18n.locale import resolve_locale
from services.chat_service import (
    INTENT_HELP,
    INTENT_MAINTENANCE,
    INTENT_OFF_TOPIC,
    INTENT_UNAVAILABLE,
    ChatResult,
    ChatService,
)
from services.maintenance_service import (
    MaintenanceService,
    ResolvedResources,
    active_window,
    recurrence_config_from,
)
from zabbix.client import ZabbixClient

logger = logging.getLogger(__name__)

#: Map the orchestration-level :class:`ChatResult` intents to the legacy wire
#: ``type`` vocabulary the widget consumes (Req 15.3). ``maintenance_request``
#: keeps its name; ``help`` becomes ``help_request``; every other conversational
#: intent (clarification / unavailable / unknown) degrades to
#: ``clarification_needed`` so the widget always shows a sensible prompt.
_INTENT_TO_TYPE: dict[str, str] = {
    INTENT_MAINTENANCE: "maintenance_request",
    INTENT_HELP: "help_request",
    INTENT_OFF_TOPIC: "off_topic",
    INTENT_UNAVAILABLE: "clarification_needed",
}


def _read_message(data: Any) -> str | None:
    """Extract and normalise the ``message`` from a request body.

    Returns the stripped message, or ``None`` when the body is missing, is not
    an object, lacks a ``message`` field or the message is empty/blank. The
    caller turns ``None`` into an HTTP 400 (Req 15.7: an invalid request changes
    no state).
    """
    if not isinstance(data, dict) or "message" not in data:
        return None
    raw = data.get("message")
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    return text or None


def _read_user_payload(data: Any) -> Any:
    """Return the user payload, accepting both ``user`` and ``user_info``.

    The v2 contract sends ``user``; the legacy widget sent ``user_info``. Both
    are accepted so existing widget builds keep working (Req 15.6). ``user``
    takes precedence when both are present.
    """
    if not isinstance(data, dict):
        return None
    if data.get("user") is not None:
        return data.get("user")
    return data.get("user_info")


def _read_locale(data: Any, config: AppConfig) -> str:
    """Resolve the effective locale for the request (Req 21.3).

    Reads the optional ``locale`` field and resolves it against the configured
    supported locales, falling back to the default (``es``) when absent or
    unsupported. Accepting ``locale`` does not alter the existing request schema
    (Req 21.3).
    """
    requested = data.get("locale") if isinstance(data, dict) else None
    return resolve_locale(
        requested if isinstance(requested, str) else None,
        config.supported_locales,
        config.default_locale,
    )


#: Safety cap on how many prior turns the stateless backend accepts on a
#: ``/chat`` call. The widget already caps its resent buffer to the last 10
#: turns; this is defense in depth so a crafted body can never grow the prompt
#: unbounded. Only the LAST :data:`_MAX_HISTORY_TURNS` items are kept.
_MAX_HISTORY_TURNS = 10

#: Roles accepted for a conversation turn (anything else is dropped).
_VALID_HISTORY_ROLES = frozenset({"user", "assistant"})


def _read_history(data: Any) -> list[ConversationTurn]:
    """Read/normalize the optional ``history`` array into conversation turns.

    The stateless backend has no server-side sessions: the widget resends the
    recent, maintenance-scoped conversation on every ``/chat`` call and the AI
    re-reads it to merge fields across turns. This helper is the pure,
    unit-testable normalization of that resent array:

    * accepts a list of ``{role, content}`` items, oldest-first;
    * tolerates the ``content`` value under the aliases ``message`` / ``text``
      (coerced to ``content``) for backward/robustness;
    * keeps only items whose ``role`` is ``"user"`` or ``"assistant"`` and whose
      resolved content is a non-empty string (blank/whitespace is dropped);
    * caps the result to the LAST :data:`_MAX_HISTORY_TURNS` valid items
      (defense in depth even though the widget also caps).

    Returns an empty list when ``history`` is absent, not a list, or every item
    is invalid — in which case the interpretation behaves exactly as before
    (single stateless message). Pure and deterministic; no I/O.
    """
    if not isinstance(data, dict):
        return []
    raw = data.get("history")
    if not isinstance(raw, list):
        return []

    turns: list[ConversationTurn] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        if not isinstance(role, str) or role not in _VALID_HISTORY_ROLES:
            continue
        # Accept content under `content` (canonical) or the `message` / `text`
        # aliases, in that precedence order.
        content = item.get("content")
        if content is None:
            content = item.get("message")
        if content is None:
            content = item.get("text")
        if not isinstance(content, str):
            continue
        stripped = content.strip()
        if not stripped:
            continue
        turns.append(ConversationTurn(role=role, content=stripped))

    # Keep only the most recent turns (defense in depth alongside the widget).
    if len(turns) > _MAX_HISTORY_TURNS:
        turns = turns[-_MAX_HISTORY_TURNS:]
    return turns


def _resolution_fields(resolved: ResolvedResources) -> dict[str, Any]:
    """Shape the host/group resolution into the legacy preview fields (Req 14.6).

    Mirrors the legacy ``/chat`` response so the widget preview keeps working:
    ``found_hosts`` / ``found_groups`` are the resolved resource dicts,
    ``missing_hosts`` / ``missing_groups`` the requested names that did not
    resolve, and ``search_summary`` the counters the widget shows.
    """
    return {
        "found_hosts": list(resolved.hosts),
        "found_groups": list(resolved.groups),
        "missing_hosts": list(resolved.missing_hosts),
        "missing_groups": list(resolved.missing_groups),
        "search_summary": {
            "total_hosts_found": len(resolved.hosts),
            "total_groups_found": len(resolved.groups),
            "has_missing": bool(resolved.missing_hosts or resolved.missing_groups),
        },
    }


def _recurrence_config_fields(tp: TimePeriod) -> dict[str, Any]:
    """Serialize a computed :class:`TimePeriod` into the ``recurrence_config`` dict.

    Honours "AI extrae, backend calcula" (Req 3.2): the AI only supplies the
    structured recurrence; the backend has already computed every Zabbix field
    with :func:`~core.recurrence.build_timeperiod`, and this function only
    *serializes* the resulting :class:`~core.domain.TimePeriod` into the exact
    keys the widget's confirmation popup reads for daily/weekly/monthly
    schedules:

    * daily   -- ``duration``, ``every``, ``start_time``;
    * weekly  -- ``duration``, ``dayofweek`` (Zabbix day bitmask), ``every``,
      ``start_time``;
    * monthly -- ``duration``, ``start_time``, ``every`` and whichever of
      ``day`` / ``dayofweek`` / ``month`` the engine set.

    The dict is assembled from the non-``None`` :class:`TimePeriod` fields among
    ``{start_time, every, dayofweek, day, month}`` (the scheduling fields the
    widget consumes), so a single rule covers all three recurring types, PLUS
    the maintenance ``duration`` in SECONDS (the :class:`TimePeriod`'s
    ``period``, always set on a recurring time period). ``duration`` is emitted
    under that key to match the legacy v1 monolith contract and the widget's
    expectation, and is what lets the create side (``POST /create_maintenance``,
    :func:`api.maintenance._parse_recurrence`) reconstruct ``duration_hours``
    when the widget resends this ``recurrence_config`` verbatim.
    ``timeperiod_type`` / ``start_date`` are intentionally omitted.
    """
    fields: dict[str, Any] = {}
    for key in ("start_time", "every", "dayofweek", "day", "month"):
        value = getattr(tp, key)
        if value is not None:
            fields[key] = value
    # ``period`` is always set on a recurring TimePeriod; expose it as
    # ``duration`` (seconds) so the widget can resend it and the create side can
    # rebuild ``duration_hours`` (Req 3.2 — the backend already computed it).
    fields["duration"] = tp.period
    return fields


def make_chat_blueprint(
    chat_service: ChatService,
    maintenance_service: MaintenanceService,
    client: ZabbixClient,
    config: AppConfig,
) -> Blueprint:
    """Build the chat :class:`~flask.Blueprint` bound to its dependencies.

    The app factory (Task 11.4) calls this with the built
    :class:`ChatService`, :class:`MaintenanceService`, :class:`ZabbixClient` and
    :class:`AppConfig`, then registers the returned blueprint. Passing the
    dependencies explicitly keeps the blueprint decoupled from global state and
    trivially testable with fakes.

    ``/chat`` and ``/parse`` are registered on the **same** handler so they are
    byte-for-byte identical (Req 15.2, Property 22).
    """
    bp = Blueprint("chat", __name__)

    def _handle_chat() -> Any:
        """Shared handler for ``/chat`` and its ``/parse`` alias (Req 15.1, 15.2).

        Flow:

        1. Read and validate the ``message`` (missing/blank -> 400, no state
           change, Req 15.7).
        2. Validate the ``Info_Usuario`` (missing/invalid -> 401, Req 11).
        3. Resolve the effective locale (Req 21.3) and read the optional,
           maintenance-scoped conversation ``history`` the widget resends
           (:func:`_read_history`); the backend stays stateless.
        4. Interpret the message via :meth:`ChatService.interpret`, passing the
           history so extraction accumulates details across turns.
        5. For a complete ``maintenance_request``, resolve hosts/groups via
           :meth:`MaintenanceService.resolve_resources` and attach the preview
           fields (Req 14.6); if nothing resolves, degrade to
           ``clarification_needed`` (legacy behaviour).
        6. Map the :class:`ChatResult` to the legacy ``type`` vocabulary and
           return it.
        """
        data = request.get_json(silent=True)

        message = _read_message(data)
        if message is None:
            # Missing/blank message: invalid request, no state change (Req 15.7).
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": (
                            "No recibí ningún mensaje. "
                            "¿Qué mantenimiento necesitas crear?"
                        ),
                    }
                ),
                400,
            )

        # Validate the Info_Usuario before acting on Zabbix (Req 11).
        auth = validate_user(_read_user_payload(data), client)
        if not auth.ok or auth.user is None:
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": "Acceso no autorizado. Debe estar logueado en Zabbix.",
                    }
                ),
                401,
            )

        locale = _read_locale(data, config)
        history = _read_history(data)

        try:
            result = chat_service.interpret(
                message, locale=locale, history=history or None
            )
        except Exception:  # noqa: BLE001 - never leak an internal trace
            logger.exception("Unexpected error interpreting a chat message")
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": (
                            "Ocurrió un error inesperado al procesar tu solicitud. "
                            "¿Podrías intentar de nuevo?"
                        ),
                    }
                ),
                500,
            )

        return jsonify(_shape_response(result, data))

    def _shape_response(result: ChatResult, data: Any) -> dict[str, Any]:
        """Map a :class:`ChatResult` to the legacy response dict (Req 15.3, 15.4).

        For a complete ``maintenance_request`` the host/group resolution is
        performed here (via the maintenance service) and the preview fields are
        merged in so the widget can render the confirmation (Req 14.6). When no
        resource resolves, the type degrades to ``clarification_needed`` exactly
        like the legacy ``/chat`` did.
        """
        response: dict[str, Any] = {
            "type": _INTENT_TO_TYPE.get(result.intent, "clarification_needed"),
            "message": result.message,
            "original_message": result.raw_message,
            "locale": result.locale,
        }
        if result.ticket is not None:
            response["ticket_number"] = result.ticket
        if result.missing_fields:
            response["missing_fields"] = list(result.missing_fields)

        # Echo the user payload back for the widget, like the legacy endpoint.
        user_payload = _read_user_payload(data)
        if user_payload is not None:
            response["user_info"] = user_payload

        if result.intent != INTENT_MAINTENANCE or result.request is None:
            return response

        # Complete maintenance request: resolve hosts/groups so the widget can
        # preview the target resources (Req 14.6).
        req = result.request
        try:
            resolved = maintenance_service.resolve_resources(
                hosts=req.hosts,
                groups=req.groups,
                trigger_tags=req.trigger_tags,
            )
        except Exception:  # noqa: BLE001 - resolution failure -> clarification
            logger.exception("Host/group resolution failed for a chat request")
            response["type"] = "clarification_needed"
            response["message"] = (
                "No pude verificar los hosts o grupos en Zabbix. "
                "¿Podrías revisar los nombres e intentar de nuevo?"
            )
            return response

        response.update(_resolution_fields(resolved))
        response["recurrence_type"] = (
            req.recurrence.recurrence_type.value if req.recurrence else "once"
        )

        # The widget renders the "Period" line from the top-level
        # ``start_time``/``end_time`` display strings for EVERY maintenance type
        # (they are the maintenance ACTIVE WINDOW — Zabbix ``active_since`` /
        # ``active_till`` — exactly as the legacy v1 monolith emitted them), so
        # recurring types no longer show "Period: -" (Req 14.6). Recurring types
        # ADDITIONALLY carry ``recurrence_config`` for the schedule detail.
        #
        # "AI extrae, backend calcula" (Req 3.2): the backend computes the
        # window and every Zabbix field; we only format/serialize them. The
        # ``TimePeriod`` is computed ONCE and reused for both the active window
        # and the recurrence config. A RecurrenceError is logged and swallowed
        # so the response never crashes.
        rec = req.recurrence
        if rec is not None:
            try:
                tp: TimePeriod = build_timeperiod(recurrence_config_from(rec))
            except RecurrenceError:
                logger.exception(
                    "Could not compute the active window for a chat request"
                )
            else:
                start_ts, end_ts = active_window(rec, tp)
                fmt = "%Y-%m-%d %H:%M"
                response["start_time"] = datetime.fromtimestamp(start_ts).strftime(fmt)
                response["end_time"] = datetime.fromtimestamp(end_ts).strftime(fmt)
                if rec.recurrence_type != RecurrenceType.ONCE:
                    response["recurrence_config"] = _recurrence_config_fields(tp)

        if resolved.is_empty:
            # Nothing matched: ask the user to verify the names (legacy behaviour).
            response["type"] = "clarification_needed"
            response["message"] = (
                "No encontré ningún servidor o grupo con esos nombres.\n\n"
                "Sugerencias:\n"
                "- Verifica los nombres de los servidores\n"
                "- Usa nombres exactos como aparecen en Zabbix\n"
                "- Puedes usar grupos en lugar de servidores individuales\n\n"
                "¿Podrías verificar los nombres y intentar de nuevo?"
            )

        return response

    @bp.post("/chat")
    def chat() -> Any:
        """Interpret a conversational maintenance message (Req 15.1)."""
        return _handle_chat()

    @bp.post("/parse")
    def parse() -> Any:
        """Alias of :func:`chat` with an identical contract (Req 15.2)."""
        return _handle_chat()

    return bp
