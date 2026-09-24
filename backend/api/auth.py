"""Session authentication for the HTTP layer (Req 11, 27).

This module is the authentication **edge** of the API. It authenticates every
acting request against a REAL Zabbix frontend **session** before any action is
taken, returning a clear "unauthorized" outcome (which the blueprints map to
HTTP **401**) when the session is missing, invalid or expired.

Why sessions, not a client-supplied ``userid``
-----------------------------------------------
An earlier design merely checked that a client-supplied ``userid`` EXISTED in
Zabbix (``user.get``). That is NOT authentication: anyone who guesses a valid
userid (e.g. ``1`` = Admin) could act. This module closes that hole. The client
now sends the Zabbix **session id** (obtained server-side by the widget from the
logged-in frontend session). The backend calls
:meth:`~zabbix.client.ZabbixClient.check_authentication`
(``user.checkAuthentication``), and Zabbix returns the VERIFIED user. The
backend uses THAT identity and ignores any client-claimed ``userid`` — the old
"trust the client's userid" path is removed (fail-closed), not kept as a
fallback.

Design:

* The **core decision** lives in :func:`authenticate_session`, a small,
  Flask-free, fully testable function returning an :class:`AuthResult`
  ``(ok, user, error)`` triple. Blueprints call it — or use the
  :func:`require_zabbix_user` decorator built on top of it — so the HTTP
  coupling stays thin. :func:`validate_user` is a thin alias kept for callers /
  tests that still import that name.
* A :class:`~cache.user_cache.UserValidationCache` is **interposed between the
  session validation and the ZabbixClient** (Req 27.2), now keyed on the
  **session id** (a validated credential): a valid cache entry avoids the
  ``user.checkAuthentication`` round-trip; an absent/expired entry revalidates
  against Zabbix (Req 27.3) and, on success, is written back.
* Cache access is wrapped defensively: a cache failure MUST NEVER prevent the
  underlying validation — on any cache error we fall through to Zabbix
  validation as if the cache had missed.

The validation sequence for a request carrying a ``sessionid``:

1. Extract ``sessionid`` from the payload (key ``sessionid``, alias
   ``session_id``); missing/blank → unauthorized WITHOUT any Zabbix call.
2. If a cache is provided, try :meth:`UserValidationCache.get_valid` keyed by
   the session id; a hit skips ``user.checkAuthentication`` (Req 27.2).
3. On a miss/expiry (or no cache), call
   :meth:`~zabbix.client.ZabbixClient.check_authentication`; a verified user
   dict → build :class:`UserInfo` from the VERIFIED fields, cache it and
   proceed; ``None`` (invalid/expired session or Zabbix unreachable) →
   unauthorized (fail closed).

The session id is a secret: it is NEVER written to logs or error messages, and
the generic :data:`UNAUTHORIZED_MESSAGE` never reveals whether it was missing,
invalid or expired (Req 18.4).

Requirements: 11.1, 11.2, 11.3, 18.4, 27.2, 27.3.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar, cast

from cache.user_cache import UserValidationCache
from core.domain import UserInfo
from zabbix.client import ZabbixClient

logger = logging.getLogger(__name__)

#: Default message returned to the client on an unauthorized outcome. Kept
#: generic on purpose — it never leaks whether the failure was a missing
#: session, an invalid/expired one or a Zabbix error (Req 11.3, 18.4).
UNAUTHORIZED_MESSAGE = "Unauthorized: invalid or missing session"

#: Payload keys carrying the Zabbix frontend session id, in precedence order.
_SESSION_KEYS = ("sessionid", "session_id")


@dataclass(frozen=True)
class AuthResult:
    """Outcome of an :func:`authenticate_session` call.

    A small value object the blueprints serialize. When ``ok`` is ``False`` the
    caller responds with HTTP 401 using :attr:`error` as the message; when
    ``True``, :attr:`user` holds the VERIFIED :class:`~core.domain.UserInfo`
    Zabbix returned for the session.
    """

    ok: bool
    user: UserInfo | None = None
    error: str | None = None

    @classmethod
    def success(cls, user: UserInfo) -> AuthResult:
        """Build a successful result carrying the verified ``user``."""
        return cls(ok=True, user=user, error=None)

    @classmethod
    def unauthorized(cls, message: str = UNAUTHORIZED_MESSAGE) -> AuthResult:
        """Build an unauthorized result (the blueprint maps this to 401)."""
        return cls(ok=False, user=None, error=message)


class AuthError(Exception):
    """Raised by :func:`require_zabbix_user` when authentication fails.

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


