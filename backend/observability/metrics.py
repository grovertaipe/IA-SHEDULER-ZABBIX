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

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

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
