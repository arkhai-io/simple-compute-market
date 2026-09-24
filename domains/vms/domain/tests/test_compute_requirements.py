from arkhai_vms import (
    DIMENSION_KEYS, DISK_GB_DIMENSION, GPU_COUNT_DIMENSION,
    RAM_GB_DIMENSION, VCPU_COUNT_DIMENSION,
)


def test_canonical_dimension_vocabulary():
    assert DIMENSION_KEYS == (
        GPU_COUNT_DIMENSION, VCPU_COUNT_DIMENSION, RAM_GB_DIMENSION, DISK_GB_DIMENSION
    )


import pytest

from market_capability_shape import CapabilityShapeError, FieldKind, flatten_shape

from arkhai_vms import VM_CAPABILITY_SCHEMA


def test_schema_quantities_are_the_dimension_vocabulary():
    assert set(VM_CAPABILITY_SCHEMA.flat_names(FieldKind.QUANTITY)) == set(DIMENSION_KEYS)


def test_only_the_gpu_family_is_required():
    required = {field.path for field in VM_CAPABILITY_SCHEMA.fields if field.required}
    assert required == {"gpu.count", "gpu.model"}


def test_a_vm_shape_flattens_to_wire_names():
    flat = flatten_shape(
        {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
         "memory": {"gib": 64}, "storage": {"gib": 500}},
        VM_CAPABILITY_SCHEMA,
    )
    assert dict(flat.quantities) == {
        "gpu_count": 1, "vcpu_count": 8, "ram_gb": 64, "disk_gb": 500,
    }
    assert dict(flat.attributes) == {"gpu_model": "H100"}


def test_a_shape_without_a_gpu_model_is_refused():
    with pytest.raises(CapabilityShapeError) as refused:
        flatten_shape({"gpu": {"count": 1}, "memory": {"gib": 64}}, VM_CAPABILITY_SCHEMA)
    assert [problem.path for problem in refused.value.problems] == ["gpu.model"]
