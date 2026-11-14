"""The five-tier resolution of a listing's settlement terms."""

from __future__ import annotations

import pytest

from market_resource_pools_contracts import (
    CapacityBounds,
    ListingTerms,
    model_hint_bounds,
    resolve_listing_terms,
)

FAMILY = "gpu"
OVERRIDE = ListingTerms(accepted_escrows=["override"], settlements=["override"])
MODEL_CONFIG = {"H100": ListingTerms(accepted_escrows=["model-config"], settlements=["model-config"])}
FLAT = ListingTerms(accepted_escrows=["flat"], settlements=["flat"])


def _tags(*, model: dict | None = None, pool: list | None = None) -> dict:
    pricing: dict = {}
    if model is not None:
        pricing[FAMILY] = {"H100": model}
    if pool is not None:
        pricing["settlements"] = pool
    return {"pricing": pricing}


def _resolve(tags, *, model="H100", override=ListingTerms(), config=MODEL_CONFIG, flat=FLAT):
    return resolve_listing_terms(
        tags,
        model_family=FAMILY,
        model=model,
        storefront_override=override,
        config_defaults_by_model=config,
        flat_default=flat,
    )


class TestEachTierWins:
    """Each tier supplies the terms when every tier above it states nothing."""

    TAGS = _tags(model={"accepted_escrows": ["model-hint"], "settlements": ["model-hint"]}, pool=["pool-hint"])

    def test_the_override_wins_over_every_tier(self):
        assert _resolve(self.TAGS, override=OVERRIDE) == OVERRIDE

    def test_the_model_hint_wins_below_the_override(self):
        assert _resolve(self.TAGS) == ListingTerms(
            accepted_escrows=["model-hint"], settlements=["model-hint"]
        )

    def test_the_pool_hint_wins_below_the_model_hint(self):
        # The pool-level hint states clauses only; the model configuration
        # supplies the accepted escrows the pool hint has no opinion on.
        assert _resolve(_tags(pool=["pool-hint"])) == ListingTerms(
            accepted_escrows=["model-config"], settlements=["pool-hint"]
        )

    def test_the_model_configuration_wins_below_the_hints(self):
        assert _resolve({}) == MODEL_CONFIG["H100"]

    def test_the_flat_configuration_is_the_last_tier(self):
        assert _resolve({}, model="A100") == FLAT

    def test_nothing_stated_resolves_nothing(self):
        assert _resolve({}, config={}, flat=ListingTerms()) == ListingTerms()


class TestFieldByField:
    def test_a_tier_stating_one_field_lets_the_other_fall_through(self):
        result = _resolve(
            _tags(model={"settlements": ["model-hint"]}),
            override=ListingTerms(accepted_escrows=["override"]),
        )
        assert result == ListingTerms(accepted_escrows=["override"], settlements=["model-hint"])

    def test_a_clause_list_resolves_whole_and_is_never_merged(self):
        result = _resolve(_tags(model={"settlements": ["a"]}, pool=["b", "c"]))
        assert result.settlements == ["a"]

    def test_an_empty_list_is_a_statement_that_stops_lower_tiers(self):
        assert _resolve(_tags(pool=[])).settlements == []
        assert _resolve(_tags(model={"settlements": []}, pool=["pool-hint"])).settlements == []


class TestTheModel:
    def test_a_hint_for_another_model_is_not_this_models(self):
        tags = {"pricing": {FAMILY: {"A100": {"settlements": ["a100"]}}}}
        assert _resolve(tags).settlements == ["model-config"]

    def test_a_listing_without_a_model_reads_the_override_pool_hint_and_flat_tiers(self):
        tags = _tags(model={"settlements": ["model-hint"]})
        assert _resolve(tags, model=None) == FLAT
        assert _resolve(_tags(pool=["pool-hint"]), model=None).settlements == ["pool-hint"]

    def test_the_family_is_data(self):
        tags = {"pricing": {"accelerator": {"X1": {"settlements": ["x1"]}}}}
        result = resolve_listing_terms(
            tags, model_family="accelerator", model="X1", flat_default=FLAT
        )
        assert result.settlements == ["x1"]


class TestAMalformedHint:
    @pytest.mark.parametrize(
        "tags",
        [
            {"pricing": "not-a-mapping"},
            {"pricing": {FAMILY: "not-a-mapping"}},
            {"pricing": {FAMILY: {"H100": "not-a-mapping"}}},
            _tags(model={"settlements": "not-a-list", "accepted_escrows": {"a": 1}}),
            _tags(pool={"not": "a list"}),
            _tags(pool="not-a-list"),
        ],
    )
    def test_a_field_of_the_wrong_shape_falls_through_like_an_absent_one(self, tags):
        assert _resolve(tags) == MODEL_CONFIG["H100"]

    def test_a_pool_level_accepted_escrow_list_is_not_read(self):
        tags = {"pricing": {"accepted_escrows": ["pool"]}}
        assert _resolve(tags, model="A100").accepted_escrows == ["flat"]


class TestModelHintBounds:
    def test_a_model_hint_states_bounds(self):
        tags = _tags(model={"max_duration_seconds": 3600, "available_until_utc": "2030-01-01T00:00:00+00:00"})
        assert model_hint_bounds(tags, model_family=FAMILY, model="H100") == CapacityBounds(
            max_duration_seconds=3600, available_until_utc="2030-01-01T00:00:00Z"
        )

    def test_no_model_or_no_hint_states_none(self):
        assert model_hint_bounds({}, model_family=FAMILY, model="H100") == CapacityBounds()
        tags = _tags(model={"max_duration_seconds": 3600})
        assert model_hint_bounds(tags, model_family=FAMILY, model=None) == CapacityBounds()

    @pytest.mark.parametrize(
        "model",
        [{"max_duration_seconds": "3600"}, {"available_until_utc": "2030-01-01T00:00:00"}],
    )
    def test_a_malformed_bound_is_refused_not_ignored(self, model):
        with pytest.raises(ValueError):
            model_hint_bounds(_tags(model=model), model_family=FAMILY, model="H100")
