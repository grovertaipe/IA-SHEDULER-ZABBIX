"""Pure domain data models for zabbix-ai-maintenance-v2.

These are the structured **contract types** shared between the AI extraction
(:class:`ExtractedRequest`), the recurrence engine input
(:class:`RecurrenceConfig`) and the output toward Zabbix (:class:`TimePeriod` /
:class:`MaintenancePayload`).

This module contains **pure data definitions only**: no business logic, no I/O,
no Flask / AI / Zabbix dependencies (Req 1.4). The recurrence engine (bitmask
computation, time-period dispatch and validation) lives in ``core/recurrence.py``.

Design principle "AI extrae, backend calcula" (Req 3.2): the AI output
(:class:`ExtractedRecurrence`) carries **no precomputed bitmasks** — only
structured sets of day/month/occurrence names, hours and duration. Bitmasks are
computed by the backend later.

Requirements: 1.4, 3.2, 20.1, 32.1, 32.2, 32.3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, StrEnum


class RecurrenceType(StrEnum):
    """Supported recurrence types (Req 4-8)."""

    ONCE = "once"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class UserInfo:
    """Info_Usuario — authenticated user metadata (Req 11)."""

    userid: str
    username: str
    name: str = ""
    surname: str = ""


@dataclass
class PromptContext:
    """Context injected into the Prompt_IA (Req 3.6).

    Both dates are ISO 8601 (``YYYY-MM-DD``) so the AI can resolve relative
    expressions ("today", "tomorrow") deterministically without arithmetic.
    """

    today_iso: str
    tomorrow_iso: str


# --------------------------------------------------------------------------- #
# AI output contract (WITHOUT precomputed bitmasks, Req 3.2)                   #
# --------------------------------------------------------------------------- #
@dataclass
class ExtractedRecurrence:
    """Recurrence details extracted by the AI as structured names/values.

    No bitmasks here: only day/month/occurrence names, hour, duration and the
    ``once`` timestamps. The backend computes bitmasks and the time period.
    """

    recurrence_type: RecurrenceType
    days: set[str] = field(default_factory=set)  # day names (weekly / monthly-dow)
    months: set[str] = field(default_factory=set)  # month names (monthly)
    occurrences: set[str] = field(default_factory=set)  # first..last (monthly-dow)
    day_of_month: int | None = None  # 1..31 (monthly-dom)
    start_hour: int | None = None  # 0..23
    duration_hours: float | None = None  # > 0
    every: int | None = None  # interval (days/weeks/months)
    # once:
    start_date: str | None = None  # ISO "YYYY-MM-DD" resolved calendar date (once)
    start_ts: int | None = None
    end_ts: int | None = None
    # Precomputed Zabbix bitmasks a client may resend verbatim (e.g. the widget
    # echoing back the ``recurrence_config`` the backend produced in ``/chat``).
    # Normally None (AI extraction carries no bitmasks, Req 3.2); when present
    # they are threaded to RecurrenceConfig and validated by the engine (Req 2.7).
    day_bitmask: int | None = None  # Bitmask_Dias (weekly / monthly-dow)
    month_bitmask: int | None = None  # Bitmask_Meses (monthly)


# --------------------------------------------------------------------------- #
# Maintenance problem tags (Req 32)                                           #
# --------------------------------------------------------------------------- #
class TagOperator(int, Enum):
    """Operador_Tag — how a problem tag value is matched (Req 32.2, 32.6)."""

    EQUALS = 0  # exact match
    CONTAINS = 2  # substring (default)


class TagsEvalType(int, Enum):
    """Tags_Evaltype — how multiple problem tags are combined (Req 32.1, 32.5)."""

    AND_OR = 0  # And/Or (default)
    OR = 2  # Or


@dataclass
class ProblemTag:
    """Maintenance problem tag (Req 32.2).

    Distinct from ``trigger_tags`` (see :class:`ExtractedRequest`): problem tags
    travel to ``maintenance.create`` to filter which problems are suppressed,
    while ``trigger_tags`` are used only for host discovery (Req 14.4).
    """

    tag: str
    value: str = ""
    operator: int = TagOperator.CONTAINS  # 0 = Equals, 2 = Contains (default)


@dataclass
class ExtractedRequest:
    """Full output of the Proveedor_IA (AI provider).

    Carries **no** precomputed bitmasks (Req 3.2): the recurrence is expressed
    as the structured :class:`ExtractedRecurrence`.

    ``trigger_tags`` (host discovery only, Req 14.4) is kept explicitly separate
    from ``problem_tags`` (maintenance suppression, Req 32).
    """

    intent: str  # "maintenance_request"|"help"|"clarification"|"off_topic" (Req 13)
    hosts: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    trigger_tags: list[dict] = field(default_factory=list)  # Req 14.4 (host discovery ONLY)
    problem_tags: list[ProblemTag] = field(
        default_factory=list
    )  # Req 32 (filter suppressed problems)
    tags_evaltype: int = TagsEvalType.AND_OR  # Req 32.1 (0 And/Or def., 2 Or)
    maintenance_type: int = 0  # 0 = with data collection (def.), 1 = without (Req 32.3)
    ticket: str | None = None  # may be completed by the backend (Req 10.3)
    recurrence: ExtractedRecurrence | None = None
    raw_message: str = ""  # original request preserved (Req 3.8)
    # Conversational reply written by the AI IN THE USER'S LANGUAGE (any
    # language), natural but guided toward creating a Zabbix maintenance. This is
    # ONLY prose: it never carries bitmasks, JSON or computed numbers — those stay
    # in the structured fields above and are computed deterministically by the
    # backend core. Empty when the AI did not provide one (the service then falls
    # back to the localized i18n catalog message).
    assistant_message: str = ""


# --------------------------------------------------------------------------- #
# Recurrence engine input (already-normalized data)                           #
# --------------------------------------------------------------------------- #
@dataclass
class RecurrenceConfig:
    """Normalized input for the recurrence engine.

    Optional ``day_bitmask`` / ``month_bitmask`` may be supplied already
    precomputed by a client; when present they are validated (Req 2.7).
    """

    recurrence_type: RecurrenceType
    days: set[str] = field(default_factory=set)
    months: set[str] = field(default_factory=set)
    occurrences: set[str] = field(default_factory=set)
    day_of_month: int | None = None
    start_hour: int | None = None
    duration_hours: float | None = None
    every: int | None = None
    # once: either the explicit epochs OR a structured ISO date + start_hour +
    # duration_hours (the backend computes the epochs from the structured date,
    # mirroring ExtractedRecurrence.start_date).
    start_date: str | None = None
    start_ts: int | None = None
    end_ts: int | None = None
    # bitmasks optionally precomputed by a client (validated, Req 2.7)
    day_bitmask: int | None = None
    month_bitmask: int | None = None


# --------------------------------------------------------------------------- #
# Recurrence engine output toward Zabbix (Req 4-8, 20.1)                       #
# --------------------------------------------------------------------------- #
@dataclass
class TimePeriod:
    """A Zabbix time period (maps to ``timeperiods`` in ``maintenance.create``)."""

    timeperiod_type: int  # 0 | 2 | 3 | 4
    period: int  # duration in seconds
    start_time: int | None = None  # seconds since midnight (daily/weekly/monthly)
    start_date: int | None = None  # timestamp (once)
    every: int | None = None
    dayofweek: int | None = None  # Bitmask_Dias (weekly/monthly-dow)
    day: int | None = None  # day of month (monthly-dom)
    month: int | None = None  # Bitmask_Meses (monthly)


@dataclass
class MaintenanceWindow:
    """Payload assembled around the ``once`` time period (Req 4.4).

    Extended for Req 32 with ``maintenance_type``, problem ``tags`` and
    ``tags_evaltype`` so the window can carry the suppression configuration.
    """

    active_since: int
    active_till: int
    timeperiods: list[TimePeriod]
    maintenance_type: int = 0  # 0 = with data collection (def.), 1 = without (Req 32.3)
    tags: list[ProblemTag] = field(default_factory=list)  # problem tags (Req 32.2, 32.4)
    tags_evaltype: int = TagsEvalType.AND_OR  # evaluation method (Req 32.1)


@dataclass
class MaintenancePayload:
    """Payload for ``maintenance.create`` toward Zabbix (Req 4-8, 32).

    ``tags`` are the problem tags (Req 32.2, 32.4) — kept explicitly distinct
    from any host-discovery ``trigger_tags`` which never reach this payload.
    """

    name: str
    description: str
    active_since: int
    active_till: int
    maintenance_type: int  # 0 = with data collection (def.), 1 = without (Req 32.3)
    timeperiods: list[TimePeriod]
    tags: list[ProblemTag] = field(default_factory=list)  # problem tags (Req 32.2, 32.4)
    tags_evaltype: int = TagsEvalType.AND_OR  # evaluation method (Req 32.1)


class RecurrenceError(ValueError):
    """Recurrence-engine validation error with a specific field/message (Req 2, 9)."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Domain utilities — pure deterministic functions (Req 10, 11.4, 20.6)        #
