"""User validation cache with injectable clock (Req 27).

The validity decision is a **pure, deterministic** function
(:func:`is_cache_entry_valid`, Req 27.4). The cache itself
(:class:`UserValidationCache`) holds state (an in-memory dict) but derives the
current time exclusively from an **injected clock**, so its logic is fully
testable without coupling to :func:`time.time`.

It is used by ``api/auth.py`` to avoid issuing a ``user.get`` request against
Zabbix on every call: a successful validation is cached for a configurable TTL
(``user_cache_ttl_seconds``, Req 27.1) and reused while still valid (Req 27.2);
once expired the cache returns ``None`` to force revalidation (Req 27.3).

Requirements: 27.1, 27.2, 27.3, 27.4.
"""

from __future__ import annotations

from collections.abc import Callable

from core.domain import UserInfo


def is_cache_entry_valid(now: float, cached_at: float, ttl: int) -> bool:
    """Return whether a cached entry is still valid (Req 27.4).

    Pure and deterministic: the entry is valid **if and only if**
    ``(now - cached_at) < ttl``. The boundary ``(now - cached_at) == ttl`` is
    considered EXPIRED (strict less-than).

    Args:
        now: Current timestamp (seconds).
        cached_at: Timestamp when the entry was recorded (seconds).
        ttl: Time-to-live in seconds.

    Returns:
        ``True`` while the entry is within its TTL, ``False`` otherwise.
    """
    return (now - cached_at) < ttl


class UserValidationCache:
    """In-memory cache of successful user validations with a TTL (Req 27).

    State (the ``userid -> (info, cached_at)`` map) lives here, but the current
    time comes solely from the injected ``clock`` callable, keeping the caching
    logic deterministic and testable.
    """

    def __init__(self, ttl: int, clock: Callable[[], float]) -> None:
        """Initialize the cache.

        Args:
            ttl: Time-to-live for each entry, in seconds (Req 27.1).
            clock: Callable returning the current time in seconds. Injected so
                tests can control time without touching :func:`time.time`.
        """
        self._ttl = ttl
        self._clock = clock
        self._entries: dict[str, tuple[UserInfo, float]] = {}

    def get_valid(self, userid: str) -> UserInfo | None:
        """Return the cached :class:`UserInfo` if still valid, else ``None``.

        Returns the cached user metadata when a matching entry exists and is
        within its TTL (Req 27.2); otherwise returns ``None`` to force
        revalidation against Zabbix (Req 27.3).

        Args:
            userid: The identifier of the user to look up.

        Returns:
            The cached :class:`UserInfo` while valid, otherwise ``None``.
        """
        entry = self._entries.get(userid)
        if entry is None:
            return None
        info, cached_at = entry
        if is_cache_entry_valid(self._clock(), cached_at, self._ttl):
            return info
        return None

    def put(self, userid: str, info: UserInfo) -> None:
        """Record a successful validation with the current timestamp (Req 27.1).

        Args:
            userid: The identifier of the validated user.
            info: The user metadata to cache.
        """
        self._entries[userid] = (info, self._clock())
