"""Common AI provider abstraction (Req 12.4) and shared response parsing.

This module defines the provider-agnostic :class:`AIProvider` interface plus the
pure, dependency-free helpers that turn a raw LLM text response into the
structured :class:`~backend.core.domain.ExtractedRequest` contract.

Design principle "AI extrae, backend calcula" (Req 3.2): the parsing here never
computes Zabbix bitmasks nor time-in-seconds conversions. It only maps the JSON
the model returns into the structured names/values carried by
:class:`~backend.core.domain.ExtractedRecurrence`; the backend recurrence engine
computes bitmasks later (Task 3/4).

Intent recognition (Req 13.1-13.4): the parser normalizes the model's ``intent``
(or legacy ``type``) into one of ``maintenance_request`` / ``help`` /
``clarification`` / ``off_topic``. Infrastructure terminology mentioned by the
user (CIs, servers, routers, switches, nodes, instances, appliances, ...) is
surfaced by the model as ``hosts`` (Req 13.5); the prompt instructs the model to
do so, and this parser preserves whatever host list the model returns.

The concrete providers (:mod:`backend.ai.gemini_provider`,
:mod:`backend.ai.openai_provider`) import their heavy SDKs lazily so that
importing this package never hard-fails when the AI libraries are not installed.

Requirements: 3.2, 3.8, 12.4, 12.5, 13.1, 13.2, 13.3, 13.4, 13.5.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    ProblemTag,
    PromptContext,
    RecurrenceType,
    TagsEvalType,
)

__all__ = [
    "AIProvider",
    "AIProviderError",
    "extract_json_object",
    "parse_extracted_request",
    "parse_response_text",
    "VALID_INTENTS",
]


# --------------------------------------------------------------------------- #
# Error type                                                                  #
# --------------------------------------------------------------------------- #
class AIProviderError(RuntimeError):
    """Raised when a provider cannot fulfil an extraction request.

    Used for both an unconfigured/unavailable provider (Req 12.5) and for
    unusable model output (empty response or no JSON object found). The
    failover / service layer catches this to degrade gracefully (Task 21.3);
    this module only signals the error clearly.
    """


# --------------------------------------------------------------------------- #
# Interface (Req 12.4)                                                         #
# --------------------------------------------------------------------------- #
class AIProvider(ABC):
    """Provider-agnostic interface for structured request extraction (Req 12.4)."""

    @abstractmethod
    def extract(self, message: str, ctx: PromptContext) -> ExtractedRequest:
        """Extract structured data from ``message`` WITHOUT bitmasks (Req 3.2).

        ``ctx`` is the prompt context (dates for relative-expression resolution,
        Req 13.6). The original request is preserved in
        :attr:`ExtractedRequest.raw_message` (Req 3.8).

        Implementations raise :class:`AIProviderError` when the provider is not
        available (Req 12.5) or the model output cannot be parsed.
        """

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether the provider is configured and usable (Req 12.5)."""


# --------------------------------------------------------------------------- #
# Intent normalization (Req 13.1-13.4)                                        #
# --------------------------------------------------------------------------- #
#: Canonical intents produced by :func:`parse_extracted_request`.
INTENT_MAINTENANCE = "maintenance_request"
INTENT_HELP = "help"
INTENT_CLARIFICATION = "clarification"
INTENT_OFF_TOPIC = "off_topic"

_VALID_INTENTS = frozenset(
    {INTENT_MAINTENANCE, INTENT_HELP, INTENT_CLARIFICATION, INTENT_OFF_TOPIC}
)

#: Map the raw ``intent``/``type`` values a model may emit (including the legacy
#: monolith's ``type`` vocabulary) onto the canonical intents (Req 13.1-13.4).
_INTENT_ALIASES: dict[str, str] = {
    "maintenance_request": INTENT_MAINTENANCE,
    "maintenance": INTENT_MAINTENANCE,
    "help": INTENT_HELP,
    "help_request": INTENT_HELP,
    "clarification": INTENT_CLARIFICATION,
    "clarification_needed": INTENT_CLARIFICATION,
    "off_topic": INTENT_OFF_TOPIC,
    "offtopic": INTENT_OFF_TOPIC,
}


