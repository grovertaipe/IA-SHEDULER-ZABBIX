"""Unit tests for Info_Usuario validation with cache interposition (Tasks 11.1, 22.3).

These tests use a fake :class:`~zabbix.client.ZabbixClient` (``user_exists``
overridden, no network) plus a real
:class:`~cache.user_cache.UserValidationCache` driven by a controllable fake
clock, so the caching behavior is fully deterministic. They verify:

* missing / empty ``userid`` → unauthorized without any Zabbix call (Req 11.3);
* the first validation calls ``user_exists`` and caches the result (Req 11.2);
* a second validation within the TTL is served from the cache and does NOT call
  ``user_exists`` again (Req 27.2);
* an expired entry revalidates against Zabbix (Req 27.3);
* an unknown user → unauthorized (Req 11.1, 11.2);
* a cache failure never blocks the underlying validation (defensive wrapping).
"""

from __future__ import annotations

from api.auth import UNAUTHORIZED_MESSAGE, validate_user
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
    """A ZabbixClient whose ``user_exists`` is a fake counting known userids."""

    def __init__(self, known: set[str], *, fail: bool = False) -> None:
        super().__init__("http://zabbix.invalid/api_jsonrpc.php", "token")
        self._known = known
        self._fail = fail
        self.user_exists_calls = 0

    def user_exists(self, userid: str) -> bool:
        self.user_exists_calls += 1
        if self._fail:
            raise ZabbixError("Zabbix unreachable")
        return userid in self._known


def _cache(clock: _FakeClock, ttl: int = 300) -> UserValidationCache:
    return UserValidationCache(ttl=ttl, clock=clock)


def test_missing_userid_is_unauthorized_without_zabbix_call() -> None:
    """An absent/empty userid is unauthorized and never touches Zabbix (Req 11.3)."""
    client = _FakeZabbixClient(known={"1"})

    for payload in (None, {}, {"userid": ""}, {"userid": "   "}, {"username": "ops"}):
        result = validate_user(payload, client)
        assert result.ok is False
        assert result.user is None
        assert result.error == UNAUTHORIZED_MESSAGE

    assert client.user_exists_calls == 0


def test_first_validation_calls_zabbix_and_caches() -> None:
    """First validation hits user_exists and stores the user (Req 11.2, 27.1)."""
    clock = _FakeClock()
    client = _FakeZabbixClient(known={"1"})
    cache = _cache(clock)

    result = validate_user({"userid": "1", "username": "ops"}, client, cache)

    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "1"
    assert result.user.username == "ops"
    assert client.user_exists_calls == 1
    # The successful validation is now cached.
    assert cache.get_valid("1") is not None


def test_second_validation_within_ttl_skips_zabbix() -> None:
    """A cache hit within the TTL avoids the user.get round-trip (Req 27.2)."""
    clock = _FakeClock()
    client = _FakeZabbixClient(known={"1"})
    cache = _cache(clock, ttl=300)

    first = validate_user({"userid": "1", "username": "ops"}, client, cache)
    assert first.ok is True
    assert client.user_exists_calls == 1

    clock.advance(299)  # still strictly within the 300s TTL
    second = validate_user({"userid": "1", "username": "ops"}, client, cache)

    assert second.ok is True
    assert second.user is not None
    assert second.user.userid == "1"
    # No further Zabbix call: served from cache (Req 27.2).
    assert client.user_exists_calls == 1


def test_expired_entry_revalidates_against_zabbix() -> None:
    """An expired cache entry forces a fresh user.get (Req 27.3)."""
    clock = _FakeClock()
    client = _FakeZabbixClient(known={"1"})
    cache = _cache(clock, ttl=300)

    validate_user({"userid": "1", "username": "ops"}, client, cache)
    assert client.user_exists_calls == 1

    clock.advance(300)  # boundary: (now - cached_at) == ttl -> EXPIRED
    result = validate_user({"userid": "1", "username": "ops"}, client, cache)

    assert result.ok is True
    assert client.user_exists_calls == 2  # revalidated


def test_unknown_user_is_unauthorized() -> None:
    """A userid Zabbix does not know yields unauthorized (Req 11.1, 11.2)."""
    client = _FakeZabbixClient(known={"1"})
    cache = _cache(_FakeClock())

    result = validate_user({"userid": "999"}, client, cache)

    assert result.ok is False
    assert result.user is None
    assert client.user_exists_calls == 1
    # A failed validation must not be cached.
    assert cache.get_valid("999") is None


def test_zabbix_error_is_unauthorized() -> None:
    """A Zabbix transport/API error fails closed as unauthorized (Req 11.3)."""
    client = _FakeZabbixClient(known={"1"}, fail=True)

    result = validate_user({"userid": "1"}, client)

    assert result.ok is False
    assert result.error == UNAUTHORIZED_MESSAGE


def test_cache_failure_never_blocks_validation() -> None:
    """A broken cache falls through to Zabbix validation (Req 27, defensive)."""

    class _BrokenCache(UserValidationCache):
        def get_valid(self, userid: str) -> UserInfo | None:
            raise RuntimeError("cache backend down")

        def put(self, userid: str, info: UserInfo) -> None:
            raise RuntimeError("cache backend down")

    client = _FakeZabbixClient(known={"1"})
    cache = _BrokenCache(ttl=300, clock=_FakeClock())

    result = validate_user({"userid": "1", "username": "ops"}, client, cache)

    # Cache errors are swallowed: validation still succeeds via Zabbix.
    assert result.ok is True
    assert result.user is not None
    assert client.user_exists_calls == 1


def test_validate_user_accepts_userinfo_instance() -> None:
    """A pre-built UserInfo payload is validated directly."""
    client = _FakeZabbixClient(known={"7"})

    result = validate_user(UserInfo(userid="7", username="admin"), client)

    assert result.ok is True
    assert result.user is not None
    assert result.user.userid == "7"
    assert client.user_exists_calls == 1
