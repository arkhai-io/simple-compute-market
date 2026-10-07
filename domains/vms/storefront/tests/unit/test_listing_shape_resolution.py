"""Per-listing resolution of VM listing shapes and their admissibility.

The listings package has no suite of its own; the storefront's unit suite
covers it. Policies are opaque, so each is examined only through the
admissibility kit's own evaluation.
"""

from __future__ import annotations

import pytest
from market_capability_admissibility import ProblemCode, parse_declaration

from arkhai_vms import VM_CAPABILITY_SCHEMA
from arkhai_vms_listings import resolve_vm_asking_rates
from arkhai_vms_listings.listing_shapes import (
    CONFIGURED_DEFAULT_TIER,
    SHAPE_SOURCE_DEFAULT,
    SHAPE_SOURCE_HINT,
    SHAPE_SOURCE_OVERRIDE,
    resolve_shape,
    resolve_vm_listing_shapes,
)

H100 = {"gpu": {"model": "H100"}}


def _default(raw):
    parsed = parse_declaration(raw, tier=CONFIGURED_DEFAULT_TIER, schema=VM_CAPABILITY_SCHEMA)
    assert parsed.declaration is not None, parsed.problems
    return parsed.declaration


def _hint(*shapes):
    return {"listing_shapes": {"vm": list(shapes)}}


def _member(count, model="H100"):
    return {"capacity": {"gpu_count": count}, "attributes": {"gpu_model": model}, "enabled": True}


def _resolve(policy_tags, *, default=None, override=None, members=()):
    return resolve_vm_listing_shapes(
        policy_tags,
        members,
        configured_default=default,
        override_shapes=override,
    )


def _gpu_counts(policy):
    values = policy.admissible_values("gpu.count", H100)
    return values.minimum, values.maximum


class TestStatedShapes:
    def test_shorthand_scalars_are_listings_constrained_by_nothing(self):
        shape = {"gpu": {"model": "H100", "count": 2}, "memory": {"gib": 64}}
        resolution = _resolve(_hint(shape))
        assert resolution.source == SHAPE_SOURCE_HINT and not resolution.unreadable
        (listing,) = resolution.listings
        assert listing.shape == resolve_shape(shape)
        assert listing.policy is not None and listing.policy_problems == ()
        assert _gpu_counts(listing.policy) == (1, None)

    def test_a_constrained_offer_is_the_base_shape_and_bounds_the_policy(self):
        resolution = _resolve(_hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}))
        (listing,) = resolution.listings
        assert listing.shape.shape == {"gpu": {"count": 1, "model": "H100"}}
        assert _gpu_counts(listing.policy) == (1, 4)

    def test_a_constraint_only_field_is_omitted_from_the_base_shape(self):
        resolution = _resolve(
            _hint({"gpu": {"model": "H100", "count": 1}, "memory": {"gib": {"max": 512}}})
        )
        (listing,) = resolution.listings
        assert listing.shape.shape == {"gpu": {"count": 1, "model": "H100"}}
        assert "ram_gb" not in listing.shape.quantities
        (problem,) = listing.policy.admissibility_problems(
            {"gpu": {"model": "H100", "count": 1}, "memory": {"gib": 1024}}
        )
        assert problem.code is ProblemCode.ABOVE_MAXIMUM
        assert problem.tier == SHAPE_SOURCE_HINT

    def test_identical_entries_are_one_listing(self):
        shape = {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}
        assert len(_resolve(_hint(shape, shape)).listings) == 1


class TestConfiguredDefault:
    def test_a_listing_narrows_the_configured_default(self):
        resolution = _resolve(
            _hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}),
            default=_default({"gpu": {"count": {"min": 1, "max": 16}}}),
        )
        assert _gpu_counts(resolution.listings[0].policy) == (1, 4)

    def test_a_listing_widens_the_configured_default(self):
        resolution = _resolve(
            _hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 32}}}),
            default=_default({"gpu": {"count": {"max": 16}}}),
        )
        assert _gpu_counts(resolution.listings[0].policy) == (1, 32)

    def test_the_default_fills_a_field_the_listing_leaves_unconstrained(self):
        resolution = _resolve(
            _hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}),
            default=_default({"memory": {"gib": {"max": 512}}}),
        )
        (problem,) = resolution.listings[0].policy.admissibility_problems(
            {"gpu": {"model": "H100", "count": 1}, "memory": {"gib": 1024}}
        )
        assert problem.tier == CONFIGURED_DEFAULT_TIER

    def test_an_override_does_not_inherit_the_hints_constraints(self):
        hint = _hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}})
        resolution = _resolve(
            hint,
            default=_default({"gpu": {"count": {"max": 16}}}),
            override=[{"gpu": {"model": "H100", "count": 1}}],
        )
        assert resolution.source == SHAPE_SOURCE_OVERRIDE
        assert _gpu_counts(resolution.listings[0].policy) == (1, 16)

    def test_override_constraints_carry_the_override_tier(self):
        resolution = _resolve(
            {}, override=[{"gpu": {"model": "H100", "count": {"offer": 1, "max": 2}}}]
        )
        (problem,) = resolution.listings[0].policy.admissibility_problems(
            {"gpu": {"model": "H100", "count": 3}}
        )
        assert problem.tier == SHAPE_SOURCE_OVERRIDE


