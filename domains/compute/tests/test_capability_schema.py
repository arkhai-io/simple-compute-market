"""The compute-family capability schema."""

from __future__ import annotations

from market_capability_shape import FieldKind, flatten_shape, unflatten_shape

from arkhai_compute import (
    COMPUTE_CAPABILITY_SCHEMA,
    DIMENSION_KEYS,
    DISK_GB_DIMENSION,
    GPU_COUNT_DIMENSION,
    GPU_MODEL_ATTRIBUTE,
    RAM_GB_DIMENSION,
    VCPU_COUNT_DIMENSION,
)


def test_the_families_are_the_compute_families():
    assert COMPUTE_CAPABILITY_SCHEMA.families == {"gpu", "cpu", "memory", "storage"}


def test_quantities_are_the_dimension_vocabulary():
    assert DIMENSION_KEYS == (
        GPU_COUNT_DIMENSION, VCPU_COUNT_DIMENSION, RAM_GB_DIMENSION, DISK_GB_DIMENSION
    )
    assert COMPUTE_CAPABILITY_SCHEMA.flat_names(FieldKind.QUANTITY) == DIMENSION_KEYS


def test_the_one_attribute_is_the_gpu_model():
    assert COMPUTE_CAPABILITY_SCHEMA.flat_names(FieldKind.ATTRIBUTE) == (GPU_MODEL_ATTRIBUTE,)


def test_only_the_gpu_family_is_required():
    required = {field.path for field in COMPUTE_CAPABILITY_SCHEMA.fields if field.required}
    assert required == {"gpu.count", "gpu.model"}


def test_a_whole_machine_round_trips_through_its_flat_names():
    shape = {"gpu": {"count": 8, "model": "H200"}, "memory": {"gib": 2048}}
    flat = flatten_shape(shape, COMPUTE_CAPABILITY_SCHEMA)

    assert dict(flat.quantities) == {"gpu_count": 8, "ram_gb": 2048}
    assert dict(flat.attributes) == {"gpu_model": "H200"}
    assert unflatten_shape(flat.quantities, flat.attributes, COMPUTE_CAPABILITY_SCHEMA) == shape
