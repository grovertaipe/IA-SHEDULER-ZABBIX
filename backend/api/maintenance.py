"""Maintenance blueprint: create / list / templates / test (Req 15.1-15.4, 15.7).

Thin HTTP adapter over :class:`~services.maintenance_service.MaintenanceService`
and the :class:`~zabbix.client.ZabbixClient`. It contains no business logic
(Req 1.2): it reads/validates the request, builds the structured
:class:`~core.domain.ExtractedRequest`, delegates to the service and shapes the
response into the exact contract the widget already consumes (Req 15.3, 15.4).

Endpoints:

* ``POST /create_maintenance`` -- validate the user (Req 11), assemble the
  request and call :meth:`MaintenanceService.create`; return the legacy
  ``maintenance_created`` confirmation shape (Req 11.4). On a recurrence /
  validation error or when no resource resolves, return an ``error`` /
  ``clarification_needed`` response WITHOUT creating anything (Req 15.7, 14.6).
* ``GET /maintenance/list`` -- return the configured maintenances in the legacy
  ``maintenance_list`` shape (Req 15.4).
* ``GET /maintenance/templates`` -- return the static routine templates the
  legacy exposed (Req 15.4).
* ``POST /test/routine`` -- validate a routine ``recurrence_config`` by building
  the time period and decoding it, WITHOUT creating anything in Zabbix (mirrors
  the legacy ``/test/routine``).

Flask coupling is confined to this layer; the blueprint is built by the factory
:func:`make_maintenance_blueprint`, which receives the
:class:`MaintenanceService`, the :class:`ZabbixClient` (for the list / user
validation) and the :class:`~config.AppConfig` (for locale resolution). The app
factory (Task 11.4) builds these and registers the blueprint.
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from flask import Blueprint, jsonify, request

from api.auth import validate_user
from cache.user_cache import UserValidationCache
from config import AppConfig
from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    ProblemTag,
    RecurrenceConfig,
    RecurrenceError,
    RecurrenceType,
    TagOperator,
    TagsEvalType,
    decode_days,
    decode_months,
    extract_ticket,
)
from core.recurrence import build_timeperiod
from i18n.locale import resolve_locale
from i18n.messages import get_message
from services.maintenance_service import MaintenanceService
from zabbix.client import ZabbixClient, ZabbixError

logger = logging.getLogger(__name__)

#: Human-readable day names by ascending bit value, for the legacy decode used
#: by ``/test/routine`` and ``/maintenance/list`` (Spanish, matching legacy).
_DAY_LABELS_ES: dict[str, str] = {
    "monday": "Lunes",
    "tuesday": "Martes",
    "wednesday": "Miércoles",
    "thursday": "Jueves",
    "friday": "Viernes",
    "saturday": "Sábado",
    "sunday": "Domingo",
}

#: Human-readable month names by ascending bit value (Spanish, matching legacy).
_MONTH_LABELS_ES: dict[str, str] = {
    "january": "Enero",
    "february": "Febrero",
    "march": "Marzo",
    "april": "Abril",
    "may": "Mayo",
    "june": "Junio",
    "july": "Julio",
    "august": "Agosto",
    "september": "Septiembre",
    "october": "Octubre",
    "november": "Noviembre",
    "december": "Diciembre",
}

#: Week-occurrence labels (Spanish), matching the legacy ``/test/routine``.
_WEEK_LABELS_ES: dict[int, str] = {
    1: "primera",
    2: "segunda",
    3: "tercera",
    4: "cuarta",
    5: "última",
}

#: Localized routine templates exposed by ``/maintenance/templates`` so the
#: widget's template picker follows the request locale (Req 15.4, 21.3).
#:
#: Examples use 24h times (``HH:MM`` / ``HH:MM-HH:MM``) and a sample ticket.
#: Tickets accept ANY nomenclature (``INC0012345``, ``JIRA-4521``, ``100-178306``,
#: ...); the identifiers below are just samples, not a required format. The
#: default-locale (es) catalog preserves the previous contract shape
#: (name/description/examples per type).
_ROUTINE_TEMPLATES_BY_LOCALE: dict[str, dict[str, dict[str, Any]]] = {
    "es": {
        "daily": {
            "name": "Mantenimiento Diario",
            "description": "Mantenimiento que se ejecuta todos los días",
            "examples": [
                "backup diario 02:00-03:00 ticket INC0012345",
                "limpieza de logs cada día 23:00-23:30 ticket JIRA-4521",
                "reinicio de servicios diario 03:00-04:00 ticket 100-178306",
            ],
        },
        "weekly": {
            "name": "Mantenimiento Semanal",
            "description": "Mantenimiento que se ejecuta semanalmente",
            "examples": [
                "cada domingo 01:00-03:00 ticket CHG-2024-001",
                "actualización de BD cada viernes 22:00-23:00 ticket 200-8341",
                "respaldo completo todos los sábados 02:00-04:00 ticket 500-43116",
            ],
        },
        "monthly": {
            "name": "Mantenimiento Mensual",
            "description": "Mantenimiento que se ejecuta mensualmente",
            "examples": [
                "día 1 de cada mes 02:00-04:00 ticket 100-178306",
                "día 15 de cada mes 01:00-02:00 ticket 200-8341",
                "primer domingo del mes 03:00-05:00 ticket 500-43116",
            ],
        },
    },
    "en": {
        "daily": {
            "name": "Daily Maintenance",
            "description": "Maintenance that runs every day",
            "examples": [
                "daily backup 02:00-03:00 ticket INC0012345",
                "log cleanup every day 23:00-23:30 ticket JIRA-4521",
                "daily service restart 03:00-04:00 ticket 100-178306",
            ],
        },
        "weekly": {
            "name": "Weekly Maintenance",
            "description": "Maintenance that runs weekly",
            "examples": [
                "every Sunday 01:00-03:00 ticket CHG-2024-001",
                "DB update every Friday 22:00-23:00 ticket 200-8341",
                "full backup every Saturday 02:00-04:00 ticket 500-43116",
            ],
        },
        "monthly": {
            "name": "Monthly Maintenance",
            "description": "Maintenance that runs monthly",
            "examples": [
                "day 1 of every month 02:00-04:00 ticket 100-178306",
                "day 15 of every month 01:00-02:00 ticket 200-8341",
                "first Sunday of the month 03:00-05:00 ticket 500-43116",
            ],
        },
    },
    "pt": {
        "daily": {
            "name": "Manutenção Diária",
            "description": "Manutenção que é executada todos os dias",
            "examples": [
                "backup diário 02:00-03:00 ticket INC0012345",
                "limpeza de logs todo dia 23:00-23:30 ticket JIRA-4521",
                "reinício de serviços diário 03:00-04:00 ticket 100-178306",
            ],
        },
        "weekly": {
            "name": "Manutenção Semanal",
            "description": "Manutenção que é executada semanalmente",
            "examples": [
                "todo domingo 01:00-03:00 ticket CHG-2024-001",
                "atualização de BD toda sexta 22:00-23:00 ticket 200-8341",
                "backup completo todo sábado 02:00-04:00 ticket 500-43116",
            ],
        },
        "monthly": {
            "name": "Manutenção Mensal",
            "description": "Manutenção que é executada mensalmente",
            "examples": [
                "dia 1 de cada mês 02:00-04:00 ticket 100-178306",
                "dia 15 de cada mês 01:00-02:00 ticket 200-8341",
                "primeiro domingo do mês 03:00-05:00 ticket 500-43116",
            ],
        },
    },
}

#: Localized ``message`` for the ``/maintenance/templates`` response, keyed by
#: locale. Falls back to the default-locale entry (Req 21.5, 21.6).
_TEMPLATES_MESSAGE_BY_LOCALE: dict[str, str] = {
    "es": "Aquí tienes las plantillas disponibles para mantenimientos rutinarios",
    "en": "Here are the available templates for routine maintenance",
    "pt": "Aqui estão os modelos disponíveis para manutenções rotineiras",
}


def _read_user_payload(data: Any) -> Any:
    """Return the user payload, accepting both ``user`` and ``user_info``.

    The v2 contract sends ``user``; the legacy widget sent ``user_info``. Both
    are accepted (``user`` wins) so existing widget builds keep working.
    """
    if not isinstance(data, dict):
        return None
    if data.get("user") is not None:
        return data.get("user")
    return data.get("user_info")


def _read_locale(data: Any, config: AppConfig) -> str:
    """Resolve the effective locale for the request (Req 21.3)."""
    requested = data.get("locale") if isinstance(data, dict) else None
    return resolve_locale(
        requested if isinstance(requested, str) else None,
        config.supported_locales,
        config.default_locale,
    )


def _as_int(value: Any) -> int | None:
    """Best-effort coercion of ``value`` to ``int``; ``None`` when not possible."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    """Best-effort coercion of ``value`` to ``float``; ``None`` when not possible."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_opt_str(value: Any) -> str | None:
    """Coerce ``value`` to a trimmed string, or ``None`` when absent/blank.

    Used for the ``once`` structured ``start_date`` (ISO ``YYYY-MM-DD``); the
    recurrence engine validates the actual date format (Req 3.2).
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _parse_recurrence(data: dict[str, Any]) -> ExtractedRecurrence:
    """Build an :class:`ExtractedRecurrence` from the request body.

    Accepts the v2 structured recurrence (``recurrence`` object with day/month/
    occurrence name sets, ``start_hour``, ``duration_hours``, ``every``) and,
    for a ``once`` maintenance, the legacy ``start_time`` / ``end_time`` strings
    (``"%Y-%m-%d %H:%M"``) which are converted to ``start_ts`` / ``end_ts``.

    For a RECURRING type (daily/weekly/monthly) it ALSO accepts the Zabbix-format
    ``recurrence_config`` object the widget resends verbatim — the very object
    the backend produced in ``/chat`` via
    :func:`api.chat._recurrence_config_fields` (keys among ``{start_time,
    duration, every, dayofweek, day, month}`` where ``start_time`` / ``duration``
    are SECONDS and ``dayofweek`` / ``month`` are precomputed bitmasks). Those
    are mapped into the :class:`ExtractedRecurrence` fields the engine consumes:
    ``start_time`` → ``start_hour`` (``// 3600``), ``duration`` →
    ``duration_hours`` (``/ 3600``), ``every`` → ``every``, ``day`` →
    ``day_of_month``, and the precomputed ``dayofweek`` / ``month`` bitmasks are
    threaded through as ``day_bitmask`` / ``month_bitmask`` (validated by the
    engine, Req 2.7). This mirrors what the v1 monolith accepted and fixes the
    contract drift where recurring creates failed with "Falta start_time".

    Precedence: explicit intent-format ``recurrence`` values win when present;
    ``recurrence_config`` only fills the gaps (in practice the widget sends only
    ``recurrence_config`` for recurring types). The ``once`` path is unchanged.

    Purely reads and normalises the payload; all validation and bitmask
    computation stay in the recurrence engine (Req 3.2).
    """
    rec_type = RecurrenceType(str(data.get("recurrence_type", "once")).lower())
    rec_obj = data.get("recurrence")
    rec_obj = rec_obj if isinstance(rec_obj, dict) else {}

    # Zabbix-format config the widget resends verbatim (the /chat output).
    cfg = data.get("recurrence_config")
    cfg = cfg if isinstance(cfg, dict) else {}

    start_ts = _as_int(rec_obj.get("start_ts"))
    end_ts = _as_int(rec_obj.get("end_ts"))

    # Structured once date (v2): the widget sends back the AI-parsed ISO date
    # (start_date) + start_hour + duration_hours; the recurrence engine computes
    # the epochs (design "AI extrae, backend calcula", Req 3.2).
    start_date = _as_opt_str(rec_obj.get("start_date"))

    # Legacy once payload: start_time / end_time as "%Y-%m-%d %H:%M" strings.
    if rec_type == RecurrenceType.ONCE and (start_ts is None or end_ts is None):
        start_ts = start_ts if start_ts is not None else _parse_legacy_ts(data.get("start_time"))
        end_ts = end_ts if end_ts is not None else _parse_legacy_ts(data.get("end_time"))

    # Intent-format scheduling fields (v2 structured recurrence) take precedence.
    start_hour = _as_int(rec_obj.get("start_hour"))
    duration_hours = _as_float(rec_obj.get("duration_hours"))
    every = _as_int(rec_obj.get("every"))
    day_of_month = _as_int(rec_obj.get("day_of_month"))
    day_bitmask: int | None = None
    month_bitmask: int | None = None

    # RECURRING type with the Zabbix-format recurrence_config present: fill any
    # gap left by the intent-format fields from the resent /chat config. ``once``
    # never reads recurrence_config (its window comes from the legacy strings or
    # the structured start_date path above), so its behaviour is unchanged.
    if rec_type != RecurrenceType.ONCE and cfg:
        if start_hour is None:
            start_time_seconds = _as_int(cfg.get("start_time"))
            if start_time_seconds is not None:
                start_hour = int(start_time_seconds // 3600)
        if duration_hours is None:
            duration_seconds = _as_int(cfg.get("duration"))
            if duration_seconds is not None:
                duration_hours = duration_seconds / 3600
        if every is None:
            every = _as_int(cfg.get("every"))
        if day_of_month is None:
            day_of_month = _as_int(cfg.get("day"))
        # Precomputed Zabbix bitmasks pass straight through (engine validates).
        day_bitmask = _as_int(cfg.get("dayofweek"))
        month_bitmask = _as_int(cfg.get("month"))

    return ExtractedRecurrence(
        recurrence_type=rec_type,
        days=set(rec_obj.get("days", []) or []),
        months=set(rec_obj.get("months", []) or []),
        occurrences=set(rec_obj.get("occurrences", []) or []),
        day_of_month=day_of_month,
        start_hour=start_hour,
        duration_hours=duration_hours,
        every=every,
        start_date=start_date,
        start_ts=start_ts,
        end_ts=end_ts,
        day_bitmask=day_bitmask,
        month_bitmask=month_bitmask,
    )


def _parse_legacy_ts(value: Any) -> int | None:
    """Parse a legacy ``"%Y-%m-%d %H:%M"`` datetime string into an epoch int.

    Returns ``None`` when ``value`` is absent or malformed; the caller treats a
    missing timestamp as a validation error (the recurrence engine rejects an
    incomplete ``once`` window).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        dt = datetime.datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return int(dt.timestamp())


def _parse_problem_tags(data: dict[str, Any]) -> list[ProblemTag]:
    """Build the maintenance problem tags from the request body (Req 32).

    Reads the ``problem_tags`` list of ``{tag, value?, operator?}`` objects.
    ``trigger_tags`` are intentionally NOT read here — those are host-discovery
    tags handled separately by the resolution phase (Req 14.4, 32).
    """
    raw = data.get("problem_tags")
    if not isinstance(raw, list):
        return []
    tags: list[ProblemTag] = []
    for item in raw:
        if not isinstance(item, dict) or "tag" not in item:
            continue
        operator = _as_int(item.get("operator"))
        tags.append(
            ProblemTag(
                tag=str(item["tag"]),
                value=str(item.get("value", "")),
                operator=operator if operator is not None else TagOperator.CONTAINS,
            )
        )
    return tags


def _build_request(data: dict[str, Any]) -> ExtractedRequest:
    """Assemble an :class:`ExtractedRequest` from the create payload.

    Reads the target hosts/groups, host-discovery ``trigger_tags``, maintenance
    problem tags (Req 32), the ticket and the recurrence. Pure normalisation:
    the service + recurrence engine own all validation.
    """
    trigger_tags = data.get("trigger_tags")
    tags_evaltype = _as_int(data.get("tags_evaltype"))
    maintenance_type = _as_int(data.get("maintenance_type"))
    ticket = data.get("ticket") or data.get("ticket_number")

    return ExtractedRequest(
        intent="maintenance_request",
        hosts=[str(h) for h in (data.get("hosts") or [])],
        groups=[str(g) for g in (data.get("groups") or [])],
        trigger_tags=list(trigger_tags) if isinstance(trigger_tags, list) else [],
        problem_tags=_parse_problem_tags(data),
        tags_evaltype=tags_evaltype if tags_evaltype is not None else TagsEvalType.AND_OR,
        maintenance_type=maintenance_type if maintenance_type is not None else 0,
        ticket=str(ticket).strip() if ticket else None,
        recurrence=_parse_recurrence(data),
        raw_message=str(data.get("message", "") or data.get("original_message", "")),
    )


def _read_user_from_query(args: Any) -> dict[str, Any] | None:
    """Build a minimal user payload from a GET query string (Req 11).

    ``/maintenance/list`` is a GET with no body, so the widget carries the
    logged-in Zabbix user via ``?userid=<id>`` (and optionally ``?username=``).
    Returns ``{"userid": ..., "username"?: ...}`` when a non-empty ``userid`` is
    present, or ``None`` otherwise so the caller returns 401. The payload is
    validated exactly like the body-carried user via :func:`validate_user`.
    """
    raw_userid = args.get("userid")
    if raw_userid is None:
        return None
    userid = str(raw_userid).strip()
    if not userid:
        return None
    payload: dict[str, Any] = {"userid": userid}
    username = args.get("username")
    if username is not None and str(username).strip():
        payload["username"] = str(username).strip()
    return payload


def make_maintenance_blueprint(
    maintenance_service: MaintenanceService,
    client: ZabbixClient,
    config: AppConfig,
    cache: UserValidationCache | None = None,
) -> Blueprint:
    """Build the maintenance :class:`~flask.Blueprint` bound to its dependencies.

    The app factory (Task 11.4) calls this with the built
    :class:`MaintenanceService`, :class:`ZabbixClient`, :class:`AppConfig` and
    the shared :class:`UserValidationCache`, then registers the returned
    blueprint. Passing the dependencies explicitly keeps the blueprint free of
    global state and trivially testable with fakes.

    Every endpoint that reads or writes Zabbix validates the ``Info_Usuario``
    first (401 on failure, Req 11): ``create_maintenance`` (body), ``list`` (via
    the ``?userid=`` query string) and ``test/routine`` (body). Only the static
    ``templates`` endpoint stays public.
    """
    bp = Blueprint("maintenance", __name__)

    @bp.post("/create_maintenance")
    def create_maintenance() -> Any:
        """Create a maintenance window (Req 11.4, 15.7, 14.6).

        Validates the user (401 on failure, Req 11), assembles the request and
        delegates to :meth:`MaintenanceService.create`. On a recurrence /
        validation error or when no resource resolves, returns an error /
        clarification WITHOUT creating anything in Zabbix (Req 15.7, 14.6).
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return (
                jsonify({"type": "error", "message": "Se requieren datos de la solicitud"}),
                400,
            )

        # Validate the Info_Usuario before acting on Zabbix (Req 11).
        auth = validate_user(_read_user_payload(data), client, cache)
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

        # A maintenance needs at least a host or a group (Req 15.7 — no state
        # change on an invalid request).
        if not data.get("hosts") and not data.get("groups") and not data.get("trigger_tags"):
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": "Se requieren hosts específicos o grupos para el mantenimiento",
                    }
                ),
                400,
            )

        extracted = _build_request(data)
        locale = _read_locale(data, config)

        try:
            confirmation = maintenance_service.create(extracted, auth.user)
        except RecurrenceError as exc:
            # Recurrence / problem-tag validation failed: NOT created (Req 15.7).
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": f"Configuración inválida ({exc.field}): {exc}",
                    }
                ),
                400,
            )
        except ValueError as exc:
            # No recurrence, or no host/group resolved: ask the user to refine
            # WITHOUT creating anything (Req 14.6, 15.7).
            return (
                jsonify({"type": "clarification_needed", "message": str(exc)}),
                400,
            )
        except ZabbixError as exc:
            logger.error("Zabbix error creating maintenance: %s", exc)
            return (
                jsonify({"type": "error", "message": f"Error de Zabbix: {exc}"}),
                400,
            )
        except Exception:  # noqa: BLE001 - never leak an internal trace
            logger.exception("Unexpected error creating a maintenance")
            return (
                jsonify({"type": "error", "message": "Error interno al crear el mantenimiento"}),
                500,
            )

        return jsonify(_confirmation_response(confirmation, extracted, locale))

    @bp.get("/maintenance/list")
    def list_maintenance() -> Any:
        """Return the configured maintenance windows (Req 15.4).

        Shapes the raw ``maintenance.get`` result into the legacy
        ``maintenance_list`` contract: human-readable ``active_since`` /
        ``active_till``, the derived ``is_routine`` / ``routine_type`` and the
        extracted ``ticket_number``.

        This endpoint reads Zabbix, so it requires a validated logged-in user
        (Req 11). Being a GET with no body, the user is carried in the query
        string as ``?userid=<id>`` (optionally ``?username=``); a missing or
        invalid user yields 401 without touching Zabbix.
        """
        # Validate the Info_Usuario (from the query string) before acting (Req 11).
        auth = validate_user(_read_user_from_query(request.args), client, cache)
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

        try:
            maintenances = [dict(m) for m in client.list_maintenance()]
        except ZabbixError as exc:
            logger.error("Error listing maintenances: %s", exc)
            return (
                jsonify({"type": "error", "message": f"Error obteniendo mantenimientos: {exc}"}),
                400,
            )

        for maint in maintenances:
            _decorate_list_entry(maint)

        return jsonify(
            {
                "type": "maintenance_list",
                "maintenances": maintenances,
                "total": len(maintenances),
                "message": f"Mostrando {len(maintenances)} mantenimiento(s) más recientes",
            }
        )

    @bp.get("/maintenance/templates")
    def maintenance_templates() -> Any:
        """Return the localized routine maintenance templates (Req 15.4, 21.3).

        The widget sends the active UI locale via the ``?locale=xx`` query
        string; it is resolved against the configured supported/default locales
        so unknown values degrade to the default (Req 21.5, 21.6). The response
        contract shape (``type`` / ``templates`` / ``message``) is preserved.
        """
        locale = resolve_locale(
            request.args.get("locale"),
            config.supported_locales,
            config.default_locale,
        )
        # Fall back to Spanish (the guaranteed baseline, Req 21.4) if the
        # resolved locale has no catalog of its own.
        templates = _ROUTINE_TEMPLATES_BY_LOCALE.get(
            locale, _ROUTINE_TEMPLATES_BY_LOCALE["es"]
        )
        message = _TEMPLATES_MESSAGE_BY_LOCALE.get(
            locale, _TEMPLATES_MESSAGE_BY_LOCALE["es"]
        )
        return jsonify(
            {
                "type": "templates",
                "templates": templates,
                "message": message,
            }
        )

    @bp.post("/test/routine")
    def test_routine() -> Any:
        """Validate a routine recurrence config WITHOUT creating it (Req 15.1).

        Builds the time period from the supplied recurrence and decodes it into
        human-readable details, mirroring the legacy ``/test/routine``. Nothing
        is created in Zabbix; a :class:`RecurrenceError` is reported as an
        invalid configuration.
        """
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return (
                jsonify({"type": "error", "message": "Se requieren datos de prueba"}),
                400,
            )

        # Validate the Info_Usuario before doing anything (logged-in only policy,
        # Req 11). This endpoint does not touch Zabbix but is protected for
        # consistency with every other acting endpoint.
        auth = validate_user(_read_user_payload(data), client, cache)
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

        recurrence_type = str(data.get("recurrence_type", "once")).lower()
        result: dict[str, Any] = {"type": "test_result", "valid": True, "details": []}

        try:
            cfg = _test_config_from(data)
            timeperiod = build_timeperiod(cfg)
        except (RecurrenceError, ValueError) as exc:
            result["valid"] = False
            result["message"] = f"Error en configuración: {exc}"
            return jsonify(result)

        result["details"] = _describe_timeperiod(timeperiod)
        result["message"] = f"Configuración {recurrence_type} válida"
        return jsonify(result)

    return bp


# --------------------------------------------------------------------------- #
# Response shaping helpers (pure)                                             #
# --------------------------------------------------------------------------- #
def _confirmation_response(
    confirmation: Any, request_obj: ExtractedRequest, locale: str = "es"
) -> dict[str, Any]:
    """Shape a :class:`MaintenanceConfirmation` into the legacy success dict.

    Preserves the legacy ``maintenance_created`` fields the widget consumes
    (Req 11.4): ``maintenance_id``, ``name``, ``description``,
    ``hosts_affected``, ``groups_affected``, ``recurrence_type``,
    ``is_routine``, ``ticket_number``, ``user_info`` and a human ``message``.

    The human ``message`` is a LOCALIZED TEMPLATE assembled from the i18n catalog
    (Req 21.1): the confirmation is post-action and must be precise, so it stays
    controlled/templated rather than free AI text (the natural, same-language
    free text lives in the ``/chat`` conversational replies). The structured
    fields the widget renders are unchanged.
    """
    resolved = confirmation.resolved
    rec_type = (
        request_obj.recurrence.recurrence_type.value
        if request_obj.recurrence
        else "once"
    )
    user = confirmation.user
    user_display = " ".join(part for part in (user.name, user.surname) if part).strip()
    if not user_display:
        user_display = user.username

    message = get_message(
        "confirmation.created_message",
        locale,
        name=confirmation.name,
        hosts_affected=len(resolved.host_ids),
        groups_affected=len(resolved.group_ids),
    )
    if rec_type != "once":
        message += get_message(
            "confirmation.line_routine", locale, recurrence_type=rec_type
        )
    if request_obj.ticket:
        message += get_message(
            "confirmation.line_ticket", locale, ticket=request_obj.ticket
        )
    message += get_message(
        "confirmation.line_requested_by", locale, user=user_display
    )
    message += get_message("confirmation.footer_active", locale)

    return {
        "type": "maintenance_created",
        "success": True,
        "maintenance_id": confirmation.maintenanceid,
        "name": confirmation.name,
        "description": confirmation.description,
        "hosts_affected": len(resolved.host_ids),
        "groups_affected": len(resolved.group_ids),
        "recurrence_type": rec_type,
        "is_routine": rec_type != "once",
        "ticket_number": request_obj.ticket or "",
        "missing_hosts": list(resolved.missing_hosts),
        "missing_groups": list(resolved.missing_groups),
        "user_info": {
            "userid": user.userid,
            "username": user.username,
            "name": user.name,
            "surname": user.surname,
        },
        "message": message,
    }


def _decorate_list_entry(maint: dict[str, Any]) -> None:
    """Enrich a raw maintenance entry with the legacy display fields (in place).

    Formats the epoch ``active_since`` / ``active_till`` to ``"%Y-%m-%d %H:%M"``,
    derives ``is_routine`` / ``routine_type`` from the first time period's
    ``timeperiod_type`` and extracts a ``ticket_number`` from the name/description.
    """
    for key in ("active_since", "active_till"):
        raw = maint.get(key)
        ts = _as_int(raw)
        if ts is not None:
            maint[key] = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

    is_routine = False
    routine_type = "once"
    timeperiods = maint.get("timeperiods")
    if isinstance(timeperiods, list) and timeperiods:
        tp_type = _as_int(timeperiods[0].get("timeperiod_type")) or 0
        routine_type = {2: "daily", 3: "weekly", 4: "monthly"}.get(tp_type, "once")
        is_routine = tp_type in (2, 3, 4)
    maint["is_routine"] = is_routine
    maint["routine_type"] = routine_type

    # Ticket is format-agnostic: reuse the shared fallback extractor rather than a
    # rigid ``NNN-NNNNNN`` regex so any nomenclature the system stored in the
    # name/description (e.g. ``Ticket: INC0012345``) is surfaced. Opaque string;
    # contract (``ticket_number``) unchanged.
    haystack = f"{maint.get('name', '')} {maint.get('description', '')}"
    maint["ticket_number"] = extract_ticket(haystack) or ""


def _test_config_from(data: dict[str, Any]) -> RecurrenceConfig:
    """Build a :class:`RecurrenceConfig` for ``/test/routine`` from the payload.

    Accepts either the v2 structured ``recurrence`` object or a legacy
    ``recurrence_config`` carrying precomputed bitmasks (``dayofweek`` / ``month``)
    and seconds (``start_time`` / ``duration`` / ``every`` / ``day``). Precomputed
    bitmasks are passed straight through so the engine validates them.
    """
    rec = _parse_recurrence(data)

    legacy = data.get("recurrence_config")
    legacy = legacy if isinstance(legacy, dict) else {}

    day_bitmask = _as_int(legacy.get("dayofweek"))
    month_bitmask = _as_int(legacy.get("month"))

    start_hour = rec.start_hour
    duration_hours = rec.duration_hours
    if start_hour is None and "start_time" in legacy:
        seconds = _as_int(legacy.get("start_time"))
        start_hour = seconds // 3600 if seconds is not None else None
    if duration_hours is None and "duration" in legacy:
        seconds = _as_int(legacy.get("duration"))
        duration_hours = seconds / 3600 if seconds is not None else None

    return RecurrenceConfig(
        recurrence_type=rec.recurrence_type,
        days=rec.days,
        months=rec.months,
        occurrences=rec.occurrences,
        day_of_month=(
            rec.day_of_month if rec.day_of_month is not None else _as_int(legacy.get("day"))
        ),
        start_hour=start_hour,
        duration_hours=duration_hours,
        every=rec.every if rec.every is not None else _as_int(legacy.get("every")),
        start_date=rec.start_date,
        start_ts=rec.start_ts,
        end_ts=rec.end_ts,
        day_bitmask=day_bitmask,
        month_bitmask=month_bitmask,
    )


def _describe_timeperiod(tp: Any) -> list[str]:
    """Decode a built :class:`~core.domain.TimePeriod` into human-readable lines.

    Mirrors the legacy ``/test/routine`` output: decodes the day-of-week and
    month bitmasks to Spanish names, reports the day-of-month, the week
    occurrence, and formats the start time / duration.
    """
    details: list[str] = []

    if tp.dayofweek:
        names = [_DAY_LABELS_ES[n] for n in decode_days(tp.dayofweek)]
        details.append(f"Días: {', '.join(names)} (bitmask: {tp.dayofweek})")
    if tp.day:
        details.append(f"Día del mes: {tp.day}")
    if tp.every and tp.dayofweek:
        week_name = _WEEK_LABELS_ES.get(tp.every, f"semana {tp.every}")
        details.append(f"Semana: {week_name} (valor: {tp.every})")
    if tp.month:
        names = [_MONTH_LABELS_ES[n] for n in decode_months(tp.month)]
        details.append(f"Meses: {', '.join(names)} (bitmask: {tp.month})")
    if tp.start_time is not None:
        hours = tp.start_time // 3600
        minutes = (tp.start_time % 3600) // 60
        details.append(f"Hora inicio: {hours:02d}:{minutes:02d} ({tp.start_time}s)")
    if tp.period is not None:
        hours = tp.period // 3600
        minutes = (tp.period % 3600) // 60
        details.append(f"Duración: {hours}h {minutes}m ({tp.period}s)")

    return details
