"""Motor_Recurrencia — deterministic recurrence engine (pure functions).

This module is part of the pure core (Req 1.4): no I/O, no Flask, no AI and no
Zabbix dependencies. It is the contract between the AI extraction
(:class:`~core.domain.ExtractedRequest`) and the creation of a Zabbix
maintenance window.

Design principle "AI extrae, backend calcula" (Req 3.2): the LLM only produces
structured sets of day/month/occurrence *names* plus hours and duration; this
module computes the Zabbix bitmasks and performs the time conversions
deterministically.

Task 3.1 scope (implemented here):
    * bitmask value tables: :data:`DAY_VALUES`, :data:`MONTH_VALUES`,
      :data:`OCCURRENCE_VALUES`;
    * :func:`compute_day_bitmask` (sum, 1..127, rejects empty set);
    * :func:`compute_month_bitmask` (sum, 1..4095, rejects empty set);
    * :func:`compute_week_occurrence` (sum, 1..5);
    * :func:`hours_to_seconds_from_midnight` (0..23 -> ``*3600``);
    * :func:`duration_hours_to_seconds` (> 0 -> ``*3600``).

Task 3.6 scope (also implemented here):
    * precomputed-bitmask range validation: :func:`validate_day_bitmask`
      (1..127), :func:`validate_month_bitmask` (1..4095),
      :func:`validate_week_occurrence` (1..5). Out-of-range values are rejected
      with a "bitmask inválido" :class:`~core.domain.RecurrenceError` (Req 2.7,
      6.5, 7.5).
    * Invalid-time rejection (hour outside ``0..23`` / duration ``<= 0``,
      Req 2.9) is already enforced by :func:`hours_to_seconds_from_midnight`
      and :func:`duration_hours_to_seconds` above; no duplicate helper is added
      so the single validation path is preserved.

Task 4.1 scope (also implemented here):
    * :func:`build_timeperiod` — dispatch by ``recurrence_type`` producing a
      :class:`~core.domain.TimePeriod` with the exact ``timeperiod_type`` and
      fields Zabbix expects for ``once`` (0), ``daily`` (2), ``weekly`` (3) and
      ``monthly`` (4). Pre-validates the recurrence type and, for recurring
      types, requires ``start_hour`` and ``duration_hours`` (Req 9). Composes
      the Task 3.1 / 3.6 helpers (``compute_*`` / ``validate_*``) rather than
      reimplementing any bitmask arithmetic.

Task 4.10 scope (also implemented here):
    * duration-range validation and minute-flooring: ``PERIOD_MIN_SECONDS``
      (300) / ``PERIOD_MAX_SECONDS`` (86399940), :func:`validate_period_seconds`
      (returns the value inside the Rango_Period, else a "duración fuera de
      rango" :class:`RecurrenceError`) and :func:`floor_to_minute` (greatest
      multiple of 60 ``<=`` the input; idempotent). These are *wired into*
      :func:`build_timeperiod` at the ``# SEAM (Task 4.10)`` markers so every
      ``period`` (``once`` and recurring) is validated against
      ``[300, 86399940]`` and then floored, and ``start_time`` / ``start_date``
      are floored to whole minutes consistently with Zabbix (Req 31.1-31.4).

Task 4.11 scope (also implemented here):
    * problem-tag validation: value tables ``TAGS_EVALTYPE_VALUES`` (``{0, 2}``)
      and ``TAG_OPERATOR_VALUES`` (``{0, 2}``) and :func:`validate_problem_tags`
      — a pure, deterministic guard run before ``maintenance.create``. It
      rejects non-empty ``problem_tags`` with ``maintenance_type == 1`` (tags
      only allowed with ``maintenance_type == 0``, Req 32.3), an invalid
      ``tags_evaltype`` (not in ``{0, 2}``, Req 32.5) and any tag whose
      ``operator`` is not in ``{0, 2}`` (Req 32.6). An empty tag list is valid
      with any valid ``maintenance_type`` (Zabbix then suppresses all problems
      by default, Req 32.4). No I/O.

This is the last task editing this file in the core phase.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 4.1, 4.2, 4.3, 4.4,
5.1, 5.2, 5.4, 6.1, 6.2, 6.3, 6.5, 6.6, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3,
8.4, 8.5, 8.6, 9.1, 9.2, 9.3, 9.4, 9.5, 32.3, 32.4, 32.5, 32.6.
"""

