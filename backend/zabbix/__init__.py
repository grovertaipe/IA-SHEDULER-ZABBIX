"""Zabbix client (JSON-RPC, Zabbix 7.2). Concentrates network effects.

Exposes the :class:`~zabbix.client.ZabbixClient` boundary and its
:class:`~zabbix.client.ZabbixError`.
"""

from zabbix.client import ZabbixClient, ZabbixError

__all__ = ["ZabbixClient", "ZabbixError"]
