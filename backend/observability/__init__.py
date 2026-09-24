"""Observabilidad y registro seguro (observability/) — secure logging (Req 30).

The masking decision is a pure, deterministic function
(:func:`observability.logger.mask_sensitive`, Req 30.4); the structured logger
(:class:`observability.logger.SecureLogger`) is a thin stateful boundary that
routes every event through :func:`mask_sensitive` before emitting it as JSON,
so secret values never appear in clear text (Req 30.2, 30.3).
"""