from __future__ import annotations

from collections.abc import Callable

from .domain import (
    ProblemTag,
    RecurrenceConfig,
    RecurrenceError,
    RecurrenceType,
    TimePeriod,
)

# --------------------------------------------------------------------------- #
# Bitmask value tables (Req 2.1, 2.2, 2.3)                                     #
# --------------------------------------------------------------------------- #
#: Day-of-week bit values (Bitmask_Dias). Sum over a subset is in 1..127.
DAY_VALUES: dict[str, int] = {
    "monday": 1,
    "tuesday": 2,
    "wednesday": 4,
    "thursday": 8,
    "friday": 16,
    "saturday": 32,
    "sunday": 64,
}

#: Month bit values (Bitmask_Meses). Sum over a subset is in 1..4095.
MONTH_VALUES: dict[str, int] = {
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

#: Week-occurrence values (Ocurrencia_Semana). Individually 1..5.
OCCURRENCE_VALUES: dict[str, int] = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "last": 5,
}


# --------------------------------------------------------------------------- #
# Bitmask computation (Req 2.1, 2.2, 2.3, 2.6, 2.8)                            #
# --------------------------------------------------------------------------- #
def compute_day_bitmask(days: set[str]) -> int:
    """Return the day-of-week bitmask as the sum of :data:`DAY_VALUES`.

    The result is inherently within ``1..127`` because it is the sum over a
    subset of the seven known day values (Req 2.1, 2.6).

    Args:
        days: set of lowercase day names (e.g. ``{"thursday", "friday"}``).

    Returns:
        The Bitmask_Dias in ``1..127``.

    Raises:
        RecurrenceError: if ``days`` is empty (Req 2.8) or contains an unknown
            day name (invalid input).
    """
    if not days:
        raise RecurrenceError("days", "At least one day is required.")
    total = 0
    for day in days:
        value = DAY_VALUES.get(day)
        if value is None:
            raise RecurrenceError("days", f"Unknown day name: {day!r}.")
        total += value
    return total


def compute_month_bitmask(months: set[str]) -> int:
    """Return the month bitmask as the sum of :data:`MONTH_VALUES`.

    The result is inherently within ``1..4095`` because it is the sum over a
    subset of the twelve known month values (Req 2.2, 2.6).

    Args:
        months: set of lowercase month names (e.g. ``{"january", "june"}``).

    Returns:
        The Bitmask_Meses in ``1..4095``.

    Raises:
        RecurrenceError: if ``months`` is empty (Req 2.8) or contains an unknown
            month name (invalid input).
    """
    if not months:
        raise RecurrenceError("months", "At least one month is required.")
    total = 0
    for month in months:
        value = MONTH_VALUES.get(month)
        if value is None:
            raise RecurrenceError("months", f"Unknown month name: {month!r}.")
        total += value
    return total


def compute_week_occurrence(occurrences: set[str]) -> int:
    """Return the week occurrence as the sum of :data:`OCCURRENCE_VALUES`.

    A single occurrence maps to ``1..5`` (Req 2.3, 2.6).

    Args:
        occurrences: set of lowercase occurrence names (``first``..``last``).

    Returns:
        The Ocurrencia_Semana in ``1..5``.

    Raises:
        RecurrenceError: if ``occurrences`` is empty (Req 2.8) or contains an
            unknown occurrence name (invalid input).
    """
    if not occurrences:
        raise RecurrenceError("occurrences", "At least one occurrence is required.")
    total = 0
    for occurrence in occurrences:
        value = OCCURRENCE_VALUES.get(occurrence)
        if value is None:
            raise RecurrenceError("occurrences", f"Unknown occurrence name: {occurrence!r}.")
        total += value
    return total