#                                                                             #
# No I/O, no Flask/AI/Zabbix dependencies (Req 1.4). These helpers derive     #
# maintenance metadata (ticket, name, description) and decode Zabbix bitmasks #
# back to canonical names for previews and round-trip verification.           #
# --------------------------------------------------------------------------- #

# Ticket extraction (Req 10.1, 10.2). Tickets have NO single mandatory format:
# every organization uses its own nomenclature (``INC0012345``, ``JIRA-4521``,
# ``CHG-2024-001``, ``#88213``, ``REQ-99``, ``100-178306``, ...). The AI is the
# PRIMARY extractor; this regex is only a BROAD, conservative FALLBACK used when
# the AI does not return one. Nothing company-specific is hard-coded here.
#
# The pattern recognizes an optional leading label (``ticket:`` / ``ticket`` /
# ``#``, case-insensitive) that is NOT captured, then a generic identifier:
#   * an alphanumeric token with optional ``-`` / ``_`` / ``.`` separators,
#   * containing AT LEAST ONE digit (so plain words are ignored), and
#   * at least 3 characters long (so 1-2 char noise is ignored).
# Word boundaries and a negative lookbehind/lookahead for ``:`` keep clock times
# like ``22:00`` and ``22:00-23:00`` from being mistaken for tickets, while the
# separator set deliberately EXCLUDES ``:`` for the same reason. A label-anchored
# match is preferred; a bare token is the second alternative. The returned value
# is always the bare identifier (label stripped).
_TICKET_LABEL = r"(?:ticket\s*[:#]?\s*|#)"

