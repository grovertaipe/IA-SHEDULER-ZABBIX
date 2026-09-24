"""FROZEN parity oracle extracted from the legacy monolith ``backend/main.py``.

This module is a *frozen reference* (an "oracle") of how the **legacy**
monolithic backend computed the Zabbix ``timeperiod`` fields and decoded the
day/month bitmasks into human-readable names. It is used by the exhaustive
parity/regression tests (Tasks 13.2-13.5, Properties 25-29) to prove that the
v2 recurrence engine (``core/recurrence.py`` + ``core/domain.py``) reproduces
the legacy behavior *exactly* (Req 20).

Design constraints (intentional and load-bearing):

* **Independent.** Nothing here imports from the v2 core. The whole point of an
  oracle is to be an *independent* transcription of the legacy code so it can
  catch regressions in the v2 core. If both sides shared code, a bug in the
  shared code would hide behind itself.
* **Pure.** No network, no ``requests``, no Flask, no I/O, no logging. Every
  function is a deterministic mapping from structured inputs to plain data.
* **Frozen.** These functions mirror ``backend/main.py`` as it was at
  extraction time and must NOT be "improved". They deliberately preserve legacy
  quirks (e.g. ``.get(..., default)`` fallbacks and the monthly
  ``day`` / ``dayofweek`` / neither dispatch order) because the parity tests
  compare against exactly those quirks.

Provenance (line references are into the legacy ``backend/main.py``):

* ``ZabbixAPI.create_maintenance`` timeperiod switch  → lines ~278-341.
* Bitmask value tables (days/months/occurrences)      → AI prompt, lines ~543-594.
* Bitmask → Spanish name decode (confirmation message) → lines ~1343-1391.

The legacy AI prompt instructed the LLM to compute the ``dayofweek`` / ``month``
bitmasks and the week ``every`` occurrence *before* calling the backend, so the
legacy Python only ever received precomputed integers. To make this oracle
useful for parity over the *logical* inputs (sets of days/months/occurrences),
the value tables the prompt documented are frozen here as
:data:`LEGACY_DAY_VALUES`, :data:`LEGACY_MONTH_VALUES` and
:data:`LEGACY_OCCURRENCE_VALUES`, and helper summations reproduce the exact
arithmetic the prompt specified.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Frozen value tables (transcribed from the legacy AI prompt, main.py ~543-594)
# ---------------------------------------------------------------------------

#: Day-of-week bitmask values. monday=1 .. sunday=64 (main.py lines ~543-549).
LEGACY_DAY_VALUES: dict[str, int] = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 4,
    "thursday": 8,
    "friday": 16,
    "saturday": 32,
    "sunday": 64,
}

#: Month bitmask values. january=1 .. december=2048 (main.py lines ~581-583).
LEGACY_MONTH_VALUES: dict[str, int] = {
    "january": 1,
    "february": 2,
    "march": 4,
    "april": 8,
    "may": 16,
    "june": 32,
    "july": 64,
    "august": 128,
    "september": 256,
    "october": 512,
    "november": 1024,
    "december": 2048,
}

#: Week-occurrence values for monthly-by-day-of-week (main.py lines ~568-573).
#: first=1, second=2, third=3, fourth=4, last=5. Multiple occurrences sum
#: as a bitmask (e.g. second+fourth = 6), per the legacy prompt (lines ~574-579).
LEGACY_OCCURRENCE_VALUES: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "last": 5,
}

#: "All months" sentinel the legacy backend used as the ``month`` default.
LEGACY_ALL_MONTHS: int = 4095

# ---------------------------------------------------------------------------
# Frozen decode tables (transcribed from main.py ~1343-1391, in bit order)
# ---------------------------------------------------------------------------

#: Ordered (bit, Spanish name) pairs for day decoding (main.py lines ~1344-1350).
_LEGACY_DAY_DECODE: tuple[tuple[int, str], ...] = (
    (1, "Lunes"),
    (2, "Martes"),
    (4, "Miércoles"),
    (8, "Jueves"),
    (16, "Viernes"),
    (32, "Sábado"),
    (64, "Domingo"),
)

#: Ordered (bit, Spanish name) pairs for month decoding (main.py lines ~1379-1390).
_LEGACY_MONTH_DECODE: tuple[tuple[int, str], ...] = (
    (1, "Enero"),
    (2, "Febrero"),
    (4, "Marzo"),
    (8, "Abril"),
    (16, "Mayo"),
    (32, "Junio"),
    (64, "Julio"),
    (128, "Agosto"),
    (256, "Septiembre"),
    (512, "Octubre"),
    (1024, "Noviembre"),
    (2048, "Diciembre"),
)

#: Week-occurrence names for the confirmation message (main.py line ~1370).
_LEGACY_WEEK_NAMES: dict[int, str] = {
    1: "primera",
    2: "segunda",
    3: "tercera",
    4: "cuarta",
    5: "última",
}


# ---------------------------------------------------------------------------
# Frozen bitmask arithmetic (mirrors what the legacy AI prompt documented)
# ---------------------------------------------------------------------------


def legacy_day_bitmask(days: list[str]) -> int:
    """Sum the legacy day values for ``days`` (monday=1 .. sunday=64).

    Mirrors the summation the legacy prompt documented, e.g.
    ``{thursday, friday}`` → ``8 + 16 = 24`` (main.py line ~556).

    Args:
        days: day names drawn from :data:`LEGACY_DAY_VALUES`.

    Returns:
        The summed bitmask.
    """
    return sum(LEGACY_DAY_VALUES[d] for d in days)


def legacy_month_bitmask(months: list[str]) -> int:
    """Sum the legacy month values for ``months`` (january=1 .. december=2048).

    Args:
        months: month names drawn from :data:`LEGACY_MONTH_VALUES`.

    Returns:
        The summed bitmask.
    """
    return sum(LEGACY_MONTH_VALUES[m] for m in months)


def legacy_week_occurrence(occurrences: list[str]) -> int:
    """Sum the legacy occurrence values for ``occurrences`` (first=1 .. last=5).

    Multiple occurrences sum as a bitmask, e.g. second+fourth = 6 (main.py
    lines ~574-579).

    Args:
        occurrences: occurrence names drawn from :data:`LEGACY_OCCURRENCE_VALUES`.

    Returns:
        The summed occurrence value.
    """
    return sum(LEGACY_OCCURRENCE_VALUES[o] for o in occurrences)


# ---------------------------------------------------------------------------
# Frozen timeperiod construction (mirrors ZabbixAPI.create_maintenance switch)
# ---------------------------------------------------------------------------


def legacy_build_timeperiod(
    recurrence_type: str,
    start_time: int | None = None,
    end_time: int | None = None,
    recurrence_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reproduce the legacy ``create_maintenance`` timeperiod dict, frozen.

    This is a verbatim transcription of the ``if/elif`` switch in
    ``ZabbixAPI.create_maintenance`` (main.py lines ~278-341). It returns the
    single ``timeperiod`` dict the legacy backend placed in
    ``params["timeperiods"][0]``. It deliberately preserves every legacy quirk:

    * ``once`` (``timeperiod_type=0``): ``start_date`` and ``period = end - start``
      derived from the absolute ``start_time`` / ``end_time`` arguments.
    * ``daily`` (``timeperiod_type=2``): ``start_time`` / ``period`` / ``every``
      read from ``recurrence_config`` with legacy defaults ``0`` / ``3600`` / ``1``.
    * ``weekly`` (``timeperiod_type=3``): adds ``dayofweek`` (default ``1``).
    * ``monthly`` (``timeperiod_type=4``): ``month`` default ``4095`` and the
      legacy dispatch — if ``"day"`` present use it; else if ``"dayofweek"``
      present use it; else default to ``day=1`` (main.py lines ~326-337). In
      every monthly branch ``every`` defaults to ``1``.

    Args:
        recurrence_type: one of ``"once"``, ``"daily"``, ``"weekly"``, ``"monthly"``.
        start_time: absolute epoch start (used by ``once``).
        end_time: absolute epoch end (used by ``once``).
        recurrence_config: legacy recurrence config dict (required for the
            recurring types, matching the legacy ``raise ValueError`` guards).

    Returns:
        The frozen ``timeperiod`` dict as the legacy backend would have built it.

    Raises:
        ValueError: for a recurring type without ``recurrence_config`` and for an
            unsupported ``recurrence_type`` — mirroring the legacy guards.
    """
    if recurrence_type == "once":
        # main.py lines ~278-284
        return {
            "timeperiod_type": 0,  # período único
            "start_date": start_time,
            "period": (end_time or 0) - (start_time or 0),
        }

    if recurrence_type == "daily":
        # main.py lines ~286-296
        if not recurrence_config:
            raise ValueError("Se requiere recurrence_config para mantenimientos diarios")
        return {
            "timeperiod_type": 2,  # diario
            "start_time": recurrence_config.get("start_time", 0),
            "period": recurrence_config.get("duration", 3600),
            "every": recurrence_config.get("every", 1),
        }

    if recurrence_type == "weekly":
        # main.py lines ~298-311
        if not recurrence_config:
            raise ValueError("Se requiere recurrence_config para mantenimientos semanales")
        dayofweek_bitmask = recurrence_config.get("dayofweek", 1)
        return {
            "timeperiod_type": 3,  # semanal
            "start_time": recurrence_config.get("start_time", 0),
            "period": recurrence_config.get("duration", 3600),
            "dayofweek": dayofweek_bitmask,
            "every": recurrence_config.get("every", 1),
        }

    if recurrence_type == "monthly":
        # main.py lines ~313-339
        if not recurrence_config:
            raise ValueError("Se requiere recurrence_config para mantenimientos mensuales")
        timeperiod: dict[str, Any] = {
            "timeperiod_type": 4,  # mensual
            "start_time": recurrence_config.get("start_time", 0),
            "period": recurrence_config.get("duration", 3600),
            "month": recurrence_config.get("month", 4095),
        }
        if "day" in recurrence_config:
            # Por día específico del mes (ej: día 5 de cada mes)
            timeperiod["day"] = recurrence_config["day"]
            timeperiod["every"] = recurrence_config.get("every", 1)  # Cada X meses
        elif "dayofweek" in recurrence_config:
            timeperiod["dayofweek"] = recurrence_config["dayofweek"]
            timeperiod["every"] = recurrence_config.get("every", 1)
        else:
            # Por defecto, primer día del mes
            timeperiod["day"] = 1
            timeperiod["every"] = recurrence_config.get("every", 1)
        return timeperiod

    raise ValueError(f"Tipo de recurrencia no soportado: {recurrence_type}")