# --------------------------------------------------------------------------- #
# Time conversions (Req 2.4, 2.5)                                             #
# --------------------------------------------------------------------------- #
def hours_to_seconds_from_midnight(hour: int) -> int:
    """Convert an hour of the day to seconds since midnight (Req 2.4).

    Args:
        hour: hour of the day in ``0..23``.

    Returns:
        ``hour * 3600`` seconds since midnight.

    Raises:
        RecurrenceError: if ``hour`` is outside ``0..23`` (Req 2.9).
    """
    if not 0 <= hour <= 23:
        raise RecurrenceError("start_hour", f"Hour must be in 0..23, got {hour}.")
    return hour * 3600


def duration_hours_to_seconds(duration_hours: float) -> int:
    """Convert a duration in hours to seconds (Req 2.5).

    Args:
        duration_hours: duration in hours; must be strictly positive.

    Returns:
        ``int(duration_hours * 3600)`` seconds.

    Raises:
        RecurrenceError: if ``duration_hours`` is not strictly positive (Req 2.9).
    """
    if duration_hours <= 0:
        raise RecurrenceError(
            "duration_hours", f"Duration must be greater than 0, got {duration_hours}."
        )
    return int(duration_hours * 3600)


# --------------------------------------------------------------------------- #
# Duration range validation and minute-flooring (Req 31)                      #
#                                                                             #
# Zabbix accepts a maintenance `period` (duration in seconds) inside the      #
# Rango_Period [300, 86399940] (both inclusive) and rounds active_since /     #
# active_till / period / start_date / start_time DOWN to whole minutes        #
# internally. The two pure helpers below let build_timeperiod reject          #
# out-of-range durations (validate_period_seconds) and produce field values   #
# already consistent with that rounding (floor_to_minute), so parity with     #
# Zabbix does not depend on sub-minute precision. Both are pure, deterministic#
# and free of I/O.                                                            #
# --------------------------------------------------------------------------- #
#: Minimum accepted maintenance duration in seconds (5 minutes, Req 31.1).
PERIOD_MIN_SECONDS = 300
#: Maximum accepted maintenance duration in seconds (~999d 23:59:00, Req 31.2).
PERIOD_MAX_SECONDS = 86399940


def validate_period_seconds(period: int) -> int:
    """Validate a maintenance duration against the Zabbix range (Req 31).

    Pure and deterministic (Req 31.1, 31.2, 31.4): checks that ``period`` (in
    seconds) lies within the Rango_Period ``[300, 86399940]`` (both inclusive)
    and returns the same value when it is valid. Boundaries: ``299`` invalid,
    ``300`` valid, ``86399940`` valid, ``86400000`` invalid. It is the single
    reference consumed by :func:`build_timeperiod` for **every** ``period``
    (recurring and ``once``). No I/O.

    Args:
        period: the maintenance duration in seconds.

    Returns:
        The same ``period`` when it is within ``[300, 86399940]``.

    Raises:
        RecurrenceError: on the field ``"period"`` if ``period`` is outside the
            Rango_Period ("duración fuera de rango").
    """
    if not PERIOD_MIN_SECONDS <= period <= PERIOD_MAX_SECONDS:
        raise RecurrenceError(
            "period",
            f"Duración fuera de rango: debe estar en "
            f"[{PERIOD_MIN_SECONDS}, {PERIOD_MAX_SECONDS}] segundos, se obtuvo {period}.",
        )
    return period


def floor_to_minute(seconds: int) -> int:
    """Round ``seconds`` DOWN to the nearest whole minute (Req 31.3).

    Pure helper returning the greatest multiple of ``60`` that is ``<= seconds``
    (``seconds - seconds % 60``). Zabbix rounds ``active_since`` /
    ``active_till`` / ``period`` / ``start_date`` / ``start_time`` down to whole
    minutes internally; the engine produces values consistent with that
    rounding so parity does not depend on sub-minute precision. Idempotent:
    ``floor_to_minute(floor_to_minute(x)) == floor_to_minute(x)``.

    Args:
        seconds: a value in seconds (duration or timestamp).

    Returns:
        The greatest multiple of ``60`` less than or equal to ``seconds``.
    """
    return seconds - seconds % 60