def extract_sessionid(data: Any) -> str | None:
    """Extract the Zabbix session id from a request payload.

    Accepts the canonical key ``sessionid`` and the alias ``session_id``
    (``sessionid`` wins). Returns the trimmed session id, or ``None`` when the
    payload is not a usable shape or carries no non-empty session id. Never
    raises for malformed input — an unusable payload is simply "unauthorized".
    The value is a secret and is never logged.

    Args:
        data: The request body (or query args mapping) to read from.

    Returns:
        The non-empty session id string, or ``None``.
    """
    if not isinstance(data, dict):
        return None
    for key in _SESSION_KEYS:
        raw = data.get(key)
        if raw is None:
            continue
        sid = str(raw).strip()
        if sid:
            return sid
    return None


def _user_info_from_zabbix(verified: dict[str, Any]) -> UserInfo | None:
    """Build a :class:`UserInfo` from the VERIFIED ``user.checkAuthentication`` dict.

    Uses ONLY the fields Zabbix returned for the session (``userid`` /
    ``username`` / ``name`` / ``surname``); any client-claimed identity is
    ignored. Returns ``None`` when the verified object lacks a non-empty
    ``userid`` (an unexpected shape → fail closed).
    """
    raw_userid = verified.get("userid")
    if raw_userid is None:
        return None
    userid = str(raw_userid).strip()
    if not userid:
        return None
    return UserInfo(
        userid=userid,
        username=str(verified.get("username", "")),
        name=str(verified.get("name", "")),
        surname=str(verified.get("surname", "")),
    )


def _cache_lookup(
    cache: UserValidationCache | None, key: str
) -> UserInfo | None:
    """Look up ``key`` (a validated session id) in ``cache`` defensively.

    Returns the cached :class:`UserInfo` on a valid hit, or ``None`` on a
    miss/expiry. Any exception raised by the cache is swallowed and treated as a
    miss so a cache failure can NEVER block the underlying Zabbix validation.

    Args:
        cache: The validation cache, or ``None`` when caching is disabled.
        key: The session id to look up.

    Returns:
        The cached :class:`UserInfo` while valid, otherwise ``None``.
    """
    if cache is None:
        return None
    try:
        return cache.get_valid(key)
    except Exception:  # noqa: BLE001 - cache must never break validation
        logger.warning("Session validation cache lookup failed; revalidating", exc_info=True)
        return None


def _cache_store(
    cache: UserValidationCache | None, key: str, info: UserInfo
) -> None:
    """Write a successful validation back to ``cache`` defensively (Req 27.1).

    Keyed by the validated session id. A failure to persist the entry is logged
    and ignored: caching is an optimization and must never turn a valid session
    into an error.
    """
    if cache is None:
        return
    try:
        cache.put(key, info)
    except Exception:  # noqa: BLE001 - cache must never break validation
        logger.warning("Session validation cache store failed; continuing", exc_info=True)


