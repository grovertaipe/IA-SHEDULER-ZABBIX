"""Message lookup API for the localization layer (Req 21.4, 21.5).

This module is part of the pure core: no I/O, no Flask, no AI and no Zabbix
dependencies. It exposes :func:`get_message`, a deterministic function that
selects a per-locale catalog, looks up a message key and applies parameter
substitution.

Resolution rules (Req 21.4):

* The catalog is chosen by resolving ``locale`` against the set of available
  catalogs (defaulting to ``es`` when unknown or unsupported).
* If the key is missing in the chosen catalog, the lookup falls back to the
  default (``es``) catalog.
* If the key is missing everywhere, the key itself is returned; the function
  never raises for a missing key.

The ``Motor_Recurrencia`` and the ``Contrato_API`` do not depend on the
``Locale`` (Req 21).
"""

from __future__ import annotations

from i18n.catalogs import en, es, pt
from i18n.locale import DEFAULT_LOCALE, resolve_locale

#: Registry of available catalogs keyed by locale code. ``es`` is the default
#: and complete catalog; every other catalog mirrors its keys (Req 21.4, 21.5).
_CATALOGS: dict[str, dict[str, str]] = {
    "es": es.CATALOG,
    "en": en.CATALOG,
    "pt": pt.CATALOG,
}

#: The default catalog used as the fallback for missing keys (Req 21.4).
_DEFAULT_CATALOG: dict[str, str] = _CATALOGS[DEFAULT_LOCALE]


def get_message(key: str, locale: str, **params: object) -> str:
    """Return the localized message for ``key`` in the effective ``locale``.

    Pure, deterministic lookup (Req 21.4):

    1. Resolve ``locale`` against the available catalogs; unknown or unsupported
       values fall back to the default locale (``es``).
    2. Look up ``key`` in the chosen catalog; if absent, look it up in the
       default (``es``) catalog.
    3. If the key is absent from both, return ``key`` unchanged (never raises).
    4. When ``params`` are given, apply :meth:`str.format` to the template.

    Args:
        key: The message key to look up.
        locale: The requested locale code (e.g. ``"es"``, ``"en"``).
        **params: Optional substitution parameters for the template.

    Returns:
        The localized (and optionally formatted) message text, or ``key`` when
        no catalog defines it.
    """
    effective = resolve_locale(locale, list(_CATALOGS), DEFAULT_LOCALE)
    catalog = _CATALOGS[effective]

    template = catalog.get(key)
    if template is None:
        template = _DEFAULT_CATALOG.get(key)
    if template is None:
        return key

    if params:
        return template.format(**params)
    return template