# --------------------------------------------------------------------------- #
# Precomputed-bitmask range validation (Req 2.7, 6.5, 7.5)                    #
#                                                                             #
# These validators guard bitmasks that arrive already computed (e.g. from an  #
# external caller or a previously stored configuration) rather than being     #
# summed here from name sets. On success they return the same value unchanged #
# so they compose transparently; on an out-of-range value they raise a        #
# "bitmask inválido" RecurrenceError with the design-mandated field name.     #
# --------------------------------------------------------------------------- #
def validate_day_bitmask(value: int) -> int:
    """Validate a precomputed day-of-week bitmask (Req 2.7, 6.5).

    Args:
        value: the Bitmask_Dias to validate; valid range is ``1..127``.

    Returns:
        The same ``value`` when it is within ``1..127``.

    Raises:
        RecurrenceError: on the field ``"day"`` if ``value`` is outside
            ``1..127`` ("bitmask inválido").
    """
    if not 1 <= value <= 127:
        raise RecurrenceError("day", f"bitmask inválido: must be in 1..127, got {value}.")
    return value


def validate_month_bitmask(value: int) -> int:
    """Validate a precomputed month bitmask (Req 2.7, 7.5).

    Args:
        value: the Bitmask_Meses to validate; valid range is ``1..4095``.

    Returns:
        The same ``value`` when it is within ``1..4095``.

    Raises:
        RecurrenceError: on the field ``"month"`` if ``value`` is outside
            ``1..4095`` ("bitmask inválido").
    """
    if not 1 <= value <= 4095:
        raise RecurrenceError("month", f"bitmask inválido: must be in 1..4095, got {value}.")
    return value


def validate_week_occurrence(value: int) -> int:
    """Validate a precomputed week occurrence (Req 2.7, 8.x).

    Args:
        value: the Ocurrencia_Semana to validate; valid range is ``1..5``.

    Returns:
        The same ``value`` when it is within ``1..5``.

    Raises:
        RecurrenceError: on the field ``"occurrence"`` if ``value`` is outside
            ``1..5`` ("bitmask inválido").
    """
    if not 1 <= value <= 5:
        raise RecurrenceError("occurrence", f"bitmask inválido: must be in 1..5, got {value}.")
    return value


# --------------------------------------------------------------------------- #
# TimePeriod construction — dispatch by recurrence type (Req 4-9)             #
#                                                                             #
# build_timeperiod composes the Task 3.1 / 3.6 helpers (compute_* / validate_#
# *); it never re-sums bitmasks itself. Each recurring branch resolves its    #
# dayofweek / month bitmask either from a precomputed value on the config     #
# (validated via validate_*_bitmask, Req 2.7) or from the AI name-sets (via   #
# compute_*_bitmask). Pure and deterministic: no I/O.                         #
# --------------------------------------------------------------------------- #
def _resolve_day_bitmask(cfg: RecurrenceConfig) -> int:
    """Resolve the Bitmask_Dias for a config, from precomputed or names.

    If ``cfg.day_bitmask`` is present it is range-validated (Req 2.7); otherwise
    it is computed from ``cfg.days`` (Req 2.1). Raises a "falta el día de la
    semana" :class:`RecurrenceError` when neither is available (Req 6.4).
    """
    if cfg.day_bitmask is not None:
        return validate_day_bitmask(cfg.day_bitmask)
    if cfg.days:
        return compute_day_bitmask(cfg.days)
    raise RecurrenceError("dayofweek", "Falta el día de la semana (Bitmask_Dias).")


def _resolve_month_bitmask(cfg: RecurrenceConfig) -> int:
    """Resolve the Bitmask_Meses for a monthly config (default 4095).

    Precomputed ``cfg.month_bitmask`` is range-validated (Req 2.7); otherwise it
    is computed from ``cfg.months`` (Req 2.2). When neither is provided the
    default of ``4095`` (all months) applies (Req 7.4).
    """
    if cfg.month_bitmask is not None:
        return validate_month_bitmask(cfg.month_bitmask)
    if cfg.months:
        return compute_month_bitmask(cfg.months)
    return 4095


