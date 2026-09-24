"""Per-locale message catalogs for the localization layer (Req 21.4, 21.5).

Each catalog is a plain ``dict[str, str]`` mapping a stable message key to a
localized template. Templates use :meth:`str.format`-style ``{placeholders}``
for parameter substitution. The Spanish catalog (:mod:`i18n.catalogs.es`) is the
product default and the complete reference set of keys (Req 21.5, 21.6); the
English catalog (:mod:`i18n.catalogs.en`) mirrors the same keys.

The lookup API that selects and reads from these catalogs lives in
:mod:`i18n.messages`. These catalogs carry no logic and no I/O.
"""
