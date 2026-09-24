"""Secure structured logging (observability/) (Req 30).

The masking decision is a **pure, deterministic** function
(:func:`mask_sensitive`, Req 30.4): given a record it returns a copy in which
the value of every *sensitive* key (matched by name, case-insensitively) is
replaced by a fixed mask, while non-sensitive values are preserved verbatim.
It recurses into nested dictionaries and lists and is idempotent — applying it
twice yields the same result.

The :class:`SecureLogger` is the stateful boundary that *applies* that pure
decision: :meth:`SecureLogger.info` / :meth:`SecureLogger.error` build an event
record, route it through :func:`mask_sensitive`, and emit it as a JSON line via
the standard library ``logging`` module. No event is ever written without first
passing through the mask, so tokens/keys/credentials never appear in clear text
(Req 30.2, 30.3).

Requirements: 30.2, 30.3, 30.4.
"""

from __future__ import annotations

import json
import logging
from typing import Any

#: Keys whose values are considered sensitive and must be masked (Req 30.3).
#: Matching is performed by name, case-insensitively (see :func:`mask_sensitive`).
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "token",
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "credential",
        "zabbix_token",
        "gemini_api_key",
        "openai_api_key",
    }
)

#: The placeholder written in place of a sensitive value.
MASK: str = "***"


def _mask_value(value: Any) -> Any:
    """Recursively mask sensitive keys inside ``value`` (helper for :func:`mask_sensitive`).

    Dictionaries are traversed key by key; lists (and tuples) are traversed
    element by element so that sensitive keys nested inside collections of
    records are also masked. Scalars and other types are returned unchanged.

    Args:
        value: An arbitrary value drawn from a log record.

    Returns:
        A copy of ``value`` with every sensitive key's value replaced by
        :data:`MASK`. The input is never mutated.
    """
    if isinstance(value, dict):
        return {
            key: (MASK if key.lower() in SENSITIVE_KEYS else _mask_value(inner))
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_mask_value(item) for item in value)
    return value


def mask_sensitive(record: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``record`` with every sensitive value masked (Req 30.4).

    Pure, deterministic and idempotent: the value of every key whose name
    matches :data:`SENSITIVE_KEYS` (compared case-insensitively) is replaced by
    :data:`MASK`, while non-sensitive values are preserved identically. Nested
    dictionaries and lists of dictionaries are traversed recursively, so
    secrets are masked at any nesting level. The input record is never mutated;
    a fresh copy is always returned.

    Args:
        record: The log record (a mapping of field name to value).

    Returns:
        A new dictionary in which no sensitive value appears in clear text.
    """
    return {
        key: (MASK if key.lower() in SENSITIVE_KEYS else _mask_value(value))
        for key, value in record.items()
    }


class SecureLogger:
    """Structured (JSON) logger that masks every event before writing it (Req 30.2, 30.3).

    Thin wrapper over the standard library :mod:`logging` module. Each call to
    :meth:`info` / :meth:`error` assembles an event record, routes it through
    the pure :func:`mask_sensitive`, and emits the masked record as a single
    JSON line. No event reaches the underlying logger unmasked.
    """

    def __init__(self, name: str = "zabbix_ai_maintenance") -> None:
        """Initialize the logger.

        Args:
            name: Name of the underlying stdlib logger to write through.
        """
        self._logger = logging.getLogger(name)

    def info(self, event: str, **fields: Any) -> None:
        """Emit an informational event as a masked JSON line.

        Args:
            event: A short, stable event name/identifier.
            **fields: Arbitrary structured fields; sensitive ones are masked.
        """
        self._logger.info(self._render(event, fields))

    def error(self, event: str, **fields: Any) -> None:
        """Emit an error event as a masked JSON line.

        Args:
            event: A short, stable event name/identifier.
            **fields: Arbitrary structured fields; sensitive ones are masked.
        """
        self._logger.error(self._render(event, fields))

    @staticmethod
    def _render(event: str, fields: dict[str, Any]) -> str:
        """Build the event record, mask it, and serialize it to a JSON string.

        Args:
            event: The event name/identifier.
            fields: The structured fields supplied by the caller.

        Returns:
            A JSON string of the masked ``{"event": event, **fields}`` record.
        """
        record: dict[str, Any] = {"event": event, **fields}
        return json.dumps(mask_sensitive(record), default=str, sort_keys=True)
