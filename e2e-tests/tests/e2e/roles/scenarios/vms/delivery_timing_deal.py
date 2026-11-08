"""VM deals that exercise delivery's timing, after the canonical deal's own.

Two deals on the capacity the canonical deal and its surrender freed, each
agreed, escrowed and settled through the typed clients:

- a deal whose Agreement starts later: settlement commits its window at once
  and dispatches nothing, a re-drive before the start dispatches nothing
  either, and once the start is reached a re-drive delivers it, activating
  the lease within the Agreement's window; the buyer then ends it, which
  returns the capacity;
- a deal whose acceptance hold has lapsed and whose settlement placement then
  finds no capacity: delivery records the seller's failure before anything is
  dispatched and makes no reservation of its own.

A re-drive is one step of VM's resume pass, the loop a restarted storefront
runs first. Settle answers before its delivery runs, and drives it in the
background, so a stage waits for the delivery's own stage event or settled
status before it measures. The storefront's loops, fulfillment convergence and
the lease watchdog are held for the module, so every effect asserted here is
one a stage asked for; the one wait not on a request is for the forward deal's
start.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    advance_storefront,
    assert_lease_watchdog_held,
    delete_mock_rules_if_present,
    latest_stage_event_id,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.compute_deal_stages import (
    BUYER_INITIAL_PRICE,
    BUYER_MAX_PRICE,
    DEAL_TOKEN,
    DURATION_HOURS,
    ESCROW_TTL_SECONDS,
    WINDOW_TOLERANCE,
    alkahest_opening,
    utc_instant,
    wait_until,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.escrow import create_buyer_escrow
from tests.e2e.roles.scenarios.vms.compute_deal_driver import PROV_RULE_ID, REMOVE_RULE_ID
from tests.e2e.roles.scenarios.vms.conftest import step_listing_reconciliation
from tests.e2e.roles.scenarios.vms.lifecycle_deal import LifecyclePurchase

log = logging.getLogger(__name__)

RESUME = "fulfillment-resume"
#: How far ahead the forward deal's Agreement starts: room to agree, escrow,
#: settle and observe the deal waiting before its start arrives.
FORWARD_LEAD = timedelta(seconds=30)


@dataclass
class AgreedDeal:
    negotiation_id: str
    escrow_uid: str
    start: datetime
    end: datetime


def _reopen_listing(storefront_admin_client, registry_client, listing_id: str) -> None:
    """Return the freed capacity to the listing, as the canonical deal's
    second deal does: reconcile the release, then publish the reopening."""
    step_listing_reconciliation(storefront_admin_client)
    advance_storefront(storefront_admin_client, "publication")
    listing = registry_client.get_listing(listing_id)
    assert listing.status == "open", f"the freed capacity did not reopen the listing: {listing}"


def _agree_and_escrow(
    storefront_client, storefront_admin_client, registry_client, deal_driver,
    buyer_config, seller_wallet, listing_id: str, *, start: datetime | None = None,
    before_escrow=None,
) -> AgreedDeal:
    """Agree a deal on the listing, force-accepted at the canonical price, and
    fund its escrow on chain. ``start`` asks for an Agreement start; without
    one the deal starts at acceptance. ``before_escrow`` runs once the deal is
    accepted, with its negotiation id, before the escrow exists."""
    expiration = int(time.time()) + ESCROW_TTL_SECONDS
    option, escrow = alkahest_opening(registry_client.get_listing(listing_id))
    terms = deal_driver.provision_terms()
    if start is not None:
        terms["payload"]["start_utc"] = start.isoformat().replace("+00:00", "Z")
    opened = storefront_client.negotiate_new(
        listing_id=listing_id, initial_amount=BUYER_INITIAL_PRICE,
        escrow_expiration_unix=expiration, provision_terms=terms,
        token=DEAL_TOKEN["contract_address"], chain_name=escrow["chain_name"],
        escrow_address=escrow["escrow_address"], literal_fields=escrow["literal_fields"],
        demands=[escrow["demand"]],
        settlement_selection=deal_driver.opening_selection(option, expiration),
    )
    negotiation_id = opened["negotiation_id"]
    agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
    accepted = storefront_admin_client.force_accept_negotiation(
        listing_id, negotiation_id, amount=agreed,
    )
    assert accepted.action == "accept", accepted
    detail = storefront_admin_client.get_negotiation(listing_id, negotiation_id)
    agreement_start = utc_instant(detail.extra.get("requested_start_utc"))
    agreement_end = agreement_start + timedelta(
        seconds=int(detail.extra.get("agreed_duration_seconds") or 0)
    )
    if before_escrow is not None:
        before_escrow(negotiation_id)
    escrow_uid = create_buyer_escrow(
        buyer_private_key=buyer_config["private_key"], seller_wallet_address=seller_wallet,
        agreed_amount=agreed, duration_seconds=DURATION_HOURS * 3600,
        token_contract_address=DEAL_TOKEN["contract_address"], rpc_url=buyer_config["rpc_url"],
        expiration_unix=expiration,
    )
    return AgreedDeal(negotiation_id, escrow_uid, agreement_start, agreement_end)


def _assert_agreement_window(lease: Any, deal: AgreedDeal) -> None:
    assert lease.lease_start_utc is not None, lease
    assert abs(lease.lease_start_utc - deal.start) < WINDOW_TOLERANCE, (lease, deal)
    assert abs(lease.lease_end_utc - deal.end) < WINDOW_TOLERANCE, (lease, deal)


def _dispatches(storefront_admin_client, negotiation_id: str, since_id: int) -> list[Any]:
    events = storefront_admin_client.get_events(
        stage="provision", negotiation_id=negotiation_id, since_id=since_id, limit=500,
    )
    return [event for event in events.events if event.event == "job_submitted"]


class Stage13a_ForwardDealCommittedAndWaiting:
    def test_13a_a_deal_starting_later_is_committed_and_dispatches_nothing(
        self, storefront_client, storefront_admin_client, registry_client,
        provisioning_client, provisioning_test_client, deal_driver, buyer_config,
        seller_wallet, site_capacity, deal_state,
    ):
        """Settlement before the Agreement start commits the window and waits.

        Settle answers before its delivery runs, so the stage waits for the
        delivery's ``reserved`` event, which follows the drive's commit. The
        deal's one reservation is then leased under the Agreement's start and
        end; nothing is dispatched, the lease is not activated, and the buyer
        sees no fulfillment. With the resume pass stepped before the start,
        nothing is dispatched either.
        """
        require_state(deal_state, "lifecycle_purchase", "seller_listing_id")
        assert deal_state.lifecycle_purchase.reports, "the canonical second deal did not release"
        listing_id = deal_state.seller_listing_id
        _reopen_listing(storefront_admin_client, registry_client, listing_id)
        # The deal's create runs as a buyer's would, with no gate held.
        delete_mock_rules_if_present(provisioning_test_client.vm_rules, PROV_RULE_ID, REMOVE_RULE_ID)

        asked = (datetime.now(timezone.utc) + FORWARD_LEAD).replace(microsecond=0)
        deal = _agree_and_escrow(
            storefront_client, storefront_admin_client, registry_client, deal_driver,
            buyer_config, seller_wallet, listing_id, start=asked,
        )
        assert abs(deal.start - asked) < WINDOW_TOLERANCE, (
            f"the Agreement does not start when the buyer asked: {deal} vs {asked}"
        )
        mark = latest_stage_event_id(storefront_admin_client, negotiation_id=deal.negotiation_id)
        storefront_client.settle_evm(
            deal.escrow_uid, negotiation_id=deal.negotiation_id,
            buyer_evm_address=buyer_config["wallet_address"],
        )
        wait_for_stage_event(
            storefront_admin_client, "provision", "reserved",
            negotiation_id=deal.negotiation_id, since_id=mark, timeout=30.0,
        )
        assert datetime.now(timezone.utc) < deal.start, (
            f"the deal was committed after its Agreement start {deal.start.isoformat()}; "
            "raise FORWARD_LEAD"
        )

        (reservation,) = site_capacity.reservations_for_negotiation(deal.negotiation_id)
        assert reservation["state"] == "leased", f"the deal's reservation is not committed: {reservation}"
        lease = provisioning_client.get_lease(reservation["capacity_reservation_id"])
        _assert_agreement_window(lease, deal)
        assert lease.activated_at_utc is None, f"a lease was activated before its start: {lease}"
        assert storefront_client.get_settle_status(deal.escrow_uid).fulfillment_id is None
        assert _dispatches(storefront_admin_client, deal.negotiation_id, mark) == []

        advance_storefront(storefront_admin_client, RESUME)

        assert datetime.now(timezone.utc) < deal.start, "the re-drive ran after the start"
        assert storefront_client.get_settle_status(deal.escrow_uid).fulfillment_id is None
        assert _dispatches(storefront_admin_client, deal.negotiation_id, mark) == []
        again = site_capacity.reservations_for_negotiation(deal.negotiation_id)
        assert [r["capacity_reservation_id"] for r in again] == [
            reservation["capacity_reservation_id"]
        ], again
        deal_state.forward_deal = deal
        deal_state.forward_reservation_id = reservation["capacity_reservation_id"]
        deal_state._forward_events_since = mark
        log.info("[13a] forward deal %s committed for %s and waiting", deal.negotiation_id, deal.start)


class Stage13b_ForwardDealDeliveredAtItsStart:
    def test_13b_the_deal_is_delivered_once_its_start_is_reached(
        self, storefront_client, storefront_admin_client, provisioning_client,
        provisioning_test_client, site_capacity, deal_state,
    ):
        """Once its start is reached, a re-drive dispatches and delivers the deal.

        The resume pass is stepped once the clock reaches the Agreement start:
        it dispatches the fulfillment on the reservation committed at
        settlement, and once the fulfillment is ready a further step activates
        the lease, inside the Agreement's window, and the deal becomes ready.
        """
        require_state(deal_state, "forward_deal", "forward_reservation_id", "_forward_events_since")
        deal: AgreedDeal = deal_state.forward_deal
        reservation_id = deal_state.forward_reservation_id

        wait_until(deal.start + WINDOW_TOLERANCE)
        advance_storefront(storefront_admin_client, RESUME)
        wait_for_stage_event(
            storefront_admin_client, "provision", "job_submitted",
            negotiation_id=deal.negotiation_id,
            since_id=deal_state._forward_events_since, timeout=30.0,
        )
        fulfillment_id = storefront_client.get_settle_status(deal.escrow_uid).fulfillment_id
        assert fulfillment_id, "the re-drive after the start dispatched no fulfillment"

        provisioning_test_client.drain(timeout=30)
        advance_fulfillment_to(provisioning_client, fulfillment_id, "active")
        advance_storefront(storefront_admin_client, RESUME)
        ready = storefront_admin_client.wait_for_settlement(deal.escrow_uid, timeout=30.0)
        assert ready.ready and ready.status == "ready", ready

        reservations = site_capacity.reservations_for_negotiation(deal.negotiation_id)
        assert [r["capacity_reservation_id"] for r in reservations] == [reservation_id], reservations
        lease = provisioning_client.get_lease(reservation_id)
        _assert_agreement_window(lease, deal)
        assert lease.activated_at_utc is not None, f"the delivered lease is not activated: {lease}"
        assert lease.activated_at_utc >= deal.start - WINDOW_TOLERANCE, (
            f"the lease was activated before its Agreement start: {lease}"
        )
        deal_state.forward_fulfillment_id = fulfillment_id


class Stage13c_ForwardDealEndedAndReleased:
    def test_13c_the_buyer_ends_the_deal_and_its_capacity_returns(
        self, storefront_admin_client, provisioning_client, provisioning_test_client,
        vm_lifecycle_buyer, deal_state,
    ):
        """The buyer's end tears the delivered deal down and returns its capacity,
        so the deal after it finds the capacity free unless a stage holds it."""
        require_state(deal_state, "forward_deal", "forward_reservation_id", "forward_fulfillment_id")
        assert_lease_watchdog_held(provisioning_client)
        deal: AgreedDeal = deal_state.forward_deal
        reservation_id = deal_state.forward_reservation_id
        fulfillment_id = deal_state.forward_fulfillment_id
        purchase = LifecyclePurchase(deal.negotiation_id, fulfillment_id, reservation_id)

        ended = vm_lifecycle_buyer.end(purchase)
        assert ended["delivery"]["progress"] == "tearing_down", ended
        provisioning_test_client.drain(timeout=30)
        advance_fulfillment_to(provisioning_client, fulfillment_id, "torn_down")
        existing = storefront_admin_client.get_events(stage="fulfillment", limit=500)
        since_id = max((event.id for event in existing.events), default=0)
        provisioning_client.check_leases()
        wait_for_stage_event(
            storefront_admin_client, "fulfillment", "capacity_released",
            since_id=since_id, timeout=10.0,
        )
        assert provisioning_client.get_lease(reservation_id).status == "released"
        deal_state._forward_deal_released = True


class Stage13d_SettlementFindsNoCapacity:
    def test_13d_a_settlement_placement_finding_no_capacity_is_the_seller_s_failure(
        self, storefront_client, storefront_admin_client, registry_client, deal_driver,
        buyer_config, seller_wallet, site_capacity, vm_lifecycle_buyer, deal_state,
    ):
        """A lapsed hold whose replacement finds no capacity ends the deal undelivered.

        The deal's acceptance hold is released at the site before settlement,
        so it has lapsed, and the resource is then held by another reservation.
        Delivery cannot commit the released hold and places no reservation of
        its own, since the replacement placement finds no capacity: it records
        the end as the seller's, with nothing dispatched. The deal's only
        reservation stays the released hold. A step of the resume pass, which
        drives no ended deal, leaves all of it as it was.
        """
        require_state(deal_state, "_forward_deal_released", "seller_listing_id")
        listing_id = deal_state.seller_listing_id
        _reopen_listing(storefront_admin_client, registry_client, listing_id)
        held: dict[str, Any] = {}

        def lapse_hold_and_take_the_capacity(negotiation_id: str) -> None:
            (hold,) = site_capacity.reservations_for_negotiation(negotiation_id)
            assert site_capacity.release(hold["capacity_reservation_id"]) is not None, hold
            held["hold"] = hold["capacity_reservation_id"]
            held["blocker"] = deal_driver.reserve_released_capacity(
                storefront_admin_client, listing_id=listing_id,
                escrow_uid=f"{negotiation_id}-blocker",
            )
            assert held["blocker"].capacity_reservation_id, held

        deal = _agree_and_escrow(
            storefront_client, storefront_admin_client, registry_client, deal_driver,
            buyer_config, seller_wallet, listing_id, before_escrow=lapse_hold_and_take_the_capacity,
        )
        try:
            mark = latest_stage_event_id(storefront_admin_client, negotiation_id=deal.negotiation_id)
            settled = storefront_client.settle_evm(
                deal.escrow_uid, negotiation_id=deal.negotiation_id,
                buyer_evm_address=buyer_config["wallet_address"],
            )
            log.info("[13d] settle answered %s", settled)
            # Settle answers before its delivery runs; the long-poll returns once
            # the settlement is terminal.
            waited = storefront_admin_client.wait_for_settlement(deal.escrow_uid, timeout=30.0)
            assert waited.ready and waited.status == "ended", waited
            purchase = LifecyclePurchase(deal.negotiation_id, "", held["hold"])

            delivery = vm_lifecycle_buyer.read(purchase)
            end = delivery["recorded_end"]
            assert end is not None, f"no end was recorded for the undeliverable deal: {delivery}"
            assert end["cause"] == "capacity_unavailable" and end["source"] == "delivery", end
            reservations = site_capacity.reservations_for_negotiation(deal.negotiation_id)
            assert [r["capacity_reservation_id"] for r in reservations] == [held["hold"]], (
                f"delivery placed a reservation for a deal with no capacity: {reservations}"
            )
            assert reservations[0]["state"] == "released", reservations
            assert storefront_client.get_settle_status(deal.escrow_uid).fulfillment_id is None
            assert _dispatches(storefront_admin_client, deal.negotiation_id, mark) == []

            advance_storefront(storefront_admin_client, RESUME)

            again = vm_lifecycle_buyer.read(purchase)
            assert again["recorded_end"] == end, (end, again)
            after = site_capacity.reservations_for_negotiation(deal.negotiation_id)
            assert [r["capacity_reservation_id"] for r in after] == [held["hold"]], after
            assert _dispatches(storefront_admin_client, deal.negotiation_id, mark) == []
        finally:
            if "blocker" in held:
                deal_driver.release_reserved(held["blocker"])
