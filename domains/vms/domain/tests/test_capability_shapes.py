"""VM-bound shape operations exposed to VM concept packages."""

from __future__ import annotations

import pytest

from arkhai_vms import (
    CapabilityShapeError,
    canonical_vm_shape,
    flatten_vm_shape,
    vm_shape_digest,
    vm_shape_problems,
)

SHAPE = {"memory": {"gib": 64}, "gpu": {"model": "H100", "count": 1}}


def test_flatten_uses_the_vm_schema():
    flat = flatten_vm_shape(SHAPE)
    assert dict(flat.quantities) == {"gpu_count": 1, "ram_gb": 64}
    assert dict(flat.attributes) == {"gpu_model": "H100"}


def test_digest_and_canonical_form_refuse_a_shape_outside_the_vocabulary():
    bad = {"gpu": {"count": 1, "model": "H100"}, "tpu": {"count": 1}}
    assert [p.path for p in vm_shape_problems(bad)] == ["tpu.count"]
    with pytest.raises(CapabilityShapeError):
        vm_shape_digest(bad)
    with pytest.raises(CapabilityShapeError):
        canonical_vm_shape(bad)


def test_digest_ignores_key_order():
    reordered = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}
    assert vm_shape_digest(SHAPE) == vm_shape_digest(reordered)
    assert list(canonical_vm_shape(SHAPE)) == ["gpu", "memory"]
