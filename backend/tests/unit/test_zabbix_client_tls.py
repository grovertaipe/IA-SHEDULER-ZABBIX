"""Unit tests for outbound-TLS behaviour of :class:`~zabbix.client.ZabbixClient`.

A fake :class:`requests.Session` records the keyword arguments passed to
``.post`` so we can assert that the ``verify`` value handed to the client is
forwarded verbatim to every outbound request (mirroring :mod:`requests`'
semantics):

* ``verify=True`` (secure default) -> ``post(..., verify=True)``
* ``verify=False`` (explicit opt-out) -> ``post(..., verify=False)`` and the
  warning-suppression path runs without raising.
* ``verify="/certs/ca.pem"`` (CA bundle) -> ``post(..., verify="/certs/ca.pem")``.
"""

from __future__ import annotations

from typing import Any

from zabbix.client import ZabbixClient


class _FakeResponse:
    """Minimal stand-in for a ``requests.Response`` with a JSON-RPC result."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _RecordingSession:
    """Fake session that records the kwargs of the last ``.post`` call."""

    def __init__(self) -> None:
        self.last_kwargs: dict[str, Any] | None = None

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.last_kwargs = kwargs
        return _FakeResponse({"jsonrpc": "2.0", "result": [], "id": 1})


def _client(verify: bool | str) -> tuple[ZabbixClient, _RecordingSession]:
    session = _RecordingSession()
    client = ZabbixClient(
        "https://zabbix.invalid/api_jsonrpc.php",
        "token",
        session=session,  # type: ignore[arg-type]
        verify=verify,
    )
    return client, session


def test_default_verify_true_is_forwarded_to_post() -> None:
    """The secure default (True) is forwarded to the session ``.post`` call."""
    client, session = _client(True)
    client.is_connected()
    assert session.last_kwargs is not None
    assert session.last_kwargs["verify"] is True


def test_verify_false_is_forwarded_and_suppression_does_not_raise() -> None:
    """``verify=False`` is forwarded and the warning-suppression path is safe."""
    # Constructing with verify=False exercises the InsecureRequestWarning
    # suppression + one-time warning; it must not raise.
    client, session = _client(False)
    assert client._verify is False
    client.is_connected()
    assert session.last_kwargs is not None
    assert session.last_kwargs["verify"] is False


def test_ca_bundle_path_is_forwarded_to_post() -> None:
    """A CA bundle path string is forwarded verbatim to the session ``.post``."""
    bundle = "/certs/zabbix-ca.pem"
    client, session = _client(bundle)
    client.is_connected()
    assert session.last_kwargs is not None
    assert session.last_kwargs["verify"] == bundle


def test_verify_defaults_to_true_when_omitted() -> None:
    """Omitting ``verify`` keeps the secure default (True)."""
    session = _RecordingSession()
    client = ZabbixClient(
        "https://zabbix.invalid/api_jsonrpc.php",
        "token",
        session=session,  # type: ignore[arg-type]
    )
    client.is_connected()
    assert session.last_kwargs is not None
    assert session.last_kwargs["verify"] is True
