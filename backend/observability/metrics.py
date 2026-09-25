"""Prometheus metrics registry and collection (observability/) (Req 30.1).

This module owns the *metric definitions* and small helper functions that
record them, plus a :func:`render` function that produces the Prometheus
exposition text consumed by the ``GET /metrics`` blueprint (``api/metrics.py``).

Design notes:

* Metrics are grouped in a :class:`Metrics` object bound to a private
  :class:`~prometheus_client.CollectorRegistry` rather than the process-global
  default registry. This keeps the collector **dependency-injectable and
  testable**: each :class:`Metrics` instance is isolated, so building one in a
  test (or a second app instance) never raises the duplicate-timeseries error
  the global registry would produce.
* The metrics only ever observe *operational* signals — endpoint names, HTTP
  status codes, latencies and failover events. No configuration value, token or
  other secret is ever used as a label or sample, so the exposition text cannot
  leak sensitive configuration (Req 30.1).

Requirements: 30.1.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

if TYPE_CHECKING:  # pragma: no cover - typing-only imports
    from flask import Flask, Response

#: Prometheus content type for the exposition format, re-exported so callers
#: (the ``/metrics`` blueprint) do not need to import ``prometheus_client``.
PROMETHEUS_CONTENT_TYPE: str = CONTENT_TYPE_LATEST

#: Histogram buckets (seconds) tuned for typical HTTP request latencies.
_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


class Metrics:
    """Container for the application's Prometheus collectors (Req 30.1).

    Each instance holds its own :class:`~prometheus_client.CollectorRegistry`
    and the collectors registered against it. Instances are independent, which
    makes the object safe to build in tests and in multiple app instances
    without clashing on the process-global default registry.

    Collectors:

    * ``request_count`` -- counter of handled requests, labelled by
      ``endpoint`` and ``status`` (HTTP status code as a string).
    * ``request_latency`` -- histogram of request durations in seconds,
      labelled by ``endpoint``.
    * ``ai_failover_events`` -- counter of AI provider failover switches,
      labelled by the chosen ``outcome`` (e.g. ``"secondary"``/``"unavailable"``).
    """

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        """Build the collectors against ``registry`` (a fresh one by default).

        Args:
            registry: The collector registry to register against. When ``None``
                a private :class:`~prometheus_client.CollectorRegistry` is
                created, keeping this ``Metrics`` instance isolated from the
                global default registry.
        """
        self.registry: CollectorRegistry = registry or CollectorRegistry()

        self.request_count: Counter = Counter(
            "http_requests_total",
            "Total number of HTTP requests handled.",
            labelnames=("endpoint", "status"),
            registry=self.registry,
        )
        self.request_latency: Histogram = Histogram(
            "http_request_duration_seconds",
            "HTTP request latency in seconds.",
            labelnames=("endpoint",),
            buckets=_LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.request_errors: Counter = Counter(
            "http_request_errors_total",
            "Total number of HTTP requests that resulted in an error response.",
            labelnames=("endpoint", "status"),
            registry=self.registry,
        )
        self.ai_failover_events: Counter = Counter(
            "ai_failover_events_total",
            "Total number of AI provider failover selections.",
            labelnames=("outcome",),
            registry=self.registry,
        )

    def record_request(self, endpoint: str, status: int, latency_seconds: float) -> None:
        """Record a handled request: count, latency and (if applicable) error.

        A response whose ``status`` is >= 400 also increments the error counter,
        so an error *rate* can be derived from ``http_request_errors_total`` over
        ``http_requests_total``.

        Args:
            endpoint: Logical endpoint name (never a secret / config value).
            status: HTTP status code of the response.
            latency_seconds: Wall-clock duration of the request in seconds.
        """
        status_label = str(status)
        self.request_count.labels(endpoint=endpoint, status=status_label).inc()
        self.request_latency.labels(endpoint=endpoint).observe(latency_seconds)
        if status >= 400:
            self.request_errors.labels(endpoint=endpoint, status=status_label).inc()

    def record_failover(self, outcome: str) -> None:
        """Record an AI provider failover selection (Req 26, 30.1).

        Args:
            outcome: The selection result (e.g. ``"primary"``, ``"secondary"``
                or ``"unavailable"``). It is an operational label, not a secret.
        """
        self.ai_failover_events.labels(outcome=outcome).inc()

    def render(self) -> bytes:
        """Return the Prometheus exposition text for this registry.

        Returns:
            The metrics serialized in the Prometheus text exposition format.
            The bytes contain only metric names, help/type lines and the
            operational labels defined above — never configuration secrets.
        """
        return generate_latest(self.registry)


def render(metrics: Metrics) -> tuple[bytes, str]:
    """Render ``metrics`` to ``(exposition_text, content_type)``.

    Convenience helper for the ``/metrics`` blueprint so it does not need to
    import ``prometheus_client`` directly.

    Args:
        metrics: The :class:`Metrics` instance to serialize.

    Returns:
        A ``(payload, content_type)`` tuple ready to build an HTTP response.
    """
    return metrics.render(), PROMETHEUS_CONTENT_TYPE


# ---------------------------------------------------------------------------
# Request-metrics middleware (Req 30.1)
# ---------------------------------------------------------------------------
#
# The collectors above only expose samples once something records them; on their
# own they render as bare ``# HELP``/``# TYPE`` lines with no data. This edge
# feeds :meth:`Metrics.record_request` once per handled request so the ``/metrics``
# blueprint (``api/metrics.py``) exposes real samples.
#
# Design (mirrors ``api/rate_limit.py``):
#
# * :func:`install_request_metrics` is the ``install_*`` helper the app factory
#   calls; it registers a ``before_request`` hook that stamps a monotonic start
#   time on :data:`flask.g` and an ``after_request`` hook that observes the
#   elapsed latency, the response status and a low-cardinality endpoint label.
# * The clock is an **injected** callable (default :func:`time.perf_counter`, a
#   monotonic timer — never :func:`time.time`) so latency measurement is
#   deterministic and testable without patching the standard library.
# * Flask is imported **lazily inside the hooks** so this module — and the pure
#   collectors above — stay importable and testable without Flask installed.
# * Endpoint label hygiene: the label is derived from the matched Flask ROUTE
#   (``request.url_rule.rule``, e.g. ``"/maintenance/list"``), falling back to
#   ``request.endpoint`` and then to ``"unknown"``. The raw URL / query string is
#   NEVER used, which keeps label cardinality bounded and prevents leaking query
#   parameters such as ``?sessionid=`` into the exposition text (Req 30.1).

#: Key under which the per-request start timestamp is stashed on ``flask.g``.
_METRICS_START_ATTR = "_metrics_start"

#: Label used when no route/endpoint can be resolved for a request (e.g. a 404
#: that never matched a rule). Keeps the label set bounded.
_UNKNOWN_ENDPOINT = "unknown"


def _endpoint_label(request: object) -> str:
    """Derive a low-cardinality endpoint label from ``request`` (Req 30.1).

    Prefers the matched route *rule* (e.g. ``"/maintenance/list"``) so the label
    is the template rather than the concrete path — this bounds cardinality and,
    critically, never contains the raw URL or query string (so a value like
    ``?sessionid=...`` can never leak into the metrics). Falls back to the Flask
    endpoint name and finally to :data:`_UNKNOWN_ENDPOINT`.

    Args:
        request: The Flask request (duck-typed for testability).

    Returns:
        A stable, non-sensitive endpoint label string.
    """
    url_rule = getattr(request, "url_rule", None)
    if url_rule is not None:
        rule = getattr(url_rule, "rule", None)
        if rule:
            return str(rule)
    endpoint = getattr(request, "endpoint", None)
    if endpoint:
        return str(endpoint)
    return _UNKNOWN_ENDPOINT


def install_request_metrics(
    app: Flask,
    metrics: Metrics,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    """Register per-request metric hooks on ``app`` (Req 30.1).

    Wires ``metrics`` into Flask so every handled request contributes a sample:

    * a ``before_request`` hook stamps a monotonic start time on
      :data:`flask.g`;
    * an ``after_request`` hook computes the elapsed latency, resolves a
      low-cardinality endpoint label (:func:`_endpoint_label`) and calls
      :meth:`Metrics.record_request` before returning the response unchanged.

    The start stamp is read defensively: a request that skipped
    ``before_request`` (for example a 404 that matched no rule) still gets
    counted, with a ``0.0`` latency, so no request is silently dropped from the
    counts.

    Following ``install_rate_limit``'s pattern, Flask is imported lazily inside
    the hooks and the clock is injectable for deterministic tests.

    Args:
        app: The Flask application to instrument. Registered after the
            rate-limit hook so it observes every request that reaches a view
            (including ``/metrics`` itself).
        metrics: The shared :class:`Metrics` collector to feed.
        clock: Monotonic time source (seconds). Defaults to
            :func:`time.perf_counter`; injected so tests can control latency.
    """

    @app.before_request
    def _stamp_start() -> None:
        from flask import g

        setattr(g, _METRICS_START_ATTR, clock())

    @app.after_request
    def _observe(response: Response) -> Response:
        from flask import g, request

        start = getattr(g, _METRICS_START_ATTR, None)
        latency = (clock() - start) if start is not None else 0.0
        endpoint = _endpoint_label(request)
        metrics.record_request(endpoint, response.status_code, latency)
        return response
