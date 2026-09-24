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
