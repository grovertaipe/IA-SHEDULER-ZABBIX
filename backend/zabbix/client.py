"""Cliente_Zabbix — JSON-RPC client for the Zabbix 7.2 API (Req 11, 14, 16, 32).

This module is a **boundary**: it concentrates all Zabbix network effects. It is
NOT pure (it performs HTTP I/O) and is therefore kept out of the pure core
(``core/recurrence.py``, ``core/domain.py``). The recurrence engine and domain
utilities never import it; higher-level services orchestrate it.

Authentication uses the Zabbix 7.2 bearer-token scheme: every request carries an
``Authorization: Bearer <token>`` header and a JSON-RPC 2.0 envelope
``{"jsonrpc": "2.0", "method": ..., "params": ..., "id": ...}`` (no ``auth``
field in the body, as required from Zabbix 6.4+/7.2).

Responsibilities (design §5 "Cliente_Zabbix"):

* :meth:`ZabbixClient._rpc` — low-level JSON-RPC call with structured error
  handling (timeouts, transport errors, malformed JSON, Zabbix ``error``
  payloads) surfaced as :class:`ZabbixError`.
* User validation (:meth:`user_exists`, Req 11.2).
* Host / group resolution: exact match (Req 14.1, 14.3), wildcard search
  (Req 14.2, 14.3) and tag-based host **discovery** (Req 14.4).
* Maintenance creation (:meth:`create_maintenance`, Req 4-8, 32) and listing.
* Lightweight connectivity check (:meth:`is_connected`, Req 16.2, 16.3) used by
  ``/health``.

**Critical distinction (Req 32).** ``trigger_tags`` (used by
:meth:`get_hosts_by_tags` to *discover which hosts* to include) are a completely
different concept from the maintenance **problem tags** (:class:`ProblemTag` +
``tags_evaltype``) that travel inside the ``maintenance.create`` payload to
*filter which problems are suppressed*. ``trigger_tags`` never reach
``maintenance.create``; problem tags do (fields ``tags`` and ``tags_evaltype``)
and are only valid with ``maintenance_type == 0``.

Secrets: the bearer token is never logged. Logging here is intentionally
minimal — the :class:`~observability.logging.SecureLogger` exists for structured
masking elsewhere, but this boundary simply avoids emitting the token at all.

Requirements: 11.2, 14.1, 14.2, 14.3, 14.4, 16.2, 16.3, 32.1, 32.2.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from core.domain import MaintenancePayload, ProblemTag, TimePeriod

logger = logging.getLogger(__name__)

#: Default network timeout (seconds) for every JSON-RPC request. Mirrors the
#: legacy monolith's 30 s ceiling; kept generous because ``maintenance.create``
#: and broad ``host.get`` queries can be slow on large Zabbix installs.
DEFAULT_TIMEOUT_SECONDS = 30

#: ``evaltype`` used for tag-based host discovery in ``host.get`` (And/Or). This
#: is the discovery evaltype (Req 14.4) and is unrelated to the maintenance
#: problem-tag ``tags_evaltype`` (Req 32.1).
_HOST_DISCOVERY_EVALTYPE = 0

#: Output fields requested for hosts across resolution/discovery calls.
_HOST_OUTPUT = ["hostid", "host", "name", "status"]

#: Output fields requested for host groups.
_GROUP_OUTPUT = ["groupid", "name"]


class ZabbixError(RuntimeError):
    """Raised when a Zabbix JSON-RPC call fails.

    Wraps three failure classes behind one clear exception so callers do not
    have to distinguish transport-level problems from API-level ``error``
    payloads:

    * connectivity / timeout / transport errors,
    * malformed (non-JSON) responses,
    * Zabbix ``error`` objects returned in an otherwise-200 response.

    The optional :attr:`data` carries the Zabbix ``error`` object (``code`` /
    ``message`` / ``data``) when available, for diagnostics. The token is never
    included.
    """

    def __init__(self, message: str, *, data: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.data = data


class ZabbixClient:
    """JSON-RPC client for the Zabbix 7.2 API (bearer-token auth).

    A thin, stateless wrapper around a single Zabbix endpoint. Construct it once
    per configured Zabbix instance and reuse it; a :class:`requests.Session` is
    kept for connection reuse. All methods raise :class:`ZabbixError` on failure
    rather than returning error dicts, so callers get a single, explicit failure
    path.

    TLS verification for the outbound HTTPS connection is controlled by the
    ``verify`` constructor argument (secure by default); see :meth:`__init__`.
    """

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
        session: requests.Session | None = None,
        verify: bool | str = True,
    ) -> None:
        """Create a client bound to ``url`` authenticated with ``token``.

        ``timeout`` bounds every request (seconds). ``session`` may be injected
        (mainly for tests); otherwise a fresh :class:`requests.Session` is used.
        The token is stored only to build the ``Authorization`` header and is
        never logged.

        ``verify`` controls TLS certificate verification for the outbound HTTPS
        connection to the Zabbix API and mirrors :mod:`requests`' ``verify``
        semantics (it is forwarded verbatim to every request):

        * ``True`` (default, SECURE) — verify against the system CA bundle.
        * ``False`` — do NOT verify (relaxes verification). Use ONLY for a
          self-signed Zabbix you cannot otherwise trust; prefer a CA bundle.
        * a ``str`` — filesystem path to a CA bundle (PEM) to verify the Zabbix
          certificate against a private/internal CA.

        When (and only when) ``verify is False`` the client suppresses urllib3's
        ``InsecureRequestWarning`` once at construction (so logs are not spammed)
        and emits a single WARNING that verification is disabled. The suppression
        is best-effort and never raises.
        """
        self.url = url
        self._token = token
        self._timeout = timeout
        self._session = session or requests.Session()
        self._verify = verify
        self._id = 0

        if self._verify is False:
            # Explicit opt-out only: silence the per-request InsecureRequestWarning
            # so disabling verification does not flood the logs. Guard the import
            # defensively — urllib3 is a requests dependency, but never crash the
            # client over a warning-suppression concern.
            try:
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            except Exception:  # noqa: BLE001
                pass
            # One-time heads-up (no token / URL credentials are ever logged).
            logger.warning(
                "Zabbix TLS verification is DISABLED (ZABBIX_VERIFY_TLS=false); "
                "use a CA bundle in production"
            )

    # ------------------------------------------------------------------ #
    # Low-level JSON-RPC transport                                        #
    # ------------------------------------------------------------------ #
    def _rpc(
        self, method: str, params: dict[str, Any], *, authenticated: bool = True
    ) -> Any:
        """Perform a single JSON-RPC 2.0 call and return the ``result`` payload.

        Builds the ``{jsonrpc, method, params, id}`` envelope, sends it with the
        bearer-token header and returns the value of the ``result`` field. Any
        failure — connection error, timeout, HTTP status error, non-JSON body or
        a Zabbix ``error`` object — is raised as :class:`ZabbixError` (Req 14,
        16). The token is never included in the message.
        """
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": self._id,
        }
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            # user.checkAuthentication / user.login MUST be called WITHOUT an
            # Authorization header; Zabbix 7.2 rejects them otherwise. Callers
            # verifying a session pass authenticated=False.
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = self._session.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
                verify=self._verify,
            )
            response.raise_for_status()
        except requests.exceptions.Timeout as exc:
            raise ZabbixError(f"Zabbix request timed out for method {method!r}") from exc
        except requests.exceptions.RequestException as exc:
            raise ZabbixError(
                f"Zabbix request failed for method {method!r}: {exc}"
            ) from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise ZabbixError(
                f"Invalid JSON in Zabbix response for method {method!r}"
            ) from exc

        if isinstance(body, dict) and "error" in body:
            error = body["error"]
            message = "Unknown Zabbix API error"
            if isinstance(error, dict):
                message = str(error.get("data") or error.get("message") or message)
            raise ZabbixError(
                f"Zabbix API error for method {method!r}: {message}",
                data=error if isinstance(error, dict) else None,
            )

        if not isinstance(body, dict) or "result" not in body:
            raise ZabbixError(
                f"Malformed Zabbix response for method {method!r}: missing 'result'"
            )

        return body["result"]

    # ------------------------------------------------------------------ #
    # User validation (Req 11.2)                                          #
    # ------------------------------------------------------------------ #
    def user_exists(self, userid: str) -> bool:
        """Return whether ``userid`` exists in Zabbix (Req 11.2).

        Uses ``user.get`` filtered by ``userids``. Returns ``True`` when at
        least one user is returned, ``False`` otherwise. Transport / API errors
        propagate as :class:`ZabbixError` so the auth layer can distinguish
        "user absent" from "Zabbix unreachable".
        """
        result = self._rpc(
            "user.get",
            {"output": ["userid", "username"], "userids": [userid]},
        )
        return bool(result)

    def check_authentication(self, sessionid: str) -> dict[str, Any] | None:
        """Verify a frontend session via ``user.checkAuthentication`` (Req 11).

        This is the REAL authentication mechanism (Zabbix 7.2): given the
        frontend **session id** (the token the logged-in Zabbix frontend holds),
        ``user.checkAuthentication`` returns the VERIFIED user object
        (``userid`` / ``username`` / ``name`` / ``surname`` / ``type`` / ...) on
        a valid session, or reports an error on an invalid/expired one. It is
        called with ``extend=false`` so merely checking a session does NOT
        prolong it.

        The caller must trust ONLY the identity returned here — never a
        client-supplied ``userid`` — since the session id is the credential the
        user actually possesses.

        Deliberate fail-closed behaviour: :meth:`_rpc` raises
        :class:`ZabbixError` for BOTH an invalid/expired session ("Session
        terminated..." / "Not authorized") AND a genuine transport failure
        (timeout, connection refused, malformed body). Cleanly distinguishing
        the two from the error text is brittle, and for AUTHENTICATION the safe
        outcome in every case is the same: treat the request as NOT
        authenticated. So this method swallows ANY :class:`ZabbixError` into
        ``None`` (do NOT re-raise), logging only that a session check failed and
        NEVER the session id (a secret, Req 18.4). This is the ONLY client
        method that swallows :class:`ZabbixError`; the maintenance/host calls
        keep propagating it so their callers can surface real Zabbix errors.

        Args:
            sessionid: The Zabbix frontend session token to verify. Never logged.

        Returns:
            The verified user object (dict) on a valid session, or ``None`` when
            the session is invalid/expired OR Zabbix could not be reached. In
            both ``None`` cases the auth layer fails closed (HTTP 401).
        """
        try:
            result = self._rpc(
                "user.checkAuthentication",
                {"sessionid": sessionid, "extend": False},
                authenticated=False,
            )
        except ZabbixError:
            # Invalid/expired session OR Zabbix unreachable — both fail closed.
            # Never log the session id (secret, Req 18.4); log only the failure.
            logger.warning(
                "Zabbix session check failed (invalid session or Zabbix "
                "unreachable); treating request as unauthenticated"
            )
            return None
        if isinstance(result, dict):
            return result
        return None

    # ------------------------------------------------------------------ #
    # Host resolution (Req 14.1, 14.2, 14.4)                              #
    # ------------------------------------------------------------------ #
    def get_hosts_exact(self, names: list[str]) -> list[dict[str, Any]]:
        """Return hosts matching ``names`` exactly (Req 14.1).

        Uses ``host.get`` with a ``filter`` on both ``host`` (technical name)
        and ``name`` (visible name) so either identifier resolves. Returns an
        empty list for empty input without a network call.
        """
        if not names:
            return []
        result = self._rpc(
            "host.get",
            {
                "output": _HOST_OUTPUT,
                "filter": {"host": names, "name": names},
                "searchByAny": True,
            },
        )
        return list(result)

    def search_hosts(self, term: str) -> list[dict[str, Any]]:
        """Return hosts whose name contains ``term`` (Req 14.2, wildcards).

        Uses ``host.get`` with ``search`` on ``host``/``name`` and
        ``searchWildcardsEnabled`` so ``*`` patterns work. Results are capped to
        keep responses bounded.
        """
        result = self._rpc(
            "host.get",
            {
                "output": _HOST_OUTPUT,
                "search": {"host": term, "name": term},
                "searchByAny": True,
                "searchWildcardsEnabled": True,
                "limit": 20,
            },
        )
        return list(result)

    def get_hosts_by_tags(self, tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Discover hosts matching the given ``trigger_tags`` (Req 14.4).

        These are **discovery** tags: they select *which hosts* to include in a
        maintenance, via ``host.get`` with ``evaltype``/``tags``. They are NOT
        the maintenance problem tags (:class:`ProblemTag`) and never travel to
        ``maintenance.create``. Returns an empty list for empty input without a
        network call. Each tag is a dict such as
        ``{"tag": "env", "value": "prod", "operator": 0}``.
        """
        if not tags:
            return []
        result = self._rpc(
            "host.get",
            {
                "output": _HOST_OUTPUT,
                "evaltype": _HOST_DISCOVERY_EVALTYPE,
                "tags": tags,
            },
        )
        return list(result)

    # ------------------------------------------------------------------ #
    # Group resolution (Req 14.3)                                         #
    # ------------------------------------------------------------------ #
    def get_groups_exact(self, names: list[str]) -> list[dict[str, Any]]:
        """Return host groups matching ``names`` exactly (Req 14.3).

        Uses ``hostgroup.get`` with a ``filter`` on ``name``. Returns an empty
        list for empty input without a network call.
        """
        if not names:
            return []
        result = self._rpc(
            "hostgroup.get",
            {"output": _GROUP_OUTPUT, "filter": {"name": names}},
        )
        return list(result)

    def search_groups(self, term: str) -> list[dict[str, Any]]:
        """Return host groups whose name contains ``term`` (Req 14.3, wildcards).

        Uses ``hostgroup.get`` with ``search`` on ``name`` and
        ``searchWildcardsEnabled``. Results are capped to keep responses bounded.
        """
        result = self._rpc(
            "hostgroup.get",
            {
                "output": _GROUP_OUTPUT,
                "search": {"name": term},
                "searchWildcardsEnabled": True,
                "limit": 20,
            },
        )
        return list(result)

    # ------------------------------------------------------------------ #
    # Maintenance creation & listing (Req 4-8, 32)                        #
    # ------------------------------------------------------------------ #
    def create_maintenance(
        self,
        payload: MaintenancePayload,
        *,
        host_ids: list[str] | None = None,
        group_ids: list[str] | None = None,
    ) -> str:
        """Create a maintenance window and return its ``maintenanceid`` (Req 4-8, 32).

        ``payload`` is the assembled :class:`~core.domain.MaintenancePayload`
        (name, description, active window, ``maintenance_type``, time periods and
        the problem ``tags`` / ``tags_evaltype``). ``host_ids`` and ``group_ids``
        are the already-resolved target hosts/groups (resolution — exact →
        wildcard → tag discovery, plus dedup — is the service layer's job).

        Problem tags (Req 32) are mapped to the ``maintenance.create`` ``tags``
        field as ``{"tag", "operator", "value"}`` and ``tags_evaltype`` is passed
        through. They are the suppression filter and are distinct from
        ``trigger_tags`` (host discovery), which never reach this call. The
        caller is responsible for the domain rule that tags require
        ``maintenance_type == 0`` (validated in the recurrence/service layer);
        this boundary faithfully forwards whatever the payload carries.

        At least one of ``host_ids`` / ``group_ids`` should be provided so the
        maintenance has a target. Raises :class:`ZabbixError` on failure.
        """
        params: dict[str, Any] = {
            "name": payload.name,
            "description": payload.description,
            "active_since": payload.active_since,
            "active_till": payload.active_till,
            "maintenance_type": payload.maintenance_type,
            "timeperiods": [_timeperiod_to_dict(tp) for tp in payload.timeperiods],
        }

        if host_ids:
            params["hosts"] = [{"hostid": hid} for hid in host_ids]
        if group_ids:
            params["groups"] = [{"groupid": gid} for gid in group_ids]

        # Problem tags (Req 32.2) travel to maintenance.create as the suppression
        # filter, together with their evaluation method (Req 32.1). Only emitted
        # when present so the default (no tags -> suppress everything, Req 32.4)
        # keeps the payload minimal and backward compatible.
        if payload.tags:
            params["tags"] = [_problem_tag_to_dict(tag) for tag in payload.tags]
            params["tags_evaltype"] = payload.tags_evaltype

        result = self._rpc("maintenance.create", params)
        maintenance_ids = _extract_ids(result, "maintenanceids")
        if not maintenance_ids:
            raise ZabbixError(
                "maintenance.create returned no maintenanceid"
            )
        return maintenance_ids[0]

    def list_maintenance(self) -> list[dict[str, Any]]:
        """Return the configured maintenance windows (newest first).

        Uses ``maintenance.get`` selecting the hosts, groups, tags and time
        periods consumed by the widget's list view, sorted by ``active_since``
        descending and capped at 50 entries. Timestamps are returned raw (epoch
        seconds); formatting for display is the HTTP layer's concern.
        """
        result = self._rpc(
            "maintenance.get",
            {
                "output": [
                    "maintenanceid",
                    "name",
                    "active_since",
                    "active_till",
                    "description",
                    "maintenance_type",
                    "tags_evaltype",
                ],
                "selectHosts": ["hostid", "host", "name"],
                "selectHostGroups": ["groupid", "name"],
                "selectTags": ["tag", "value", "operator"],
                "selectTimeperiods": [
                    "timeperiod_type",
                    "start_time",
                    "start_date",
                    "period",
                    "every",
                    "dayofweek",
                    "day",
                    "month",
                ],
                "sortfield": "active_since",
                "sortorder": "DESC",
                "limit": 50,
            },
        )
        return list(result)

    # ------------------------------------------------------------------ #
    # Connectivity check (Req 16.2, 16.3)                                 #
    # ------------------------------------------------------------------ #
    def is_connected(self) -> bool:
        """Return whether the Zabbix API is reachable and the token is valid.

        Lightweight probe used by ``/health`` (Req 16.2, 16.3): issues a bounded
        ``user.get`` (limit 1) and returns ``True`` on success. Any failure
        (transport, timeout, auth/API error) is swallowed and reported as
        ``False`` so the health endpoint can degrade gracefully instead of
        erroring.
        """
        try:
            self._rpc("user.get", {"output": ["userid"], "limit": 1})
            return True
        except ZabbixError:
            return False


# --------------------------------------------------------------------------- #
# Payload mapping helpers (pure)                                              #
# --------------------------------------------------------------------------- #
def _timeperiod_to_dict(tp: TimePeriod) -> dict[str, Any]:
    """Convert a :class:`~core.domain.TimePeriod` to the Zabbix dict shape.

    Only non-``None`` optional fields are included so the emitted period matches
    what Zabbix expects for each ``timeperiod_type`` (e.g. ``once`` carries
    ``start_date`` but not ``start_time``/``dayofweek``). ``timeperiod_type`` and
    ``period`` are always present.
    """
    period: dict[str, Any] = {
        "timeperiod_type": tp.timeperiod_type,
        "period": tp.period,
    }
    optional = {
        "start_time": tp.start_time,
        "start_date": tp.start_date,
        "every": tp.every,
        "dayofweek": tp.dayofweek,
        "day": tp.day,
        "month": tp.month,
    }
    for key, value in optional.items():
        if value is not None:
            period[key] = value
    return period


def _problem_tag_to_dict(tag: ProblemTag) -> dict[str, Any]:
    """Convert a :class:`~core.domain.ProblemTag` to the Zabbix ``tags`` shape.

    Emits ``{"tag", "operator", "value"}`` — the exact triple
    ``maintenance.create`` expects (Req 32.2). ``operator`` is one of ``{0, 2}``
    (Equals / Contains); enforcing that domain rule is the validation layer's
    job (Req 32.6), so this helper forwards the stored value faithfully.
    """
    return {
        "tag": tag.tag,
        "operator": int(tag.operator),
        "value": tag.value,
    }


def _extract_ids(result: Any, key: str) -> list[str]:
    """Extract the ID list (e.g. ``maintenanceids``) from a ``*.create`` result.

    Zabbix ``create`` methods return ``{"<key>": ["<id>", ...]}``. Returns the
    IDs as strings, or an empty list when the field is absent/empty so callers
    can raise a clear error.
    """
    if isinstance(result, dict):
        ids = result.get(key) or []
        return [str(i) for i in ids]
    return []
