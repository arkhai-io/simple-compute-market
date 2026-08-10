"""The inventory guard reads both row shapes it is fed.

A storefront-local resource row carries a `state` string. A site-authority
projection carries no `state` at all — it reports `enabled` plus an `available`
mapping. The guard filtered on `state` alone, so once `use_site_projection_for_listings`
flipped, every projected row was discarded before its attributes were examined
and the guard vetoed every negotiation against a correctly populated projection.
"""

from __future__ import annotations

from arkhai_vms.negotiation.policies import has_matching_inventory_guard
from market_policy import NegotiationContext

_OFFER = {"gpu_model": "RTX 4090", "region": "California, US"}


def _context(rows):
    return NegotiationContext(
        direction="maximize",
        our_reference_amount=100,
        listing={"offer_resource": dict(_OFFER)},
        available_resources={"resources": rows},
    )


def _projected(**overrides):
    """A row shaped as the site authority projects it — no `state` key."""
    row = {
        "resource_id": "kvm1",
        "pool_id": "default",
        "resource_type": "compute.gpu",
        "enabled": True,
        "capacity": {"gpu_count": 4},
        "available": {"gpu_count": 4},
        "attributes": dict(_OFFER) | {"vm_host": "kvm1"},
    }
    row.update(overrides)
    return row


def _local(**overrides):
    """A row shaped as the storefront's own table stores it."""
    row = {"state": "available", "attributes": dict(_OFFER)}
    row.update(overrides)
    return row


def test_a_matching_projected_row_is_accepted() -> None:
    decision, _ = has_matching_inventory_guard([], _context([_projected()]))

    assert decision is None


def test_a_matching_local_row_is_still_accepted() -> None:
    """The local shape must keep working — both reach this guard."""
    decision, _ = has_matching_inventory_guard([], _context([_local()]))

    assert decision is None


def test_a_local_row_that_is_not_available_is_rejected() -> None:
    decision, _ = has_matching_inventory_guard([], _context([_local(state="reserved")]))

    assert decision is not None
    assert decision.reason == "no_matching_inventory"


def test_a_disabled_projected_row_is_rejected() -> None:
    decision, _ = has_matching_inventory_guard([], _context([_projected(enabled=False)]))

    assert decision is not None


def test_a_projected_row_with_nothing_left_is_rejected() -> None:
    row = _projected(available={"gpu_count": 0})

    decision, _ = has_matching_inventory_guard([], _context([row]))

    assert decision is not None


def test_a_projected_row_without_an_available_key_is_accepted() -> None:
    """Unreported remaining capacity is not zero remaining capacity.

    The fallback projection for a host with no registered capacity resource omits
    `available`; that is the shape a host-seeded deployment sells with today.
    """
    row = _projected()
    del row["available"]

    decision, _ = has_matching_inventory_guard([], _context([row]))

    assert decision is None


def test_a_projected_row_with_the_wrong_region_is_rejected() -> None:
    row = _projected(attributes={"gpu_model": "RTX 4090", "region": "Oregon, US"})

    decision, _ = has_matching_inventory_guard([], _context([row]))

    assert decision is not None


def test_an_empty_portfolio_is_rejected() -> None:
    decision, _ = has_matching_inventory_guard([], _context([]))

    assert decision is not None
