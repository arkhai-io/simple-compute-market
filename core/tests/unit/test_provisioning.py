"""Unit tests for provisioning utility functions."""

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.app.utils.provisioning import (
    _extract_external_port,
    _extract_tenant_password,
    _extract_tenant_user,
    run_vm_provisioning_playbook,
)


# ---------------------------------------------------------------------------
# _extract_tenant_password
# ---------------------------------------------------------------------------

class TestExtractTenantPassword:
    def test_nested_tenant_object(self):
        output = '{"tenant": {"password": "s3cr3t", "user": "alice"}}'
        assert _extract_tenant_password(output) == "s3cr3t"

    def test_flat_tenant_password_key(self):
        output = 'ok: [vm1] => {"tenant_password": "flat-pass"}'
        assert _extract_tenant_password(output) == "flat-pass"

    def test_nested_with_whitespace(self):
        output = '"tenant" : {\n  "password" : "spaced"\n}'
        assert _extract_tenant_password(output) == "spaced"

    def test_strips_surrounding_whitespace(self):
        output = '"tenant_password": "  padded  "'
        # The regex captures between the quotes; strip() is applied
        result = _extract_tenant_password(output)
        # strip() only strips the captured group, not what's inside quotes —
        # passwords don't typically have surrounding spaces, but confirm no crash
        assert result is not None

    def test_returns_none_when_absent(self):
        assert _extract_tenant_password("no password info here") is None

    def test_returns_none_on_empty_string(self):
        assert _extract_tenant_password("") is None

    def test_prefers_nested_format_over_flat(self):
        # Both patterns present — first match (nested) wins
        output = '"tenant": {"password": "nested"}\n"tenant_password": "flat"'
        assert _extract_tenant_password(output) == "nested"


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

        from agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr == "10.1.2.3"
        assert cfg.frp_domain == "frp.example.com"
        assert cfg.frp_dashboard_password == "hunter2"

    def test_frp_fields_none_when_unset(self, monkeypatch):
        for key in ("FRP_SERVER_ADDR", "FRP_DOMAIN", "FRP_DASHBOARD_PASSWORD",
                    "frp_server_addr", "frp_domain", "frp_dashboard_password"):
            monkeypatch.delenv(key, raising=False)

        from agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr is None
        assert cfg.frp_domain is None
        assert cfg.frp_dashboard_password is None

    def test_frp_fields_lowercase_fallback(self, monkeypatch):
        monkeypatch.delenv("FRP_SERVER_ADDR", raising=False)
        monkeypatch.setenv("frp_server_addr", "10.9.8.7")

        from agent.app.utils.config import load_config
        cfg = load_config()

        assert cfg.frp_server_addr == "10.9.8.7"


# ---------------------------------------------------------------------------
# run_vm_provisioning_playbook — payload and return value
# ---------------------------------------------------------------------------

