"""Gate configuration reads the deployment's prefix and keeps the authority credential file-scoped."""

from __future__ import annotations

import pytest

from arkhai_api_gate.config import GateConfig

PREFIX = "GATE_TEST_"


def test_gate_config_reads_only_the_deployments_prefix(monkeypatch):
    monkeypatch.setenv(f"{PREFIX}SERVICE_URL", "http://authority:8082/")
    monkeypatch.setenv("APICREDITS_MIDDLEWARE_SERVICE_URL", "http://elsewhere")

    config = GateConfig.from_env(PREFIX, authority_label="test-authority")

    assert config.service_url == "http://authority:8082"
    assert config.authority_label == "test-authority"


def test_gate_config_reads_admin_key_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "admin-key"
    secret_file.write_text("role-scoped-secret\n", encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}ADMIN_KEY_FILE", str(secret_file))
    monkeypatch.delenv(f"{PREFIX}ADMIN_KEY", raising=False)

    assert GateConfig.from_env(PREFIX, authority_label="test-authority").admin_key == "role-scoped-secret"


def test_gate_config_rejects_competing_admin_key_sources(monkeypatch, tmp_path):
    secret_file = tmp_path / "admin-key"
    secret_file.write_text("file-secret", encoding="utf-8")
    monkeypatch.setenv(f"{PREFIX}ADMIN_KEY_FILE", str(secret_file))
    monkeypatch.setenv(f"{PREFIX}ADMIN_KEY", "inline-secret")

    with pytest.raises(ValueError, match="mutually exclusive"):
        GateConfig.from_env(PREFIX, authority_label="test-authority")


def test_gate_config_rejects_non_regular_admin_key_file(monkeypatch, tmp_path):
    monkeypatch.setenv(f"{PREFIX}ADMIN_KEY_FILE", str(tmp_path))
    monkeypatch.delenv(f"{PREFIX}ADMIN_KEY", raising=False)

    with pytest.raises(ValueError, match="regular file"):
        GateConfig.from_env(PREFIX, authority_label="test-authority")
