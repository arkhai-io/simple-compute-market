"""Bare metal's part of a buyer purchase on a real, relay-backed machine.

``RealBareMetalComputeDealDriver`` with ``BareMetalPurchaseParts``: the purchase
stages run against the real-provisioning target's machine, and, as on every real
lane, no mock gate is implemented. The listing is the one the target's
declaration publishes, whose options are the deal mechanisms the storefront
composes, so its payments option is one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from market_core.schemas import SettlementOption
from market_identity import TrustedIdentitySet

from tests.e2e.roles.helpers.payment_compensation import fulfillment_or_none
from tests.e2e.roles.scenarios.bare_metal.purchase_driver import BareMetalPurchaseParts
from tests.e2e.roles.scenarios.bare_metal.real_compute_deal_driver import (
    RealBareMetalComputeDealDriver,
    RealBareMetalDealState,
)


@dataclass(kw_only=True)
class RealBareMetalPurchaseDriver(BareMetalPurchaseParts, RealBareMetalComputeDealDriver):
    """Bare metal's ``PurchaseDriver`` on a real machine, with no mock gate."""

    #: The registry, signed as the buyer's purchase profile.
    purchase_registry: Any
    #: The storefront principal every listing and response is pinned to.
    storefront_pins: TrustedIdentitySet
    #: The purchase profile's buyer configuration file.
    config_path: str

    @property
    def declared_host_id(self) -> str:
        return self.target.host_id

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        resource = listing.listing_resource
        assert resource.get("host_id") == self.target.host_id, resource
        assert resource.get("physical_host_id") == self.physical_host_id, resource
        # The terms are the deployment's storefront's, which this run did not
        # write; the Agreement and its payment are checked against them.
        self.check_payments_listing(listing, option)

    # -- compensation ----------------------------------------------------

    def purchase_status(self, negotiation_id: str) -> Optional[Any]:
        """The purchase's fulfillment, for its compensation; ``None`` where no
        host was delivered (``fulfillment_or_none``)."""
        return fulfillment_or_none(self.fulfillment.status, negotiation_id)

    def end_purchase(self, negotiation_id: str, status: Any, known: Any) -> None:
        """End a failed purchase's tenancy through its lease's own reclaim, as
        the real lane's recovery does, confirming the release.

        ``known`` is the purchase's state as far as its stages recorded it:
        its grant job, once recorded, lets the recovery tell it from a reclaim
        job its reservation also ran, and its delivered access lets an already
        released lease's relay holding be checked.
        """
        self.tear_down_after_failure(RealBareMetalDealState(
            negotiation_id=negotiation_id, settlement_ref=negotiation_id,
            fulfillment_id=str(status["fulfillment_id"]),
            create_job_id=known.create_job_id, delivered_access=known.delivered_access,
        ))