def _normalize_intent(raw: Any) -> str:
    """Map a raw ``intent``/``type`` value to a canonical intent.

    Unknown or missing values fall back to ``clarification`` so the service
    layer asks the user for details rather than proceeding on a guess
    (Req 13.4). Pure and deterministic.
    """
    if not isinstance(raw, str):
        return INTENT_CLARIFICATION
    key = raw.strip().lower()
    if key in _VALID_INTENTS:
        return key
    return _INTENT_ALIASES.get(key, INTENT_CLARIFICATION)


# --------------------------------------------------------------------------- #
# Robust JSON extraction                                                      #
# --------------------------------------------------------------------------- #
def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first balanced JSON object from arbitrary model text.

    Models frequently wrap the JSON in prose or Markdown code fences. This helper
    locates the outermost ``{...}`` object by scanning for balanced braces
    (ignoring braces inside strings) and parses it. Pure and deterministic; no
    I/O.

    Raises :class:`AIProviderError` when no JSON object is present or the located
    candidate is not valid JSON.
    """
    if not text or not text.strip():
        raise AIProviderError("empty AI response")

    start = text.find("{")
    if start == -1:
        raise AIProviderError("no JSON object found in AI response")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : index + 1]
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError as exc:
                    raise AIProviderError(
                        f"invalid JSON in AI response: {exc}"
                    ) from exc
                if not isinstance(parsed, dict):
                    raise AIProviderError("AI response JSON is not an object")
                return parsed

    raise AIProviderError("unbalanced JSON object in AI response")


# --------------------------------------------------------------------------- #
# Tolerant field coercion helpers (pure)                                      #
# --------------------------------------------------------------------------- #
def _as_str_list(value: Any) -> list[str]:
    """Coerce a value into a list of non-empty trimmed strings.

    Accepts a list (each stringifiable item) or a single scalar. Missing/None
    yields an empty list. Tolerant by design: unknown shapes degrade to ``[]``
    rather than raising (Req parsing tolerance).
    """
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list | tuple | set):
        result: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []


def _as_str_set(value: Any) -> set[str]:
    """Coerce a value into a set of lowercase names (day/month/occurrence)."""
    return {item.lower() for item in _as_str_list(value)}


def _as_opt_str(value: Any) -> str | None:
    """Coerce a value into a trimmed string, or ``None`` when absent/blank.

    Used for the ``once`` ``start_date`` (ISO ``YYYY-MM-DD``): the model returns
    a string or ``null``. Any non-string/blank value degrades to ``None`` so the
    recurrence engine's structured-date path only fires with real data. No date
    format validation happens here (that stays in the engine, Req 3.2).
    """
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _as_int(value: Any) -> int | None:
    """Coerce a value into an int, or ``None`` when absent/uncoercible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def _as_float(value: Any) -> float | None:
    """Coerce a value into a float, or ``None`` when absent/uncoercible."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _parse_recurrence_type(value: Any) -> RecurrenceType | None:
    """Map a raw recurrence-type string onto :class:`RecurrenceType`.

    Returns ``None`` for missing or unrecognized values; the recurrence engine
    validates the type later (Req 9.1), so parsing stays tolerant here.
    """
    if not isinstance(value, str):
        return None
    key = value.strip().lower()
    try:
        return RecurrenceType(key)
    except ValueError:
        return None


def _parse_problem_tags(value: Any) -> list[ProblemTag]:
    """Parse the optional ``problem_tags`` list into :class:`ProblemTag` objects.

    Each entry is expected to be an object with ``tag`` and optional ``value`` /
    ``operator`` fields. Entries without a ``tag`` are skipped. The ``operator``
    is passed through as-is (validated later by ``validate_problem_tags``,
    Req 32.6); a missing operator keeps the :class:`ProblemTag` default.
    """
    tags: list[ProblemTag] = []
    if not isinstance(value, list | tuple):
        return tags
    for entry in value:
        if not isinstance(entry, dict):
            continue
        name = entry.get("tag")
        if not isinstance(name, str) or not name.strip():
            continue
        raw_value = entry.get("value", "")
        tag_value = str(raw_value) if raw_value is not None else ""
        operator = _as_int(entry.get("operator"))
        if operator is None:
            tags.append(ProblemTag(tag=name.strip(), value=tag_value))
        else:
            tags.append(
                ProblemTag(tag=name.strip(), value=tag_value, operator=operator)
            )
    return tags


def _parse_recurrence(data: dict[str, Any]) -> ExtractedRecurrence | None:
    """Build an :class:`ExtractedRecurrence` from the response payload.

    Reads the recurrence details from a nested ``recurrence`` object when
    present, otherwise from the top level (legacy-flat shape). The recurrence
    type may live under ``recurrence_type`` at either level. Returns ``None``
    when no recurrence type can be determined (e.g. help/off-topic responses).
    No bitmask arithmetic is performed (Req 3.2).
    """
    nested = data.get("recurrence")
    source: dict[str, Any] = nested if isinstance(nested, dict) else data

    rec_type = _parse_recurrence_type(
        source.get("recurrence_type", data.get("recurrence_type"))
    )
    if rec_type is None:
        return None

    return ExtractedRecurrence(
        recurrence_type=rec_type,
        days=_as_str_set(source.get("days")),
        months=_as_str_set(source.get("months")),
        occurrences=_as_str_set(source.get("occurrences")),
        day_of_month=_as_int(source.get("day_of_month")),
        start_hour=_as_int(source.get("start_hour")),
        duration_hours=_as_float(source.get("duration_hours")),
        every=_as_int(source.get("every")),
        start_date=_as_opt_str(source.get("start_date")),
        start_ts=_as_int(source.get("start_ts")),
        end_ts=_as_int(source.get("end_ts")),
    )


def parse_extracted_request(data: dict[str, Any], message: str) -> ExtractedRequest:
    """Map a parsed model JSON object into an :class:`ExtractedRequest` (Req 3.2).

    Tolerant by design: unknown or missing fields fall back to their defaults;
    the JSON-schema validation (Task 20.1) and the service layer perform the
    authoritative validation later. This function never computes bitmasks and
    always preserves the original request in ``raw_message`` (Req 3.8).

    - ``intent`` is normalized to one of the canonical intents (Req 13.1-13.4);
      the legacy ``type`` key is accepted as an alias.
    - ``hosts`` reflect the infrastructure terminology the model recognized
      (Req 13.5); they are preserved verbatim.
    """
    intent = _normalize_intent(data.get("intent", data.get("type")))

    # Conversational reply written by the AI in the user's language (prose only,
    # never bitmasks). Coerce non-str/None to "" and strip; the service prefers
    # this text and falls back to the i18n catalog when it is empty.
    raw_assistant = data.get("assistant_message")
    assistant_message = raw_assistant.strip() if isinstance(raw_assistant, str) else ""

    tags_evaltype = _as_int(data.get("tags_evaltype"))
    maintenance_type = _as_int(data.get("maintenance_type"))
    ticket = data.get("ticket") or data.get("ticket_number")

    trigger_tags_raw = data.get("trigger_tags")
    trigger_tags = (
        [tag for tag in trigger_tags_raw if isinstance(tag, dict)]
        if isinstance(trigger_tags_raw, list | tuple)
        else []
    )

    return ExtractedRequest(
        intent=intent,
        hosts=_as_str_list(data.get("hosts")),
        groups=_as_str_list(data.get("groups")),
        trigger_tags=trigger_tags,
        problem_tags=_parse_problem_tags(data.get("problem_tags")),
        tags_evaltype=(
            tags_evaltype if tags_evaltype is not None else TagsEvalType.AND_OR
        ),
        maintenance_type=maintenance_type if maintenance_type is not None else 0,
        ticket=ticket.strip() if isinstance(ticket, str) and ticket.strip() else None,
        recurrence=_parse_recurrence(data),
        raw_message=message,
        assistant_message=assistant_message,
    )


def parse_response_text(text: str, message: str) -> ExtractedRequest:
    """Convenience: extract the JSON object from ``text`` and map it.

    Combines :func:`extract_json_object` and :func:`parse_extracted_request`;
    used by the concrete providers after calling their SDK.
    """
    return parse_extracted_request(extract_json_object(text), message)


# Kept for callers that only need to know the recognized intent vocabulary.
VALID_INTENTS: frozenset[str] = _VALID_INTENTS