# LABELED token (after ``ticket:`` / ``#``): the user has already signalled intent,
# so accept any alnum token with optional ``-`` / ``_`` / ``.`` separators that has
# at least one digit and is at least 3 characters long. ``:`` is deliberately not a
# separator so a trailing clock time is never swallowed.
_TICKET_TOKEN_LABELED = (
    r"(?=[A-Za-z0-9._-]{3,}(?![A-Za-z0-9._-]))"  # >=3 chars for the whole token
    r"(?=[A-Za-z0-9._-]*[0-9])"  # must contain at least one digit
    r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*"
)

# BARE token (no label): must be unmistakably ticket-shaped to avoid false
# positives on hostnames (``srv-web01``), plain numbers (``10``, ``12``) and clock
# times (``22:00``). Two accepted shapes:
#   1. an UPPERCASE alphanumeric id with >=1 digit and >=1 letter, >=3 chars
#      (e.g. INC0012345, JIRA-4521, CHG-2024-001, REQ-99) — hostnames are
#      conventionally lowercase, so requiring an uppercase letter excludes them;
#   2. a purely numeric hyphenated id ``NN..-NN..`` (e.g. 100-178306).
_TICKET_TOKEN_BARE = (
    r"(?:"
    r"(?=[A-Z0-9._-]{3,}(?![A-Za-z0-9._-]))"  # >=3 chars, uppercase-only alphabet
    r"(?=[A-Z0-9._-]*[0-9])"  # at least one digit
    r"(?=[A-Z0-9._-]*[A-Z])"  # at least one uppercase letter
    r"[A-Z0-9]+(?:[._-][A-Z0-9]+)*"
    r"|"
    r"[0-9]{2,}-[0-9]{2,}"  # numeric hyphenated ticket, e.g. 100-178306
    r")"
)

# The bare branch is wrapped in ``(?-i:...)`` so the uppercase-letter requirement
# stays case-sensitive even though the label match is case-insensitive.
TICKET_REGEX = (
    r"(?<![A-Za-z0-9:._-])"  # left boundary (not mid-word, not after a clock ':')
    rf"(?:{_TICKET_LABEL}({_TICKET_TOKEN_LABELED})|(?-i:({_TICKET_TOKEN_BARE})))"
    r"(?![A-Za-z0-9:])"  # right boundary (not mid-word, not a clock time)
)

_TICKET_PATTERN = re.compile(TICKET_REGEX, re.IGNORECASE)


