"""Tests for conversation-history rendering in :func:`ai.prompt.build_prompt`.

Multi-turn memory: when history is provided the prompt embeds a compact
role-labeled transcript BEFORE the current message so the model merges fields
across turns. Covered here:

* an empty/absent history still formats cleanly (no ``str.format`` error) and
  behaves like a single-message prompt (with a "sin historial previo" note);
* a non-empty history renders ``Usuario:`` / ``Asistente:`` transcript lines
  and includes the current user message;
* a user turn containing literal ``{`` / ``}`` does NOT break ``str.format``
  (brace escaping works) and the text survives into the prompt;
* blank-content turns are skipped.

Pure functions; no network, no SDKs.
"""

from __future__ import annotations

import pytest

from ai.prompt import _EMPTY_HISTORY, build_prompt, render_history
from core.domain import ConversationTurn, PromptContext

CTX = PromptContext(today_iso="2024-01-01", tomorrow_iso="2024-01-02")


def test_build_prompt_without_history_formats_and_notes_empty() -> None:
    prompt = build_prompt("web01 mañana 22:00-23:00", CTX)
    # The current message is present and the empty-history note is rendered.
    assert "web01 mañana 22:00-23:00" in prompt
    assert _EMPTY_HISTORY in prompt


def test_build_prompt_with_none_history_matches_empty_history() -> None:
    assert build_prompt("hola", CTX, None) == build_prompt("hola", CTX, [])


def test_build_prompt_renders_transcript_lines() -> None:
    history = [
        ConversationTurn(role="user", content="mantenimiento para web01"),
        ConversationTurn(role="assistant", content="¿A qué hora?"),
    ]
    prompt = build_prompt("de 2 a 4am", CTX, history)
    assert "Usuario: mantenimiento para web01" in prompt
    assert "Asistente: ¿A qué hora?" in prompt
    # The current message is still present after the transcript.
    assert "de 2 a 4am" in prompt


def test_build_prompt_with_braces_in_history_does_not_raise() -> None:
    # A user turn with literal braces must not break str.format on the template.
    history = [
        ConversationTurn(role="user", content='usa {"json": "like"} y {llaves}'),
    ]
    # Should not raise (regression guard for the brace escaping).
    prompt = build_prompt("continua", CTX, history)
    # The braced text survives into the rendered prompt (as literal text).
    assert '{"json": "like"}' in prompt
    assert "{llaves}" in prompt
    assert "continua" in prompt


def test_build_prompt_with_braces_in_current_message_does_not_raise() -> None:
    # The current message is a format VALUE (not re-interpreted), but assert the
    # end-to-end call is robust regardless of braces in it.
    prompt = build_prompt('apaga {host} usando {config}', CTX, [])
    assert "{host}" in prompt
    assert "{config}" in prompt


def test_build_prompt_renders_problem_tag_fields_and_rules() -> None:
    # The prompt must instruct the model to emit maintenance problem tags so the
    # user's "put host X in maintenance but only for CPU" use case works.
    prompt = build_prompt("solo la CPU de web01", CTX)
    # Formats without raising (regression guard: every literal JSON brace in the
    # new fields/examples must be doubled for str.format).
    assert isinstance(prompt, str) and prompt
    # New output-contract fields are advertised in the OUTPUT FORMAT block.
    assert "problem_tags" in prompt
    assert "tags_evaltype" in prompt
    assert "maintenance_type" in prompt
    # The problem-tag extraction rule and the colloquial CPU mapping are present.
    assert "component=cpu" in prompt
    assert "SUPRESIÓN POR RECURSO/TAG" in prompt
    # The two tag concepts are kept distinct.
    assert "DESCUBRIR HOSTS POR TAG" in prompt
    # An example wires host + problem_tags together.
    assert '"problem_tags":[{"tag":"component","value":"cpu","operator":2}]' in prompt


def test_render_history_empty_returns_note() -> None:
    assert render_history(None) == _EMPTY_HISTORY
    assert render_history([]) == _EMPTY_HISTORY


def test_render_history_skips_blank_turns() -> None:
    history = [
        ConversationTurn(role="user", content="   "),
        ConversationTurn(role="assistant", content=""),
        ConversationTurn(role="user", content="real"),
    ]
    rendered = render_history(history)
    assert rendered == "Usuario: real"


def test_render_history_all_blank_returns_note() -> None:
    history = [ConversationTurn(role="user", content="  ")]
    assert render_history(history) == _EMPTY_HISTORY


def test_render_history_unknown_role_labeled_as_user() -> None:
    # Defensive: the intake normalizes roles, but the transcript never mislabels.
    history = [ConversationTurn(role="weird", content="hi")]
    assert render_history(history) == "Usuario: hi"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
