"""VM's part of a buyer purchase on a real KVM host.

``RealVmComputeDealDriver`` with ``VmPurchaseParts``: the purchase stages run
against the real-provisioning target's host, and, as on every real lane, no
mock gate is implemented. What differs from the real canonical deal is that a
purchase is keyed on its negotiation, not an escrow: its delivery, delivered
access and, for a failed run's recovery, its settle status are read by the
negotiation the buyer's ``market buy`` agreed.

``market buy`` finds the target's listing by its region, which only the real
lane's resource states (``REAL_REGION``). That listing offers every deal
mechanism the storefront composes (``composed_listing.py``), so its payments
option is one of several.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any, Optional

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_core.schemas import SettlementOption
from storefront_client import StorefrontClientError

from tests.e2e.roles.helpers.ssh_access import SshEndpoint
from tests.e2e.roles.scenarios.vms.host_registry import refresh_storefront_projections
from tests.e2e.roles.scenarios.vms.purchase_driver import VmPurchaseParts
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import (
    REAL_REGION,
    RealVmComputeDealDriver,
    RealVmDealState,
    delivered_endpoint,
)


def listing_status_after(capacity: dict[str, int], shape: dict[str, int], guests: int) -> str:
    """The listing's status once ``guests`` guests of ``shape`` hold the host:
    open while another guest still fits."""
    fits = all(capacity[dimension] >= (guests + 1) * shape[dimension] for dimension in shape)
    return "open" if fits else "closed"


@dataclass(kw_only=True)
class RealVmPurchaseDriver(VmPurchaseParts, RealVmComputeDealDriver):
    """VM's ``PurchaseDriver`` on a real host, with no mock gate."""

    #: The registry, read as the buyer discovers.
    purchase_registry: Any
    seller_account: str
    #: The payments option's dispute window, as the run's seller states it.
    dispute_window: str
    #: How many guests hold the host once this purchase is delivered; the
    #: listing's status after delivery, which ``Stage09b`` reads, follows.
    guests_once_delivered: int = 1

    @property
    def declared_host_id(self) -> str:
        return self.target.host_id

    @property
    def buyer_config(self) -> dict[str, str]:
        # The key generated for the run, the only buyer input the buy states.
        return {"ssh_public_key": self.buyer_public_key}

    @property
    def listing_status_after_first_fulfillment(self) -> str:
        return listing_status_after(
            self.capacity, self.target.listing_shape.model_dump(), self.guests_once_delivered,
        )

    def resource_query(self) -> str:
        return f'region="{REAL_REGION}"'

    def discover(self, listing_id: str) -> Any:
        refresh_storefront_projections(self.storefront_admin_client)
        # The CLI discovers by region, which must select this resource alone
        # before it can approve a payment. Resource identifiers are not part
        # of the registry's query vocabulary.
        matches = self.purchase_registry.list_listings(region=REAL_REGION, limit=2).listings
        assert len(matches) == 1 and str(matches[0].id) == listing_id, (
            "real VM purchase discovery is ambiguous or selects another listing",
            [str(item.id) for item in matches], listing_id,
        )
        listing = self.purchase_registry.get_listing(listing_id)
        assert listing.listing_resource.get("resource_id") == self.reserved_resource_id, listing
        return listing

    def second_purchase(self, buyer_public_key: str) -> RealVmPurchaseDriver:
        """This driver for a second purchase made while this one's guest runs."""
        return dataclasses.replace(self, buyer_public_key=buyer_public_key, guests_once_delivered=2)

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        resource = listing.listing_resource
        assert resource.get("resource_id") == self.reserved_resource_id, resource
        assert resource.get("region") == REAL_REGION, resource
        assert not any(resource.get(key) for key in ("gpu_model", "gpu_count")), (
            "the target sells no GPU, but its listing states one", resource,
        )
        assert option.settlement_schema == ARKHAI_PAYMENTS_MECHANISM, option
        self.check_payments_option(option)

    def assert_delivery(self, deal_state: Any) -> None:
        """Delivery by the purchase's negotiation, naming the fulfillment its
        commit began, at an SSH endpoint the target's access reaches."""
        status = self.storefront_client.get_settle_status(deal_state.negotiation_id)
        assert status.status == "ready", status
        assert status.tenant_credentials, f"tenant_credentials missing from settlement status: {status}"
        assert status.fulfillment_id == deal_state.fulfillment_id, status
        self.delivered_access(deal_state)

    def delivered_access(self, deal_state: Any) -> SshEndpoint:
        endpoint = delivered_endpoint(
            self.storefront_client.get_settle_status(deal_state.negotiation_id)
        )
        expected = self._buyer_address()
        assert endpoint.host == expected, (
            f"the delivered access names {endpoint.host!r}, not {expected!r}, the "
            f"address the target's {self.target.access.mode!r} access reaches"
        )
        self.assert_relay_delivery(deal_state.fulfillment_id, endpoint)
        return endpoint

    def _settle_status(self, deal_state: RealVmDealState) -> Optional[Any]:
        try:
            return self.storefront_client.get_settle_status(deal_state.negotiation_id)
        except StorefrontClientError as error:
            if error.status_code == 404:
                return None
            raise

    def reserve_guest_shape(self, storefront_admin_client: Any, *, listing_id: str,
                            escrow_uid: str) -> Any:
        """Reserve one guest's shape of the resource: what a released guest
        returns while another still holds its own slice."""
        return storefront_admin_client.admin_reserve_capacity(
            required_attributes={"resource_id": self.reserved_resource_id,
                                 "dimensions": self.target.listing_shape.model_dump()},
            listing_id=listing_id,
            escrow_uid=escrow_uid,
        )

    # -- compensation ----------------------------------------------------

    def purchase_status(self, negotiation_id: str) -> Optional[dict[str, Any]]:
        """The purchase's fulfillment, for its compensation; ``None`` where the
        storefront dispatched none (``dispatched_fulfillment``)."""
        fulfillment_id = self.dispatched_fulfillment(
            RealVmDealState(negotiation_id=negotiation_id, settlement_ref=negotiation_id)
        )
        return None if fulfillment_id is None else {"fulfillment_id": fulfillment_id}

    def end_purchase(self, negotiation_id: str, status: dict[str, Any], known: Any) -> None:
        """End a failed purchase's guest through its lease's expiry, as the
        real lane's recovery does, confirming it gone from the host.

        ``known`` is the purchase's state as far as its stages recorded it:
        its create job and guest, once recorded, let the recovery tell the
        create job from a teardown job its reservation also ran.
        """
        self.tear_down_after_failure(RealVmDealState(
            negotiation_id=negotiation_id, settlement_ref=negotiation_id,
            fulfillment_id=str(status["fulfillment_id"]),
            create_job_id=known.create_job_id, vm_name=known.vm_name,
        ))
