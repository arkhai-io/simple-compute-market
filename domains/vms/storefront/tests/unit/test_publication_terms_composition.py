"""Composing a shape-priced listing's settlement clause rates."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from market_settlement_runtime import (
    SettlementPublicationClause,
    decimal_rate_to_base_units,
)
from market_storefront.services.publication_terms import compose_clause_rates

_TOKEN = "0x" + "11" * 20
_SHAPE = {
    "gpu": {"count": 2, "model": "H100"},
    "cpu": {"count": 16},
    "memory": {"gib": 128},
}


def _rates(rate: str, asset: str = _TOKEN) -> list[dict[str, str]]:
    return [{"asset": asset, "rate": rate, "per": "hour"}]


_FAMILY_RATES = {
    "gpu": _rates("80"),
    "cpu": _rates("0.5"),
    "memory": _rates("0.05"),
    "storage": _rates("0.001"),
}


def _alkahest(rate: str | None = None) -> SettlementPublicationClause:
    return SettlementPublicationClause(
        mechanism="alkahest.v1",
        asset=_TOKEN,
        rate=rate,
        per="hour" if rate is not None else None,
        mechanism_input={"chain": "anvil", "escrow_kind": "erc20_escrow_obligation_default"},
    )


class _Registry:
    """Answers only the question composition asks: scalar participation."""

    def __init__(self, non_scalar: set[str] = frozenset()) -> None:
        self._non_scalar = non_scalar

    def registration(self, mechanism: str) -> SimpleNamespace:
        return SimpleNamespace(negotiates_scalar_amount=mechanism not in self._non_scalar)


def test_a_listing_without_family_rates_is_flat_priced_and_unchanged() -> None:
    clauses = (_alkahest("100"),)

    composed = compose_clause_rates(clauses, listing_shape=_SHAPE, family_rates={})

    assert composed.clauses == clauses
    assert composed.clauses[0] is clauses[0]
    assert composed.rate_structure is None


def test_the_worked_example_composes_its_rate() -> None:
    composed = compose_clause_rates(
        (_alkahest(),),
        listing_shape=_SHAPE,
        family_rates=_FAMILY_RATES,
        registry=_Registry(),
    )

    (clause,) = composed.clauses
    assert (clause.rate, clause.per) == ("174.4", "hour")
    # What the Alkahest mechanism publishes for an 18-decimal token.
    assert decimal_rate_to_base_units(clause.rate, 18) == 174_400_000_000_000_000_000
    # Every resolved family is recorded, including storage, which this shape
    # omits: a revised shape priced from the record may name it.
    assert composed.rate_structure == _FAMILY_RATES


def test_the_storefront_registry_answers_scalar_participation() -> None:
    composed = compose_clause_rates(
        (_alkahest(),), listing_shape=_SHAPE, family_rates=_FAMILY_RATES
    )
    assert composed.clauses[0].rate == "174.4"


def test_gpu_only_listings_price_by_count() -> None:
    rates = [
        compose_clause_rates(
            (_alkahest(),),
            listing_shape={"gpu": {"count": n, "model": "H100"}},
            family_rates=_FAMILY_RATES,
            registry=_Registry(),
        ).clauses[0].rate
        for n in (1, 2, 8)
    ]
    assert rates == ["80", "160", "640"]


def test_a_non_scalar_mechanism_passes_through_rateless() -> None:
    other = SettlementPublicationClause(
        mechanism="contact-exchange.v1", asset="introduction"
    )

    composed = compose_clause_rates(
        (_alkahest(), other),
        listing_shape=_SHAPE,
        family_rates=_FAMILY_RATES,
        registry=_Registry(non_scalar={"contact-exchange.v1"}),
    )

    assert composed.clauses[0].rate == "174.4"
    assert composed.clauses[1] is other
    assert composed.clauses[1].rate is None


def test_a_shape_priced_clause_stating_its_own_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="states its own rate"):
        compose_clause_rates(
            (_alkahest("100"),),
            listing_shape=_SHAPE,
            family_rates=_FAMILY_RATES,
            registry=_Registry(),
        )


def test_a_family_without_a_rate_in_the_clause_asset_is_not_charged() -> None:
    rates = {**_FAMILY_RATES, "memory": _rates("0.05", asset="usd")}

    composed = compose_clause_rates(
        (_alkahest(),),
        listing_shape=_SHAPE,
        family_rates=rates,
        registry=_Registry(),
    )

    # 2 x 80 + 16 x 0.5; memory has no rate in this clause's asset.
    assert composed.clauses[0].rate == "168"


def test_a_listing_that_would_be_free_in_an_asset_is_refused() -> None:
    rates = {"gpu": _rates("80", asset="usd")}
    with pytest.raises(ValueError, match=r"would be free in asset"):
        compose_clause_rates(
            (_alkahest(),),
            listing_shape=_SHAPE,
            family_rates=rates,
            registry=_Registry(),
        )


def test_any_family_with_rates_makes_a_listing_shape_priced() -> None:
    composed = compose_clause_rates(
        (_alkahest(),),
        listing_shape=_SHAPE,
        family_rates={"cpu": _rates("0.5")},
        registry=_Registry(),
    )
    # No family is special: the GPUs are bundled, the vCPUs are charged.
    assert composed.clauses[0].rate == "8"


def test_an_omitted_family_is_not_priced() -> None:
    composed = compose_clause_rates(
        (_alkahest(),),
        listing_shape={"gpu": {"count": 1, "model": "H100"}},
        family_rates=_FAMILY_RATES,
        registry=_Registry(),
    )
    assert composed.clauses[0].rate == "80"
    assert composed.rate_structure == _FAMILY_RATES