def extract_ticket(text: str) -> str | None:
    """Extract a ticket identifier of ANY nomenclature from arbitrary text.

    Tickets are format-agnostic (``INC0012345``, ``JIRA-4521``, ``CHG-2024-001``,
    ``#88213``, ``REQ-99``, ``100-178306`` ...). This is a broad FALLBACK; the AI
    is the primary extractor (Req 10.1, 10.2). Recognizes an optional
    ``ticket:`` / ``ticket`` / ``#`` label without including it in the result,
    and returns the bare identifier. Requires the token to contain at least one
    digit and be at least 3 characters so plain words and clock times (``22:00``)
    are not captured. Returns ``None`` when no ticket-shaped token is present.
    """
    match = _TICKET_PATTERN.search(text)
    if not match:
        return None
    # group(1) = label-anchored token, group(2) = bare token; exactly one is set.
    return match.group(1) or match.group(2)


def generate_maintenance_name(ticket: str | None, summary: str) -> str:
    """Build the maintenance name using the ticket as the primary component.

    When a ticket is present it leads the name (``"<ticket> - <summary>"``);
    otherwise the summary alone is used (Req 10.4). Surrounding whitespace is
    trimmed so callers can pass loosely formatted summaries.
    """
    summary = summary.strip()
    if ticket:
        return f"{ticket} - {summary}" if summary else ticket
    return summary


def generate_maintenance_description(
    ticket: str | None, user: UserInfo, body: str
) -> str:
    """Build the maintenance description with the ticket on its own line.

    The ticket appears exactly once on a dedicated line and is never duplicated
    inside the body: any occurrence already present in ``body`` (with or without
    the ``ticket:`` / ``#`` prefix) is stripped before the body is appended
    (Req 10.5). User data is always included for traceability (Req 11.4).
    """
    lines: list[str] = []

    if ticket:
        lines.append(f"Ticket: {ticket}")

    # Requester identity (Req 11.4): prefer the full name, fall back to username.
    full_name = " ".join(part for part in (user.name, user.surname) if part).strip()
    who = f"{full_name} ({user.username})" if full_name else user.username
    lines.append(f"Solicitado por: {who} [userid: {user.userid}]")

    cleaned_body = _strip_ticket_from_body(body, ticket).strip()
    if cleaned_body:
        lines.append("")
        lines.append(cleaned_body)

    return "\n".join(lines)


def _strip_ticket_from_body(body: str, ticket: str | None) -> str:
    """Remove any inline mention of ``ticket`` from ``body`` (Req 10.5 helper).

    Drops standalone occurrences of the ticket number, including the optional
    ``ticket:`` / ``#`` prefixes, so the ticket is not repeated once it has been
    placed on its own line. Pure and deterministic; leaves the body untouched
    when no ticket is provided.
    """
    if not ticket:
        return body
    # Escape the ticket for safe embedding, then allow the same optional label
    # recognized by extract_ticket (``ticket:`` / ``ticket`` / ``#``). ``ticket``
    # is an arbitrary identifier here, so re.escape keeps this generic.
    pattern = re.compile(
        rf"(?:{_TICKET_LABEL})?{re.escape(ticket)}", re.IGNORECASE
    )
    stripped = pattern.sub("", body)
    # Collapse whitespace/blank lines left behind by the removal.
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped


# --------------------------------------------------------------------------- #
# Bitmask decoding (Req 20.6)                                                 #
#                                                                             #
# The canonical Zabbix bit values are Monday=1..Sunday=64 for days and        #
# January=1..December=2048 for months. To guarantee a clean round-trip with   #
# the recurrence engine's compute_day_bitmask/compute_month_bitmask (which use #
# lowercase English keys), these functions return the SAME lowercase English  #
# canonical names, ordered by ascending bit value. This makes                 #
# ``decode_days(compute_day_bitmask(x)) == sorted(x)`` hold. Localization to   #
# human display names happens later in the i18n / preview layer (Task 19).    #
# --------------------------------------------------------------------------- #
DAY_NAMES_BY_BIT: tuple[tuple[int, str], ...] = (
    (1, "monday"),
    (2, "tuesday"),
    (4, "wednesday"),
    (8, "thursday"),
    (16, "friday"),
    (32, "saturday"),
    (64, "sunday"),
)

