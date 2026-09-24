"""Servicio_Mantenimiento — maintenance creation orchestration (Req 9-14, 32).

This is an **orchestration layer**: it coordinates the pure core
(:mod:`core.recurrence`, :mod:`core.domain`) with the Zabbix boundary
(:class:`zabbix.client.ZabbixClient`). It holds no bitmask arithmetic and no
network transport of its own — pure decisions live in the core, network effects
live in the client, and this service wires them together in the right order
(design §5, sequence diagram "crear(maintenance_request)").

Responsibilities:

* **Resolve** the requested hosts and groups against Zabbix following the
  exact → flexible → tag-discovery order, deduplicate hosts by ``hostid`` and
  partition requested vs found so missing resources are reported (Req 14.1-14.7).
* **Build** the Zabbix time period from the normalized recurrence via
  :func:`core.recurrence.build_timeperiod`; on :class:`RecurrenceError` the
  maintenance is NOT created in Zabbix (Req 9.5, 15.7).
* **Validate** the maintenance problem tags with
  :func:`core.recurrence.validate_problem_tags` BEFORE creating; on failure the
  maintenance is NOT created (Req 32.3, 32.4, 15.7).
* **Assemble** the :class:`core.domain.MaintenancePayload` (name, description
  with the requester's user data, active window, ``maintenance_type``, problem
  ``tags`` and ``tags_evaltype``) and call ``create_maintenance`` with the
  resolved host/group ids (Req 11.4, 32).
* **Return** a confirmation with the name, description, user info, resolved
  resources, missing resources and the ``maintenanceid`` (Req 11.4).

**Critical distinction (Req 32).** ``trigger_tags`` are used only for the host
**discovery** phase (Req 14.4) and never travel to ``maintenance.create``. The
maintenance **problem tags** (:class:`~core.domain.ProblemTag` + ``tags_evaltype``)
are the suppression filter validated here and forwarded to Zabbix, and are only
valid with ``maintenance_type == 0``.

* **Localize** the human-readable confirmation ``message`` via the catalog
  (:func:`i18n.messages.get_message`) after resolving the effective ``Locale``
  once per request with :func:`i18n.locale.resolve_locale` against
  ``cfg.supported_locales`` / ``cfg.default_locale`` (design §7, Req 21.1,
  21.4). The structured confirmation fields remain language-agnostic.

Requirements: 9.5, 10.3, 11.4, 14.5, 14.6, 14.7, 15.7, 21.1, 21.4, 32.3, 32.4.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.domain import (
    ExtractedRecurrence,
    ExtractedRequest,
    MaintenancePayload,
    RecurrenceConfig,
    RecurrenceType,
    TimePeriod,
    UserInfo,
    extract_ticket,
    generate_maintenance_description,
    generate_maintenance_name,
)
from core.recurrence import build_timeperiod, floor_to_minute, validate_problem_tags
from i18n.locale import DEFAULT_LOCALE, resolve_locale
from i18n.messages import get_message
from zabbix.client import ZabbixClient

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a hard runtime import
    from config import AppConfig

#: Catalog keys for the localized confirmation text (Task 18.3, Req 21.4). The
#: confirmation summary is assembled from these so the human-readable message is
#: fully localized while the structured fields stay language-agnostic.
MSG_MAINTENANCE_CREATED = "confirmation.maintenance_created"
MSG_HOSTS_NOT_FOUND = "confirmation.hosts_not_found"

#: Default active-window length for recurring maintenances (one year) when the
#: request does not carry explicit ``start_ts`` / ``end_ts`` bounds. ``once``
#: maintenances always derive the window from their own timestamps (Req 4.4);
#: recurring types repeat within an enclosing active window, so a bounded
#: default keeps the maintenance from being open-ended.
_DEFAULT_RECURRING_WINDOW_SECONDS = 365 * 24 * 60 * 60


# --------------------------------------------------------------------------- #
# Result structures (orchestration output, Req 14.6/14.7, 11.4)               #
# --------------------------------------------------------------------------- #
@dataclass
class ResolvedResources:
    """Outcome of resolving requested hosts/groups against Zabbix (Req 14.5-14.7).

    ``host_ids`` are deduplicated by ``hostid`` (Req 14.5). The ``missing_*``
    lists are exactly the requested names that could not be resolved, so
    ``requested == found ∪ missing`` and ``found ∩ missing == ∅`` hold
    (Property 21, Req 14.6, 14.7).
    """

    hosts: list[dict[str, Any]] = field(default_factory=list)
    groups: list[dict[str, Any]] = field(default_factory=list)
    host_ids: list[str] = field(default_factory=list)
    group_ids: list[str] = field(default_factory=list)
    missing_hosts: list[str] = field(default_factory=list)
    missing_groups: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """Return whether no host and no group was resolved (Req 14.6).

        The HTTP layer uses this to return a clarification response asking the
        user to verify the names when nothing matched.
        """
        return not self.host_ids and not self.group_ids


@dataclass
class MaintenanceConfirmation:
    """Confirmation returned after a successful ``maintenance.create`` (Req 11.4).

    Carries everything the widget needs to confirm the created maintenance: the
    generated name and description, the requester's user data, the resolved and
    missing resources and the Zabbix ``maintenanceid``.

    ``message`` is an **additive**, human-readable and **localized** summary of
    the created maintenance produced via :func:`i18n.messages.get_message`
    (design §7, Req 21.1, 21.4). It does not replace or rename any structured
    field; ``locale`` records the effective locale used to render it. Both carry
    safe defaults so existing callers/contracts that ignore them are unaffected.
    """

    maintenanceid: str
    name: str
    description: str
    user: UserInfo
    resolved: ResolvedResources
    message: str = ""
    locale: str = DEFAULT_LOCALE


class MaintenanceService:
    """Orchestrates maintenance creation around the pure core and Zabbix client.

    Construct once with a configured :class:`~zabbix.client.ZabbixClient` and
    reuse it. The service performs no HTTP itself; it delegates every network
    effect to the injected client, which makes it trivially testable with a
    mocked client (monkeypatched methods).
    """

    def __init__(
        self,
        client: ZabbixClient,
        config: AppConfig | None = None,
    ) -> None:
        """Create the service bound to a Zabbix ``client`` boundary.

        Args:
            client: the Zabbix boundary used for resolution and creation.
            config: the application configuration. When provided, its
                ``supported_locales`` / ``default_locale`` drive per-request
                locale resolution for the confirmation text (design §7, Req 21).
                When ``None`` the service falls back to the product baseline
                (``es`` only), keeping the class constructible without a config.
        """
        self._client = client
        self._config = config

    def _resolve_locale(self, requested: str | None) -> str:
        """Resolve the effective locale once per request (design §7, Req 21).

        Applies :func:`i18n.locale.resolve_locale` against the configured
        ``supported_locales`` / ``default_locale`` when a config is present;
        otherwise resolves against the guaranteed baseline (``es``). Unknown or
        unsupported values silently degrade to the default (Req 21.5, 21.6).
        """
        if self._config is not None:
            return resolve_locale(
                requested,
                self._config.supported_locales,
                self._config.default_locale,
            )
        return resolve_locale(requested, [DEFAULT_LOCALE], DEFAULT_LOCALE)

    # ------------------------------------------------------------------ #
    # Public orchestration entry point                                    #
    # ------------------------------------------------------------------ #
    def create(
        self,
        request: ExtractedRequest,
        user: UserInfo,
        *,
        locale: str | None = None,
    ) -> MaintenanceConfirmation:
        """Create a maintenance from an extracted request (Req 9-14, 32).

        Orchestration order (design sequence diagram):

        1. Build the :class:`~core.domain.TimePeriod` from the recurrence via
           :func:`build_timeperiod`; a :class:`RecurrenceError` aborts before
           any Zabbix call (Req 9.5, 15.7).
        2. Validate the problem tags with :func:`validate_problem_tags` BEFORE
           creating; a failure aborts before any Zabbix call (Req 32.3, 32.4,
           15.7).
        3. Resolve hosts/groups (exact → flexible → tag discovery, dedup by id,
           partition found/missing) (Req 14.1-14.7).
        4. Assemble the :class:`~core.domain.MaintenancePayload` (name,
           description with user data, active window, ``maintenance_type``,
           problem ``tags`` / ``tags_evaltype``) (Req 11.4, 32).
        5. Call ``create_maintenance`` with the resolved ids and return the
           confirmation (Req 11.4).

        Args:
            request: the extracted request (recurrence + resources + tags).
            user: the authenticated requester (included in the description and
                confirmation for traceability, Req 11.4).
            locale: the requested locale for the confirmation ``message``; it is
                resolved once against the configured supported/default locales
                (design §7, Req 21.5, 21.6). ``None``/unsupported degrades to
                the default (``es``).

        Returns:
            A :class:`MaintenanceConfirmation` with the created maintenance's id,
            metadata and a localized human-readable ``message`` (Req 21.1, 21.4).

        Raises:
            RecurrenceError: if the recurrence or the problem tags are invalid;
                the maintenance is NOT created in Zabbix (Req 9.5, 15.7).
            ValueError: if no recurrence is present or no host/group resolves.
            ZabbixError: if the Zabbix ``maintenance.create`` call fails.
        """
        # Resolve the effective locale ONCE per request (design §7, Req 21).
        effective_locale = self._resolve_locale(locale)

        if request.recurrence is None:
            raise ValueError(
                "La solicitud no contiene una configuración de recurrencia."
            )

        # 1. Pure recurrence build FIRST — do not touch Zabbix if it fails
        #    (Req 9.5, 15.7). RecurrenceError propagates untouched.
        cfg = _recurrence_config_from(request.recurrence)
        timeperiod = build_timeperiod(cfg)

        # 2. Validate problem tags BEFORE creating (Req 32.3, 32.4, 15.7). A
        #    failure raises RecurrenceError and no maintenance is created.
        validate_problem_tags(
            request.problem_tags,
            request.tags_evaltype,
            request.maintenance_type,
        )

        # 3. Resolve hosts/groups (exact -> flexible -> tag discovery, dedup,
        #    partition) (Req 14.1-14.7).
        resolved = self.resolve_resources(
            hosts=request.hosts,
            groups=request.groups,
            trigger_tags=request.trigger_tags,
        )
        if resolved.is_empty:
            raise ValueError(
                "No se encontró ningún host ni grupo válido; verifique los nombres."
            )

        # 4. Assemble the payload (name, description with user data, active
        #    window, maintenance_type, problem tags) (Req 11.4, 32).
        active_since, active_till = _active_window(request.recurrence, timeperiod)
        ticket = request.ticket or extract_ticket(request.raw_message)
        name = generate_maintenance_name(ticket, request.raw_message)
        description = generate_maintenance_description(ticket, user, request.raw_message)

        payload = MaintenancePayload(
            name=name,
            description=description,
            active_since=active_since,
            active_till=active_till,
            maintenance_type=request.maintenance_type,
            timeperiods=[timeperiod],
            tags=list(request.problem_tags),
            tags_evaltype=request.tags_evaltype,
        )

        # 5. Create in Zabbix and return the confirmation (Req 11.4).
        maintenanceid = self._client.create_maintenance(
            payload,
            host_ids=resolved.host_ids,
            group_ids=resolved.group_ids,
        )

        # Build the localized, human-readable confirmation message via the
        # catalog (design §7, Req 21.1, 21.4). Structured fields are unchanged.
        message = _build_confirmation_message(
            name, maintenanceid, resolved, effective_locale
        )

        return MaintenanceConfirmation(
            maintenanceid=maintenanceid,
            name=name,
            description=description,
            user=user,
            resolved=resolved,
            message=message,
            locale=effective_locale,
        )

    # ------------------------------------------------------------------ #
    # Host / group resolution (Req 14.1-14.7)                             #
    # ------------------------------------------------------------------ #
    def resolve_resources(
        self,
        *,
        hosts: list[str],
        groups: list[str],
        trigger_tags: list[dict[str, Any]] | None = None,
    ) -> ResolvedResources:
        """Resolve requested hosts/groups against Zabbix (Req 14.1-14.7).

        Hosts: exact match first (:meth:`ZabbixClient.get_hosts_exact`); each
        name not matched exactly is retried with a flexible search
        (:meth:`ZabbixClient.search_hosts`) (Req 14.1, 14.2). When
        ``trigger_tags`` are present, tag-based host **discovery**
        (:meth:`ZabbixClient.get_hosts_by_tags`) contributes additional hosts
        (Req 14.4); those discovered hosts never count against the requested
        names and never travel to ``maintenance.create``.

        Groups: exact match first (:meth:`ZabbixClient.get_groups_exact`); each
        name not matched exactly is retried with a flexible search
        (:meth:`ZabbixClient.search_groups`) (Req 14.3).

        All hosts are deduplicated by ``hostid`` (Req 14.5) and groups by
        ``groupid``. The requested names are partitioned into found vs missing
        so ``requested == found ∪ missing`` and ``found ∩ missing == ∅`` hold
        (Property 21, Req 14.6, 14.7).
        """
        found_hosts, missing_hosts = self._resolve_hosts(hosts)
        found_groups, missing_groups = self._resolve_groups(groups)

        # Tag-based host discovery contributes extra hosts (Req 14.4). These are
        # additive and are merged into the deduplicated host set below.
        discovered_hosts: list[dict[str, Any]] = []
        if trigger_tags:
            discovered_hosts = list(self._client.get_hosts_by_tags(trigger_tags))

        deduped_hosts = _dedup_by_key(found_hosts + discovered_hosts, "hostid")
        deduped_groups = _dedup_by_key(found_groups, "groupid")

        return ResolvedResources(
            hosts=deduped_hosts,
            groups=deduped_groups,
            host_ids=[str(h["hostid"]) for h in deduped_hosts],
            group_ids=[str(g["groupid"]) for g in deduped_groups],
            missing_hosts=missing_hosts,
            missing_groups=missing_groups,
        )

    def _resolve_hosts(
        self, names: list[str]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Resolve host ``names`` exact→flexible, returning (found, missing).

        Exact matches are collected first; every requested name still unmatched
        is retried with a wildcard search. A requested name is "found" when
        either step resolves at least one host for it; otherwise it is reported
        missing (Req 14.1, 14.2, 14.7).
        """
        if not names:
            return [], []

        found: list[dict[str, Any]] = []
        matched_names: set[str] = set()

        exact = self._client.get_hosts_exact(names)
        for host in exact:
            found.append(host)
            matched_names |= _matching_requested_names(host, names)

        for name in names:
            if name in matched_names:
                continue
            results = self._client.search_hosts(name)
            if results:
                found.extend(results)
                matched_names.add(name)

        missing = [name for name in names if name not in matched_names]
        return found, missing

    def _resolve_groups(
        self, names: list[str]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Resolve group ``names`` exact→flexible, returning (found, missing).

        Same strategy as :meth:`_resolve_hosts` but against the host-group
        endpoints; a requested name resolved by neither exact nor flexible
        search is reported missing (Req 14.3, 14.7).
        """
        if not names:
            return [], []

        found: list[dict[str, Any]] = []
        matched_names: set[str] = set()

        exact = self._client.get_groups_exact(names)
        for group in exact:
            found.append(group)
            matched_names |= _matching_requested_group_names(group, names)

        for name in names:
            if name in matched_names:
                continue
            results = self._client.search_groups(name)
            if results:
                found.extend(results)
                matched_names.add(name)

        missing = [name for name in names if name not in matched_names]
        return found, missing


# --------------------------------------------------------------------------- #
# Pure helpers (no I/O)                                                        #
# --------------------------------------------------------------------------- #
def _build_confirmation_message(
    name: str,
    maintenanceid: str,
    resolved: ResolvedResources,
    locale: str,
) -> str:
    """Assemble the localized confirmation message (design §7, Req 21.1, 21.4).

    Pure, deterministic string assembly delegated entirely to the catalog via
    :func:`i18n.messages.get_message`; it never hard-codes user-facing prose.
    The base sentence is ``confirmation.maintenance_created`` (with the created
    ``name`` and ``maintenance_id``). When some requested resources could not be
    resolved, ``confirmation.hosts_not_found`` is appended so the user learns
    which names matched and which did not (Req 14.6, 14.7). All templates are
    resolved in ``locale`` with fallback to the default catalog.
    """
    missing = resolved.missing_hosts + resolved.missing_groups
    if missing:
        found = [str(item.get("name") or item.get("host")) for item in resolved.hosts]
        found += [str(g.get("name")) for g in resolved.groups]
        summary = get_message(
            MSG_HOSTS_NOT_FOUND,
            locale,
            missing=", ".join(missing),
            found=", ".join(found) if found else "-",
        )
    else:
        summary = ""

    return get_message(
        MSG_MAINTENANCE_CREATED,
        locale,
        name=name,
        maintenance_id=maintenanceid,
        summary=summary,
    ).strip()


def _recurrence_config_from(rec: ExtractedRecurrence) -> RecurrenceConfig:
    """Map an :class:`ExtractedRecurrence` to a :class:`RecurrenceConfig`.

    A direct field copy: the AI extraction carries no bitmasks (Req 3.2), so the
    config is handed to :func:`build_timeperiod` which computes them. Pure and
    deterministic.
    """
    return RecurrenceConfig(
        recurrence_type=rec.recurrence_type,
        days=set(rec.days),
        months=set(rec.months),
        occurrences=set(rec.occurrences),
        day_of_month=rec.day_of_month,
        start_hour=rec.start_hour,
        duration_hours=rec.duration_hours,
        every=rec.every,
        start_date=rec.start_date,
        start_ts=rec.start_ts,
        end_ts=rec.end_ts,
    )


def _active_window(rec: ExtractedRecurrence, timeperiod: TimePeriod) -> tuple[int, int]:
    """Compute the maintenance active window ``(active_since, active_till)``.

    For ``once`` the window matches the period exactly: ``active_since`` is the
    period's ``start_date`` and ``active_till`` is ``start_date + period``
    (Req 4.4) — both already floored to whole minutes by the recurrence engine
    (Req 31.3). For recurring types the individual occurrences repeat inside an
    enclosing window: it starts at the request's ``start_ts`` when provided
    (else "now") and lasts until ``end_ts`` when provided (else one year later),
    floored to whole minutes for Zabbix consistency (Req 31.3).
    """
    if rec.recurrence_type == RecurrenceType.ONCE:
        start = timeperiod.start_date or 0
        return start, start + timeperiod.period

    start = rec.start_ts if rec.start_ts is not None else int(time.time())
    if rec.end_ts is not None:
        end = rec.end_ts
    else:
        end = start + _DEFAULT_RECURRING_WINDOW_SECONDS
    return floor_to_minute(start), floor_to_minute(end)


def _dedup_by_key(items: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Return ``items`` deduplicated by ``item[key]``, preserving first order.

    Used to deduplicate hosts by ``hostid`` (Req 14.5) and groups by
    ``groupid``. The resulting id set equals the input id set with no loss and
    no duplication (Property 20). Pure and deterministic.
    """
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        identifier = str(item.get(key))
        if identifier in seen:
            continue
        seen.add(identifier)
        result.append(item)
    return result


def _matching_requested_names(host: dict[str, Any], names: list[str]) -> set[str]:
    """Return which requested ``names`` a resolved ``host`` satisfies.

    A host matches a requested name when the name equals its technical ``host``
    or its visible ``name`` field, so exact resolution can mark the right
    requested names as found (Req 14.1, 14.7).
    """
    identifiers = {host.get("host"), host.get("name")}
    return {name for name in names if name in identifiers}


def _matching_requested_group_names(
    group: dict[str, Any], names: list[str]
) -> set[str]:
    """Return which requested ``names`` a resolved ``group`` satisfies.

    A group matches a requested name when the name equals its ``name`` field
    (Req 14.3, 14.7).
    """
    return {name for name in names if name == group.get("name")}
