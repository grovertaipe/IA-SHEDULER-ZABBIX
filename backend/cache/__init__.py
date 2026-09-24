"""Caché de validación de usuario (cache/) — user validation cache (Req 27).

The validity decision is a pure, deterministic function
(:func:`cache.user_cache.is_cache_entry_valid`); the cache itself
(:class:`cache.user_cache.UserValidationCache`) is a thin stateful abstraction
with an injectable clock, used by ``api/auth.py`` to avoid calling ``user.get``
against Zabbix on every request (Req 27.1-27.4).
"""
