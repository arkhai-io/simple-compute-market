"""The profile and configuration a root passes are validated once and read everywhere."""

from __future__ import annotations

import dataclasses

import pytest
from arkhai_api.labels import IssuanceLabel
from arkhai_api_authority import AuthorityConfig, CapacityProfile
from market_resource_pools_contracts import BACKED, UNBACKED


def _profile(**overrides) -> CapacityProfile:
    values = dict(
        offering_mode="example",
        pool_provider="example_provider",
        pool_id="default",
        pool_label="Default Pool",
        deliverable_modes=frozenset({"example", "other"}),
        advertisable_modes=frozenset({"example"}),
        backing=BACKED,
    )
    values.update(overrides)
    return CapacityProfile(**values)


def test_the_profile_states_the_pools_declarations_in_the_resolvers_spelling():
    assert _profile().pool_policy_tags() == {
        "deliverable_modes": ["example", "other"],
        "advertisable_modes": ["example"],
        "capacity_backing": "backed",
    }
    assert _profile(backing=UNBACKED).pool_policy_tags()["capacity_backing"] == "unbacked"


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("offering_mode", "Api Credits", "underscores"),
        ("pool_provider", "", "underscores"),
        ("pool_id", " ", "empty"),
        ("pool_label", "", "empty"),
        ("deliverable_modes", frozenset(), "at least one"),
        ("advertisable_modes", frozenset({"bad mode"}), "at least one"),
        ("deliverable_modes", frozenset({"other"}), "include offering_mode"),
        ("advertisable_modes", frozenset({"example", "unlisted"}), "advertises only what it delivers"),
    ],
)
def test_an_invalid_profile_is_refused_naming_the_rule(field, value, reason):
    with pytest.raises(ValueError, match=reason):
        _profile(**{field: value})


def test_the_profile_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        _profile().offering_mode = "other"  # type: ignore[misc]


def test_the_configuration_validates_its_database_distribution_and_key_namespace():
    config = AuthorityConfig(
        label=IssuanceLabel("example"), profile=_profile(),
        database_url="sqlite:///:memory:", distribution="example-service", key_prefix="ak",
    )
    for field, value in (("database_url", " "), ("distribution", ""), ("key_prefix", "Ak-1")):
        with pytest.raises(ValueError):
            dataclasses.replace(config, **{field: value})
