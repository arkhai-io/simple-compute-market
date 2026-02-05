"""Unit tests for VM shutdown scheduling via provisioning service."""

import pytest
from async_provisioning_service.services.provisioning import ProvisioningParams, _build_vm_vars


def test_provisioning_params_with_vm_lease_end():
    """Test that ProvisioningParams accepts vm_lease_end parameter."""
    params = ProvisioningParams(
        ssh_pubkey="ssh-rsa AAAA...",
        vm_host="vm1",
        vm_target="tenant-vm",
        vm_action="lease_end",
        vm_ram=2048,
        vm_vcpus=2,
        vm_disk_size="25G",
        vm_lease_end="2026-02-06 15:30",
    )

    assert params.vm_lease_end == "2026-02-06 15:30"
    assert params.vm_action == "lease_end"


def test_provisioning_params_without_vm_lease_end():
    """Test that ProvisioningParams works without vm_lease_end (default create action)."""
    params = ProvisioningParams(
        ssh_pubkey="ssh-rsa AAAA...",
        vm_host="vm1",
        vm_target="tenant-vm",
        vm_action="create",
        vm_ram=2048,
        vm_vcpus=2,
        vm_disk_size="25G",
    )

    assert params.vm_lease_end is None
    assert params.vm_action == "create"


def test_build_vm_vars_includes_lease_end():
    """Test that _build_vm_vars includes vm_lease_end when present."""
    params = ProvisioningParams(
        ssh_pubkey="ssh-rsa AAAA...",
        vm_host="vm1",
        vm_target="tenant-vm",
        vm_action="lease_end",
        vm_ram=2048,
        vm_vcpus=2,
        vm_disk_size="25G",
        vm_lease_end="2026-02-06 15:30",
    )

    vm_vars = _build_vm_vars(params)

    assert "vm_lease_end: 2026-02-06 15:30" in vm_vars
    assert "vm_action: lease_end" in vm_vars
    assert "vm_host: vm1" in vm_vars
    assert "vm_target: tenant-vm" in vm_vars


def test_build_vm_vars_excludes_lease_end_when_not_present():
    """Test that _build_vm_vars excludes vm_lease_end when not present."""
    params = ProvisioningParams(
        ssh_pubkey="ssh-rsa AAAA...",
        vm_host="vm1",
        vm_target="tenant-vm",
        vm_action="create",
        vm_ram=2048,
        vm_vcpus=2,
        vm_disk_size="25G",
    )

    vm_vars = _build_vm_vars(params)

    assert "vm_lease_end" not in vm_vars
    assert "vm_action: create" in vm_vars
    assert "vm_host: vm1" in vm_vars


def test_build_vm_vars_escapes_pubkey():
    """Test that _build_vm_vars properly escapes quotes in SSH public keys."""
    params = ProvisioningParams(
        ssh_pubkey='ssh-rsa AAAA... comment="with quotes"',
        vm_host="vm1",
        vm_target="tenant-vm",
        vm_action="create",
        vm_ram=2048,
        vm_vcpus=2,
        vm_disk_size="25G",
    )

    vm_vars = _build_vm_vars(params)

    # Quotes should be escaped
    assert 'comment=\\"with quotes\\"' in vm_vars