def _require_recurring_time(cfg: RecurrenceConfig) -> tuple[int, int]:
    """Validate and convert the shared start_time/period of a recurring type.

    Recurring maintenances (daily/weekly/monthly) require both ``start_hour``
    and ``duration_hours`` (Req 9.3, 9.4). Returns ``(start_time, period)`` in
    seconds. Range checks on the hour/duration are delegated to the Task 3.1
    converters (Req 2.4, 2.5, 2.9).
    """
    if cfg.start_hour is None:
        raise RecurrenceError("start_time", "Falta start_time en la configuración recurrente.")
    if cfg.duration_hours is None:
        raise RecurrenceError("duration", "Falta duration en la configuración recurrente.")
    start_time = hours_to_seconds_from_midnight(cfg.start_hour)
    # SEAM (Task 4.10): validate the requested duration is within the
    # Rango_Period first (Req 31.1, 31.2, 31.4), then floor `period` and
    # `start_time` down to whole minutes for Zabbix consistency (Req 31.3).
    period = floor_to_minute(validate_period_seconds(duration_hours_to_seconds(cfg.duration_hours)))
    start_time = floor_to_minute(start_time)
    return start_time, period


def _build_once(cfg: RecurrenceConfig) -> TimePeriod:
    """Build the ``once`` time period (timeperiod_type=0, Req 4).

    ``start_date`` is the start timestamp and ``period`` is ``end - start``
    (Req 4.2). The enclosing window carries ``active_since=start`` /
    ``active_till=end``; those are recoverable as ``start_date`` and
    ``start_date + period`` by the maintenance assembler (Req 4.4). Rejects
    ``end <= start`` on the ``end_ts`` field (Req 4.3).
    """
    if cfg.start_ts is None:
        raise RecurrenceError("start_ts", "Falta el timestamp de inicio para 'once'.")
    if cfg.end_ts is None:
        raise RecurrenceError("end_ts", "Falta el timestamp de fin para 'once'.")
    if cfg.end_ts <= cfg.start_ts:
        raise RecurrenceError(
            "end_ts", "El timestamp de fin debe ser mayor que el de inicio."
        )
    # SEAM (Task 4.10): validate the requested duration (end - start) is within
    # the Rango_Period first (Req 31.1, 31.2, 31.4), then floor `period` and
    # `start_date` down to whole minutes for Zabbix consistency (Req 31.3). The
    # enclosing window's active_since/active_till are floored by the assembler
    # from these same floored values (start_date and start_date + period).
    period = floor_to_minute(validate_period_seconds(cfg.end_ts - cfg.start_ts))
    start_date = floor_to_minute(cfg.start_ts)
    return TimePeriod(timeperiod_type=0, period=period, start_date=start_date)


def _build_daily(cfg: RecurrenceConfig) -> TimePeriod:
    """Build the ``daily`` time period (timeperiod_type=2, Req 5).

    Sets ``start_time`` (seconds from midnight), ``period`` (duration in
    seconds) and ``every`` (day interval, default 1) (Req 5.2, 5.4).
    """
    start_time, period = _require_recurring_time(cfg)
    every = cfg.every if cfg.every is not None else 1
    return TimePeriod(
        timeperiod_type=2, period=period, start_time=start_time, every=every
    )


def _build_weekly(cfg: RecurrenceConfig) -> TimePeriod:
    """Build the ``weekly`` time period (timeperiod_type=3, Req 6).

    Sets ``dayofweek`` (Bitmask_Dias in 1..127), ``start_time``, ``period`` and
    ``every`` (week interval, default 1) (Req 6.2, 6.3, 6.6).
    """
    start_time, period = _require_recurring_time(cfg)
    dayofweek = _resolve_day_bitmask(cfg)
    every = cfg.every if cfg.every is not None else 1
    return TimePeriod(
        timeperiod_type=3,
        period=period,
        start_time=start_time,
        every=every,
        dayofweek=dayofweek,
    )


