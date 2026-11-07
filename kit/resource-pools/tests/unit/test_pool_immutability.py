"""Pure comparisons of a pool's stored and proposed routing context."""

import pytest

from market_resource_pools.db import ResourcePool
from market_resource_pools.service import pool_immutability_problems


@pytest.mark.parametrize("provider", ["ansible", "bare_metal.ansible"])
@pytest.mark.parametrize("backing", ["backed", "unbacked"])
def test_each_changed_field_is_reported_with_values(provider, backing):
    pool = ResourcePool(
        id="hetzner-eu", provider="ansible", policy_tags={"capacity_backing": "backed"},
    )

    problems = pool_immutability_problems(pool, provider, {"capacity_backing": backing})

    assert [(p.field, p.code, p.stored, p.supplied) for p in problems] == (
        ([("provider", "provider_immutable", "ansible", provider)] if provider != "ansible" else [])
        + ([("policy_tags.capacity_backing", "capacity_backing_immutable", "backed", backing)]
           if backing != "backed" else [])
    )
    assert pool.provider == "ansible"
    assert pool.policy_tags == {"capacity_backing": "backed"}


@pytest.mark.parametrize("tags", [None, {}, {"capacity_backing": None}])
def test_missing_stored_backing_allows_repair_but_not_provider_change(tags):
    pool = ResourcePool(id="legacy", provider="ansible", policy_tags=tags)

    assert pool_immutability_problems(pool, "ansible", {"capacity_backing": "backed"}) == ()
    assert [p.code for p in pool_immutability_problems(
        pool, "bare_metal.ansible", {"capacity_backing": "backed"},
    )] == ["provider_immutable"]


def test_messages_are_stable_and_explain_the_supported_path():
    pool = ResourcePool(
        id="hetzner-eu", provider="ansible", policy_tags={"capacity_backing": "backed"},
    )

    provider, backing = pool_immutability_problems(
        pool, "bare_metal.ansible", {"capacity_backing": "unbacked"},
    )

    assert provider.message == (
        "provider of pool 'hetzner-eu' is fixed at creation as 'ansible' and cannot "
        "become 'bare_metal.ansible'; declare a second pool with the intended "
        "provider and migrate its members instead"
    )
    assert backing.message == (
        "capacity_backing of pool 'hetzner-eu' is fixed at creation as 'backed' "
        "and cannot become 'unbacked'; declare a second pool with the intended backing instead"
    )


def test_removing_stored_backing_is_a_change():
    pool = ResourcePool(id="pool", provider="provider", policy_tags={"capacity_backing": "backed"})

    problem, = pool_immutability_problems(pool, "provider", {})

    assert problem.code == "capacity_backing_immutable"
    assert problem.supplied is None