class TestGeneratedShapes:
    def test_a_generated_shapes_policy_is_the_configured_default_alone(self):
        resolution = _resolve(
            {}, default=_default({"gpu": {"count": {"max": 4}}}), members=[_member(8)]
        )
        assert resolution.source == SHAPE_SOURCE_DEFAULT
        assert [listing.shape.gpu_count for listing in resolution.listings] == [1, 2, 3, 4]
        assert all(_gpu_counts(listing.policy) == (1, 4) for listing in resolution.listings)

    def test_with_no_configured_default_generation_is_unchanged(self):
        resolution = _resolve({}, members=[_member(3)])
        assert [listing.shape.gpu_count for listing in resolution.listings] == [1, 2, 3]
        assert all(listing.policy is not None for listing in resolution.listings)


class TestUncomputablePolicy:
    """Every base shape reads, so the list is readable; one listing has no policy."""

    PLAIN = {"gpu": {"model": "A100", "count": 1}}

    def _uncomputable(self, resolution):
        assert not resolution.unreadable
        computable = [listing for listing in resolution.listings if listing.policy is not None]
        assert [listing.shape.gpu_model for listing in computable] == ["A100"]
        (listing,) = [listing for listing in resolution.listings if listing.policy is None]
        return listing

    def test_an_unknown_constraint_key(self):
        listing = self._uncomputable(_resolve(_hint(
            self.PLAIN, {"gpu": {"model": "H100", "count": {"offer": 1, "step": 2}}},
        )))
        (problem,) = listing.policy_problems
        assert problem.code is ProblemCode.UNKNOWN_CONSTRAINT_KEY
        assert problem.paths == ("gpu.count",)

    def test_a_constraint_on_a_field_the_vm_domain_does_not_define(self):
        listing = self._uncomputable(_resolve(_hint(
            self.PLAIN, {"gpu": {"model": "H100", "count": 1}, "memory": {"foo": {"max": 4}}},
        )))
        (problem,) = listing.policy_problems
        assert problem.code is ProblemCode.NOT_A_QUANTITY
        assert problem.paths == ("memory.foo",)

    def test_an_empty_merged_range_names_both_tiers(self):
        listing = self._uncomputable(_resolve(
            _hint(self.PLAIN, {"gpu": {"model": "H100", "count": {"offer": 1, "max": 2}}}),
            default=_default({"gpu": {"count": {"min": 4}}}),
        ))
        (problem,) = listing.policy_problems
        assert problem.code is ProblemCode.EMPTY_RANGE
        assert {(bound.tier, bound.value) for bound in problem.bounds} == {
            (SHAPE_SOURCE_HINT, 2),
            (CONFIGURED_DEFAULT_TIER, 4),
        }

    def test_one_base_shape_stated_with_different_constraints(self):
        listing = self._uncomputable(_resolve(_hint(
            {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}},
            self.PLAIN,
            {"gpu": {"model": "H100", "count": {"offer": 1, "max": 8}}},
        )))
        (problem,) = listing.policy_problems
        assert problem.code is ProblemCode.CONFLICTING_DUPLICATE
        assert problem.entries == (0, 2)


class TestUnreadableBaseShape:
    @pytest.mark.parametrize(
        ("shape", "fragment"),
        [
            ({"gpu": {"model": {"max": 4}, "count": 1}}, "gpu.model"),
            ({"gpu": {"model": "H100", "count": {"min": 2, "max": 8}}}, "gpu.count"),
            ({"gpu": {"model": "H100", "count": 1}, "network": {"gbps": 10}}, "network"),
        ],
    )
    def test_any_unreadable_base_shape_makes_the_list_unreadable(self, shape, fragment):
        resolution = _resolve(_hint({"gpu": {"model": "A100", "count": 1}}, shape))
        assert resolution.unreadable
        assert resolution.listings == ()
        assert any(problem.startswith("[1] ") and fragment in problem for problem in resolution.problems)


class TestIdentity:
    def test_identity_is_the_base_shape_whatever_the_constraints(self):
        digests = {
            _resolve(_hint({"gpu": {"model": "H100", "count": count}})).listings[0].shape.digest
            for count in (1, {"offer": 1}, {"offer": 1, "max": 4}, {"offer": 1, "min": 1, "max": 8})
        }
        assert len(digests) == 1

    def test_an_asking_rate_for_the_plain_shape_prices_the_constrained_listing(self):
        tags = {
            **_hint({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}),
            "asking_rates": {"vm": [{
                "shape": {"gpu": {"model": "H100", "count": 1}},
                "amount": "2.10", "asset": "usd", "period": "hour",
            }]},
        }
        (listing,) = _resolve(tags).listings
        rates = resolve_vm_asking_rates(tags)
        assert not rates.unreadable
        assert rates.rate_for(listing.shape.digest) is not None
