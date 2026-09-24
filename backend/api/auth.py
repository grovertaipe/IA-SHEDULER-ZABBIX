"""Info_Usuario validation for the HTTP layer (Req 11, 27).

This module is the authentication **edge** of the API: it validates the
``Info_Usuario`` carried by an incoming request against Zabbix before any action
is taken, returning a clear "unauthorized" outcome (which the blueprints map to
HTTP **401**) when the user is absent or invalid (Req 11.1, 11.2, 11.3).

Design (design.md §"Capa HTTP" + §8 "Caché de validación de usuario"):

* The **core decision** lives in :func:`validate_user`, a small, Flask-free,
  fully testable function returning an :class:`AuthResult`
  ``(ok, user, error)`` triple. Blueprints (Tasks 11.2 / 11.3) call it — or use
  the :func:`require_zabbix_user` decorator built on top of it — so the HTTP
  coupling stays thin.
* A :class:`~cache.user_cache.UserValidationCache` is **interposed between the
  Info_Usuario validation and the ZabbixClient** (Req 27.2): a valid cache entry
  avoids the ``user.get`` round-trip; an absent/expired entry revalidates
  against Zabbix (Req 27.3) and, on success, is written back to the cache.
* Cache access is wrapped defensively: a cache failure MUST NEVER prevent the
  underlying validation — on any cache error we fall through to Zabbix
  validation as if the cache had missed.

The validation sequence for a request carrying ``userid``:

1. Extract ``userid`` from the payload; missing/empty → unauthorized (Req 11.3).
2. If a cache is provided, try :meth:`UserValidationCache.get_valid`; a hit
   skips ``user.get`` (Req 27.2).
3. On a miss/expiry (or no cache), call
   :meth:`~zabbix.client.ZabbixClient.user_exists` (Req 11.2); success →
   cache the result and proceed, failure/absence → unauthorized.

Requirements: 11.1, 11.2, 11.3, 27.2, 27.3.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from cache.user_cache import UserValidationCache
from core.domain import UserInfo
from zabbix.client import ZabbixClient, ZabbixError

logger = logging.getLogger(__name__)

#: Default message returned to the client on an unauthorized outcome. Kept
#: generic on purpose — it never leaks whether the failure was a missing field,
#: an unknown user or a Zabbix error (Req 11.3).
UNAUTHORIZED_MESSAGE = "Unauthorized: invalid or missing user information"


@dataclass(frozen=True)
class AuthResult:
    """Outcome of an :func:`validate_user` call.

    A small value object the blueprints serialize. When ``ok`` is ``False`` the
    caller responds with HTTP 401 using :attr:`error` as the message; when
    ``True``, :attr:`user` holds the validated :class:`~core.domain.UserInfo`.
    """

    ok: bool
    user: UserInfo | None = None
    error: str | None = None

    @classmethod
    def success(cls, user: UserInfo) -> AuthResult:
        """Build a successful result carrying the validated ``user``."""
        return cls(ok=True, user=user, error=None)

    @classmethod
    def unauthorized(cls, message: str = UNAUTHORIZED_MESSAGE) -> AuthResult:
        """Build an unauthorized result (the blueprint maps this to 401)."""
        return cls(ok=False, user=None, error=message)


class AuthError(Exception):
    """Raised by :func:`require_zabbix_user` when validation fails.

    Carries the client-facing :attr:`message` and the HTTP :attr:`status_code`
    (401) so the Flask app / blueprint can turn it into a JSON 401 response
    (Req 11.3). Using an exception keeps the decorator's happy path clean while
    still letting the app centralize error serialization.
    """

    def __init__(
        self, message: str = UNAUTHORIZED_MESSAGE, *, status_code: int = 401
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _coerce_user_info(user_info: UserInfo | dict[str, Any]) -> UserInfo | None:
    """Normalize the incoming user payload into a :class:`UserInfo`.

    Accepts either an already-built :class:`UserInfo` or the raw ``dict`` sent by
    the widget. Returns ``None`` when the payload is not a usable shape or lacks
    a non-empty ``userid`` (Req 11.3). Never raises for malformed input — an
    unusable payload is simply "unauthorized".

    Args:
        user_info: The ``user`` payload from the request (dict or UserInfo).

    Returns:
        A :class:`UserInfo` with a non-empty ``userid``, or ``None``.
    """
    if isinstance(user_info, UserInfo):
        return user_info if str(user_info.userid).strip() else None

    if not isinstance(user_info, dict):
        return None

    raw_userid = user_info.get("userid")
    if raw_userid is None:
        return None
    userid = str(raw_userid).strip()
    if not userid:
        return None

    return UserInfo(
        userid=userid,
        username=str(user_info.get("username", "")),
        name=str(user_info.get("name", "")),
        surname=str(user_info.get("surname", "")),
    )


def _cache_lookup(
    cache: UserValidationCache | None, userid: str
) -> UserInfo | None:
    """Look up ``userid`` in ``cache`` defensively (Req 27.2, 27.3).

    Returns the cached :class:`UserInfo` on a valid hit, or ``None`` on a
    miss/expiry. Any exception raised by the cache is swallowed and treated as a
    miss so a cache failure can NEVER block the underlying Zabbix validation.

    Args:
        cache: The validation cache, or ``None`` when caching is disabled.
        userid: The user identifier to look up.

    Returns:
        The cached :class:`UserInfo` while valid, otherwise ``None``.
    """
    if cache is None:
        return None
    try:
        return cache.get_valid(userid)
    except Exception:  # noqa: BLE001 - cache must never break validation
        logger.warning("User validation cache lookup failed; revalidating", exc_info=True)
        return None


def _cache_store(
    cache: UserValidationCache | None, userid: str, info: UserInfo
) -> None:
    """Write a successful validation back to ``cache`` defensively (Req 27.1).

    A failure to persist the entry is logged and ignored: caching is an
    optimization and must never turn a valid user into an error.
    """
    if cache is None:
        return
    try:
        cache.put(userid, info)
    except Exception:  # noqa: BLE001 - cache must never break validation
        logger.warning("User validation cache store failed; continuing", exc_info=True)


def validate_user(
    user_info: UserInfo | dict[str, Any] | None,
    client: ZabbixClient,
    cache: UserValidationCache | None = None,
) -> AuthResult:
    """Validate the request's ``Info_Usuario`` (Req 11.1, 11.2, 11.3, 27.2, 27.3).

    This is the Flask-free core decision, safe to unit-test in isolation. The
    flow:

    1. Extract ``userid`` from ``user_info`` (dict or :class:`UserInfo`); a
       missing/empty identifier yields an unauthorized result (Req 11.3).
    2. When a ``cache`` is provided, a valid entry short-circuits and skips the
       ``user.get`` call (Req 27.2). Cache errors are swallowed and treated as a
       miss so they never block validation.
    3. On a cache miss/expiry (or no cache), call
       :meth:`~zabbix.client.ZabbixClient.user_exists` (Req 11.2). Success →
       cache the user and return it; absence or a Zabbix error → unauthorized.

    Args:
        user_info: The ``user`` payload from the request.
        client: The Zabbix client used to validate against ``user.get``.
        cache: Optional :class:`UserValidationCache` interposed before Zabbix.

    Returns:
        An :class:`AuthResult`: ``ok=True`` with the validated user, or
        ``ok=False`` with an error message the blueprint maps to HTTP 401.
    """
    if user_info is None:
        return AuthResult.unauthorized()

    info = _coerce_user_info(user_info)
    if info is None:
        return AuthResult.unauthorized()

    userid = info.userid

    # Step 2 — cache first (Req 27.2). A hit avoids the user.get round-trip.
    cached = _cache_lookup(cache, userid)
    if cached is not None:
        return AuthResult.success(cached)

    # Step 3 — revalidate against Zabbix (Req 11.2, 27.3).
    try:
        exists = client.user_exists(userid)
    except ZabbixError:
        # Zabbix unreachable or API error: fail closed (unauthorized) without
        # leaking details to the client (Req 11.3).
        logger.warning("Zabbix user validation failed for a request", exc_info=True)
        return AuthResult.unauthorized()

    if not exists:
        return AuthResult.unauthorized()

    _cache_store(cache, userid, info)
    return AuthResult.success(info)


F = TypeVar("F", bound=Callable[..., Any])


def require_zabbix_user(
    client: ZabbixClient,
    cache: UserValidationCache | None = None,
    *,
    user_arg: str = "user",
) -> Callable[[F], F]:
    """Decorator enforcing a valid ``Info_Usuario`` before a view runs (Req 11).

    Reads the request JSON body (via :mod:`flask`), validates the ``user`` field
    with :func:`validate_user` and, on failure, raises :class:`AuthError` (401,
    Req 11.3) which the app serializes. On success the validated
    :class:`~core.domain.UserInfo` is passed to the wrapped view as the ``user``
    keyword argument so blueprints get the authenticated user directly.

    Flask coupling is intentionally confined to this decorator; the core
    decision stays in :func:`validate_user`. ``flask`` is imported lazily so the
    module (and :func:`validate_user`) can be imported and tested without Flask.

    Args:
        client: The Zabbix client used for validation.
        cache: Optional user-validation cache interposed before Zabbix.
        user_arg: Name of the keyword argument used to pass the validated user
            to the wrapped view (default ``"user"``).

    Returns:
        A decorator wrapping a Flask view function.
    """

    def decorator(view: F) -> F:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from flask import request

            payload = request.get_json(silent=True) or {}
            user_payload = payload.get("user") if isinstance(payload, dict) else None

            result = validate_user(user_payload, client, cache)
            if not result.ok:
                raise AuthError(result.error or UNAUTHORIZED_MESSAGE)

            kwargs[user_arg] = result.user
            return view(*args, **kwargs)

        return cast(F, wrapper)

    return decorator