def authenticate_session(
    data: Any,
    client: ZabbixClient,
    cache: UserValidationCache | None = None,
) -> AuthResult:
    """Authenticate a request against a real Zabbix session (Req 11, 27).

    This is the Flask-free core decision, safe to unit-test in isolation. The
    flow (fail-closed throughout):

    1. Extract the ``sessionid`` (or ``session_id`` alias) from ``data``; a
       missing/blank session yields an unauthorized result WITHOUT any Zabbix
       call (Req 11.3).
    2. When a ``cache`` is provided, a valid entry keyed by the SESSION ID
       short-circuits and skips the ``user.checkAuthentication`` call (Req
       27.2). Cache errors are swallowed and treated as a miss.
    3. On a cache miss/expiry (or no cache), call
       :meth:`~zabbix.client.ZabbixClient.check_authentication`. A verified user
       dict → build :class:`UserInfo` from the VERIFIED fields Zabbix returned
       (NOT anything the client claimed), cache it and return success. ``None``
       (invalid/expired session OR Zabbix unreachable) → unauthorized.

    Args:
        data: The request payload carrying the session id (dict or query args).
        client: The Zabbix client used to verify the session.
        cache: Optional :class:`UserValidationCache` interposed before Zabbix,
            keyed by the session id.

    Returns:
        An :class:`AuthResult`: ``ok=True`` with the verified user, or
        ``ok=False`` with a generic error the blueprint maps to HTTP 401.
    """
    sessionid = extract_sessionid(data)
    if sessionid is None:
        return AuthResult.unauthorized()

    # Step 2 — cache first (Req 27.2), keyed by the validated session id. A hit
    # avoids the user.checkAuthentication round-trip.
    cached = _cache_lookup(cache, sessionid)
    if cached is not None:
        return AuthResult.success(cached)

    # Step 3 — verify the session against Zabbix (Req 11.2, 27.3). Note:
    # check_authentication already fails closed to None for BOTH an
    # invalid/expired session AND an unreachable Zabbix, so there is nothing to
    # re-raise here — the outcome is uniformly "unauthorized" (Req 11.3).
    verified = client.check_authentication(sessionid)
    if verified is None:
        return AuthResult.unauthorized()

    info = _user_info_from_zabbix(verified)
    if info is None:
        return AuthResult.unauthorized()

    _cache_store(cache, sessionid, info)
    return AuthResult.success(info)


def validate_user(
    data: Any,
    client: ZabbixClient,
    cache: UserValidationCache | None = None,
) -> AuthResult:
    """Backward-compatible alias of :func:`authenticate_session`.

    The name is kept so existing imports keep working, but the semantics are the
    new session-based ones: ``data`` must carry a ``sessionid`` (any
    client-supplied ``userid`` is ignored for identity). Prefer
    :func:`authenticate_session` in new code.
    """
    return authenticate_session(data, client, cache)


F = TypeVar("F", bound=Callable[..., Any])


def require_zabbix_user(
    client: ZabbixClient,
    cache: UserValidationCache | None = None,
    *,
    user_arg: str = "user",
) -> Callable[[F], F]:
    """Decorator enforcing a valid Zabbix session before a view runs (Req 11).

    Reads the request JSON body (via :mod:`flask`), authenticates the
    ``sessionid`` with :func:`authenticate_session` and, on failure, raises
    :class:`AuthError` (401, Req 11.3) which the app serializes. On success the
    VERIFIED :class:`~core.domain.UserInfo` Zabbix returned is passed to the
    wrapped view as the ``user`` keyword argument so blueprints get the
    authenticated user directly.

    Flask coupling is intentionally confined to this decorator; the core
    decision stays in :func:`authenticate_session`. ``flask`` is imported lazily
    so the module can be imported and tested without Flask.

    Args:
        client: The Zabbix client used for session verification.
        cache: Optional session-validation cache interposed before Zabbix.
        user_arg: Name of the keyword argument used to pass the verified user
            to the wrapped view (default ``"user"``).

    Returns:
        A decorator wrapping a Flask view function.
    """

    def decorator(view: F) -> F:
        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from flask import request

            payload = request.get_json(silent=True) or {}

            result = authenticate_session(payload, client, cache)
            if not result.ok:
                raise AuthError(result.error or UNAUTHORIZED_MESSAGE)

            kwargs[user_arg] = result.user
            return view(*args, **kwargs)

        return cast(F, wrapper)

    return decorator
