"""Bare metal's re-drives of its mock-provisioned deals.

The lifecycle's cycle (`delivery-recovery`) is what a restarted bare-metal
storefront runs first: it drives every started, unfinished delivery from what
its records hold. Bare metal's settlement drives the deal once and returns, so a
step of the cycle meets the deal as a restart would, owning it alone. VM's resume
pass would skip a deal its settlement call is still driving, so VM's recovery is
exercised by a deal that waits for its start instead
(`vms/delivery_timing_deal.py`).

Two stages re-drive the canonical deal between the shared stages, before and
after its fulfillment is ready; a third, after the second deal, follows a deal
whose settlement placement finds no capacity.
"""

from __future__ import annotations

import logging
import time

from tests.e2e.roles.helpers.compute_deal import advance_storefront
from tests.e2e.roles.helpers.compute_deal_stages import (
    BUYER_INITIAL_PRICE,
    BUYER_MAX_PRICE,
    DEAL_TOKEN,
    DURATION_HOURS,
    ESCROW_TTL_SECONDS,
    alkahest_opening,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.escrow import create_buyer_escrow

log = logging.getLogger(__name__)

RECOVERY = "delivery-recovery"


def _reservation_ids(deal_driver, deal_state) -> list[str]:
    return [r["capacity_reservation_id"] for r in deal_driver.deal_reservations(deal_state)]


def _step_recovery(storefront_admin_client) -> None:
    """One step of the cycle. It drives every started delivery that is not yet
    available or has no recorded result, which the canonical deal is at both
    re-drives; its report counts the deals it read, not those it drove."""
    advance_storefront(storefront_admin_client, RECOVERY)


class BareMetalRecoveryBeforeReadiness:
    def test_08b1_recovery_adopts_the_dispatched_fulfillment(
        self, storefront_admin_client, provisioning_client, deal_driver, deal_state,
    ):
        """A re-drive between dispatch and readiness adopts what was dispatched.

        Stepped after settlement dispatched the fulfillment, the cycle meets the
        deal where a restart after dispatch would: the reservation committed, the
        fulfillment recorded and not yet ready, since fulfillment convergence is
        held for the module and only 09a's advance observes the provider's
        outcome. Such a drive only polls the fulfillment, so nothing shows that
        it ran; what the stage measures is that it reserves nothing more and
        dispatches nothing again: the fulfillment the storefront records stays
        the one 08b read, still dispatching.
        """
        require_state(deal_state, "fulfillment_id")
        before = _reservation_ids(deal_driver, deal_state)
        assert len(before) == 1, f"the deal should hold one reservation: {before}"

        _step_recovery(storefront_admin_client)

        assert _reservation_ids(deal_driver, deal_state) == before
        assert deal_driver.recorded_fulfillment(deal_state) == deal_state.fulfillment_id
        status = provisioning_client.get_fulfillment_status(deal_state.fulfillment_id)
        assert status.state == "dispatching", (
            f"the unready fulfillment moved under a re-drive: {status}"
        )
        log.info("[08b1] re-drive kept reservation %s and fulfillment %s",
                 before[0], deal_state.fulfillment_id)


class BareMetalRecoveryActivatesTheReadyDelivery:
    def test_09a1_recovery_activates_the_lease_on_the_deal_s_resources(
        self, storefront_admin_client, provisioning_client, deal_driver, deal_state,
    ):
        """Once the fulfillment is ready, a re-drive carries delivery to activation.

        The cycle re-drives the deal from its records, as after a restart
        between readiness and activation. The lease is unactivated before the
        step, and nothing else drives the deal meanwhile (settlement's drive has
        returned, and the stage reads the lease at the site rather than through
        the buyer's status read, which would drive it); after the step the site
        records the activation on the deal's one reservation, with the recorded
        fulfillment unchanged and no second reservation.
        """
        require_state(deal_state, "fulfillment_id", "provisioning_result_injected")
        reservations = _reservation_ids(deal_driver, deal_state)
        assert len(reservations) == 1, f"the deal should hold one reservation: {reservations}"
        unactivated = provisioning_client.get_lease(reservations[0])
        assert unactivated.activated_at_utc is None, (
            f"the lease was activated before the re-drive: {unactivated}"
        )

        _step_recovery(storefront_admin_client)

        assert _reservation_ids(deal_driver, deal_state) == reservations
        lease = provisioning_client.get_lease(reservations[0])
        assert lease.activated_at_utc is not None, (
            f"a re-drive of a ready delivery left its lease unactivated: {lease}"
        )
        assert deal_driver.recorded_fulfillment(deal_state) == deal_state.fulfillment_id
        log.info("[09a1] re-drive activated lease %s at %s",
                 reservations[0], lease.activated_at_utc)


class BareMetalSettlementFindsNoCapacity:
    def test_13a_a_settlement_placement_finding_no_capacity_is_the_seller_s_failure(
        self, storefront_client, storefront_admin_client, registry_client, deal_driver,
        buyer_config, seller_wallet, buyer_fulfillment, deal_state,
    ):
        """A deal whose machine is taken before settlement ends undelivered.

        Once the deal is accepted, the machine is held by another reservation.
        Settlement's placement under the deal's ``:settlement`` key finds no
        capacity, and delivery records the end as the seller's, with nothing
        reserved for the deal and nothing dispatched. A step of the recovery
        cycle, which drives no ended delivery, leaves all of it as it was.
        """
        require_state(deal_state, "_second_deal_released", "seller_listing_id")
        listing_id = deal_state.seller_listing_id
        # The second deal's release freed the machine; one poller step sees it,
        # and one publication pass reopens its listing.
        advance_storefront(storefront_admin_client, "site-projections")
        advance_storefront(storefront_admin_client, "publication")
        assert registry_client.get_listing(listing_id).status == "open"

        expiration = int(time.time()) + ESCROW_TTL_SECONDS
        _option, escrow = alkahest_opening(registry_client.get_listing(listing_id))
        opened = storefront_client.negotiate_new(
            listing_id=listing_id, initial_amount=BUYER_INITIAL_PRICE,
            escrow_expiration_unix=expiration, provision_terms=deal_driver.provision_terms(),
            token=DEAL_TOKEN["contract_address"], chain_name=escrow["chain_name"],
            escrow_address=escrow["escrow_address"], literal_fields=escrow["literal_fields"],
            demands=[escrow["demand"]],
        )
        negotiation_id = opened["negotiation_id"]
        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        accepted = storefront_admin_client.force_accept_negotiation(
            listing_id, negotiation_id, amount=agreed,
        )
        assert accepted.action == "accept", accepted
        blocker = deal_driver.reserve_released_capacity(
            storefront_admin_client, listing_id=listing_id,
            escrow_uid=f"{negotiation_id}-blocker",
        )
        assert blocker.capacity_reservation_id, blocker
        try:
            escrow_uid = create_buyer_escrow(
                buyer_private_key=buyer_config["private_key"],
                seller_wallet_address=seller_wallet, agreed_amount=agreed,
                duration_seconds=DURATION_HOURS * 3600,
                token_contract_address=DEAL_TOKEN["contract_address"],
                rpc_url=buyer_config["rpc_url"], expiration_unix=expiration,
            )
            settled = storefront_client.settle_evm(
                escrow_uid, negotiation_id=negotiation_id,
                buyer_evm_address=buyer_config["wallet_address"],
            )
            log.info("[13a] settle answered %s", settled)

            delivery = buyer_fulfillment.delivery(negotiation_id)["delivery"]
            end = delivery["recorded_end"]
            assert end is not None, f"no end was recorded for the undeliverable deal: {delivery}"
            assert end["cause"] == "capacity_unavailable" and end["source"] == "delivery", end
            ours = deal_driver.site_capacity.reservations_for_negotiation(negotiation_id)
            assert ours == [], f"delivery reserved capacity it could not find: {ours}"

            advance_storefront(storefront_admin_client, RECOVERY)

            again = buyer_fulfillment.delivery(negotiation_id)["delivery"]
            assert again["recorded_end"] == end, (end, again)
            assert deal_driver.site_capacity.reservations_for_negotiation(negotiation_id) == []
        finally:
            deal_driver.release_reserved(blocker)
