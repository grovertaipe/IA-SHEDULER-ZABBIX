"""Search blueprint: ``POST /search_hosts`` and ``POST /search_groups`` (Req 15.1).

Thin HTTP adapter over the :class:`~zabbix.client.ZabbixClient` search methods.
It contains no business logic (Req 1.2): it validates the ``Info_Usuario`` (Req
11), reads the search term from the JSON body, delegates to the client and
shapes the response into the exact contract the widget already consumes (Req
15.3, 15.4).

Both endpoints hit Zabbix, so each requires a validated logged-in Zabbix user:
the ``user`` / ``user_info`` payload is validated with :func:`api.auth.validate_user`
before the search term is read, and a missing/invalid user maps to HTTP **401**
without touching Zabbix (Req 11, 15.7).

Response contract (preserved verbatim from the legacy monolith so the widget
keeps working):

* success  -> ``{"type": "search_results", "search_term", "hosts_found"/"groups_found",
  "hosts"/"groups", "message"}``
* bad input -> HTTP 400 ``{"type": "error", "message"}``
* failure  -> HTTP 500 ``{"type": "error", "message"}``

Flask coupling is confined to this layer; the blueprint is built by the factory
:func:`make_search_blueprint`, which receives the :class:`ZabbixClient` so the
blueprint is fully testable without an app factory or global state.
"""

from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify, request

from api.auth import validate_user
from cache.user_cache import UserValidationCache
from zabbix.client import ZabbixClient, ZabbixError

logger = logging.getLogger(__name__)


def _read_user_payload(data: Any) -> Any:
    """Return the user payload, accepting both ``user`` and ``user_info``.

    The v2 contract sends ``user``; the legacy widget sent ``user_info``. Both
    are accepted (``user`` wins) so existing widget builds keep working. Mirrors
    the helper used by the chat / maintenance blueprints so the auth edge stays
    consistent across the API.
    """
    if not isinstance(data, dict):
        return None
    if data.get("user") is not None:
        return data.get("user")
    return data.get("user_info")


def _read_search_term(data: Any) -> str | None:
    """Extract and normalise the ``search`` term from a request body.

    Returns the stripped term, or ``None`` when the body is missing, is not an
    object, lacks a ``search`` field, or the term is empty/blank. The caller
    turns ``None`` into an HTTP 400 (Req 15.7: an invalid request changes no
    state).
    """
    if not isinstance(data, dict) or "search" not in data:
        return None
    raw = data.get("search")
    if not isinstance(raw, str):
        return None
    term = raw.strip()
    return term or None


def make_search_blueprint(
    client: ZabbixClient, cache: UserValidationCache | None = None
) -> Blueprint:
    """Build the search :class:`~flask.Blueprint` bound to ``client``.

    The app factory (Task 11.4) calls this with the configured
    :class:`ZabbixClient` (and the shared :class:`UserValidationCache`) and
    registers the returned blueprint. Passing the dependencies explicitly keeps
    the blueprint decoupled from global state and trivially testable with a fake
    client.

    Both ``/search_hosts`` and ``/search_groups`` hit Zabbix, so each validates
    the ``Info_Usuario`` first (401 on failure, Req 11) before reading the
    search term or calling the client.
    """
    bp = Blueprint("search", __name__)

    def _require_user() -> Any | None:
        """Validate the request user; return a 401 response tuple on failure.

        Reads ``user`` / ``user_info`` from the JSON body and validates it via
        :func:`validate_user` (interposing the shared cache when present, Req
        27). Returns ``None`` when the user is valid so the caller proceeds, or
        the ``(json, 401)`` tuple the view should return otherwise (Req 11).
        """
        auth = validate_user(
            _read_user_payload(request.get_json(silent=True)), client, cache
        )
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
        return None

    @bp.post("/search_hosts")
    def search_hosts() -> Any:
        """Search hosts whose name matches the ``search`` term (Req 14.2, 15.1)."""
        unauthorized = _require_user()
        if unauthorized is not None:
            return unauthorized

        term = _read_search_term(request.get_json(silent=True))
        if term is None:
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": "Se requiere el campo 'search' con un término no vacío",
                    }
                ),
                400,
            )

        try:
            hosts = client.search_hosts(term)
        except ZabbixError as exc:
            logger.error("Error searching hosts: %s", exc)
            return (
                jsonify({"type": "error", "message": "Error interno al buscar hosts"}),
                500,
            )

        return jsonify(
            {
                "type": "search_results",
                "search_term": term,
                "hosts_found": len(hosts),
                "hosts": hosts,
                "message": f"Encontré {len(hosts)} host(s) que coinciden con '{term}'",
            }
        )

    @bp.post("/search_groups")
    def search_groups() -> Any:
        """Search host groups whose name matches the ``search`` term (Req 14.3, 15.1)."""
        unauthorized = _require_user()
        if unauthorized is not None:
            return unauthorized

        term = _read_search_term(request.get_json(silent=True))
        if term is None:
            return (
                jsonify(
                    {
                        "type": "error",
                        "message": "Se requiere el campo 'search' con un término no vacío",
                    }
                ),
                400,
            )

        try:
            groups = client.search_groups(term)
        except ZabbixError as exc:
            logger.error("Error searching groups: %s", exc)
            return (
                jsonify({"type": "error", "message": "Error interno al buscar grupos"}),
                500,
            )

        return jsonify(
            {
                "type": "search_results",
                "search_term": term,
                "groups_found": len(groups),
                "groups": groups,
                "message": f"Encontré {len(groups)} grupo(s) que coinciden con '{term}'",
            }
        )

    return bp
