"""
Unit tests for ProvisionRequest Pydantic validation.

Covers the @model_validator cross-field rules and field-level constraints.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.jobs import ProvisionRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _req(**kwargs) -> ProvisionRequest:
    """Build a ProvisionRequest with sensible defaults, applying overrides."""
    defaults = {
        "vm_host": "ww1",
        "vm_action": "create",
        "vm_target": "test-vm",
    }
    defaults.update(kwargs)
    return ProvisionRequest(**defaults)


def _expect_error(match: str, **kwargs):
    with pytest.raises(ValidationError, match=match):
        _req(**kwargs)


# ---------------------------------------------------------------------------
# vm_target requirement
# ---------------------------------------------------------------------------

class TestVmTargetRequired:
    def test_create_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="create", vm_target=None)

    def test_start_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="start", vm_target=None)

    def test_shutdown_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="shutdown", vm_target=None)

    def test_destroy_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="destroy", vm_target=None)

    def test_reboot_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="reboot", vm_target=None)

    def test_monitor_requires_vm_target(self):
        _expect_error("vm_target is required", vm_action="monitor", vm_target=None)

    def test_list_does_not_require_vm_target(self):
        req = ProvisionRequest(vm_host="ww1", vm_action="list")
        assert req.vm_target is None

    def test_check_does_not_require_vm_target(self):
        req = ProvisionRequest(vm_host="ww1", vm_action="check")
        assert req.vm_target is None


# ---------------------------------------------------------------------------
# lease_end requirement
# ---------------------------------------------------------------------------

class TestLeaseEndRequired:
    def test_lease_end_action_requires_vm_lease_end(self):
        _expect_error("vm_lease_end is required", vm_action="lease_end", vm_lease_end=None)

    def test_lease_end_action_valid_with_vm_lease_end(self):
        req = _req(vm_action="lease_end", vm_lease_end="2025-12-31 23:59")
        assert req.vm_lease_end == "2025-12-31 23:59"

    def test_other_actions_do_not_require_vm_lease_end(self):
        req = _req(vm_action="shutdown")
        assert req.vm_lease_end is None


# ---------------------------------------------------------------------------
# FRP password requirement
# ---------------------------------------------------------------------------

class TestFrpPasswordRequired:
    def test_frp_server_addr_without_password_raises(self):
        _expect_error(
            "frp_dashboard_password required",
            vm_action="create",
            frp_server_addr="1.2.3.4",
            frp_dashboard_password=None,
        )

    def test_frp_server_addr_with_password_valid(self):
        req = _req(
            vm_action="create",
            frp_server_addr="1.2.3.4",
            frp_dashboard_password="secret",
        )
        assert req.frp_server_addr == "1.2.3.4"

    def test_no_frp_server_addr_no_password_required(self):
        req = _req(vm_action="create")
        assert req.frp_server_addr is None
        assert req.frp_dashboard_password is None


# ---------------------------------------------------------------------------
# Field-level constraints
# ---------------------------------------------------------------------------

class TestFieldConstraints:
    def test_vm_ram_minimum(self):
        with pytest.raises(ValidationError):
            _req(vm_ram=256)  # below minimum of 512

    def test_vm_ram_maximum(self):
        with pytest.raises(ValidationError):
            _req(vm_ram=65536)  # above maximum of 32768

    def test_vm_ram_valid_boundary(self):
        assert _req(vm_ram=512).vm_ram == 512
        assert _req(vm_ram=32768).vm_ram == 32768

    def test_vm_vcpus_minimum(self):
        with pytest.raises(ValidationError):
            _req(vm_vcpus=0)

    def test_vm_vcpus_maximum(self):
        with pytest.raises(ValidationError):
            _req(vm_vcpus=21)

    def test_vm_disk_size_valid_formats(self):
        assert _req(vm_disk_size="20G").vm_disk_size == "20G"
        assert _req(vm_disk_size="1T").vm_disk_size == "1T"
        assert _req(vm_disk_size="512M").vm_disk_size == "512M"

    def test_vm_disk_size_invalid_format(self):
        with pytest.raises(ValidationError):
            _req(vm_disk_size="20GB")  # invalid suffix

    def test_max_retries_minimum(self):
        with pytest.raises(ValidationError):
            _req(max_retries=-1)

    def test_max_retries_maximum(self):
        with pytest.raises(ValidationError):
            _req(max_retries=11)

    def test_max_retries_valid_boundary(self):
        assert _req(max_retries=0).max_retries == 0
        assert _req(max_retries=10).max_retries == 10


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestDefaults:
    def test_vm_action_defaults_to_create(self):
        req = ProvisionRequest(vm_host="ww1", vm_target="test-vm")
        assert req.vm_action == "create"

    def test_image_setup_type_defaults_to_scratch(self):
        req = _req()
        assert req.image_setup_type == "scratch"

    def test_optional_fields_default_to_none(self):
        req = _req()
        assert req.vm_ram is None
        assert req.ssh_pubkey is None
        assert req.gpu_provisioned is None
        assert req.buyer_agent_id is None

    def test_vm_gpu_count_minimum(self):
        with pytest.raises(ValidationError):
            _req(vm_gpu_count=0)


# ---------------------------------------------------------------------------
# Valid action coverage
# ---------------------------------------------------------------------------

class TestValidActions:
    @pytest.mark.parametrize("action", [
        "create", "start", "shutdown", "destroy", "reboot",
        "undefine", "monitor", "reset_password", "lease_remove",
    ])
    def test_all_target_actions_valid_with_vm_target(self, action):
        req = _req(vm_action=action, vm_target="test-vm")
        assert req.vm_action == action

    def test_lease_end_valid_with_all_required_fields(self):
        req = _req(vm_action="lease_end", vm_target="test-vm", vm_lease_end="2025-12-31 23:59")
        assert req.vm_action == "lease_end"
