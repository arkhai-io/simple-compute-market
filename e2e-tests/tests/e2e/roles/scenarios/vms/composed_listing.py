"""A VM resource's one listing, offering every mechanism a deal on it settles by.

A listing's binding to its capacity source outlives the listing. Modules on a
resource share its sole open listing, retaining closed bindings as history.
Closed history alone does not allow replacement creation, and multiple open
listings are ambiguous. A real-provisioning target's modules settle through
Alkahest or through Arkhai payments.

So creation states one settlement for each deal mechanism the storefront
reports ready — Alkahest and Arkhai payments, the mechanisms a buyer pays for
the resource's capacity by — and adoption requires the listing to offer the
adopting module's own mechanism. A listing that does not fails the module
naming the listing and its options, before any deal and changing nothing. On a
stack composing one of them, the listing offers that one.

The settlements a VM listing states for Arkhai payments are built here too
(``payments_settlement``), for every VM module listing in that mechanism, and so
are the real-provisioning target's resource and the settlements every module
dealing on it states (``real_target_resource``, ``listing_settlements``).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from market_alkahest.plans import ALKAHEST_MECHANISM
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM

from e2e_harness.real_provisioning_target import VmHost
from tests.e2e.roles.helpers.compute_deal_stages import DEAL_TOKEN, LISTED_HOURLY_RATE
from tests.e2e.roles.helpers.payments import dispute_window_seconds, payment_setting
from tests.e2e.roles.scenarios.vms.conftest import capacity_source_for
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import REAL_REGION, REAL_RESOURCE_ID

#: The mechanisms a buyer pays for a VM resource's capacity by, which a
#: resource's listing offers wherever the storefront reports them ready. A
#: mechanism settling no paid deal, such as contact exchange, is not one.
DEAL_MECHANISMS = (ALKAHEST_MECHANISM, ARKHAI_PAYMENTS_MECHANISM)
#: The most listings one read of the storefront's listings asks for: the
#: largest page the storefront serves, which refuses a larger limit.
_LISTING_PAGE = 200
#: The default delivery latency, covered by the run's dispute coverage.
DELIVERY_DEADLINE_SECONDS = 300


def delivery_deadline_seconds() -> int:
    """The VM run's declared delivery allowance, a positive whole-second input."""
    value = payment_setting("VM_DELIVERY_DEADLINE_SECONDS", DELIVERY_DEADLINE_SECONDS)
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdecimal() and int(value.strip()) > 0:
        return int(value.strip())
    pytest.fail(
        "PAYMENTS.VM_DELIVERY_DEADLINE_SECONDS must be a positive integer number "
        f"of seconds, not {value!r}"
    )


def payments_settlement(
    *, seller_account: str, dispute_window: str, hourly_rate: str = "1.00",
) -> dict[str, Any]:
    """A VM listing's Arkhai payments settlement: ``hourly_rate`` USD an hour,
    paid to ``seller_account``, under the seller's dispute window, with the
    run's dispute coverage."""
    deadline = delivery_deadline_seconds()
    return {
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": "USD/6", "rate": hourly_rate,
        "per": "hour",
        "mechanism_input": {
            "payee_account": seller_account, "asset": "USD/6", "window": dispute_window,
            "delivery_deadline_seconds": deadline,
            "dispute_window_seconds": dispute_window_seconds(
                delivery_deadline_seconds=deadline,
            ),
        },
    }


#: The canonical deal's asking rate on the dev chain's deal token, stated in
#: whole tokens an hour, which the storefront's Alkahest composition publishes
#: in the token's base units as ``LISTED_HOURLY_RATE``; a deal settles on the
#: escrow the published option names.
ALKAHEST_SETTLEMENT = {
    "mechanism": ALKAHEST_MECHANISM,
    "asset": DEAL_TOKEN["contract_address"],
    "rate": str(Decimal(LISTED_HOURLY_RATE) / 10 ** DEAL_TOKEN["decimals"]),
    "per": "hour",
    "mechanism_input": {"chain": "anvil", "escrow_kind": "erc20_escrow_obligation_default"},
}


def listing_settlements() -> dict[str, dict]:
    """The settlement every module on the real target's resource states for
    each mechanism it can.

    Alkahest always; Arkhai payments where the run names the seller's payments
    account, so a stack composing it lists the resource with both, and a module
    of either mechanism, whichever runs first, creates the listing the other
    adopts.
    """
    settlements = {ALKAHEST_MECHANISM: ALKAHEST_SETTLEMENT}
    seller_account = payment_setting("SELLER_ACCOUNT")
    if seller_account:
        settlements[ARKHAI_PAYMENTS_MECHANISM] = payments_settlement(
            seller_account=str(seller_account),
            dispute_window=str(payment_setting("DISPUTE_WINDOW", "P7D")),
        )
    return settlements


def real_target_resource(target: VmHost) -> dict[str, Any]:
    """The real-provisioning target's resource: its explicit guest listing
    shape, and no GPU."""
    return {
        "offering_mode": "vm",
        "interruptible": True,
        "resource_id": target.resource_id or REAL_RESOURCE_ID,
        **target.listing_shape.model_dump(),
        "sla": 90.0,
        "region": REAL_REGION,
    }


