"""Rate-limit decision and per-client middleware for the API layer (Req 28).

The **decision** is a single pure, deterministic function,
:func:`is_within_rate_limit` (Req 28.4): no I/O, no Flask, given the number of
requests already counted in the current window it only encodes the boundary.

On top of it this module hosts the **edge**: :class:`RateLimiter` owns the
stateful, per-client windowed counters, and :func:`install_rate_limit` /
:func:`make_rate_limit_before_request` wire that limiter into Flask as a
``before_request`` hook that returns 429 when a client is over the limit
(Req 28.1, 28.2, 28.3). Flask is imported lazily inside the hook so the pure
decision stays importable and testable without Flask.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from flask import Flask, Response


def is_within_rate_limit(count_in_window: int, limit: int) -> bool:
    """Decide whether a request is within the rate limit (Req 28.4).

    Pure and deterministic: allows the request if and only if
    ``count_in_window < limit``. The boundary (``count_in_window == limit``)
    is REJECTED.

    Args:
        count_in_window: Number of requests already counted in the current
            window for the client (``>= 0``).
        limit: Maximum number of requests allowed per window (``>= 0``).

    Returns:
        ``True`` if the request is within the limit (``count_in_window <
        limit``), otherwise ``False``.
    """
    return count_in_window < limit


# ---------------------------------------------------------------------------
# Per-client rate-limit middleware (Req 28.1, 28.2, 28.3)
# ---------------------------------------------------------------------------
#
# The pure decision above (:func:`is_within_rate_limit`) encodes only the
# boundary; the stateful, per-client windowed counters live here at the edge.
#
# Design (design.md §9 "Limitación de tasa"):
#
# * :class:`RateLimiter` identifies the client (remote IP, honoring
#   ``X-Forwarded-For``), keeps a fixed-window counter keyed by
#   ``(client, window_index)`` where ``window_index = floor(now /
#   window_seconds)``, increments it per request and asks
#   :func:`is_within_rate_limit` whether the request is allowed. The window
#   resets automatically once ``now`` crosses into the next window index — old
#   buckets are pruned so memory stays bounded.
# * The current time comes solely from an **injected clock** so the middleware
#   is deterministic and testable without patching :func:`time.time`.
# * :func:`make_rate_limit_before_request` turns a limiter into a Flask
#   ``before_request`` callable returning a **429** JSON body
#   ``{"type": "error", "message": ...}`` when over the limit (Req 28.2, 28.3)
#   and ``None`` otherwise so the request proceeds (Req 28.2).
# * :func:`install_rate_limit` registers that callable as the app's FIRST
#   ``before_request`` hook so it runs BEFORE user validation and service
#   orchestration (Req 28.1). The app factory (Task 11.4) calls this helper.

#: Client-facing message returned in the 429 body when the limit is exceeded
#: (Req 28.3). Kept generic and free of any client identifier.
RATE_LIMIT_EXCEEDED_MESSAGE = "Rate limit exceeded: too many requests"


class RateLimiter:
    """Per-client fixed-window request counter (Req 28.1, 28.2, 28.3).

    State (the ``(client, window_index) -> count`` map) lives here, but the
    current time is derived exclusively from the injected ``clock`` callable,
    keeping the counting logic deterministic and testable. The window boundary
    decision itself is delegated to the pure :func:`is_within_rate_limit`.

    Each call to :meth:`allow` maps ``now`` to a window index
    (``floor(now / window_seconds)``), evaluates whether the client is still
    within the limit for the *current* count, and — when allowed — records the
    request by incrementing the counter for that ``(client, window_index)``
    bucket. Stale buckets (from earlier windows) are discarded so memory does
    not grow unbounded.
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Initialize the limiter.

        Args:
            max_requests: Maximum number of requests allowed per window
                (``rate_limit_max_requests``, Req 28.1).
            window_seconds: Size of the fixed window in seconds
                (``rate_limit_window_seconds``, Req 28.1). Must be ``> 0``.
            clock: Callable returning the current time in seconds. Injected so
                tests can control time without touching :func:`time.time`.

        Raises:
            ValueError: If ``window_seconds`` is not strictly positive.
        """
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._clock = clock
        self._counts: dict[tuple[str, int], int] = {}

    def _window_index(self, now: float) -> int:
        """Return the fixed-window index containing timestamp ``now``."""
        return int(now // self._window_seconds)

    def allow(self, client: str) -> bool:
        """Register a request for ``client`` and decide whether to allow it.

        Computes the current window index from the injected clock, prunes
        counters from previous windows for this client, and allows the request
        iff the count already seen in the window is within the limit
        (:func:`is_within_rate_limit`). When allowed the counter is
        incremented; when rejected the counter is left untouched so a blocked
        request does not consume additional budget.

        Args:
            client: The identifier of the requesting client (e.g. its IP).

        Returns:
            ``True`` if the request is within the limit and has been counted,
            ``False`` if the limit is already reached for the current window.
        """
        now = self._clock()
        window = self._window_index(now)
        key = (client, window)

        # Prune stale buckets for this client so memory stays bounded and the
        # window "resets" once time advances into a new window index.
        self._prune(client, window)

        current = self._counts.get(key, 0)
        if not is_within_rate_limit(current, self._max_requests):
            return False

        self._counts[key] = current + 1
        return True

    def _prune(self, client: str, current_window: int) -> None:
        """Drop counters for ``client`` from windows other than the current one."""
        stale = [
            existing
            for existing in self._counts
            if existing[0] == client and existing[1] != current_window
        ]
        for existing in stale:
            del self._counts[existing]


def identify_client(request: Any) -> str:
    """Identify the client behind ``request`` (Req 28.1).

    Prefers the first hop in ``X-Forwarded-For`` (the original client when the
    app sits behind a proxy / load balancer) and falls back to the connection's
    ``remote_addr``. Returns ``"unknown"`` when neither is available so a
    missing address still maps to a single, poolable bucket rather than raising.

    Args:
        request: The Flask request object (duck-typed for testability).

    Returns:
        A stable string key identifying the client.
    """
    forwarded = request.headers.get("X-Forwarded-For") if request.headers else None
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    remote = getattr(request, "remote_addr", None)
    return remote or "unknown"


def make_rate_limit_before_request(
    limiter: RateLimiter,
) -> Callable[[], Response | None]:
    """Build a Flask ``before_request`` handler enforcing ``limiter`` (Req 28).

    The returned callable identifies the client from the current request,
    consults ``limiter`` and, when the client is over the limit, returns a
    **429** JSON response ``{"type": "error", "message": ...}`` so the action is
    NOT executed (Req 28.2, 28.3). Otherwise it returns ``None`` and Flask lets
    the request proceed to subsequent hooks (user validation) and the view
    (Req 28.2).

    ``flask`` is imported lazily so this module — and the pure
    :func:`is_within_rate_limit` — stay importable and testable without Flask.

    Args:
        limiter: The per-client :class:`RateLimiter` to enforce.

    Returns:
        A zero-argument callable suitable for ``app.before_request``.
    """

    def _before_request() -> Response | None:
        from flask import jsonify, request

        client = identify_client(request)
        if limiter.allow(client):
            return None

        response = jsonify({"type": "error", "message": RATE_LIMIT_EXCEEDED_MESSAGE})
        response.status_code = 429
        return response

    return _before_request


def install_rate_limit(app: Flask, limiter: RateLimiter) -> None:
    """Register the rate-limit middleware on ``app`` (Req 28.1).

    Attaches :func:`make_rate_limit_before_request` as a ``before_request``
    hook. Because the app factory (Task 11.4) calls this **before** registering
    user validation and service orchestration, this hook runs first and rejects
    over-limit requests with 429 before any action is taken (Req 28.1).

    Args:
        app: The Flask application to protect.
        limiter: The per-client :class:`RateLimiter` to enforce.
    """
    app.before_request(make_rate_limit_before_request(limiter))
