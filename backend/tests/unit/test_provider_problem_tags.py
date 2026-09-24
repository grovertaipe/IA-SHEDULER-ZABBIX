"""Parser tests for maintenance problem tags (Req 32).

Pins the end-to-end AI contract: a model JSON that carries ``problem_tags`` /
``tags_evaltype`` / ``maintenance_type`` must be mapped by
:func:`ai.provider.parse_response_text` into an :class:`core.domain.ExtractedRequest`
with the expected :class:`~core.domain.ProblemTag` objects and integer fields.
No bitmask arithmetic, no network.
"""

from __future__ import annotations

import json

import pytest

from ai.provider import parse_response_text
from core.domain import ProblemTag, TagsEvalType


def test_problem_tags_parsed_from_model_json() -> None:
    # "host X but only CPU problems" — the real use case this feature enables.
    data = {
        "intent": "maintenance_request",
        "hosts": ["NBJOSCCMA01"],
        "problem_tags": [{"tag": "component", "value": "cpu", "operator": 2}],
        "tags_evaltype": 0,
        "maintenance_type": 0,
        "recurrence": {"recurrence_type": "once", "start_hour": 22, "duration_hours": 1},
    }
    req = parse_response_text(json.dumps(data), "solo la CPU de NBJOSCCMA01")
    assert req.hosts == ["NBJOSCCMA01"]
    assert req.problem_tags == [ProblemTag(tag="component", value="cpu", operator=2)]
    assert req.tags_evaltype == 0
    assert req.maintenance_type == 0


def test_problem_tags_default_when_absent() -> None:
    data = {
        "intent": "maintenance_request",
        "hosts": ["web01"],
        "recurrence": {"recurrence_type": "daily", "start_hour": 2, "duration_hours": 2},
    }
    req = parse_response_text(json.dumps(data), "x")
    assert req.problem_tags == []
    assert req.tags_evaltype == TagsEvalType.AND_OR
    assert req.maintenance_type == 0


def test_tags_evaltype_or_and_no_data_collection() -> None:
    data = {
        "intent": "maintenance_request",
        "hosts": ["web01"],
        "tags_evaltype": 2,
        "maintenance_type": 1,
        "recurrence": {"recurrence_type": "once", "start_hour": 1, "duration_hours": 2},
    }
    req = parse_response_text(json.dumps(data), "x")
    assert req.tags_evaltype == 2
    assert req.maintenance_type == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