# ---------------------------------------------------------------------------
# Frozen bitmask → name decode (mirrors the confirmation message, main.py ~1343)
# ---------------------------------------------------------------------------


def legacy_decode_days(days_bitmask: int) -> list[str]:
    """Decode a day bitmask into legacy Spanish day names, in bit order.

    Verbatim transcription of the ``if days_bitmask & N`` chain in the
    confirmation message (main.py lines ~1344-1350). Order is Lunes → Domingo.

    Args:
        days_bitmask: the ``dayofweek`` bitmask.

    Returns:
        Matching Spanish day names in ascending-bit order.
    """
    return [name for bit, name in _LEGACY_DAY_DECODE if days_bitmask & bit]


def legacy_decode_months(month_bitmask: int) -> list[str]:
    """Decode a month bitmask into legacy Spanish month names, in bit order.

    Verbatim transcription of the ``if month_bitmask & N`` chain in the
    confirmation message (main.py lines ~1379-1390). Order is Enero → Diciembre.

    Args:
        month_bitmask: the ``month`` bitmask.

    Returns:
        Matching Spanish month names in ascending-bit order.
    """
    return [name for bit, name in _LEGACY_MONTH_DECODE if month_bitmask & bit]


def legacy_decode_week_occurrence(week_occurrence: int) -> str:
    """Decode a single week-occurrence value into its legacy Spanish name.

    Mirrors the ``week_names.get(week_occurrence, f"semana {week_occurrence}")``
    fallback in the confirmation message (main.py lines ~1370-1371).

    Args:
        week_occurrence: the ``every`` occurrence value (1..5 for the named set).

    Returns:
        The legacy name (``"primera"`` .. ``"última"``) or the
        ``"semana {n}"`` fallback for out-of-table values.
    """
    return _LEGACY_WEEK_NAMES.get(week_occurrence, f"semana {week_occurrence}")
