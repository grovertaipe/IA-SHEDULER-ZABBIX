"""Unit tests for generic ticket extraction and derivation (Req 10.1-10.5).

Tickets have NO single mandatory format: every organization uses its own
nomenclature (``INC0012345``, ``JIRA-4521``, ``CHG-2024-001``, ``#88213``,
``REQ-99``, ``100-178306`` ...). The AI is the primary extractor; the regex in
``core.domain`` is a broad, conservative FALLBACK. These tests pin the fallback
behavior:

* varied nomenclatures extract to the BARE identifier (label/``#`` stripped);
* clock times (``22:00`` / ``22:00-23:00``) and plain numbers/words are NOT
  captured as tickets;
* an arbitrary identifier round-trips through the name/description helpers and
  is stripped from the body so it appears exactly once.
"""

from __future__ import annotations

import pytest

from core.domain import (
    UserInfo,
    extract_ticket,
    generate_maintenance_description,
    generate_maintenance_name,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Varied nomenclatures, with and without a leading label / '#'.
        ("ticket #INC0012345", "INC0012345"),
        ("con ticket JIRA-4521 mañana", "JIRA-4521"),
        ("ticket: JIRA-4521", "JIRA-4521"),
        ("CHG-2024-001 revisar", "CHG-2024-001"),
        ("#88213", "88213"),
        ("REQ-99 urgente", "REQ-99"),
        ("ticket 100-178306", "100-178306"),
        ("Mantenimiento 100-178306 para web01 los lunes", "100-178306"),
        # Label-anchored match wins even when a lowercase hostname is present.
        ("srv-web01 mañana 22:00-23:00 ticket 100-178306", "100-178306"),
    ],
)
def test_extract_ticket_accepts_any_nomenclature(text: str, expected: str) -> None:
    """The bare identifier is returned regardless of the ticket format."""
    assert extract_ticket(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # A lone clock time must never be mistaken for a ticket.
        "mantenimiento 22:00-23:00",
        "mantenimiento 22:00-23:00 para web01",
        "backup diario a las 02:00",
        # Plain short numbers / ranges are not tickets.
        "srv-tuxito de 10 a 12",
        # No ticket-shaped token at all.
        "solo texto sin numero",
        # Lowercase hostname alone (no label) is not captured as a ticket.
        "reinicio de srv-web01",
    ],
)
def test_extract_ticket_ignores_non_tickets(text: str) -> None:
    """Clock times, plain numbers, words and bare hostnames yield ``None``."""
    assert extract_ticket(text) is None


def test_extract_ticket_bare_upper_and_numeric_hyphen_shapes() -> None:
    """Unlabeled tokens extract only for unambiguous ticket shapes."""
    # Uppercase alphanumeric id (letters + digits) is ticket-shaped.
    assert extract_ticket("Programar INC0012345 hoy") == "INC0012345"
    # Purely numeric hyphenated id is ticket-shaped.
    assert extract_ticket("orden 200-8341 completada") == "200-8341"


def test_generate_maintenance_name_keeps_ticket_opaque() -> None:
    """The name leads with whatever identifier was extracted, unchanged."""
    assert generate_maintenance_name("INC0012345", "backup") == "INC0012345 - backup"
    assert generate_maintenance_name("JIRA-4521", "") == "JIRA-4521"
    assert generate_maintenance_name(None, "backup") == "backup"


def test_generate_maintenance_name_ticketless_group_regression() -> None:
    """No ticket + empty summary + one group -> resource-based name (regression).

    This is the exact create-time bug: the widget sends an empty ``raw_message``
    and there is no ticket, so the name must be rebuilt from the resolved group
    instead of collapsing to an empty string that Zabbix rejects.
    """
    name = generate_maintenance_name(
        None, "", group_names=["Virtual machines"]
    )
    assert name == "AI Maintenance: Grupo Virtual machines"


def test_generate_maintenance_name_ticketless_host_fallback() -> None:
    """No ticket + empty summary + one host -> non-empty name including the host."""
    name = generate_maintenance_name(None, "", host_names=["web01"])
    assert "web01" in name
    assert name.strip()


def test_generate_maintenance_name_ticketless_no_resources_default() -> None:
    """No ticket + empty summary + NO resources -> safe non-empty default."""
    assert generate_maintenance_name(None, "") == "AI Maintenance"
    assert generate_maintenance_name(None, "   ") == "AI Maintenance"


def test_generate_maintenance_name_ticketless_summary_unchanged() -> None:
    """No ticket + non-empty summary -> the trimmed summary (unchanged)."""
    assert generate_maintenance_name(None, "backup nocturno") == "backup nocturno"
    assert generate_maintenance_name(None, "  backup  ") == "backup"


def test_generate_maintenance_name_ticketed_cases_unchanged() -> None:
    """A ticket always leads the name regardless of resources (unchanged)."""
    assert generate_maintenance_name("INC1", "backup") == "INC1 - backup"
    assert generate_maintenance_name("INC1", "") == "INC1"
    # Resources are ignored when a ticket is present (behavior preserved).
    assert (
        generate_maintenance_name("INC1", "", host_names=["web01"]) == "INC1"
    )


def test_generate_maintenance_name_truncates_many_hosts_and_groups() -> None:
    """More than 3 hosts / 2 groups produce a "+N more" suffix and stay non-empty."""
    name = generate_maintenance_name(
        None,
        "",
        host_names=["h1", "h2", "h3", "h4", "h5"],
        group_names=["g1", "g2", "g3"],
    )
    assert "h1" in name and "h2" in name and "h3" in name
    assert "y 2 hosts más" in name  # 5 - 3
    assert "Grupo g1" in name and "Grupo g2" in name
    assert "y 1 grupos más" in name  # 3 - 2
    assert name.strip()


@pytest.mark.parametrize("ticket", [None, "", "INC0012345"])
@pytest.mark.parametrize("summary", ["", "   ", "reinicio del cluster"])
@pytest.mark.parametrize(
    ("host_names", "group_names"),
    [
        (None, None),
        ([], []),
        (["web01"], None),
        (None, ["Virtual machines"]),
        (["h1", "h2", "h3", "h4"], ["g1", "g2", "g3"]),
    ],
)
def test_generate_maintenance_name_never_empty(
    ticket: str | None,
    summary: str,
    host_names: list[str] | None,
    group_names: list[str] | None,
) -> None:
    """Invariant: the generated name is NEVER empty/whitespace for any input."""
    name = generate_maintenance_name(
        ticket, summary, host_names=host_names, group_names=group_names
    )
    assert name is not None
    assert name.strip() != ""


def test_generate_description_strips_arbitrary_ticket_from_body() -> None:
    """An arbitrary ticket appears once on its own line, removed from the body."""
    user = UserInfo(userid="42", username="ops", name="Op", surname="Er")
    desc = generate_maintenance_description(
        "JIRA-4521", user, "reinicio ticket JIRA-4521 del cluster"
    )
    lines = desc.splitlines()
    # Ticket line present exactly once and body no longer repeats it.
    assert lines[0] == "Ticket: JIRA-4521"
    assert desc.count("JIRA-4521") == 1
    assert "reinicio del cluster" in desc