def _build_monthly(cfg: RecurrenceConfig) -> TimePeriod:
    """Build a ``monthly`` time period (timeperiod_type=4, Req 7, 8).

    Dispatches on mutual-exclusive sub-modes (design "Reglas de despacho
    mensual"):
        * by day-of-month (``day_of_month`` present) → sets ``day`` (1..31),
          ``month`` (Bitmask_Meses, default 4095) and ``every`` (month interval,
          default 1) (Req 7.1-7.4);
        * by day-of-week (``days`` present) → sets ``dayofweek`` (Bitmask_Dias),
          ``every`` = Ocurrencia_Semana (default 1) and ``month`` (Req 8.1-8.3,
          8.6).

    Rejects supplying **both** ("solo se permite uno", Req 8.4) or **neither**
    (missing-data error, Req 8.5).
    """
    start_time, period = _require_recurring_time(cfg)
    has_dom = cfg.day_of_month is not None
    # A precomputed day_bitmask also counts as a day-of-week configuration.
    has_dow = bool(cfg.days) or cfg.day_bitmask is not None

    if has_dom and has_dow:
        raise RecurrenceError(
            "monthly",
            "Configuración mensual ambigua: solo se permite uno de día del mes o "
            "día de la semana.",
        )
    if not has_dom and not has_dow:
        raise RecurrenceError(
            "monthly",
            "Falta el dato de la configuración mensual: indique día del mes o día "
            "de la semana.",
        )

    month = _resolve_month_bitmask(cfg)

    if has_dom:
        day = cfg.day_of_month
        assert day is not None  # narrowed by has_dom; kept for type-checkers
        if not 1 <= day <= 31:
            raise RecurrenceError(
                "day", f"El día del mes debe estar en 1..31, se obtuvo {day}."
            )
        every = cfg.every if cfg.every is not None else 1
        return TimePeriod(
            timeperiod_type=4,
            period=period,
            start_time=start_time,
            every=every,
            day=day,
            month=month,
        )

    # day-of-week: every carries the Ocurrencia_Semana (default 1, Req 8.6).
    dayofweek = _resolve_day_bitmask(cfg)
    if cfg.occurrences:
        every = compute_week_occurrence(cfg.occurrences)
    elif cfg.every is not None:
        every = validate_week_occurrence(cfg.every)
    else:
        every = 1
    return TimePeriod(
        timeperiod_type=4,
        period=period,
        start_time=start_time,
        every=every,
        dayofweek=dayofweek,
        month=month,
    )


#: Dispatch table from recurrence type to its builder (Req 9.1).
_BUILDERS: dict[RecurrenceType, Callable[[RecurrenceConfig], TimePeriod]] = {
    RecurrenceType.ONCE: _build_once,
    RecurrenceType.DAILY: _build_daily,
    RecurrenceType.WEEKLY: _build_weekly,
    RecurrenceType.MONTHLY: _build_monthly,
}


def build_timeperiod(cfg: RecurrenceConfig) -> TimePeriod:
    """Dispatch by ``recurrence_type`` and build the Zabbix :class:`TimePeriod`.

    Produces the exact ``timeperiod_type`` and fields Zabbix expects
    (Req 4-8): ``once`` → 0, ``daily`` → 2, ``weekly`` → 3, ``monthly`` → 4.
    Validation happens *before* construction (Req 9): an unknown recurrence type
    is rejected (Req 9.1), and every recurring type requires ``start_time`` and
    ``duration`` (Req 9.3, 9.4). All bitmask arithmetic is delegated to the
    Task 3.1 / 3.6 helpers.

    Task 4.10 (Req 31): every ``period`` (``once`` and recurring) is
    range-validated with :func:`validate_period_seconds` against
    ``[300, 86399940]`` and then floored to whole minutes with
    :func:`floor_to_minute`; ``start_time`` / ``start_date`` are likewise
    floored, at the ``# SEAM (Task 4.10)`` markers inside the type builders, so
    the dispatcher itself is unchanged.

    Args:
        cfg: normalized recurrence configuration.

    Returns:
        The built :class:`TimePeriod`.

    Raises:
        RecurrenceError: on an invalid recurrence type or any type-specific
            validation failure, each with a specific field/message.
    """
    builder = _BUILDERS.get(cfg.recurrence_type)
    if builder is None:
        raise RecurrenceError(
            "recurrence_type",
            f"Tipo de recurrencia no válido: {cfg.recurrence_type!r}.",
        )
    return builder(cfg)


