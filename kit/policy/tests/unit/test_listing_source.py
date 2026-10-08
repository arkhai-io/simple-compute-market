"""The listing-source classifier and the inventory guard that applies it."""

from __future__ import annotations

import pytest

from market_policy import (
    LISTING_SOURCE_UNVERIFIABLE,
    NO_MATCHING_DECLARATION,
    NO_MATCHING_INVENTORY,
    ListingSourceRefusal,
    ListingSourceVerdict,
    NegotiationContext,
    classify_listing_source,
    load_negotiation_chain,
)
from market_policy.listing_source import has_matching_inventory_guard


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        (ListingSourceVerdict("matches"), None),
        (
            ListingSourceVerdict("declared_mismatch", "shape changed", ("gpu_count",)),
            ListingSourceRefusal(NO_MATCHING_DECLARATION),
        ),
        (
            ListingSourceVerdict("unavailable"),
            ListingSourceRefusal(NO_MATCHING_INVENTORY),
        ),
        (
            ListingSourceVerdict("unverifiable", "site unreachable"),
            ListingSourceRefusal(LISTING_SOURCE_UNVERIFIABLE, retryable=True),
        ),
        (None, ListingSourceRefusal(NO_MATCHING_DECLARATION)),
    ],
)
def test_each_verdict_classifies_to_one_refusal(verdict, expected) -> None:
    assert classify_listing_source(verdict) == expected


def test_a_refusal_names_no_source_detail() -> None:
    refusal = classify_listing_source(
        ListingSourceVerdict("declared_mismatch", "pool p1 declares 4 GPUs", ("gpu_count",))
    )
    assert refusal is not None and refusal.reason == NO_MATCHING_DECLARATION


def test_an_unknown_outcome_is_refused_at_construction() -> None:
    with pytest.raises(ValueError):
        ListingSourceVerdict("maybe")  # type: ignore[arg-type]


def _context(verdict: ListingSourceVerdict | None) -> NegotiationContext:
    return NegotiationContext(
        direction="maximize", our_reference_amount=100, listing_source=verdict
    )


@pytest.mark.parametrize(
    ("verdict", "reason"),
    [
        (ListingSourceVerdict("declared_mismatch"), NO_MATCHING_DECLARATION),
        (ListingSourceVerdict("unavailable"), NO_MATCHING_INVENTORY),
        (None, NO_MATCHING_DECLARATION),
    ],
)
def test_the_guard_rejects_with_the_classified_reason(verdict, reason) -> None:
    decision, _ = has_matching_inventory_guard([], _context(verdict))
    assert decision is not None
    assert (decision.action, decision.reason) == ("reject", reason)


@pytest.mark.parametrize(
    "verdict",
    [ListingSourceVerdict("matches"), ListingSourceVerdict("unverifiable")],
)
def test_the_guard_passes_a_match_and_leaves_a_retryable_refusal_to_the_runtime(
    verdict,
) -> None:
    decision, context = has_matching_inventory_guard([], _context(verdict))
    assert decision is None
    assert context.listing_source is verdict


def test_the_guard_resolves_by_its_name_from_the_policy_kit() -> None:
    assert load_negotiation_chain(["has_matching_inventory_guard"]) == [
        has_matching_inventory_guard
    ]
