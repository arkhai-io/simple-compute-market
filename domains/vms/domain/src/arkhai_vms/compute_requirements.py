"""Shared VM compute-requirement dimension vocabulary.

Two independently-named vocabularies exist for the same underlying VM
shape (GPU count, vCPU count, RAM, disk): the capacity/negotiation side
(``gpu_count``/``vcpu_count``/``ram_gb``/``disk_gb`` -- the reservation's
own ``dimensions``, matching ``kit/site``'s claim vocabulary) and the
Ansible-facing fulfillment side (``vm_gpu_count``/``gpu_provisioned``/
``vm_vcpus``/``vm_ram``/``vm_disk_size`` -- ``VmFulfillmentRequirements``'
field names, in the units the provisioning adapter's Ansible tasks expect).

This module is the single place that translation happens, imported by
both ``domains/vms/storefront`` (which computes capacity dimensions from
an accepted order) and ``domains/vms/provisioning/adapter`` (which derives
Ansible fulfillment fields from a committed reservation's dimensions).
The provisioning side derives from the reservation's own committed
dimensions rather than accepting them from the fulfillment request: a
reservation's hold is placed with the terminal, post-negotiation order's
shape already, so a caller-supplied copy of the same shape could only
ever restate it, never legitimately override it, while remaining a
second value that could silently drift if that invariant ever breaks.
"""

from __future__ import annotations

from typing import Any, Mapping

# The claim/negotiation-side dimension keys, matching kit/site's
# reservation ``dimensions`` column and this repository's capacity claim
# vocabulary (``vm_job_spec_service.compute_capacity_claim_from_order``).
GPU_COUNT_DIMENSION = "gpu_count"
VCPU_COUNT_DIMENSION = "vcpu_count"
RAM_GB_DIMENSION = "ram_gb"
DISK_GB_DIMENSION = "disk_gb"

DIMENSION_KEYS: tuple[str, ...] = (
    GPU_COUNT_DIMENSION,
    VCPU_COUNT_DIMENSION,
    RAM_GB_DIMENSION,
    DISK_GB_DIMENSION,
)

# libvirt/virt-install's --ram flag is MiB, not GB; qemu-img's size
# arguments take a unit-suffixed string. Neither conversion has prior art
# elsewhere in this repository -- the storefront never sent vm_ram/
# vm_disk_size to the provider before this module existed, so there was
# nothing to be consistent with. Standard binary GB->MiB (x1024) and
# qemu-img's "<n>G" suffix convention (GiB) are used here; revisit both if
# the provisioning adapter's actual unit expectations turn out to differ.
_MIB_PER_GB = 1024


def vm_fulfillment_fields_from_dimensions(
    dimensions: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Translate reservation-committed dimensions into
    ``VmFulfillmentRequirements``-shaped fields.

    Only produces keys for dimensions actually present in ``dimensions``
    -- a reservation that never carried a given dimension (e.g. an older
    row, or a claim that only ever specified ``gpu_count``) must not
    manufacture a fabricated zero/None for fields ``VmFulfillmentRequirements``
    already treats as optional-with-a-pool-default. The caller (the
    provisioning adapter) merges this into its own field construction the
    same way it already merges pool-config defaults.
    """
    dims = dict(dimensions or {})
    fields: dict[str, Any] = {}

    if GPU_COUNT_DIMENSION in dims:
        gpu_count = int(dims[GPU_COUNT_DIMENSION])
        fields["vm_gpu_count"] = gpu_count
        fields["gpu_provisioned"] = gpu_count > 0

    if VCPU_COUNT_DIMENSION in dims:
        fields["vm_vcpus"] = int(dims[VCPU_COUNT_DIMENSION])

    if RAM_GB_DIMENSION in dims:
        fields["vm_ram"] = int(dims[RAM_GB_DIMENSION]) * _MIB_PER_GB

    if DISK_GB_DIMENSION in dims:
        fields["vm_disk_size"] = f"{int(dims[DISK_GB_DIMENSION])}G"

    return fields


__all__ = [
    "DIMENSION_KEYS",
    "DISK_GB_DIMENSION",
    "GPU_COUNT_DIMENSION",
    "RAM_GB_DIMENSION",
    "VCPU_COUNT_DIMENSION",
    "vm_fulfillment_fields_from_dimensions",
]
