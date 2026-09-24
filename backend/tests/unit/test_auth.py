"""Unit tests for session authentication with cache interposition (Tasks 11.1, 22.3).

These tests use a fake :class:`~zabbix.client.ZabbixClient`
(``check_authentication`` overridden, no network) plus a real
:class:`~cache.user_cache.UserValidationCache` driven by a controllable fake
clock, so the caching behavior is fully deterministic. They verify the REAL
session-authentication flow (``user.checkAuthentication``), which replaced the
old "trust a client-supplied userid" mechanism:

* missing / empty ``sessionid`` → unauthorized WITHOUT any Zabbix call;
* a valid ``sessionid`` → ``check_authentication`` returns the VERIFIED user and
  the result uses THAT identity, NOT any client-claimed ``userid``;
* an invalid/expired session (``check_authentication`` returns ``None``) →
  unauthorized;
* a Zabbix transport error path → unauthorized (fail closed) with a generic
  message that leaks nothing;
* the first validation calls ``check_authentication`` once and caches by session
  id; a second call within the TTL is served from cache; an expired entry
  revalidates;
* a cache failure never blocks the underlying validation (defensive wrapping).
"""

from __future__ import annotations

from typing import Any

from api.auth import (
    UNAUTHORIZED_MESSAGE,
    authenticate_session,
    validate_user,
)
from cache.user_cache import UserValidationCache
from core.domain import UserInfo
from zabbix.client import ZabbixClient, ZabbixError


