"""Unit tests for outbound-TLS configuration parsing.

Covers the ``ZABBIX_VERIFY_TLS`` / ``ZABBIX_CA_BUNDLE`` settings added for the
outbound HTTPS connection to the Zabbix API. Verification is SECURE BY DEFAULT
(``zabbix_verify_tls`` defaults to True) and the boolean parser accepts common
truthy/falsey spellings robustly. The CA bundle defaults to ``None`` and is read
as an absolute path string when set.
"""

from __future__ import annotations

import pytest

import config


def test_verify_tls_defaults_to_true_when_absent(monkeypatch) -> None:
    """Absent ``ZABBIX_VERIFY_TLS`` -> secure default True."""
    monkeypatch.delenv("ZABBIX_VERIFY_TLS", raising=False)
    cfg = config.AppConfig.from_env()
    assert cfg.zabbix_verify_tls is True


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on", "  On  "])
def test_verify_tls_parses_truthy_variants(monkeypatch, raw: str) -> None:
    """Common truthy spellings (case-insensitive, trimmed) parse to True."""
    monkeypatch.setenv("ZABBIX_VERIFY_TLS", raw)
    assert config.AppConfig.from_env().zabbix_verify_tls is True


@pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", "  Off  "])
def test_verify_tls_parses_falsey_variants(monkeypatch, raw: str) -> None:
    """Common falsey spellings (case-insensitive, trimmed) parse to False."""
    monkeypatch.setenv("ZABBIX_VERIFY_TLS", raw)
    assert config.AppConfig.from_env().zabbix_verify_tls is False


def test_verify_tls_empty_string_falls_back_to_default(monkeypatch) -> None:
    """An empty value is treated as unset and falls back to True."""
    monkeypatch.setenv("ZABBIX_VERIFY_TLS", "   ")
    assert config.AppConfig.from_env().zabbix_verify_tls is True


def test_verify_tls_invalid_value_falls_back_to_default(monkeypatch) -> None:
    """An unrecognised value falls back to the secure default (True)."""
    monkeypatch.setenv("ZABBIX_VERIFY_TLS", "maybe")
    assert config.AppConfig.from_env().zabbix_verify_tls is True


def test_parse_bool_helper_variants(monkeypatch) -> None:
    """The ``_parse_bool`` helper honours tokens and falls back defensively."""
    monkeypatch.setenv("SOME_FLAG", "yes")
    assert config._parse_bool("SOME_FLAG", False) is True
    monkeypatch.setenv("SOME_FLAG", "no")
    assert config._parse_bool("SOME_FLAG", True) is False
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert config._parse_bool("SOME_FLAG", True) is True
    assert config._parse_bool("SOME_FLAG", False) is False


def test_ca_bundle_defaults_to_none(monkeypatch) -> None:
    """Absent ``ZABBIX_CA_BUNDLE`` -> None."""
    monkeypatch.delenv("ZABBIX_CA_BUNDLE", raising=False)
    assert config.AppConfig.from_env().zabbix_ca_bundle is None


def test_ca_bundle_is_read_when_set(monkeypatch) -> None:
    """A set ``ZABBIX_CA_BUNDLE`` is read (and stripped) as a path string."""
    monkeypatch.setenv("ZABBIX_CA_BUNDLE", "  /certs/zabbix-ca.pem  ")
    assert config.AppConfig.from_env().zabbix_ca_bundle == "/certs/zabbix-ca.pem"


def test_ca_bundle_blank_is_none(monkeypatch) -> None:
    """A blank ``ZABBIX_CA_BUNDLE`` collapses to None (falls through to bool)."""
    monkeypatch.setenv("ZABBIX_CA_BUNDLE", "   ")
    assert config.AppConfig.from_env().zabbix_ca_bundle is None
