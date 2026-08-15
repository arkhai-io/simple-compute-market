"""Middleware configuration keeps the credits authority credential file-scoped."""

from __future__ import annotations

import pytest

from apicredits_middleware.config import GateConfig


def test_gate_config_reads_admin_key_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "credits-admin-key"
    secret_file.write_text("role-scoped-secret\n", encoding="utf-8")
    monkeypatch.setenv("APICREDITS_MIDDLEWARE_ADMIN_KEY_FILE", str(secret_file))
    monkeypatch.delenv("APICREDITS_MIDDLEWARE_ADMIN_KEY", raising=False)

    assert GateConfig.from_env().admin_key == "role-scoped-secret"


def test_gate_config_rejects_competing_admin_key_sources(monkeypatch, tmp_path):
    secret_file = tmp_path / "credits-admin-key"
    secret_file.write_text("file-secret", encoding="utf-8")
    monkeypatch.setenv("APICREDITS_MIDDLEWARE_ADMIN_KEY_FILE", str(secret_file))
    monkeypatch.setenv("APICREDITS_MIDDLEWARE_ADMIN_KEY", "inline-secret")

    with pytest.raises(ValueError, match="mutually exclusive"):
        GateConfig.from_env()


def test_gate_config_rejects_non_regular_admin_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv("APICREDITS_MIDDLEWARE_ADMIN_KEY_FILE", str(tmp_path))
    monkeypatch.delenv("APICREDITS_MIDDLEWARE_ADMIN_KEY", raising=False)

    with pytest.raises(ValueError, match="regular file"):
        GateConfig.from_env()
