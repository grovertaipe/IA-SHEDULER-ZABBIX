"""Metrics blueprint: ``GET /metrics`` (Prometheus) (Req 30.1).

Exposes the application's Prometheus metrics in the text exposition format so a
Prometheus server (or any compatible scraper) can pull them. Following the
convention for scrape endpoints, ``/metrics`` is **unauthenticated**: it is meant
to be reached by the monitoring system, not by end users.

The endpoint only ever emits the operational collectors defined in
:mod:`observability.metrics` (request counts, latencies, error counts and
failover events). It does **not** read or serialize any configuration value,
token or other secret, so the response cannot leak sensitive configuration
(Req 30.1).

Flask coupling stays in this layer; the blueprint is built by the factory
:func:`make_metrics_blueprint`, which receives the :class:`~observability.metrics.Metrics`
collector so it is testable without an app factory or global state. The app
factory (Task 11.4) is responsible for constructing the shared ``Metrics`` and
registering the returned blueprint.
"""

from __future__ import annotations

from flask import Blueprint, Response

from observability.metrics import Metrics, render


def make_metrics_blueprint(metrics: Metrics) -> Blueprint:
    """Build the metrics :class:`~flask.Blueprint` bound to ``metrics``.

    The app factory (Task 11.4) calls this with the shared
    :class:`~observability.metrics.Metrics` instance and registers the returned
    blueprint. Passing the collector explicitly keeps the blueprint free of
    global state and trivially testable with an isolated ``Metrics``.

    Args:
        metrics: The metrics collector whose registry is exposed at ``/metrics``.

    Returns:
        A Flask blueprint exposing an unauthenticated ``GET /metrics`` endpoint.
    """
    bp = Blueprint("metrics", __name__)

    @bp.get("/metrics")
    def metrics_endpoint() -> Response:
        """Return the Prometheus exposition text (Req 30.1).

        The scrape endpoint requires no authentication and returns only
        operational metrics — never configuration secrets.
        """
        payload, content_type = render(metrics)
        return Response(payload, mimetype=content_type)

    return bp