def ready_mechanisms(storefront_admin_client: Any) -> tuple[str, ...]:
    """The deal mechanisms the storefront reports ready, in its order."""
    status = storefront_admin_client.get_system_status()
    assert status.settlement is not None, (
        f"the storefront reports no settlement readiness in its system status: {status}"
    )
    return tuple(
        item["mechanism"] for item in status.settlement
        if item.get("ready") and item["mechanism"] in DEAL_MECHANISMS
    )


def listing_mechanisms(listing: Any) -> tuple[str, ...]:
    """The mechanisms a storefront listing's settlement options name, one per option."""
    return tuple(
        (item.get("settlement") or {}).get("schema")
        for item in listing.extra.get("settlement_options") or ()
    )


def create_or_adopt_listing(
    *,
    storefront_admin_client: Any,
    storefront_seller_client: Any,
    resource: Mapping[str, Any],
    shape: Mapping[str, Any],
    mechanism: str,
    settlements: Mapping[str, Mapping[str, Any]],
    max_duration_seconds: int,
) -> tuple[Any, bool]:
    """The listing on ``resource``, paused, and whether it was adopted.

    An existing listing is adopted when it is the only open one on the resource,
    of ``shape``, and offers the module's own ``mechanism``; it is paused unless
    it is already. Closed history is retained. No open listing, multiple open
    listings, an unknown status or incompatible terms fail naming the listings,
    their shapes and their options, and change nothing.

    With none, the listing is created paused, stating the settlement
    ``settlements`` gives for each deal mechanism the storefront reports ready.
    A ready one the run gives no settlement for fails before anything is
    created, since a listing created without it never offers it; so does the
    module's own mechanism not being ready.
    """
    listings = listings_on_resource(storefront_admin_client, resource["resource_id"])
    if listings:
        return _adopted(storefront_admin_client, listings, shape=shape, mechanism=mechanism), True
    ready = ready_mechanisms(storefront_admin_client)
    assert mechanism in ready, (
        f"the storefront reports {mechanism} not ready, so a listing created now "
        f"would never offer it; of {list(DEAL_MECHANISMS)} it reports ready: {list(ready)}"
    )
    unstated = [each for each in ready if each not in settlements]
    assert not unstated, (
        f"the storefront reports {unstated} ready, and this run states no settlement "
        f"for them: a listing on resource {resource['resource_id']!r} created without "
        "them never offers them"
    )
    created = storefront_seller_client.create_listing(
        listing_resource=dict(resource),
        capacity_source=capacity_source_for(dict(resource)),
        settlements=[dict(settlements[each]) for each in ready],
        max_duration_seconds=max_duration_seconds,
        paused=True,
    )
    assert created.listing_id, f"listing creation returned no id: {created}"
    listing = storefront_admin_client.get_listing(created.listing_id)
    assert (listing.status, listing.paused) == ("open", True), listing
    # A mechanism may publish more than one option, so the mechanisms, not the
    # options, are what each ready mechanism must have.
    offered = set(listing_mechanisms(listing))
    assert offered == set(ready), (
        f"listing {listing.listing_id} offers {sorted(offered)}, where the storefront "
        f"reported {list(ready)} ready: {listing.extra.get('settlement_options')}"
    )
    return listing, False


def _adopted(
    storefront_admin_client: Any, listings: list[Any], *, shape: Mapping[str, Any],
    mechanism: str,
) -> Any:
    stated = [
        (listing, {name: listing.listing_resource.get(name) for name in shape},
         listing_mechanisms(listing))
        for listing in listings
    ]
    open_listings = [entry for entry in stated if entry[0].status == "open"]
    assert (
        len(open_listings) == 1
        and all(each.status in ("open", "closed") for each in listings)
        and open_listings[0][1] == dict(shape)
    ), (
        "the storefront holds listings on this resource the run cannot adopt, where "
        f"one open listing of the listing shape {dict(shape)} can be: "
        + "; ".join(
            f"{each.listing_id} {each.status!r} paused={each.paused} {each_shape} "
            f"offering {list(each_offered)}"
            for each, each_shape, each_offered in stated
        )
        + ". Closing a listing does not free its source: rerun with the target the "
        "listing was made for, or against a fresh stack"
    )
    listing, _, offered = open_listings[0]
    assert mechanism in offered, (
        f"listing {listing.listing_id} on this resource offers no {mechanism} option, "
        f"so this module cannot deal on it; its options: "
        f"{listing.extra.get('settlement_options')}. A listing offers only what the "
        "storefront reported ready when it was created, and its resource keeps it: "
        "rerun against a fresh stack composing the mechanism"
    )
    if not listing.paused:
        storefront_admin_client.pause_listing(listing.listing_id)
    adopted = storefront_admin_client.get_listing(listing.listing_id)
    assert (adopted.status, adopted.paused) == ("open", True), adopted
    return adopted


def listings_on_resource(storefront_admin_client: Any, resource_id: str) -> list[Any]:
    """Every storefront listing on the resource, read page by page."""
    found: list[Any] = []
    offset = 0
    while True:
        page = storefront_admin_client.list_listings(limit=_LISTING_PAGE, offset=offset).listings
        found += [
            listing for listing in page
            if listing.listing_resource.get("resource_id") == resource_id
        ]
        if len(page) < _LISTING_PAGE:
            return found
        offset += len(page)
