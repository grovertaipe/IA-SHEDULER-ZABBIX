"""Unit tests for application-version resolution (Req 16.1).

The authoritative version reported by ``/health`` is injected at image build
time via the ``APP_VERSION`` environment variable (Dockerfile build-arg fed by
CI from the git tag). :func:`config._resolve_version` reads that env var first,
falling back to the :data:`config.APP_VERSION` module constant and finally to
:data:`config.DEFAULT_VERSION`. These tests pin that precedence so a future
refactor cannot silently reintroduce a stale hard-coded version.
"""

from __future__ import annotations

import config


def test_resolve_version_prefers_env_override(monkeypatch) -> None:
    """A non-empty ``APP_VERSION`` env var wins over the module constant.

    This is the normal-operation path: the image bakes ``APP_VERSION`` so the
    real released version flows through to ``/health`` with no manual editing.
    """
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    assert config._resolve_version() == "9.9.9"


def test_resolve_version_falls_back_to_module_constant(monkeypatch) -> None:
    """With no env override, the module constant is the last-resort default."""
    monkeypatch.delenv("APP_VERSION", raising=False)
    assert config._resolve_version() == config.APP_VERSION


def test_resolve_version_ignores_blank_env(monkeypatch) -> None:
    """A blank/whitespace ``APP_VERSION`` is treated as unset (falls back)."""
    monkeypatch.setenv("APP_VERSION", "   ")
    assert config._resolve_version() == config.APP_VERSION


def test_from_env_reports_env_version(monkeypatch) -> None:
    """``AppConfig.from_env`` surfaces the resolved version on ``config.version``."""
    monkeypatch.setenv("APP_VERSION", "9.9.9")
    cfg = config.AppConfig.from_env()
    assert cfg.version == "9.9.9"


def test_module_constant_is_not_the_stale_default() -> None:
    """The constant is kept in step with the release, not the old ``2.0.0``."""
    assert config.APP_VERSION == "2.5.1"
    assert config.DEFAULT_VERSION == "unknown"
