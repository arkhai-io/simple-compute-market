from __future__ import annotations

from arkhai_vms import vm_fulfillment_fields_from_dimensions
from arkhai_vms.compute_requirements import (
    DISK_GB_DIMENSION,
    GPU_COUNT_DIMENSION,
    RAM_GB_DIMENSION,
    VCPU_COUNT_DIMENSION,
)


def test_full_shape_translates_every_field():
    fields = vm_fulfillment_fields_from_dimensions({
        GPU_COUNT_DIMENSION: 1,
        VCPU_COUNT_DIMENSION: 4,
        RAM_GB_DIMENSION: 8,
        DISK_GB_DIMENSION: 80,
    })
    assert fields == {
        "vm_gpu_count": 1,
        "gpu_provisioned": True,
        "vm_vcpus": 4,
        "vm_ram": 8192,  # 8 GB -> MiB
        "vm_disk_size": "80G",
    }


def test_gpu_count_zero_yields_gpu_provisioned_false_not_absent():
    """A listing that explicitly declares zero GPUs is different from one
    that never mentioned GPUs at all -- the former must produce an
    explicit `gpu_provisioned=False`, not silently omit the field the way
    a genuinely-absent dimension does (see the next test)."""
    fields = vm_fulfillment_fields_from_dimensions({GPU_COUNT_DIMENSION: 0})
    assert fields["gpu_provisioned"] is False
    assert fields["vm_gpu_count"] == 0


def test_missing_dimensions_are_omitted_not_fabricated():
    """A reservation that never carried ram_gb/disk_gb (e.g. an older row,
    or a claim that only ever specified gpu_count) must not manufacture a
    fabricated zero/None for those fields -- the caller (the provisioning
    adapter) needs to distinguish "not specified, fall back to pool
    default" from "specified as zero"."""
    fields = vm_fulfillment_fields_from_dimensions({GPU_COUNT_DIMENSION: 1})
    assert fields == {"vm_gpu_count": 1, "gpu_provisioned": True}
    assert "vm_ram" not in fields
    assert "vm_vcpus" not in fields
    assert "vm_disk_size" not in fields


def test_empty_dimensions_produce_no_fields():
    assert vm_fulfillment_fields_from_dimensions({}) == {}


def test_none_dimensions_produce_no_fields():
    assert vm_fulfillment_fields_from_dimensions(None) == {}


def test_unrelated_dimension_keys_are_ignored():
    """A reservation's dimensions map is not exclusively VM shape fields --
    this function must not choke on or misinterpret keys it doesn't know."""
    fields = vm_fulfillment_fields_from_dimensions({
        GPU_COUNT_DIMENSION: 2,
        "some_future_dimension": 99,
    })
    assert fields == {"vm_gpu_count": 2, "gpu_provisioned": True}
