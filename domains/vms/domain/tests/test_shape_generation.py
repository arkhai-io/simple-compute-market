"""The default VM listing-shape generator."""

from __future__ import annotations

from market_capability_admissibility import parse_declaration, resolve

from arkhai_vms import DEFAULT_LISTING_SHAPE_GENERATOR, VM_CAPABILITY_SCHEMA, gpu_count_shapes


def _policy(default=None):
    """The default-only policy: ``default`` as the configured default, or none."""
    declarations = []
    if default is not None:
        parsed = parse_declaration(
            default, tier="configured_default", schema=VM_CAPABILITY_SCHEMA
        )
        assert parsed.declaration is not None, parsed.problems
        declarations.append(parsed.declaration)
    resolution = resolve(declarations, VM_CAPABILITY_SCHEMA)
    assert resolution.policy is not None, resolution.problems
    return resolution.policy


UNCONSTRAINED = _policy()


def _member(count, model="H100", *, enabled=True, **capacity):
    member = {"capacity": {"gpu_count": count, **capacity}, "attributes": {}, "enabled": enabled}
    if model is not None:
        member["attributes"]["gpu_model"] = model
    return member


def test_the_default_generator_is_gpu_count_enumeration():
    assert DEFAULT_LISTING_SHAPE_GENERATOR is gpu_count_shapes


def test_single_model_pool_ranges_to_its_largest_member():
    shapes = gpu_count_shapes([_member(2), _member(3, ram_gb=512)], UNCONSTRAINED)
    assert shapes == tuple({"gpu": {"count": n, "model": "H100"}} for n in (1, 2, 3))


def test_shapes_declare_the_gpu_family_only():
    (shape,) = gpu_count_shapes([_member(1, vcpu_count=64, ram_gb=512, disk_gb=900)], UNCONSTRAINED)
    assert set(shape) == {"gpu"}


def test_mixed_model_pool_generates_per_model():
    shapes = gpu_count_shapes([_member(2, "H100"), _member(1, "A100")], UNCONSTRAINED)
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
    assert gpu_count_shapes(members, UNCONSTRAINED) == ({"gpu": {"count": 1, "model": "H100"}},)


def test_with_no_configured_default_every_count_is_generated():
    shapes = gpu_count_shapes([_member(3)], _policy({}))
    assert [shape["gpu"]["count"] for shape in shapes] == [1, 2, 3]


def test_a_configured_maximum_bounds_the_counts():
    shapes = gpu_count_shapes([_member(8)], _policy({"gpu": {"count": {"max": 4}}}))
    assert [shape["gpu"]["count"] for shape in shapes] == [1, 2, 3, 4]


def test_a_configured_minimum_starts_the_counts():
    shapes = gpu_count_shapes([_member(8)], _policy({"gpu": {"count": {"min": 6}}}))
    assert [shape["gpu"]["count"] for shape in shapes] == [6, 7, 8]


def test_a_minimum_above_every_member_generates_nothing():
    assert gpu_count_shapes([_member(2), _member(3)], _policy({"gpu": {"count": {"min": 4}}})) == ()


def test_each_model_is_bounded_alike():
    shapes = gpu_count_shapes(
        [_member(8, "H100"), _member(2, "A100")],
        _policy({"gpu": {"count": {"max": 3}}}),
    )
    assert shapes == (
        {"gpu": {"count": 1, "model": "A100"}},
        {"gpu": {"count": 2, "model": "A100"}},
        {"gpu": {"count": 1, "model": "H100"}},
        {"gpu": {"count": 2, "model": "H100"}},
        {"gpu": {"count": 3, "model": "H100"}},
    )


def test_a_constraint_on_another_dimension_does_not_bound_gpu_count():
    shapes = gpu_count_shapes([_member(2)], _policy({"memory": {"gib": {"max": 64}}}))
    assert [shape["gpu"]["count"] for shape in shapes] == [1, 2]
