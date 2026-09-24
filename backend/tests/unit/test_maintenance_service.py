"""Unit tests for the MaintenanceService orchestration (Task 10.2).

These tests use a mocked :class:`~zabbix.client.ZabbixClient` (methods
monkeypatched onto a real instance) so no network I/O happens. They verify the
orchestration contract:

* a valid weekly request resolves resources, builds the correct time period and
  calls ``create_maintenance`` with the assembled payload (Req 9.5, 11.4, 14.5);
* an invalid recurrence (:class:`RecurrenceError`) does NOT call
  ``create_maintenance`` (Req 15.7);
* problem tags with ``maintenance_type == 1`` are rejected BEFORE any Zabbix
  call, so ``create_maintenance`` is NOT called (Req 32.3, 15.7).
"""

from __future__ import annotations

from typing import Any

import pytest

from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    MaintenancePayload,
    ProblemTag,
    RecurrenceError,
    RecurrenceType,
    UserInfo,
)
from services.maintenance_service import MaintenanceService
from zabbix.client import ZabbixClient


class _RecordingClient(ZabbixClient):
    """A ZabbixClient whose network methods are replaced with in-memory fakes.

    Records whether ``create_maintenance`` was called and with what arguments so
    tests can assert the "do not create on invalid input" contract (Req 15.7).
    """

    def __init__(self, hosts: dict[str, list[dict[str, Any]]] | None = None) -> None:
        super().__init__("http://zabbix.invalid/api_jsonrpc.php", "token")
        self._hosts = hosts or {}
        self.create_called = False
        self.create_args: dict[str, Any] | None = None

    # -- resolution stubs -------------------------------------------------- #
    def get_hosts_exact(self, names: list[str]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for name in names:
            result.extend(self._hosts.get(name, []))
        return result

    def search_hosts(self, term: str) -> list[dict[str, Any]]:
        return []

    def get_hosts_by_tags(self, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return []

    def get_groups_exact(self, names: list[str]) -> list[dict[str, Any]]:
        return []

    def search_groups(self, term: str) -> list[dict[str, Any]]:
        return []

    # -- creation stub ----------------------------------------------------- #
    def create_maintenance(
        self,
        payload: MaintenancePayload,
        *,
        host_ids: list[str] | None = None,
        group_ids: list[str] | None = None,
    ) -> str:
        self.create_called = True
        self.create_args = {
            "payload": payload,
            "host_ids": host_ids,
            "group_ids": group_ids,
        }
        return "42"


def _user() -> UserInfo:
    return UserInfo(userid="1", username="ops", name="Op", surname="Erator")


def test_valid_weekly_request_builds_payload_and_creates() -> None:
    """A valid weekly request builds the right period and calls create (Req 9.5, 11.4)."""
    client = _RecordingClient(hosts={"web01": [{"hostid": "100", "host": "web01"}]})
    service = MaintenanceService(client)

    request = ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        ticket="100-178306",
        raw_message="Mantenimiento 100-178306 para web01 los lunes",
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.WEEKLY,
            days={"monday"},
            start_hour=2,
            duration_hours=3,
        ),
    )

    confirmation = service.create(request, _user())

    assert client.create_called is True
    assert confirmation.maintenanceid == "42"
    assert client.create_args is not None
    assert client.create_args["host_ids"] == ["100"]

    payload = client.create_args["payload"]
    # weekly -> timeperiod_type 3, dayofweek monday=1, start_time 2h, period 3h
    tp = payload.timeperiods[0]
    assert tp.timeperiod_type == 3
    assert tp.dayofweek == 1
    assert tp.start_time == 2 * 3600
    assert tp.period == 3 * 3600
    # user data + ticket included (Req 11.4, 10.4)
    assert "100-178306" in payload.name
    assert "ops" in payload.description
    assert confirmation.user.username == "ops"


def test_invalid_recurrence_does_not_create() -> None:
    """A RecurrenceError aborts before any Zabbix call (Req 15.7)."""
    client = _RecordingClient(hosts={"web01": [{"hostid": "100", "host": "web01"}]})
    service = MaintenanceService(client)

    # weekly without start_hour/duration -> build_timeperiod raises RecurrenceError
    request = ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        raw_message="Mantenimiento web01 semanal",
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.WEEKLY,
            days={"monday"},
        ),
    )

    with pytest.raises(RecurrenceError):
        service.create(request, _user())
    assert client.create_called is False


def test_problem_tags_with_maintenance_type_1_does_not_create() -> None:
    """Problem tags with maintenance_type=1 are rejected before create (Req 32.3, 15.7)."""
    client = _RecordingClient(hosts={"web01": [{"hostid": "100", "host": "web01"}]})
    service = MaintenanceService(client)

    request = ExtractedRequest(
        intent="maintenance_request",
        hosts=["web01"],
        maintenance_type=1,
        problem_tags=[ProblemTag(tag="env", value="prod")],
        raw_message="Mantenimiento web01 lunes sin recoleccion filtrando env=prod",
        recurrence=ExtractedRecurrence(
            recurrence_type=RecurrenceType.WEEKLY,
            days={"monday"},
            start_hour=2,
            duration_hours=3,
        ),
    )

    with pytest.raises(RecurrenceError):
        service.create(request, _user())
    assert client.create_called is False


def test_resolution_dedups_hosts_and_reports_missing() -> None:
    """Resolution dedups by hostid (Req 14.5) and partitions missing (Req 14.6, 14.7)."""
    client = _RecordingClient(
        hosts={
            "web01": [
                {"hostid": "100", "host": "web01"},
                {"hostid": "100", "host": "web01"},  # duplicate id
            ]
        }
    )
    service = MaintenanceService(client)

    resolved = service.resolve_resources(
        hosts=["web01", "missing-host"], groups=[], trigger_tags=None
    )

    assert resolved.host_ids == ["100"]  # deduped
    assert resolved.missing_hosts == ["missing-host"]
    assert resolved.is_empty is False
