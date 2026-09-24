"""Pure language resolution for localization (Req 21.5, 21.6, 21.7).

This module is part of the pure core: no I/O, no Flask, no AI and no Zabbix
dependencies. It exposes a single deterministic function,
:func:`resolve_locale`, used once per request by the services layer to pick the
effective ``Locale`` before generating any output text.
"""

from __future__ import annotations

DEFAULT_LOCALE = "es"


def resolve_locale(
    requested: str | None,
    supported: list[str],
    default: str = DEFAULT_LOCALE,
) -> str:
    """Resolve the effective locale deterministically (Req 21.7).

    Pure function with no side effects:

    * ``requested`` is in ``supported`` -> returns ``requested`` (identity).
    * ``requested`` is ``None``, empty or not supported -> returns ``default``
      (silent degradation to the default language; Req 21.5, 21.6).

    Args:
        requested: The locale requested by the client, or ``None``.
        supported: The list of supported locale codes.
        default: The fallback locale, ``"es"`` by default.

    Returns:
        The requested locale when supported, otherwise ``default``.
    """
    if requested and requested in supported:
        return requested
    return default
