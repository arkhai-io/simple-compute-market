"""Projected pool declarations are judged jointly per site generation."""

from __future__ import annotations

from market_resource_pools import (
    POOL_ENABLEMENT_UNDECLARED,
    read_site_declarations,
)


def _pool(pool_id: str, *, enabled: bool | None = True, **tags) -> dict:
    metadata: dict = {"policy_tags": {"deliverable_modes": ["vm"], **tags}}
    if enabled is not None:
        metadata["enabled"] = enabled
    return {"resource_pool_id": pool_id, "pool_metadata": metadata, "resources": []}


_DECLARED = {"advertisable_modes": ["vm"], "capacity_backing": "backed"}


def test_a_generation_with_neither_declaration_reads_as_an_older_producer():
    reading = read_site_declarations([_pool("p1"), _pool("p2", enabled=None)])

    assert reading.compatibility_rule is True
    assert reading.unresolvable == {}
    for pool_id in ("p1", "p2"):
        declaration = reading.resolved[pool_id]
        assert declaration.backed
        assert declaration.advertises("vm")
        assert declaration.enabled


def test_an_older_producer_advertises_exactly_what_it_delivers():
    reading = read_site_declarations(
        [_pool("p1", deliverable_modes=["bare_metal"])]
    )

    assert not reading.resolved["p1"].advertises("vm")


def test_a_generation_declaring_every_pool_resolves_normally():
    reading = read_site_declarations(
        [
            _pool("backed", **_DECLARED),
            _pool(
                "unbacked",
                deliverable_modes=[],
                advertisable_modes=["vm"],
                capacity_backing="unbacked",
            ),
        ]
    )

    assert reading.compatibility_rule is False
    assert reading.resolved["backed"].backed
    assert not reading.resolved["unbacked"].backed
    assert reading.resolved["unbacked"].advertises("vm")


def test_one_pool_omitting_both_declarations_is_unresolvable_not_defaulted():
    reading = read_site_declarations([_pool("p1", **_DECLARED), _pool("p3")])

    assert "p1" in reading.resolved
    assert "p3" in reading.unresolvable
    assert "p3" not in reading.resolved


def test_a_generation_carrying_only_backing_is_not_an_older_producer():
    reading = read_site_declarations(
        [_pool("p1", capacity_backing="backed"), _pool("p2"), _pool("p3")]
    )

    assert reading.compatibility_rule is False
    assert set(reading.unresolvable) == {"p1", "p2", "p3"}


def test_an_unrecognized_backing_value_gets_no_tolerant_reading():
    reading = read_site_declarations(
        [_pool("p1", advertisable_modes=["vm"], capacity_backing="Backed")]
    )

    assert "p1" in reading.unresolvable


def test_a_backed_pool_advertising_what_it_does_not_deliver_is_unresolvable():
    reading = read_site_declarations(
        [
            _pool(
                "p1",
                deliverable_modes=[],
                advertisable_modes=["vm"],
                capacity_backing="backed",
            )
        ]
    )

    assert "p1" in reading.unresolvable


def test_a_disabled_pool_resolves_as_disabled():
    reading = read_site_declarations([_pool("p1", enabled=False, **_DECLARED)])

    assert reading.resolved["p1"].enabled is False


def test_a_current_producer_that_omits_enablement_is_unresolvable():
    reading = read_site_declarations([_pool("p1", enabled=None, **_DECLARED)])

    assert reading.unresolvable["p1"] == (POOL_ENABLEMENT_UNDECLARED,)


def test_a_generation_with_no_pools_is_not_read_as_an_older_producer():
    reading = read_site_declarations([])

    assert reading.compatibility_rule is False
    assert (dict(reading.resolved), dict(reading.unresolvable)) == ({}, {})


def test_a_generation_whose_only_pool_has_no_id_has_no_pools_to_read():
    reading = read_site_declarations([_pool("")])

    assert reading.compatibility_rule is False
    assert dict(reading.resolved) == {}
