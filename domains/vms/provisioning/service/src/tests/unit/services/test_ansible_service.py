"""
Unit tests for AnsibleService.

Covers: _build_vm_vars (YAML serialisation), _extract_ssh_port,
_extract_tenant_user, _extract_ansible_json, _inject_golden_image_credentials.

start_playbook / wait_for_playbook / check_connectivity are thin subprocess
wrappers and are exercised in integration tests against a mock boundary.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from models.jobs_model import AnsibleJobParams
from services.ansible_service import AnsibleService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_service(
    golden_root_ssh_filename: str = "",
    golden_root_ssh_password: str = "",
    golden_image_name: str = "",
) -> AnsibleService:
    settings = MagicMock()
    settings.resolved_playbook_path = "/playbooks/vm-operations.yaml"
    settings.resolved_inventory_path = "/inventory/hosts"
    settings.ansible_timeout_seconds = 1800
    settings.golden_root_ssh_filename = golden_root_ssh_filename
    settings.golden_root_ssh_password = golden_root_ssh_password
    settings.golden_image_name = golden_image_name
    return AnsibleService(settings)


def _base_params(**overrides) -> AnsibleJobParams:
    defaults = dict(
        vm_host="kvm1",
        vm_target="test-vm",
        vm_action="create",
    )
    defaults.update(overrides)
    return AnsibleJobParams(**defaults)


def _build(svc: AnsibleService, **overrides) -> str:
    """Shorthand: build vars YAML and return as string."""
    return svc._build_vm_vars(_base_params(**overrides))


def _lines(yaml_str: str) -> dict[str, str]:
    """Parse simple key: value lines into a dict for easy assertion."""
    result = {}
    for line in yaml_str.strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


# ---------------------------------------------------------------------------
# _build_vm_vars -- required fields always present
# ---------------------------------------------------------------------------


class TestBuildVmVarsRequired:
    def test_vm_host_always_present(self):
        svc = _make_service()
        assert "vm_host: kvm1" in _build(svc)

    def test_vm_action_always_present(self):
        svc = _make_service()
        assert "vm_action: create" in _build(svc)

    def test_vm_target_present_when_set(self):
        svc = _make_service()
        assert "vm_target: test-vm" in _build(svc)

    def test_vm_target_absent_when_none(self):
        svc = _make_service()
        yaml = svc._build_vm_vars(AnsibleJobParams(vm_host="kvm1", vm_target=None, vm_action="list"))
        assert "vm_target" not in yaml

    def test_scratch_mode_adds_not_provided_credentials(self):
        svc = _make_service()
        yaml = _build(svc, image_setup_type="scratch")
        assert "root_ssh_filename: not_provided" in yaml
        assert "root_ssh_password: not_provided" in yaml

    def test_ends_with_newline(self):
        svc = _make_service()
        assert _build(svc).endswith("\n")


# ---------------------------------------------------------------------------
# _build_vm_vars -- create-specific fields
# ---------------------------------------------------------------------------


class TestBuildVmVarsCreate:
    def test_image_setup_type_only_on_create(self):
        svc = _make_service()
        create_yaml = _build(svc, vm_action="create", image_setup_type="scratch")
        monitor_yaml = _build(svc, vm_action="monitor")
        assert "image_setup_type" in create_yaml
        assert "image_setup_type" not in monitor_yaml

    def test_vm_sizing_fields(self):
        svc = _make_service()
        yaml = _build(svc, vm_ram=4096, vm_vcpus=4, vm_disk_size="20G")
        lines = _lines(yaml)
        assert lines["vm_ram"] == "4096"
        assert lines["vm_vcpus"] == "4"
        assert lines["vm_disk_size"] == "20G"

    def test_sizing_fields_absent_when_none(self):
        svc = _make_service()
        yaml = _build(svc)
        assert "vm_ram" not in yaml
        assert "vm_vcpus" not in yaml
        assert "vm_disk_size" not in yaml

    def test_ssh_pubkey_quoted_and_escaped(self):
        svc = _make_service()
        key = 'ssh-ed25519 AAAA "quoted" rest'
        yaml = _build(svc, ssh_pubkey=key)
        assert 'vm_tenant_pubkey: "ssh-ed25519 AAAA \\"quoted\\" rest"' in yaml

    def test_ssh_pubkey_absent_when_none(self):
        svc = _make_service()
        assert "vm_tenant_pubkey" not in _build(svc)

    def test_gpu_provisioned_true(self):
        svc = _make_service()
        assert "gpu_provisioned: true" in _build(svc, gpu_provisioned=True)

    def test_gpu_provisioned_false(self):
        svc = _make_service()
        assert "gpu_provisioned: false" in _build(svc, gpu_provisioned=False)

    def test_gpu_provisioned_absent_when_none(self):
        svc = _make_service()
        assert "gpu_provisioned" not in _build(svc)

    def test_gpu_devices_serialised_as_json(self):
        svc = _make_service()
        devices = ["0000:03:00.0", "0000:04:00.0"]
        yaml = _build(svc, vm_gpu_devices=devices)
        assert f"vm_gpu_devices: {json.dumps(devices)}" in yaml

    def test_frp_fields_present_when_set(self):
        svc = _make_service()
        yaml = _build(
            svc,
            frp_server_addr="1.2.3.4",
            frp_domain="example.com",
            frp_dashboard_password="secret",
        )
        assert 'frp_server_addr: "1.2.3.4"' in yaml
        assert 'frp_domain: "example.com"' in yaml
        assert 'frp_dashboard_password: "secret"' in yaml

    def test_frp_fields_absent_when_none(self):
        svc = _make_service()
        yaml = _build(svc)
        assert "frp_server_addr" not in yaml
        assert "frp_domain" not in yaml
        assert "frp_dashboard_password" not in yaml

    def test_gcs_fields_included_when_set(self):
        svc = _make_service()
        yaml = _build(svc, gcs_bucket_url="gs://bucket", gcs_image_path="images/img.qcow2")
        assert "gcs_bucket_url: gs://bucket" in yaml
        assert "gcs_image_path: images/img.qcow2" in yaml


# ---------------------------------------------------------------------------
# _build_vm_vars -- lease / expiry
# ---------------------------------------------------------------------------


class TestBuildVmVarsExpiry:
    def test_vm_expiry_at_written_as_vm_lease_end(self):
        """API field vm_expiry_at is passed to Ansible as vm_lease_end."""
        svc = _make_service()
        yaml = svc._build_vm_vars(
            AnsibleJobParams(
                vm_host="kvm1",
                vm_target="test-vm",
                vm_action="lease_end",
                vm_expiry_at="2025-12-31T23:59:00",
            )
        )
        assert 'vm_lease_end: "2025-12-31T23:59:00"' in yaml

    def test_vm_expiry_absent_when_none(self):
        svc = _make_service()
        assert "vm_lease_end" not in _build(svc, vm_action="shutdown")


# ---------------------------------------------------------------------------
# _inject_golden_image_credentials
# ---------------------------------------------------------------------------


class TestInjectGoldenImageCredentials:
    def test_golden_credentials_injected_when_available(self):
        svc = _make_service(
            golden_root_ssh_filename="id_ed25519",
            golden_root_ssh_password="hunter2",
        )
        yaml = _build(svc, image_setup_type="golden")
        assert "root_ssh_filename: id_ed25519" in yaml
        assert "root_ssh_password: hunter2" in yaml
        assert "not_provided" not in yaml

    def test_golden_image_name_included_when_set(self):
        svc = _make_service(
            golden_root_ssh_filename="id_ed25519",
            golden_root_ssh_password="hunter2",
            golden_image_name="base-image-v3",
        )
        yaml = _build(svc, image_setup_type="golden")
        assert "golden_image_name: base-image-v3" in yaml

    def test_golden_image_name_absent_when_empty(self):
        svc = _make_service(
            golden_root_ssh_filename="id_ed25519",
            golden_root_ssh_password="hunter2",
            golden_image_name="",
        )
        yaml = _build(svc, image_setup_type="golden")
        assert "golden_image_name" not in yaml

    def test_fallback_when_credentials_not_configured(self):
        svc = _make_service(
            golden_root_ssh_filename="",
            golden_root_ssh_password="",
        )
        yaml = _build(svc, image_setup_type="golden")
        assert "root_ssh_filename: not_provided" in yaml
        assert "root_ssh_password: not_provided" in yaml


# ---------------------------------------------------------------------------
# _extract_ssh_port
# ---------------------------------------------------------------------------


class TestExtractSshPort:
    def test_extracts_from_json_field(self):
        svc = _make_service()
        output = 'some text "external_ssh_port": "54321" more text'
        assert svc._extract_ssh_port(output) == "54321"

    def test_extracts_from_ssh_command_with_host(self):
        svc = _make_service()
        output = "ssh -i key -p 2222 root@kvm1"
        assert svc._extract_ssh_port(output, vm_host="kvm1") == "2222"

    def test_fallback_to_generic_pattern_without_host(self):
        svc = _make_service()
        output = "connect using: ssh -p 9000 user@some.host.com"
        assert svc._extract_ssh_port(output) == "9000"

    def test_json_field_takes_precedence_over_ssh_command(self):
        svc = _make_service()
        output = '"external_ssh_port": "1111" and also ssh -p 2222 root@kvm1'
        assert svc._extract_ssh_port(output, vm_host="kvm1") == "1111"

    def test_returns_none_when_no_port_found(self):
        svc = _make_service()
        assert svc._extract_ssh_port("no port info here") is None

    def test_returns_none_for_empty_string(self):
        svc = _make_service()
        assert svc._extract_ssh_port("") is None


# ---------------------------------------------------------------------------
# _extract_tenant_user
# ---------------------------------------------------------------------------


class TestExtractTenantUser:
    def test_extracts_from_json_field(self):
        svc = _make_service()
        output = '"tenant_user": "agentuser" and other stuff'
        assert svc._extract_tenant_user(output) == "agentuser"

    def test_extracts_from_ssh_command_with_host(self):
        svc = _make_service()
        output = "ssh -p 2222 myuser@kvm1"
        assert svc._extract_tenant_user(output, vm_host="kvm1") == "myuser"

    def test_json_field_takes_precedence(self):
        svc = _make_service()
        output = '"tenant_user": "fromjson" and ssh -p 22 fromcmd@kvm1'
        assert svc._extract_tenant_user(output, vm_host="kvm1") == "fromjson"

    def test_returns_none_when_no_user_found(self):
        svc = _make_service()
        assert svc._extract_tenant_user("nothing useful") is None


# ---------------------------------------------------------------------------
# _extract_ansible_json
# ---------------------------------------------------------------------------


PLAYBOOK_OUTPUT_CREATE = """\
TASK [debug] ***
ok: [kvm1] => {
    "vm_creation_data": {
        "action": "create",
        "vm_name": "test-vm",
        "status": "running"
    }
}
"""

PLAYBOOK_OUTPUT_LIST = """\
ok: [kvm1] => {
    "vm_list_data": {
        "action": "list",
        "vms": [{"name": "vm-a"}, {"name": "vm-b"}],
        "vm_count": 2
    }
}
"""

PLAYBOOK_OUTPUT_CHECK = """\
ok: [kvm1] => {
    "check_data": {
        "action": "check",
        "resources": {"vcpus_total": 32}
    }
}
"""


class TestExtractAnsibleJson:
    def test_extracts_create_data(self):
        svc = _make_service()
        result = svc._extract_ansible_json(PLAYBOOK_OUTPUT_CREATE, "create")
        assert result is not None
        assert result["action"] == "create"
        assert result["vm_name"] == "test-vm"

    def test_extracts_list_data(self):
        svc = _make_service()
        result = svc._extract_ansible_json(PLAYBOOK_OUTPUT_LIST, "list")
        assert result is not None
        assert result["vm_count"] == 2

    def test_extracts_check_data(self):
        svc = _make_service()
        result = svc._extract_ansible_json(PLAYBOOK_OUTPUT_CHECK, "check")
        assert result is not None
        assert result["action"] == "check"

    def test_returns_none_for_unknown_action(self):
        svc = _make_service()
        assert svc._extract_ansible_json("anything", "unknown_action") is None

    def test_returns_none_when_marker_absent(self):
        svc = _make_service()
        assert svc._extract_ansible_json("no json here", "create") is None

    def test_all_action_names_have_mappings(self):
        """Every supported vm_action must resolve to a non-None extraction."""
        svc = _make_service()
        actions = [
            ("create", "vm_creation_data"),
            ("list", "vm_list_data"),
            ("start", "vm_start_data"),
            ("shutdown", "vm_shutdown_data"),
            ("destroy", "vm_destroy_data"),
            ("reboot", "vm_reboot_data"),
            ("undefine", "vm_undefine_data"),
            ("monitor", "vm_monitoring_data"),
            ("reset_password", "vm_password_reset_data"),
            ("lease_end", "vm_lease_end_data"),
            ("lease_remove", "vm_lease_remove_data"),
            ("check", "check_data"),
        ]
        for action, fact_name in actions:
            output = f'"{fact_name}": {{"action": "{action}"}}'
            result = svc._extract_ansible_json(output, action)
            assert result is not None, f"Failed to extract for action={action}"
            assert result["action"] == action


# ---------------------------------------------------------------------------
# public_host -- tenant-facing advertised SSH host (distinct from kvm_host)
# ---------------------------------------------------------------------------


class _FakeHost:
    def __init__(self, name, kvm_host, public_host=None):
        self.name = name
        self.kvm_host = kvm_host
        self.public_host = public_host
        self.ssh_user = "ubuntu"
        self.ssh_key_type = "path"
        self.ssh_key_value = "/home/appuser/.ssh/id_ed25519"


class TestPublicHostInventory:
    def test_emits_public_host_var_when_set(self):
        svc = _make_service()
        inv_path = svc.write_inventory([_FakeHost("kvm1", "10.0.0.5", "203.0.113.9")])
        try:
            content = inv_path.read_text(encoding="utf-8")
        finally:
            inv_path.unlink(missing_ok=True)
        assert "ansible_host=10.0.0.5" in content  # management address
        assert "public_host=203.0.113.9" in content  # tenant-facing address

    def test_omits_public_host_var_when_unset(self):
        svc = _make_service()
        inv_path = svc.write_inventory([_FakeHost("kvm1", "10.0.0.5", None)])
        try:
            content = inv_path.read_text(encoding="utf-8")
        finally:
            inv_path.unlink(missing_ok=True)
        assert "public_host=" not in content


class TestPublicHostConnection:
    def test_vm_host_ip_and_ssh_command_prefer_public_host(self):
        from services.ansible_service import AnsibleResult

        svc = _make_service()
        result = AnsibleResult(
            stdout='"external_ssh_port": "9000"\n"tenant_user": "tenantx"',
            stderr="",
            process_id=123,
        )
        parsed = svc.parse_playbook_result(
            result, _base_params(vm_host="kvm1"), public_host="203.0.113.9"
        )
        assert parsed.vm_host_ip == "203.0.113.9"
        assert parsed.ssh_command == "ssh -i <your_private_key> -p 9000 tenantx@203.0.113.9"