class _FakeClock:
    """A manually advanced monotonic clock for deterministic TTL tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeZabbixClient(ZabbixClient):
    """A ZabbixClient whose ``check_authentication`` is a controllable fake.

    ``sessions`` maps a valid session id → the VERIFIED user object Zabbix would
    return. Unknown session ids yield ``None`` (invalid/expired). When ``fail``
    is set, the underlying ``_rpc`` would raise :class:`ZabbixError`; since the
    real :meth:`check_authentication` swallows that into ``None`` (fail closed),
    this fake mimics that contract by returning ``None`` too — but we assert the
    swallow behaviour separately with a dedicated raising fake below.
    """

    def __init__(
        self, sessions: dict[str, dict[str, Any]] | None = None
    ) -> None:
        super().__init__("http://zabbix.invalid/api_jsonrpc.php", "token")
        self._sessions = sessions or {}
        self.check_calls = 0

    def check_authentication(self, sessionid: str) -> dict[str, Any] | None:
        self.check_calls += 1
        return self._sessions.get(sessionid)


class _RaisingRpcClient(ZabbixClient):
    """A ZabbixClient whose ``_rpc`` raises, to exercise the real swallow-to-None.

    This uses the REAL :meth:`ZabbixClient.check_authentication` (not a fake) so
    the test proves that a transport/API :class:`ZabbixError` is turned into
    ``None`` (fail closed) and never propagates out of the auth layer.
    """

    def __init__(self) -> None:
        super().__init__("http://zabbix.invalid/api_jsonrpc.php", "token")
        self.rpc_calls = 0

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        self.rpc_calls += 1
        raise ZabbixError("Zabbix unreachable")


#: A verified user object as Zabbix's ``user.checkAuthentication`` would return.
_VERIFIED = {
    "userid": "42",
    "username": "operator",
    "name": "Op",
    "surname": "Erator",
    "type": "3",
}


def _cache(clock: _FakeClock, ttl: int = 300) -> UserValidationCache:
    return UserValidationCache(ttl=ttl, clock=clock)


def test_missing_sessionid_is_unauthorized_without_zabbix_call() -> None:
    """An absent/empty sessionid is unauthorized and never touches Zabbix."""
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})

    for payload in (
        None,
        {},
        {"sessionid": ""},
        {"sessionid": "   "},
        {"session_id": ""},
        {"userid": "1"},  # a client-claimed userid alone is NOT a credential
    ):
        result = authenticate_session(payload, client)
        assert result.ok is False
        assert result.user is None
        assert result.error == UNAUTHORIZED_MESSAGE

    assert client.check_calls == 0


def test_valid_session_uses_zabbix_verified_identity() -> None:
    """A valid session authenticates with the identity ZABBIX returns.

    The client sends a DIFFERENT userid in the payload; the result must ignore
    it and use the verified userid/username Zabbix returned for the session.
    """
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})

    result = authenticate_session(
        {"sessionid": "sid-good", "userid": "1", "username": "attacker"},
        client,
    )

    assert result.ok is True
    assert result.user is not None
    # Verified identity from Zabbix — NOT the client-claimed "1" / "attacker".
    assert result.user.userid == "42"
    assert result.user.username == "operator"
    assert result.user.name == "Op"
    assert result.user.surname == "Erator"
    assert client.check_calls == 1


def test_session_id_alias_is_accepted() -> None:
    """The ``session_id`` alias works like ``sessionid``."""
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})

    result = authenticate_session({"session_id": "sid-good"}, client)

    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "42"


def test_invalid_or_expired_session_is_unauthorized() -> None:
    """An unknown/expired session (check_authentication → None) is unauthorized."""
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})

    result = authenticate_session({"sessionid": "sid-expired"}, client)

    assert result.ok is False
    assert result.user is None
    assert result.error == UNAUTHORIZED_MESSAGE
    assert client.check_calls == 1


def test_zabbix_transport_error_fails_closed_and_does_not_leak() -> None:
    """A Zabbix transport/API error fails closed as a generic unauthorized.

    Uses the REAL check_authentication (via a raising _rpc) to prove the
    ZabbixError is swallowed to None and the auth layer returns the generic
    message without leaking any detail.
    """
    client = _RaisingRpcClient()

    result = authenticate_session({"sessionid": "sid-any"}, client)

    assert result.ok is False
    assert result.user is None
    assert result.error == UNAUTHORIZED_MESSAGE
    # The real method was exercised (it called _rpc) and swallowed the error.
    assert client.rpc_calls == 1
    # Nothing about the session id or the underlying error leaks in the message.
    assert "sid-any" not in (result.error or "")


def test_first_validation_calls_zabbix_and_caches_by_sessionid() -> None:
    """First validation hits check_authentication and caches by session id."""
    clock = _FakeClock()
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})
    cache = _cache(clock)

    result = authenticate_session({"sessionid": "sid-good"}, client, cache)

    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "42"
    assert client.check_calls == 1
    # The successful validation is cached keyed by the SESSION ID.
    assert cache.get_valid("sid-good") is not None


def test_second_validation_within_ttl_skips_zabbix() -> None:
    """A cache hit within the TTL avoids the checkAuthentication round-trip."""
    clock = _FakeClock()
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})
    cache = _cache(clock, ttl=300)

    first = authenticate_session({"sessionid": "sid-good"}, client, cache)
    assert first.ok is True
    assert client.check_calls == 1

    clock.advance(299)  # still strictly within the 300s TTL
    second = authenticate_session({"sessionid": "sid-good"}, client, cache)

    assert second.ok is True
    assert second.user is not None
    assert second.user.userid == "42"
    # No further Zabbix call: served from cache.
    assert client.check_calls == 1


def test_expired_entry_revalidates_against_zabbix() -> None:
    """An expired cache entry forces a fresh checkAuthentication call."""
    clock = _FakeClock()
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})
    cache = _cache(clock, ttl=300)

    authenticate_session({"sessionid": "sid-good"}, client, cache)
    assert client.check_calls == 1

    clock.advance(300)  # boundary: (now - cached_at) == ttl -> EXPIRED
    result = authenticate_session({"sessionid": "sid-good"}, client, cache)

    assert result.ok is True
    assert client.check_calls == 2  # revalidated


def test_invalid_session_is_not_cached() -> None:
    """A failed session validation must not be cached."""
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})
    cache = _cache(_FakeClock())

    result = authenticate_session({"sessionid": "sid-bad"}, client, cache)

    assert result.ok is False
    assert client.check_calls == 1
    assert cache.get_valid("sid-bad") is None


def test_cache_failure_never_blocks_validation() -> None:
    """A broken cache falls through to Zabbix validation (defensive)."""

    class _BrokenCache(UserValidationCache):
        def get_valid(self, key: str) -> UserInfo | None:
            raise RuntimeError("cache backend down")

        def put(self, key: str, info: UserInfo) -> None:
            raise RuntimeError("cache backend down")

    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})
    cache = _BrokenCache(ttl=300, clock=_FakeClock())

    result = authenticate_session({"sessionid": "sid-good"}, client, cache)

    # Cache errors are swallowed: validation still succeeds via Zabbix.
    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "42"
    assert client.check_calls == 1


def test_validate_user_alias_delegates_to_session_auth() -> None:
    """The legacy ``validate_user`` name authenticates by session too."""
    client = _FakeZabbixClient(sessions={"sid-good": _VERIFIED})

    result = validate_user({"sessionid": "sid-good"}, client)

    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "42"
    assert client.check_calls == 1