MONTH_NAMES_BY_BIT: tuple[tuple[int, str], ...] = (
    (1, "january"),
    (2, "february"),
    (4, "march"),
    (8, "april"),
    (16, "may"),
    (32, "june"),
    (64, "july"),
    (128, "august"),
    (256, "september"),
    (512, "october"),
    (1024, "november"),
    (2048, "december"),
)


def decode_days(bitmask: int) -> list[str]:
    """Decode a Zabbix ``dayofweek`` bitmask into canonical day names.

    Returns the lowercase English day names whose bits are set, in ascending
    bit-value order (monday..sunday), so the result round-trips with
    ``compute_day_bitmask`` (Req 20.6). Bits outside the 7-day range are ignored.
    """
    return [name for value, name in DAY_NAMES_BY_BIT if bitmask & value]


def decode_months(bitmask: int) -> list[str]:
    """Decode a Zabbix ``month`` bitmask into canonical month names.

    Returns the lowercase English month names whose bits are set, in ascending
    bit-value order (january..december), so the result round-trips with
    ``compute_month_bitmask`` (Req 20.6). Bits outside the 12-month range are
    ignored.
    """
    return [name for value, name in MONTH_NAMES_BY_BIT if bitmask & value]


# --------------------------------------------------------------------------- #
# Human-readable maintenance preview (Req 24.4, 24.5)                          #
#                                                                             #
# The preview is produced BEFORE the maintenance is created so the user can   #
# confirm that the decoded schedule matches their intent (Req 24.4). Day and  #
# month names are the natural-language decoding of the config's bitmasks and  #
# MUST match decode_days/decode_months EXACTLY (Property 36, Req 24.5).        #
# --------------------------------------------------------------------------- #

#: Canonical week-occurrence order (first..last). Mirrors the recurrence
#: engine's OCCURRENCE_VALUES ordering without importing it (avoids an import
#: cycle: core.recurrence imports from core.domain, not the other way round).
_OCCURRENCE_ORDER: tuple[str, ...] = (
    "first",
    "second",
    "third",
    "fourth",
    "last",
)


@dataclass
class MaintenancePreview:
    """Readable preview of a maintenance schedule before creation (Req 24.4).

    ``day_names`` / ``month_names`` are the natural-language decoding of the
    configuration's day/month bitmasks and are guaranteed to equal
    :func:`decode_days` / :func:`decode_months` for that configuration exactly —
    no omissions, no additions (Property 36, Req 24.5). ``text`` is a
    deterministic one-line human summary assembled from those names.
    """

    recurrence_type: RecurrenceType
    day_names: list[str] = field(default_factory=list)  # decode_days (Req 24.5)
    month_names: list[str] = field(default_factory=list)  # decode_months (Req 24.5)
    occurrence_labels: list[str] = field(default_factory=list)
    start_hour: int | None = None
    duration_hours: float | None = None
    text: str = ""


def _preview_day_bitmask(cfg: RecurrenceConfig) -> int:
    """Resolve the day-of-week bitmask for a preview without side effects.

    Prefers a precomputed ``cfg.day_bitmask``; otherwise it sums the canonical
    bit values of ``cfg.days`` using this module's own ``DAY_NAMES_BY_BIT``
    table. Deriving the mask locally (instead of importing
    ``core.recurrence.compute_day_bitmask``) keeps this function pure and avoids
    an import cycle, while still guaranteeing that ``decode_days`` on the result
    yields exactly the config's days (Property 36). Unknown names are ignored so
    the preview never raises — validation is the recurrence engine's job.
    """
    if cfg.day_bitmask is not None:
        return cfg.day_bitmask
    return sum(value for value, name in DAY_NAMES_BY_BIT if name in cfg.days)


def _preview_month_bitmask(cfg: RecurrenceConfig) -> int:
    """Resolve the month bitmask for a preview without side effects.

    Prefers a precomputed ``cfg.month_bitmask``; otherwise it sums the canonical
    bit values of ``cfg.months`` using this module's own ``MONTH_NAMES_BY_BIT``
    table (same rationale as :func:`_preview_day_bitmask`). When no months are
    given the mask is ``0`` and ``month_names`` stays empty — the preview does
    not assume the engine's "all months" default so it reflects only what the
    user actually specified.
    """
    if cfg.month_bitmask is not None:
        return cfg.month_bitmask
    return sum(value for value, name in MONTH_NAMES_BY_BIT if name in cfg.months)


