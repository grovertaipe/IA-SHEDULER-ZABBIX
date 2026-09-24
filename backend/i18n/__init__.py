"""Localización (i18n/) — language resolution and message catalogs (Req 21).

The language-resolution decision is a pure, deterministic function
(:func:`i18n.locale.resolve_locale`); the message lookup API
(:func:`i18n.messages.get_message`) reads from per-locale catalogs under
:mod:`i18n.catalogs` (``es`` default, ``en`` alternate). The
``Motor_Recurrencia`` and the ``Contrato_API`` do not depend on the ``Locale``
(Req 21).
"""
