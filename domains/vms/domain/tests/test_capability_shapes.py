"""VM-bound shape operations exposed to VM concept packages."""

from __future__ import annotations

import pytest
from market_capability_pricing import pricing_projection_problems

from arkhai_vms import (
    VM_CAPABILITY_SCHEMA,
    VM_PRICING_PROJECTION,
    CapabilityShapeError,
    FamilyRate,
    ShapePrice,
    canonical_vm_shape,
    price_vm_shape,
    vm_family_rate,
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


def test_a_vm_shape_is_priced_through_the_domain_aggregator():
    shape = {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}
    rates = {"gpu": FamilyRate("80", "hour"), "memory": FamilyRate("0.05", "hour")}

    assert price_vm_shape(shape, rates) == ShapePrice("166.4", "hour")
    # A family without a rate is not charged.
    assert price_vm_shape(shape, {"gpu": rates["gpu"]}) == ShapePrice("160", "hour")


def test_a_shape_outside_the_vm_vocabulary_is_not_priced():
    with pytest.raises(CapabilityShapeError):
        price_vm_shape({"gpu": {"count": 1}}, {"gpu": FamilyRate("1", "hour")})


def test_the_vm_pricing_projection_agrees_with_the_vm_schema():
    assert pricing_projection_problems(VM_PRICING_PROJECTION, VM_CAPABILITY_SCHEMA) == []
    assert VM_PRICING_PROJECTION.key_of("gpu") == "model"
    assert set(VM_PRICING_PROJECTION.families) == {"gpu", "cpu", "memory", "storage"}


def test_a_vm_family_rate_is_charged_by_time():
    assert vm_family_rate("0.5", "hour").rate == "0.5"
    with pytest.raises(ValueError, match="time unit"):
        vm_family_rate("0.5", "request")
