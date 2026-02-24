"""Unit tests for VM shutdown scheduling via provisioning service."""

from async_provisioning_service.services.provisioning import ProvisioningParams, _build_vm_vars

DEFAULT_PARAMS = dict(
    vm_host="vm1",
    vm_target="tenant-vm",
    ssh_pubkey="ssh-rsa AAAA...",
    vm_ram=2048,
    vm_vcpus=2,
    vm_disk_size="25G",
)


def _make_params(**overrides) -> ProvisioningParams:
    return ProvisioningParams(**(DEFAULT_PARAMS | overrides))


def test_provisioning_params_vm_lease_end():
    """Test that ProvisioningParams stores vm_lease_end correctly (present and absent)."""
    with_lease = _make_params(vm_action="lease_end", vm_lease_end="2026-02-06 15:30")
    assert with_lease.vm_lease_end == "2026-02-06 15:30"
    assert with_lease.vm_action == "lease_end"

    without_lease = _make_params(vm_action="create")
    assert without_lease.vm_lease_end is None
    assert without_lease.vm_action == "create"


def test_build_vm_vars_lease_end():
    """Test that _build_vm_vars includes/excludes vm_lease_end based on presence."""
    vm_vars_with = _build_vm_vars(_make_params(vm_action="lease_end", vm_lease_end="2026-02-06 15:30"))
    assert 'vm_lease_end: "2026-02-06 15:30"' in vm_vars_with
    assert "vm_action: lease_end" in vm_vars_with
    assert "vm_host: vm1" in vm_vars_with
    assert "vm_target: tenant-vm" in vm_vars_with

    vm_vars_without = _build_vm_vars(_make_params(vm_action="create"))
    assert "vm_lease_end" not in vm_vars_without
    assert "vm_action: create" in vm_vars_without
    assert "vm_host: vm1" in vm_vars_without


def test_build_vm_vars_escapes_pubkey():
    """Test that _build_vm_vars properly escapes quotes in SSH public keys."""
    params = _make_params(
        vm_action="create",
        ssh_pubkey='ssh-rsa AAAA... comment="with quotes"',
    )
    vm_vars = _build_vm_vars(params)
    assert 'comment=\\"with quotes\\"' in vm_vars
