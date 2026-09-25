"""Application factory / entry point (no business logic, Req 1.2).

This module hosts the Flask **app factory**: it *wires together* the components
already implemented across the codebase (configuration, Zabbix client, AI
provider, services and HTTP blueprints) and configures the cross-cutting HTTP
concerns (rate limiting, CORS, error handling). It deliberately contains **no**
recurrence, AI or Zabbix business logic (Req 1.2) — only construction and
registration.

Wiring performed by :func:`create_app` (in order):

1. Load the :class:`~config.AppConfig` (from the environment, or an injected
   override for tests).
2. Build the shared boundaries and services:
   :class:`~zabbix.client.ZabbixClient`, the AI provider stack via
   :func:`ai.factory.build_provider`, :class:`~services.chat_service.ChatService`
   and :class:`~services.maintenance_service.MaintenanceService`, the shared
   :class:`~observability.logger.SecureLogger`, :class:`~observability.metrics.Metrics`
   and the :class:`~cache.user_cache.UserValidationCache`.
3. Install the rate-limit middleware FIRST (``before_request``) so it runs
   before user validation and any action (Req 28.1).
4. Register the chat, maintenance, search, health and metrics blueprints
   (Req 15.1).
5. Enable CORS restricted to the configured allowed origins — never the
   wildcard — with preflight handling, scoped to the API routes (Req 15.5).
6. Register an :class:`~api.auth.AuthError` handler mapping it to a 401 JSON
   response as a safety net for the ``require_zabbix_user`` decorator path.

The factory is tolerant on import: :meth:`AppConfig.from_env` never raises (it
returns a degraded config), so a WSGI server importing ``app:create_app`` or the
module-level ``application`` will not crash when environment variables are
absent — the ``/health`` endpoint will simply report a degraded state.

WSGI entry points (used by the Docker/gunicorn setup, Task 14.1):

* ``app:create_app`` — the factory Gunicorn should call, e.g.
  ``gunicorn "app:create_app()"``.
* ``app:application`` — a module-level application built defensively at import
  time for servers that expect a ready callable.

Requirements: 1.2, 1.5, 15.5.
"""

from __future__ import annotations

import logging
import time

from flask import Flask, Response, jsonify
from flask_cors import CORS

from ai.factory import build_provider
from api.auth import AuthError
from api.chat import make_chat_blueprint
from api.health import make_health_blueprint
from api.maintenance import make_maintenance_blueprint
from api.metrics import make_metrics_blueprint
from api.rate_limit import RateLimiter, install_rate_limit
from api.search import make_search_blueprint
from cache.user_cache import UserValidationCache
from config import AppConfig
from observability.logger import SecureLogger
from observability.metrics import Metrics
from services.chat_service import ChatService
from services.maintenance_service import MaintenanceService
from zabbix.client import ZabbixClient

logger = logging.getLogger(__name__)


def create_app(config: AppConfig | None = None) -> Flask:
    """Build and return the wired Flask application (Req 1.2, 1.5, 15.5).

    Constructs the shared boundaries/services and registers the HTTP layer. It
    contains no business logic: every decision lives in the services, the
    recurrence engine, the AI provider or the Zabbix client. Passing ``config``
    lets tests inject a fully controlled :class:`AppConfig` (and, together with
    a monkeypatched client, exercise the app without real network access); when
    omitted a real :class:`AppConfig` is loaded from the environment.

    Args:
        config: Optional configuration override. When ``None`` the configuration
            is loaded via :meth:`AppConfig.from_env` (tolerant: never raises).

    Returns:
        A configured :class:`~flask.Flask` application ready to serve requests.
    """
    cfg = config if config is not None else AppConfig.from_env()

    app = Flask(__name__)

    # --- Shared boundaries and services (construction only, Req 1.2) --------
    secure_logger = SecureLogger()
    metrics = Metrics()

    # Outbound TLS verification to the Zabbix API. Precedence: a CA bundle path
    # (truthy str) wins -> verify against it; otherwise the boolean
    # ``zabbix_verify_tls`` (secure default True). An empty/None bundle falls
    # through to the bool. Mirrors requests' ``verify`` semantics.
    verify: bool | str = cfg.zabbix_ca_bundle or cfg.zabbix_verify_tls
    client = ZabbixClient(cfg.zabbix_url, cfg.zabbix_token, verify=verify)
    provider = build_provider(cfg, secure_logger)

    # The validation cache is constructed here so the wiring owns its lifecycle
    # (interposed before Zabbix by the auth edge, Req 27); the clock is the real
    # wall clock in production. It is attached to the app config so the auth
    # layer / decorator path can reuse it without global state.
    user_cache = UserValidationCache(cfg.user_cache_ttl_seconds, time.time)
    app.config["USER_VALIDATION_CACHE"] = user_cache

    chat_service = ChatService(provider, cfg)
    maintenance_service = MaintenanceService(client, cfg)

    # --- Rate-limit middleware FIRST (before user validation, Req 28.1) -----
    limiter = RateLimiter(cfg.rate_limit_max_requests, cfg.rate_limit_window_seconds)
    install_rate_limit(app, limiter)

    # --- HTTP blueprints (Req 15.1) -----------------------------------------
    app.register_blueprint(
        make_chat_blueprint(chat_service, maintenance_service, client, cfg)
    )
    app.register_blueprint(
        make_maintenance_blueprint(maintenance_service, client, cfg, user_cache)
    )
    app.register_blueprint(make_search_blueprint(client, user_cache))
    app.register_blueprint(make_health_blueprint(client, cfg))
    app.register_blueprint(make_metrics_blueprint(metrics))

    # --- CORS restricted to configured origins, with preflight (Req 15.5) ---
    # Explicit origins only — never the wildcard (the config layer already
    # strips ``*``). Applying an empty list keeps CORS closed by default.
    CORS(
        app,
        origins=cfg.cors_allowed_origins,
        supports_credentials=True,
        methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
        automatic_options=True,
    )

    # --- AuthError safety net -> 401 JSON (Req 11.3) ------------------------
    # The blueprints mostly call ``validate_user`` directly and already return
    # 401; this maps the ``require_zabbix_user`` decorator path cleanly too.
    @app.errorhandler(AuthError)
    def _handle_auth_error(exc: AuthError) -> tuple[Response, int]:
        return jsonify({"type": "error", "message": exc.message}), exc.status_code

    return app


def _build_application() -> Flask | None:
    """Build the module-level application defensively for WSGI servers.

    Never raises: any unexpected failure while wiring at import time is logged
    and yields ``None`` so importing this module (e.g. ``app:application``) can
    never crash the process. Prefer the ``app:create_app()`` factory entry point
    which surfaces errors eagerly.
    """
    try:
        return create_app()
    except Exception:  # noqa: BLE001 - import must never crash the WSGI server
        logger.exception("Failed to build the application at import time")
        return None


#: Module-level WSGI callable for servers expecting a ready application. Built
#: defensively so an import-time failure degrades to ``None`` rather than
#: crashing the server; Gunicorn should prefer the ``app:create_app()`` factory.
application: Flask | None = _build_application()