# --------------------------------------------------------------------------- #
# Problem-tag validation (Req 32)                                             #
#                                                                             #
# Problem tags (distinct from host-discovery trigger_tags) travel to          #
# maintenance.create to filter which problems are suppressed. This guard runs  #
# before the API call: it enforces that tags are only used with data-          #
# collecting maintenances (maintenance_type == 0), that the evaluation method  #
# is one Zabbix accepts and that every tag operator is valid. Pure and         #
# deterministic — no I/O.                                                      #
# --------------------------------------------------------------------------- #
#: Accepted Tags_Evaltype values (0 = And/Or default, 2 = Or) (Req 32.1, 32.5).
TAGS_EVALTYPE_VALUES: set[int] = {0, 2}
#: Accepted Operador_Tag values (0 = Equals, 2 = Contains default) (Req 32.2, 32.6).
TAG_OPERATOR_VALUES: set[int] = {0, 2}


def validate_problem_tags(
    problem_tags: list[ProblemTag],
    tags_evaltype: int,
    maintenance_type: int,
) -> None:
    """Validate maintenance problem tags before ``maintenance.create`` (Req 32).

    Pure and deterministic (Req 32): validates the combination of problem tags,
    their evaluation method and the maintenance type. Returns ``None`` on
    success and raises :class:`~core.domain.RecurrenceError` on the first
    violation. No I/O.

    Rules:
        * A non-empty ``problem_tags`` list requires ``maintenance_type == 0``
          (with data collection); problem tags are not allowed with
          ``maintenance_type == 1`` → error on the field ``"problem_tags"``
          (Req 32.3).
        * ``tags_evaltype`` must be in :data:`TAGS_EVALTYPE_VALUES` (``{0, 2}``)
          → error on the field ``"tags_evaltype"`` (Req 32.5).
        * Every tag ``operator`` must be in :data:`TAG_OPERATOR_VALUES`
          (``{0, 2}``) → error on the field ``"operator"`` (Req 32.6).
        * An empty ``problem_tags`` list is valid with any valid
          ``maintenance_type``; Zabbix then suppresses **all** problems of the
          hosts under maintenance (default behaviour, Req 32.4).

    Args:
        problem_tags: the maintenance problem tags (may be empty).
        tags_evaltype: how multiple tags are combined (Tags_Evaltype).
        maintenance_type: ``0`` = with data collection, ``1`` = without.

    Returns:
        ``None`` when the configuration is valid.

    Raises:
        RecurrenceError: on the field ``"problem_tags"``, ``"tags_evaltype"`` or
            ``"operator"`` for the corresponding violation above.
    """
    if problem_tags and maintenance_type == 1:
        raise RecurrenceError(
            "problem_tags",
            "Los tags de problema solo se permiten con maintenance_type == 0 "
            "(con recolección de datos); se recibió maintenance_type == 1.",
        )
    if tags_evaltype not in TAGS_EVALTYPE_VALUES:
        raise RecurrenceError(
            "tags_evaltype",
            f"tags_evaltype inválido: debe ser uno de {sorted(TAGS_EVALTYPE_VALUES)}, "
            f"se obtuvo {tags_evaltype}.",
        )
    for tag in problem_tags:
        if tag.operator not in TAG_OPERATOR_VALUES:
            raise RecurrenceError(
                "operator",
                f"operator de tag inválido: debe ser uno de "
                f"{sorted(TAG_OPERATOR_VALUES)}, se obtuvo {tag.operator}.",
            )
