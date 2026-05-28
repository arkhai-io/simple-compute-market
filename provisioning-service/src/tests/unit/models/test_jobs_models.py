"""
Unit tests for typed VM request model validation.

``ProvisionRequest`` has been replaced by typed per-operation models in
``models/vm_request_model.py``.  Validation is now distributed:

  - ``vm_target`` is no longer validated here — it is a required URL path
    parameter enforced by FastAPI routing, not a model field.
  - ``vm_expiry_at`` is a required field on ``ScheduleVmExpiryRequest``
    (Pydantic raises on construction if absent).
  - FRP password cross-field rule lives on ``CreateVmRequest``.
  - Field-level constraints (ram, vcpus, disk_size, max_retries, gpu_count)
    live on ``CreateVmRequest``.

The ``to_ansible_job_params()`` adapter on each model is also exercised
here — that method is the boundary between the HTTP layer and the internal
``AnsibleJobParams`` DTO, so correctness matters.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from models.vm_request_model import (
    CreateVmRequest,
    ScheduleVmExpiryRequest,
    VmActionRequest,
    build_simple_params,
)


# ---------------------------------------------------------------------------
# CreateVmRequest — FRP cross-field validation
# ---------------------------------------------------------------------------

class TestCreateVmFrpValidation:
    def test_frp_server_addr_without_password_raises(self):
        with pytest.raises(ValidationError, match="frp_dashboard_password"):
            CreateVmRequest(
                vm_target="test-vm",
                frp_server_addr="1.2.3.4",
                frp_dashboard_password=None,
            )

    def test_frp_server_addr_with_password_valid(self):
        req = CreateVmRequest(
            vm_target="test-vm",
            frp_server_addr="1.2.3.4",
            frp_dashboard_password="secret",
        )
        assert req.frp_server_addr == "1.2.3.4"

    def test_no_frp_server_addr_no_password_required(self):
        req = CreateVmRequest(vm_target="test-vm")
        assert req.frp_server_addr is None
        assert req.frp_dashboard_password is None


# ---------------------------------------------------------------------------
# CreateVmRequest — field-level constraints
# ---------------------------------------------------------------------------

class TestCreateVmFieldConstraints:
    def test_vm_ram_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_ram=256)

    def test_vm_ram_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_ram=65536)

    def test_vm_ram_valid_boundaries(self):
        assert CreateVmRequest(vm_target="t", vm_ram=512).vm_ram == 512
        assert CreateVmRequest(vm_target="t", vm_ram=32768).vm_ram == 32768

    def test_vm_vcpus_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_vcpus=0)

    def test_vm_vcpus_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_vcpus=21)

    def test_vm_disk_size_valid_suffixes(self):
        assert CreateVmRequest(vm_target="t", vm_disk_size="20G").vm_disk_size == "20G"
        assert CreateVmRequest(vm_target="t", vm_disk_size="1T").vm_disk_size == "1T"
        assert CreateVmRequest(vm_target="t", vm_disk_size="512M").vm_disk_size == "512M"

    def test_vm_disk_size_invalid_suffix_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_disk_size="20GB")

    def test_max_retries_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", max_retries=-1)

    def test_max_retries_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", max_retries=11)

    def test_max_retries_valid_boundaries(self):
        assert CreateVmRequest(vm_target="t", max_retries=0).max_retries == 0
        assert CreateVmRequest(vm_target="t", max_retries=10).max_retries == 10

    def test_vm_gpu_count_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            CreateVmRequest(vm_target="t", vm_gpu_count=0)


# ---------------------------------------------------------------------------
# CreateVmRequest — defaults
# ---------------------------------------------------------------------------

class TestCreateVmDefaults:
    def test_image_setup_type_defaults_to_scratch(self):
        assert CreateVmRequest(vm_target="t").image_setup_type == "scratch"

    def test_optional_fields_default_to_none(self):
        req = CreateVmRequest(vm_target="t")
        assert req.vm_ram is None
        assert req.ssh_pubkey is None
        assert req.gpu_provisioned is None
        assert req.frp_server_addr is None


# ---------------------------------------------------------------------------
# CreateVmRequest — to_ansible_job_params adapter
# ---------------------------------------------------------------------------

class TestCreateVmToParams:
    def test_host_comes_from_argument_not_body(self):
        req = CreateVmRequest(vm_target="my-vm")
        params = req.to_ansible_job_params("kvm1")
        assert params.vm_host == "kvm1"
        assert params.vm_target == "my-vm"
        assert params.vm_action == "create"

    def test_all_sizing_fields_propagated(self):
        req = CreateVmRequest(
            vm_target="t",
            vm_ram=8192,
            vm_vcpus=8,
            vm_disk_size="40G",
            vm_os_variant="ubuntu22.04",
        )
        p = req.to_ansible_job_params("btc1")
        assert p.vm_ram == 8192
        assert p.vm_vcpus == 8
        assert p.vm_disk_size == "40G"
        assert p.vm_os_variant == "ubuntu22.04"

    def test_frp_fields_propagated(self):
        req = CreateVmRequest(
            vm_target="t",
            frp_server_addr="1.2.3.4",
            frp_domain="example.com",
            frp_dashboard_password="secret",
        )
        p = req.to_ansible_job_params("kvm1")
        assert p.frp_server_addr == "1.2.3.4"
        assert p.frp_domain == "example.com"
        assert p.frp_dashboard_password == "secret"

    def test_gpu_fields_propagated(self):
        req = CreateVmRequest(
            vm_target="t",
            gpu_provisioned=True,
            vm_gpu_count=2,
            vm_gpu_devices=["0000:03:00.0", "0000:04:00.0"],
        )
        p = req.to_ansible_job_params("kvm1")
        assert p.gpu_provisioned is True
        assert p.vm_gpu_count == 2
        assert p.vm_gpu_devices == ["0000:03:00.0", "0000:04:00.0"]

    def test_golden_image_fields_propagated(self):
        req = CreateVmRequest(
            vm_target="t",
            image_setup_type="golden",
            golden_image_name="base-v3",
            gcs_bucket_url="gs://bucket",
            gcs_image_path="images/img.qcow2",
        )
        p = req.to_ansible_job_params("kvm1")
        assert p.image_setup_type == "golden"
        assert p.golden_image_name == "base-v3"


# ---------------------------------------------------------------------------
# ScheduleVmExpiryRequest — required field and adapter
# ---------------------------------------------------------------------------

class TestScheduleVmExpiry:
    def test_vm_expiry_at_required(self):
        with pytest.raises(ValidationError):
            ScheduleVmExpiryRequest()  # type: ignore[call-arg]

    def test_to_ansible_job_params_sets_lease_end_action(self):
        req = ScheduleVmExpiryRequest(vm_expiry_at="2025-12-31T23:59:00")
        p = req.to_ansible_job_params(host="kvm1", vm_name="agent-vm-01")
        assert p.vm_action == "lease_end"
        assert p.vm_host == "kvm1"
        assert p.vm_target == "agent-vm-01"
        assert p.vm_expiry_at == "2025-12-31T23:59:00"


# ---------------------------------------------------------------------------
# VmActionRequest — max_retries constraint
# ---------------------------------------------------------------------------

class TestVmActionRequest:
    def test_max_retries_below_minimum_raises(self):
        with pytest.raises(ValidationError):
            VmActionRequest(max_retries=-1)

    def test_max_retries_above_maximum_raises(self):
        with pytest.raises(ValidationError):
            VmActionRequest(max_retries=11)

    def test_empty_body_valid(self):
        req = VmActionRequest()
        assert req.max_retries is None


# ---------------------------------------------------------------------------
# build_simple_params — action routing
# ---------------------------------------------------------------------------

class TestBuildSimpleParams:
    @pytest.mark.parametrize("action", [
        "start", "shutdown", "reboot", "destroy", "undefine",
        "monitor", "reset_password", "lease_remove",
    ])
    def test_vm_name_actions(self, action):
        body = VmActionRequest(max_retries=1)
        p = build_simple_params(action, "kvm1", body, "my-vm")
        assert p.vm_action == action
        assert p.vm_host == "kvm1"
        assert p.vm_target == "my-vm"
        assert p.max_retries == 1

    @pytest.mark.parametrize("action", ["list", "check"])
    def test_host_level_actions_have_no_vm_target(self, action):
        body = VmActionRequest()
        p = build_simple_params(action, "kvm1", body)
        assert p.vm_action == action
        assert p.vm_host == "kvm1"
        assert p.vm_target is None