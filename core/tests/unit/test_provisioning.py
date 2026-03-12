"""Unit tests for provisioning utility functions."""

import pytest
from unittest.mock import patch

from service.clients.ansible_provisioning import (
    _extract_external_port,
    _extract_tenant_user,
)


# ---------------------------------------------------------------------------
# _extract_external_port
# ---------------------------------------------------------------------------

class TestExtractExternalPort:
    def test_json_key(self):
        output = 'ok: {"external_ssh_port": "7021"}'
        assert _extract_external_port(output) == "7021"

    def test_ssh_command_with_host(self):
        output = "ssh -p 7022 alice@vm1.example.com"
        assert _extract_external_port(output, vm_host="vm1.example.com") == "7022"

    def test_generic_fallback(self):
        output = "connect via: ssh -p 9000 user@host"
        assert _extract_external_port(output) == "9000"

    def test_returns_none_when_absent(self):
        assert _extract_external_port("no port here") is None


# ---------------------------------------------------------------------------
# _extract_tenant_user
# ---------------------------------------------------------------------------

class TestExtractTenantUser:
    def test_json_key(self):
        output = '{"tenant_user": "bob"}'
        assert _extract_tenant_user(output) == "bob"

    def test_ssh_command(self):
        output = "ssh -p 7021 alice@vm1"
        assert _extract_tenant_user(output, vm_host="vm1") == "alice"

    def test_returns_none_when_absent(self):
        assert _extract_tenant_user("no user here") is None


# ---------------------------------------------------------------------------
# FRP config fields
# ---------------------------------------------------------------------------

class TestFrpConfig:
    def test_frp_fields_loaded_from_env(self, monkeypatch):
        monkeypatch.setenv("FRP_SERVER_ADDR", "10.1.2.3")
        monkeypatch.setenv("FRP_DOMAIN", "frp.example.com")
        monkeypatch.setenv("FRP_DASHBOARD_PASSWORD", "hunter2")

        from core.agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr == "10.1.2.3"
        assert cfg.frp_domain == "frp.example.com"
        assert cfg.frp_dashboard_password == "hunter2"

    def test_frp_fields_none_when_unset(self, monkeypatch):
        for key in ("FRP_SERVER_ADDR", "FRP_DOMAIN", "FRP_DASHBOARD_PASSWORD",
                    "frp_server_addr", "frp_domain", "frp_dashboard_password"):
            monkeypatch.delenv(key, raising=False)

        from core.agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr is None
        assert cfg.frp_domain is None
        assert cfg.frp_dashboard_password is None

    def test_frp_fields_lowercase_fallback(self, monkeypatch):
        monkeypatch.delenv("FRP_SERVER_ADDR", raising=False)
        monkeypatch.setenv("frp_server_addr", "10.9.8.7")

        from core.agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr == "10.9.8.7"
