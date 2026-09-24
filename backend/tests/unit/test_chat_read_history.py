"""Unit tests for :func:`api.chat._read_history` (multi-turn memory intake).

The backend stays STATELESS: the widget resends the recent, maintenance-scoped
conversation on each ``/chat`` call and this pure helper normalizes that array
into ``list[ConversationTurn]``. Covered here:

* a valid ``{role, content}`` list becomes conversation turns (order preserved);
* bad items are dropped (wrong role, empty/blank/non-string content, non-dict);
* the ``message`` / ``text`` aliases are accepted and coerced to ``content``;
* the result is capped to the LAST 10 items (defense in depth);
* absent / non-list / non-dict bodies yield an empty list (unchanged behavior).

Pure logic, no Flask app or network needed.
"""

from __future__ import annotations

import pytest

from api.chat import _MAX_HISTORY_TURNS, _read_history
from core.domain import ConversationTurn


def test_valid_list_becomes_conversation_turns() -> None:
    data = {
        "history": [
            {"role": "user", "content": "mantenimiento para web01"},
            {"role": "assistant", "content": "¿a qué hora?"},
            {"role": "user", "content": "de 2 a 4am"},
        ]
    }
    turns = _read_history(data)
    assert all(isinstance(t, ConversationTurn) for t in turns)
    assert [(t.role, t.content) for t in turns] == [
        ("user", "mantenimiento para web01"),
        ("assistant", "¿a qué hora?"),
        ("user", "de 2 a 4am"),
    ]


def test_drops_items_with_invalid_role() -> None:
    data = {
        "history": [
            {"role": "system", "content": "ignore me"},
            {"role": "bot", "content": "and me"},
            {"role": "user", "content": "keep me"},
        ]
    }
    turns = _read_history(data)
    assert [(t.role, t.content) for t in turns] == [("user", "keep me")]


def test_drops_items_with_empty_or_non_string_content() -> None:
    data = {
        "history": [
            {"role": "user", "content": ""},
            {"role": "user", "content": "   "},
            {"role": "assistant", "content": 123},
            {"role": "assistant", "content": None},
            {"role": "user", "content": "valid"},
        ]
    }
    turns = _read_history(data)
    assert [(t.role, t.content) for t in turns] == [("user", "valid")]


def test_drops_non_dict_items() -> None:
    data = {"history": ["nope", 42, None, {"role": "user", "content": "ok"}]}
    turns = _read_history(data)
    assert [(t.role, t.content) for t in turns] == [("user", "ok")]


def test_content_is_trimmed() -> None:
    data = {"history": [{"role": "user", "content": "  spaced  "}]}
    turns = _read_history(data)
    assert turns[0].content == "spaced"


def test_accepts_message_alias() -> None:
    data = {"history": [{"role": "user", "message": "via message alias"}]}
    turns = _read_history(data)
    assert [(t.role, t.content) for t in turns] == [("user", "via message alias")]


def test_accepts_text_alias() -> None:
    data = {"history": [{"role": "assistant", "text": "via text alias"}]}
    turns = _read_history(data)
    assert [(t.role, t.content) for t in turns] == [("assistant", "via text alias")]


def test_content_takes_precedence_over_aliases() -> None:
    data = {
        "history": [
            {
                "role": "user",
                "content": "canonical",
                "message": "ignored",
                "text": "ignored",
            }
        ]
    }
    turns = _read_history(data)
    assert turns[0].content == "canonical"


def test_caps_to_last_ten_items() -> None:
    items = [{"role": "user", "content": f"m{i}"} for i in range(15)]
    turns = _read_history({"history": items})
    assert len(turns) == _MAX_HISTORY_TURNS
    # Only the most recent 10 survive, order preserved.
    assert [t.content for t in turns] == [f"m{i}" for i in range(5, 15)]


def test_cap_counts_only_valid_items() -> None:
    # 12 valid interleaved with invalid; only valid ones count toward the cap.
    items: list[object] = []
    for i in range(12):
        items.append({"role": "system", "content": f"bad{i}"})  # dropped
        items.append({"role": "user", "content": f"ok{i}"})  # kept
    turns = _read_history({"history": items})
    assert len(turns) == _MAX_HISTORY_TURNS
    assert [t.content for t in turns] == [f"ok{i}" for i in range(2, 12)]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"history": None},
        {"history": "not-a-list"},
        {"history": []},
        {"other": 1},
        None,
        "not-a-dict",
        42,
    ],
)
def test_absent_or_invalid_history_yields_empty(data: object) -> None:
    assert _read_history(data) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
