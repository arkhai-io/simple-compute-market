"""The default VM listing-shape generator."""

from __future__ import annotations

from arkhai_vms import DEFAULT_LISTING_SHAPE_GENERATOR, gpu_count_shapes


def _member(count, model="H100", *, enabled=True, **capacity):
    member = {"capacity": {"gpu_count": count, **capacity}, "attributes": {}, "enabled": enabled}
    if model is not None:
        member["attributes"]["gpu_model"] = model
    return member


def test_the_default_generator_is_gpu_count_enumeration():
    assert DEFAULT_LISTING_SHAPE_GENERATOR is gpu_count_shapes


def test_single_model_pool_ranges_to_its_largest_member():
    shapes = gpu_count_shapes([_member(2), _member(3, ram_gb=512)])
    assert shapes == tuple({"gpu": {"count": n, "model": "H100"}} for n in (1, 2, 3))


def test_shapes_declare_the_gpu_family_only():
    (shape,) = gpu_count_shapes([_member(1, vcpu_count=64, ram_gb=512, disk_gb=900)])
    assert set(shape) == {"gpu"}


def test_mixed_model_pool_generates_per_model():
    shapes = gpu_count_shapes([_member(2, "H100"), _member(1, "A100")])
    assert shapes == (
        {"gpu": {"count": 1, "model": "A100"}},
        {"gpu": {"count": 1, "model": "H100"}},
        {"gpu": {"count": 2, "model": "H100"}},
    )


def test_members_without_a_usable_count_or_model_are_skipped():
    members = [
        _member(None),
        _member(0),
        _member(True),
        _member(4, model=None),
        _member(4, model=""),
        _member(5, enabled=False),
        {"attributes": {"gpu_model": "H100"}},
        _member(1),
    ]
    assert gpu_count_shapes(members) == ({"gpu": {"count": 1, "model": "H100"}},)
