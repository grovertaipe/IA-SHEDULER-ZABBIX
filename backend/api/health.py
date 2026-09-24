"""Health blueprint: ``GET /health`` (Req 16).

Reports the service liveness/readiness in a shape the widget already consumes
(Req 15.3). The endpoint never raises: any Zabbix connectivity problem degrades
the reported status instead of erroring, so the widget can always render a
state.

Response contract (fields preserved from the legacy monolith so the widget keeps
working):

* ``status``           -- ``"healthy"`` when Zabbix is reachable, otherwise
  ``"degraded"`` (Req 16.2, 16.3).
* ``timestamp``        -- current time in ISO 8601 (Req 16.1).
* ``zabbix_connected`` -- ``bool`` from :meth:`ZabbixClient.is_connected`.
* ``zabbix_version``   -- ``"connected"`` when reachable, else ``"error"``
  (kept as a string for widget compatibility).
* ``ai_provider``      -- the configured provider name (Req 16.1).
* ``version``          -- the application version from config (Req 16.1).
* ``features``         -- the list of v2 capabilities (Req 16.4).

Flask coupling stays in this layer; the blueprint is built by the factory
:func:`make_health_blueprint`, which receives the :class:`ZabbixClient` and the
:class:`AppConfig` so it is testable without an app factory or global state.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify

from config import AppConfig
from zabbix.client import ZabbixClient

logger = logging.getLogger(__name__)

#: Capabilities advertised by the v2 backend (Req 16.4). Reflects the features
#: implemented across the v2 codebase: interactive chat and the routine
#: maintenance types, ticket handling, internationalisation, AI provider
#: failover, rate limiting and metrics.
SUPPORTED_FEATURES: tuple[str, ...] = (
    "interactive_chat",
    "routine_maintenance",
    "daily",
    "weekly",
    "monthly",
    "ticket_support",
    "i18n",
    "failover",
    "rate_limiting",
    "metrics",
)


def make_health_blueprint(client: ZabbixClient, config: AppConfig) -> Blueprint:
    """Build the health :class:`~flask.Blueprint` bound to ``client``/``config``.

    The app factory (Task 11.4) calls this with the configured
    :class:`ZabbixClient` and :class:`AppConfig` and registers the returned
    blueprint. Passing both dependencies explicitly keeps the blueprint free of
    global state and trivially testable with a fake client.
    """
    bp = Blueprint("health", __name__)

    @bp.get("/health")
    def health_check() -> Any:
        """Return the service health snapshot (Req 16.1-16.4).

        Probes Zabbix connectivity via :meth:`ZabbixClient.is_connected`
        (already swallows its own errors) and, defensively, treats any
        unexpected exception as "not connected" so ``/health`` never fails.
        """
        try:
            zabbix_ok = bool(client.is_connected())
        except Exception:  # noqa: BLE001 - health must never raise
            logger.exception("Unexpected error probing Zabbix connectivity")
            zabbix_ok = False

        return jsonify(
            {
                "status": "healthy" if zabbix_ok else "degraded",
                "timestamp": datetime.now(UTC).isoformat(),
                "zabbix_connected": zabbix_ok,
                "zabbix_version": "connected" if zabbix_ok else "error",
                "ai_provider": config.ai_provider,
                "version": config.version,
                "features": list(SUPPORTED_FEATURES),
            }
        )

    return bp
