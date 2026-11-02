"""VM buyer surrender after the canonical deal's separate expiry journey."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass

from compute_provisioning_contracts import MockRuleCreate
from compute_provisioning_contracts.lease_ends import SignedLeaseEndedReport, verify_lease_end
from market_deal_lifecycle_client import LifecycleClient

from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import (
    DealLease, advance_fulfillment_to, advance_storefront, assert_lease_watchdog_held,
    delete_mock_rules_if_present, wait_for_stage_event,
)
from tests.e2e.roles.helpers.compute_deal_stages import (
    BUYER_INITIAL_PRICE, BUYER_MAX_PRICE, DEAL_TOKEN, DURATION_HOURS,
    ESCROW_TTL_SECONDS, alkahest_opening,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.escrow import create_buyer_escrow
from tests.e2e.roles.scenarios.vms.conftest import (
    _provisioning_authority_trust, _publisher_trust, _signer, capacity_site_id,
    step_listing_reconciliation,
)
from tests.e2e.roles.scenarios.vms.compute_deal_driver import PROV_RULE_ID, REMOVE_RULE_ID


@dataclass
class LifecyclePurchase:
    negotiation_id: str
    fulfillment_id: str
    reservation_id: str
    run_id: str | None = None
    receipt: dict | None = None
    reports: list | None = None


def _cli_json(run, *, returncodes=(0,)):
    assert run.returncode in returncodes, (run.returncode, run.stdout(), run.stderr())
    return json.loads(run.stdout().splitlines()[-1])


class TypedLifecycleBuyer:
    def __init__(self, client, admin, registry, driver, buyer, seller_wallet, site_capacity):
        self.client, self.admin, self.registry, self.driver = client, admin, registry, driver
        self.buyer, self.seller_wallet, self.site_capacity = buyer, seller_wallet, site_capacity

    def purchase(self, listing_id, provisioning, test_client):
        expiration = int(time.time()) + ESCROW_TTL_SECONDS
        option, escrow = alkahest_opening(self.registry.get_listing(listing_id))
        opened = self.client.negotiate_new(
            listing_id=listing_id, initial_amount=BUYER_INITIAL_PRICE,
            escrow_expiration_unix=expiration, provision_terms=self.driver.provision_terms(),
            token=DEAL_TOKEN["contract_address"], chain_name=escrow["chain_name"],
            escrow_address=escrow["escrow_address"], literal_fields=escrow["literal_fields"],
            demands=[escrow["demand"]],
            settlement_selection=self.driver.opening_selection(option, expiration),
        )
        negotiation_id = opened["negotiation_id"]
        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        assert self.admin.force_accept_negotiation(listing_id, negotiation_id, amount=agreed).action == "accept"
        uid = create_buyer_escrow(
            buyer_private_key=self.buyer["private_key"], seller_wallet_address=self.seller_wallet,
            agreed_amount=agreed, duration_seconds=DURATION_HOURS * 3600,
            token_contract_address=DEAL_TOKEN["contract_address"], rpc_url=self.buyer["rpc_url"],
            expiration_unix=expiration,
        )
        self.client.settle_evm(uid, negotiation_id=negotiation_id,
                           buyer_evm_address=self.buyer["wallet_address"])
        wait_for_stage_event(self.admin, "provision", "job_submitted",
                             negotiation_id=negotiation_id, timeout=30)
        status = self.client.get_settle_status(uid)
        assert status.fulfillment_id, status
        test_client.drain(timeout=30)
        advance_fulfillment_to(provisioning, status.fulfillment_id, "active")
        ready = self.admin.wait_for_settlement(uid, timeout=30)
        assert ready.ready and ready.status == "ready", ready
        return LifecyclePurchase(negotiation_id, status.fulfillment_id,
                                 DealLease(provisioning, self.site_capacity, negotiation_id=negotiation_id).lease_id)

    def end(self, purchase):
        async def send():
            async with self._peer() as peer:
                return (await peer.end_delivery(purchase.negotiation_id)).model_dump(mode="json")
        return asyncio.run(send())

    def read(self, purchase):
        async def read():
            async with self._peer() as peer:
                return (await peer.read(purchase.negotiation_id)).delivery.model_dump(mode="json")
        return asyncio.run(read())

    @staticmethod
    def _peer():
        return LifecycleClient(str(settings.SELLER.API_URL),
            _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL, "BUYER.MARKETPLACE_CREDENTIAL"),
            _publisher_trust())


class CliLifecycleBuyer:
    def __init__(self, cli, client, admin, site_capacity):
        self.cli, self.client, self.admin, self.site_capacity = cli, client, admin, site_capacity

    def purchase(self, listing_id, provisioning, test_client):
        run = self.cli.run([
            "negotiate", "--listing-id", listing_id, "--seller", str(settings.SELLER.API_URL),
            "--initial-price", "7", "--max-price", "12", "--duration-hours", str(DURATION_HOURS),
            "--settlement", "mechanism=alkahest.v1 asset=" + DEAL_TOKEN["contract_address"],
            "--max-rounds", "10", "--yes",
        ], timeout=120)
        assert run.returncode == 0, (run.stdout(), run.stderr())
        terminal = next(e for e in reversed(run.read_events()) if e.get("event") == "run_ended")
        assert terminal["status"] == "agreed", terminal
        negotiation_id = terminal["negotiation_id"]
        settle = self.cli.run(["settle", "--from", run.run_id, "--poll-interval", "0.1",
                               "--settlement-timeout", "60"], background=True)
        try:
            uid = settle.wait_for_event("escrow_created", timeout=60)["escrow_uid"]
            settle.wait_for_event("settle_submitted", timeout=30)
            wait_for_stage_event(self.admin, "provision", "job_submitted",
                                 negotiation_id=negotiation_id, timeout=30)
            status = self.client.get_settle_status(uid)
            assert status.fulfillment_id, status
            test_client.drain(timeout=30)
            advance_fulfillment_to(provisioning, status.fulfillment_id, "active")
            assert settle.wait(timeout=60) == 0, (settle.stdout(), settle.stderr())
        finally:
            settle.terminate()
        return LifecyclePurchase(negotiation_id, status.fulfillment_id,
            DealLease(provisioning, self.site_capacity, negotiation_id=negotiation_id).lease_id, run.run_id)

    def end(self, purchase):
        result = _cli_json(self.cli.run(["end", "--from", purchase.run_id]))
        assert result["progress"]["delivery"]["status"] == "accepted", result
        assert not result["capacity_released"], result
        return result["progress"]["acknowledgement"]

    def read(self, purchase):
        # A positive bounded wait reads current delivery, rather than merely
        # returning the immutable acknowledgement from the original surrender.
        run = self.cli.run(["end", "--from", purchase.run_id,
                            "--wait-timeout", "0.01", "--poll-interval", "0.01"])
        result = _cli_json(run, returncodes=(0, 1))
        assert result["progress"]["delivery"]["status"] == "accepted", result
        assert run.returncode == (0 if result["capacity_released"] else 1), result
        assert result["capacity_released"] == (result["delivery_view"]["progress"] == "released"), result
        return result["delivery_view"]


class Stage12a_SecondDealActive:
    def test_12a_released_capacity_delivers_a_second_deal(
        self, storefront_admin_client, registry_client, provisioning_client,
        provisioning_test_client, vm_lifecycle_buyer, deal_state,
    ):
        require_state(deal_state, "deal_lease", "seller_listing_id")
        assert deal_state.deal_lease.refresh()["status"] == "released"
        step_listing_reconciliation(storefront_admin_client)
        advance_storefront(storefront_admin_client, "publication")
        assert registry_client.get_listing(deal_state.seller_listing_id).status == "open"
        delete_mock_rules_if_present(provisioning_test_client.vm_rules, PROV_RULE_ID, REMOVE_RULE_ID)
        deal_state.lifecycle_purchase = vm_lifecycle_buyer.purchase(
            deal_state.seller_listing_id, provisioning_client, provisioning_test_client)


class Stage12b_BuyerSurrendersTwice:
    def test_12b_repeated_surrender_keeps_one_termination_and_signed_report(
        self, provisioning_client, provisioning_test_client, storefront_admin_client,
        vm_lifecycle_buyer, deal_state,
    ):
        require_state(deal_state, "lifecycle_purchase")
        assert_lease_watchdog_held(provisioning_client)
        purchase = deal_state.lifecycle_purchase
        # Keep physical completion behind a gate while the intended end and
        # the independently signed site observation become readable.
        provisioning_test_client.vm_rules.add_rule(MockRuleCreate(
            rule_id=REMOVE_RULE_ID, match={"vm_action": "vm_remove"}, pause_before_result=True))
        first = vm_lifecycle_buyer.end(purchase)
        again = vm_lifecycle_buyer.end(purchase)
        for name in ("negotiation_id", "operation_key", "receipt_at", "selected_end"):
            assert again[name] == first[name], (name, first, again)
        assert first["delivery"]["progress"] == "tearing_down", first
        advance_storefront(storefront_admin_client, "settlement-servicing")
        delivery = vm_lifecycle_buyer.read(purchase)
        assert delivery["progress"] == "tearing_down", delivery
        assert len(delivery["site_reports"]) == 1, delivery
        site = provisioning_client.get_lease(purchase.reservation_id)
        assert site.status == "releasing", site
        assert len(site.end_reports) == 1, site
        assert site.release_job_id == purchase.fulfillment_id, site
        for item in delivery["site_reports"]:
            report = SignedLeaseEndedReport.model_validate_json(base64.b64decode(item["body"]))
            event = verify_lease_end(report, capacity_reservation_id=purchase.reservation_id,
                site_id=capacity_site_id(), expected_sites=_provisioning_authority_trust())
            assert event.cause == "termination", event
            assert event.caller == next(iter(_publisher_trust().identities))
            assert report == site.end_reports[0]
        purchase.receipt, purchase.reports = first, delivery["site_reports"]


class Stage12c_CapacityReleasedOnce:
    def test_12c_only_provider_completion_and_callback_prove_capacity_return(
        self, provisioning_client, provisioning_test_client, storefront_admin_client,
        vm_lifecycle_buyer, deal_state,
    ):
        require_state(deal_state, "lifecycle_purchase")
        purchase = deal_state.lifecycle_purchase
        assert purchase.receipt and purchase.reports
        assert_lease_watchdog_held(provisioning_client)
        provisioning_client.advance_fulfillment_convergence_cycle()
        assert provisioning_client.get_fulfillment_status(purchase.fulfillment_id).state == "tearing_down"
        assert vm_lifecycle_buyer.read(purchase)["progress"] == "tearing_down"
        provisioning_test_client.vm_rules.resume_rule(REMOVE_RULE_ID)
        provisioning_test_client.drain(timeout=30)
        advance_fulfillment_to(provisioning_client, purchase.fulfillment_id, "torn_down")
        assert vm_lifecycle_buyer.read(purchase)["progress"] == "tearing_down"
        existing = storefront_admin_client.get_events(stage="fulfillment", limit=500)
        since_id = max((event.id for event in existing.events), default=0)
        provisioning_client.check_leases()
        wait_for_stage_event(storefront_admin_client, "fulfillment", "capacity_released",
                             since_id=since_id, timeout=10)
        # A repeated cycle and surrender cannot release or terminate again.
        provisioning_client.check_leases()
        delivery = vm_lifecycle_buyer.read(purchase)
        assert delivery["progress"] == "released", delivery
        assert delivery["site_reports"] == purchase.reports
        assert delivery["recorded_end"] == purchase.receipt["selected_end"]
        site = provisioning_client.get_lease(purchase.reservation_id)
        assert site.status == "released" and len(site.end_reports) == 1, site
        assert site.release_job_id == purchase.fulfillment_id, site
        # VM release events are reservation-scoped, not negotiation-scoped.
        released = [e for e in storefront_admin_client.get_events(
            stage="fulfillment", limit=500).events if e.event == "capacity_released"
            and e.data.get("capacity_reservation_id") == purchase.reservation_id]
        assert len(released) == 1, released
        assert released[0].data["capacity_reservation_id"] == purchase.reservation_id