def build_maintenance_preview(cfg: RecurrenceConfig, locale: str) -> MaintenancePreview:
    """Build a readable preview of a maintenance schedule (Req 24.4, 24.5).

    Pure and deterministic: decodes the configuration's day/month bitmasks to
    natural-language names via :func:`decode_days` / :func:`decode_months` and
    assembles a human-readable ``text`` summary. The returned ``day_names`` and
    ``month_names`` are EXACTLY what those decoders return for the config's
    bitmasks — the preview is a faithful decoding, never an interpretation
    (Property 36).

    ``locale`` selects the display language of the surrounding ``text`` labels.
    A minimal inline ``es``/``en`` label map is used; the day/month tokens
    themselves stay as the canonical lowercase names, which the full i18n
    catalog (Task 18.x) maps to localized display strings downstream. An unknown
    locale falls back to Spanish (the product default) rather than failing, so
    the preview never hard-fails on a missing catalog.
    """
    day_names = decode_days(_preview_day_bitmask(cfg))
    month_names = decode_months(_preview_month_bitmask(cfg))
    occurrence_labels = [
        occ for occ in _OCCURRENCE_ORDER if occ in cfg.occurrences
    ]

    text = _format_preview_text(
        locale=locale,
        recurrence_type=cfg.recurrence_type,
        day_names=day_names,
        month_names=month_names,
        occurrence_labels=occurrence_labels,
        day_of_month=cfg.day_of_month,
        start_hour=cfg.start_hour,
        duration_hours=cfg.duration_hours,
    )

    return MaintenancePreview(
        recurrence_type=cfg.recurrence_type,
        day_names=day_names,
        month_names=month_names,
        occurrence_labels=occurrence_labels,
        start_hour=cfg.start_hour,
        duration_hours=cfg.duration_hours,
        text=text,
    )


#: Minimal inline label catalog for the preview ``text``. The full i18n catalog
#: (Task 18.x) supersedes this; here we only need enough to render a readable,
#: localized one-liner deterministically. Falls back to Spanish for unknown
#: locales so the preview never hard-fails on a missing catalog.
_PREVIEW_LABELS: dict[str, dict[str, str]] = {
    "es": {
        RecurrenceType.ONCE: "Una vez",
        RecurrenceType.DAILY: "Diario",
        RecurrenceType.WEEKLY: "Semanal",
        RecurrenceType.MONTHLY: "Mensual",
        "days": "días",
        "months": "meses",
        "occurrences": "ocurrencias",
        "day_of_month": "día del mes",
        "at": "a las",
        "for": "durante",
        "hours": "h",
    },
    "en": {
        RecurrenceType.ONCE: "Once",
        RecurrenceType.DAILY: "Daily",
        RecurrenceType.WEEKLY: "Weekly",
        RecurrenceType.MONTHLY: "Monthly",
        "days": "days",
        "months": "months",
        "occurrences": "occurrences",
        "day_of_month": "day of month",
        "at": "at",
        "for": "for",
        "hours": "h",
    },
}


def _format_preview_text(
    *,
    locale: str,
    recurrence_type: RecurrenceType,
    day_names: list[str],
    month_names: list[str],
    occurrence_labels: list[str],
    day_of_month: int | None,
    start_hour: int | None,
    duration_hours: float | None,
) -> str:
    """Assemble the deterministic one-line preview summary (Req 24.4).

    Uses the minimal inline label catalog above; the canonical day/month tokens
    are embedded verbatim so the ``text`` stays consistent with ``day_names`` /
    ``month_names`` and the downstream i18n layer can localize the tokens.
    """
    # Normalize the locale to its base language and fall back to Spanish.
    lang = (locale or "es").split("-")[0].split("_")[0].lower()
    labels = _PREVIEW_LABELS.get(lang, _PREVIEW_LABELS["es"])

    parts: list[str] = [labels[recurrence_type]]

    if occurrence_labels:
        parts.append(f"{labels['occurrences']}: {', '.join(occurrence_labels)}")
    if day_names:
        parts.append(f"{labels['days']}: {', '.join(day_names)}")
    if day_of_month is not None:
        parts.append(f"{labels['day_of_month']}: {day_of_month}")
    if month_names:
        parts.append(f"{labels['months']}: {', '.join(month_names)}")
    if start_hour is not None:
        parts.append(f"{labels['at']} {start_hour:02d}:00")
    if duration_hours is not None:
        parts.append(f"{labels['for']} {duration_hours:g}{labels['hours']}")

    return " · ".join(parts)