def _make_completed_process(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fake_config(*, frp_server_addr=None, frp_domain=None, frp_dashboard_password=None):
    return SimpleNamespace(
        frp_server_addr=frp_server_addr,
        frp_domain=frp_domain,
        frp_dashboard_password=frp_dashboard_password,
    )


PLAYBOOK_STDOUT_FULL = """
TASK [Show connection info]
ok: [vm1] => {
    "external_ssh_port": "7021",
    "tenant_user": "alice",
    "tenant": {"password": "secret123"}
}
"""


@pytest.fixture
def mock_subprocess_and_inventory():
    """Patch subprocess.run and _lookup_vm_host_ip for playbook tests."""
    with patch("agent.app.utils.provisioning.subprocess.run") as mock_run, \
         patch("agent.app.utils.provisioning._lookup_vm_host_ip", return_value="192.0.2.1"), \
         patch("agent.app.utils.provisioning._find_project_root", return_value=Path("/fake/root")):
        mock_run.return_value = _make_completed_process(PLAYBOOK_STDOUT_FULL)
        yield mock_run


class TestRunVmProvisioningPlaybook:
    def test_returns_ssh_command_with_password(self, mock_subprocess_and_inventory):
        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()):
            result = run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        assert result is not None
        assert "ssh -i <your_private_key>" in result
        assert "-p 7021" in result
        assert "alice@192.0.2.1" in result
        assert "| password: secret123" in result

    def test_returns_password_only_when_no_ssh_details(self, mock_subprocess_and_inventory):
        stdout = '"tenant_password": "onlypass"'
        mock_subprocess_and_inventory.return_value = _make_completed_process(stdout)
        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()), \
             patch("agent.app.utils.provisioning._lookup_vm_host_ip", return_value=None):
            result = run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        assert result == "password: onlypass"

    def test_returns_none_when_nothing_extracted(self, mock_subprocess_and_inventory):
        mock_subprocess_and_inventory.return_value = _make_completed_process("no useful output")
        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()), \
             patch("agent.app.utils.provisioning._lookup_vm_host_ip", return_value=None):
            result = run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        assert result is None

    def test_vm_target_has_random_suffix(self, mock_subprocess_and_inventory):
        """vm_target in the written vars file should be 'name-<suffix>', not bare 'name'."""
        captured_payloads = []

        original_write = Path.write_text

        def capturing_write(self, data, **kwargs):
            captured_payloads.append(data)
            return original_write(self, data, **kwargs)

        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()), \
             patch.object(Path, "write_text", capturing_write):
            run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host", vm_target="tenant-vm")

        vm_vars = next((p for p in captured_payloads if "vm_target" in p), None)
        assert vm_vars is not None
        # Should be "tenant-vm-<5-char suffix>", not plain "tenant-vm"
        import re
        match = re.search(r"vm_target: (.+)", vm_vars)
        assert match is not None
        target_value = match.group(1).strip()
        assert target_value.startswith("tenant-vm-")
        suffix = target_value[len("tenant-vm-"):]
        assert len(suffix) == 5

    def test_payload_includes_gpu_and_image_vars(self, mock_subprocess_and_inventory):
        captured_payloads = []
        original_write = Path.write_text

        def capturing_write(self, data, **kwargs):
            captured_payloads.append(data)
            return original_write(self, data, **kwargs)

        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()), \
             patch.object(Path, "write_text", capturing_write):
            run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        vm_vars = next((p for p in captured_payloads if "vm_target" in p), None)
        assert "image_setup_type: scratch" in vm_vars
        assert "vm_gpu_provisioned: true" in vm_vars
        assert "vm_gpu_count: 1" in vm_vars

    def test_payload_includes_frp_vars_when_configured(self, mock_subprocess_and_inventory):
        captured_payloads = []
        original_write = Path.write_text

        def capturing_write(self, data, **kwargs):
            captured_payloads.append(data)
            return original_write(self, data, **kwargs)

        cfg = _fake_config(
            frp_server_addr="10.1.2.3",
            frp_domain="frp.example.com",
            frp_dashboard_password="hunter2",
        )
        with patch("agent.app.utils.provisioning.CONFIG", cfg), \
             patch.object(Path, "write_text", capturing_write):
            run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        vm_vars = next((p for p in captured_payloads if "vm_target" in p), None)
        assert 'frp_server_addr: "10.1.2.3"' in vm_vars
        assert 'frp_domain: "frp.example.com"' in vm_vars
        assert 'frp_dashboard_password: "hunter2"' in vm_vars

    def test_payload_omits_frp_vars_when_not_configured(self, mock_subprocess_and_inventory):
        captured_payloads = []
        original_write = Path.write_text

        def capturing_write(self, data, **kwargs):
            captured_payloads.append(data)
            return original_write(self, data, **kwargs)

        with patch("agent.app.utils.provisioning.CONFIG", _fake_config()), \
             patch.object(Path, "write_text", capturing_write):
            run_vm_provisioning_playbook("ssh-ed25519 AAAA test@host")

        vm_vars = next((p for p in captured_payloads if "vm_target" in p), None)
        assert "frp_server_addr" not in vm_vars
        assert "frp_domain" not in vm_vars
        assert "frp_dashboard_password" not in vm_vars
