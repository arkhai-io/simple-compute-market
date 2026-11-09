"""Stages of a compute buyer purchase through the shipped buyer, defined once.

A buyer purchase discovers, negotiates and pays through the domain's own buyer
CLI (``market buy``, ``market bare-metal buy``) in ``arkhai.payments.v1``, then
runs the canonical compute deal's stages from fulfillment onwards, from
``compute_deal_stages.py``, keyed on its settlement reference: the negotiation.
Every scenario buying this way declares these stages in order, by subclassing
them with an empty body, exactly as the canonical deal's lanes do, and inserts
its own stages between them; a stage whose body would differ between purchases
is not defined here. The classes are not named ``Test*``, so pytest collects
them only through those subclasses. ``tests/unit/test_buyer_purchase_stages.py``
holds every purchase module to that order.

A purchase module declares, in order:

- the canonical deal's readiness stages it shares (``Stage00`` to ``Stage00c2``,
  a mock lane's ``Stage00e``, ``Stage00f1``, which seeds the supply through the
  driver, and ``Stage00h``), then its own listing stages, which write
  ``seller_listing_id`` and ``listing_published``;
- ``Purchase01`` to ``Purchase04`` here, a mock lane arming ``Stage07a``
  before the buy and releasing and draining through ``Stage08b2`` after the
  correlation, then ``Purchase05``'s payment records;
- ``Stage09a``, ``Stage09b`` and ``Stage09c``, ``09b`` waiting on the
  negotiation through the storefront's settle wait, then ``Purchase09``, the
  buyer's command ended;
- the ending its lease ends by: the canonical deal's expiry stages, or
  ``Purchase10``'s buyer teardown, which a mock lane surrounds with
  ``Stage09c2`` and ``Stage11a2``; then ``Stage11b``.

The purchase command runs in the background from ``Purchase03`` on, because a
domain's buyer may keep polling its settlement until delivery, as ``market
buy`` does: fulfillment convergence is held for the module, so delivery is a
step later stages ask for, and a command run in the foreground would wait for
it forever. ``Purchase03`` waits only until the command has committed the paid
purchase, and ``Purchase09`` until it has ended, once delivery is ready.

What differs between domains reaches a stage two ways, as in the canonical
deal. Fixtures supply who is calling, under the canonical deal's names
(``storefront_admin_client``, ``provisioning_client``, ``deal_state``,
``deal_driver``) and two of a purchase's own: ``purchase_cli``, the buyer's
profiled CLI, and ``payments_config``, the run's payments target. The
``deal_driver`` fixture is a ``PurchaseDriver``: the domain's command, its
arguments and the buyer's configuration, besides the canonical deal's part.

The purchase writes the inputs the shared stages from fulfillment onwards read
(``openspec/specs/test-compatibility/spec.md``, "The canonical compute deal's
shared stages are defined once"): its settlement reference, the fulfillment its
dispatch began, and the expected host, from the driver's declared host, never
from the lease ``09c`` compares it with.
"""

from __future__ import annotations

import base64
import logging
import subprocess
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Optional, Protocol

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    PaymentSettlementData,
    agreement_from_bytes,
    verify_receipt,
    verify_snapshot,
)
from market_core.schemas import SettlementOption
from market_deal_lifecycle_buyer import EndDeliveryProgress
from market_deal_lifecycle_contracts.models import Accepted

from tests.e2e.roles.helpers.compute_deal import assert_lease_watchdog_held
from tests.e2e.roles.helpers.compute_deal_stages import (
    ComputeDealDriver,
    ComputeDealState,
    utc_instant,
)
from tests.e2e.roles.helpers.domain_deal import (
    assert_market_run_succeeded,
    ordered_events,
    require_state,
)
from tests.e2e.roles.helpers.mediation import mediation_if_configured
from tests.e2e.roles.helpers.payments import buyer_payments_client, payment_setting

log = logging.getLogger(__name__)

#: How long ``Purchase09`` waits for the buyer's command to end once the
#: settlement reads ready: a command polling its settlement reads it ready at
#: its next poll, and one that ended at its commit has ended already.
PURCHASE_RUN_EXIT_SECONDS = 30.0


@dataclass
class PurchaseState(ComputeDealState):
    """What a buyer purchase's stages hand each other, beside the canonical deal's.

    The purchase writes the canonical deal's ``negotiation_id`` and
    ``settlement_id`` (the payments transaction), and the handoff its shared
    stages read: ``settlement_ref`` (the negotiation), ``fulfillment_id``,
    ``expected_host_id``, and the Agreement's window, ``agreement_start`` and
    ``agreement_end``.
    """

    #: The payer account the run names, whose balance ``Purchase01`` read.
    payer_account: Optional[str] = None
    #: The payer's available balance by asset before the purchase, read with
    #: the buyer's own token.
    payer_available_before: Optional[dict[str, int]] = None
    #: The listing's ``arkhai.payments.v1`` option the buyer buys.
    purchase_option_id: Optional[str] = None
    #: The buyer CLI's purchase run (``MarketRun``).
    purchase_run: Optional[Any] = None
    #: The accepted Agreement, decoded from the run's exact bytes.
    agreement: Optional[dict[str, Any]] = None
    #: The seller's acceptance artifact: the mandate and its transaction
    #: (``PaymentSettlementData``).
    payment_settlement: Optional[Any] = None
    #: The buyer's teardown has been asked for: from then on the purchase is
    #: being ended, not abandoned, whatever ``Purchase10``'s checks find.
    _buyer_teardown_requested: bool = False


class PurchaseDriver(ComputeDealDriver, Protocol):
    """What a domain supplies to a buyer purchase, beside the canonical deal's part."""

    #: The host the purchase's lease must name: the one host the scenario
    #: registered enabled for its resource, or a real target's host.
    declared_host_id: str
    #: The domain's purchase command, as a failure names it.
    buy_command: str
    #: The domain's teardown command, as a failure names it.
    teardown_command: str
    #: How long the purchase command may take to commit, its payment wait
    #: included.
    buy_timeout_seconds: float
    #: The run-log event the purchase command writes once the seller has
    #: accepted its commit of the paid purchase; read after the command's
    #: ``payment_approved``, so an end it records without paying is not one.
    committed_event: str

    def discover(self, listing_id: str) -> Any:
        """The listing, read from the registry as the buyer's purchase profile."""

    def check_purchase_option(self, listing: Any, option: SettlementOption) -> None:
        """Assert what the domain's listing and its payments option state."""

    def buy_arguments(self, listing_id: str, option_id: str) -> list[str]:
        """The domain's purchase command and its arguments."""

    def teardown_arguments(self, run_id: str) -> list[str]:
        """The domain's buyer teardown of the run's deal, and its arguments."""

    def purchase_fulfillment(self, negotiation_id: str) -> dict[str, Any]:
        """The deal's fulfillment as the seller reports it to the buyer, once
        the seller has dispatched it."""

    def check_run_ended(self, ended: dict[str, Any], deal_state: Any) -> None:
        """Assert what the domain's purchase command records as it ends."""


def _available(balance: Any) -> dict[str, int]:
    return {asset: int(amount.root) for asset, amount in balance.available.items()}


# ===========================================================================
# Before the purchase
# ===========================================================================

class Purchase01_PayerBalanceBefore:
    def test_p01_the_payers_balance_is_read_before_the_purchase(
        self, payments_config, deal_state: PurchaseState,
    ):
        """The payer's own available balance, before the scenario's first approval.

        Read with the buyer's token, as the payments service answers a balance
        only for the caller's own account. ``Purchase05`` compares the drop
        with the purchase's debit.
        """
        payer = str(payment_setting("BUYER_ACCOUNT"))
        with buyer_payments_client(payments_config, payer) as client:
            before = _available(client.get_balance(payer))
        deal_state.payer_account = payer
        deal_state.payer_available_before = before
        log.info("[p01] Payer %s available before the purchase: %s", payer, before)


class Purchase02_ListingDiscovered:
    def test_p02_the_buyer_discovers_the_listing_and_its_payments_option(
        self, deal_driver: PurchaseDriver, deal_state: PurchaseState,
    ):
        """The buyer's purchase profile finds the open listing and its payments option.

        Once it has, the purchase is about to settle, so a mock lane's
        ``Stage07a`` may arm the create gate.
        """
        require_state(deal_state, "seller_listing_id", "listing_published",
                      "payer_available_before")
        listing = deal_driver.discover(deal_state.seller_listing_id)
        assert str(listing.id) == deal_state.seller_listing_id, listing
        assert listing.status == "open", listing
        options = [
            option for option in (
                SettlementOption.model_validate(item) for item in listing.settlement_options
            )
            if option.settlement_schema == ARKHAI_PAYMENTS_MECHANISM
        ]
        assert len(options) == 1, (
            f"listing {listing.id} offers {len(options)} {ARKHAI_PAYMENTS_MECHANISM} "
            f"options: {listing.settlement_options}"
        )
        (option,) = options
        payee = str(payment_setting("SELLER_ACCOUNT"))
        assert option.settlement_params["payee_account"] == payee, option.settlement_params
        deal_driver.check_purchase_option(listing, option)
        deal_state.purchase_option_id = option.option_id
        deal_state._settlement_imminent = True
        log.info("[p02] Listing %s offers payments option %s to payee %s",
                 listing.id, option.option_id, payee)


# ===========================================================================
# The purchase
# ===========================================================================

class Purchase03_Bought:
    def test_p03_the_buyer_buys_through_its_cli(
        self, purchase_cli, deal_driver: PurchaseDriver, deal_state: PurchaseState,
    ):
        """One run of the domain's purchase command negotiates, approves and commits.

        The command runs in the background, and the stage waits for its
        commit, not its end: a command that polls its settlement until
        delivery ends only after the later stages have stepped delivery
        (``Purchase09``). The approval comes first: a command may record its
        end without paying, as a refused negotiation does, and a run that ends
        before its approval fails here with its exit status. A run that has
        not committed is stopped here, so no stage after it depends on a
        purchase still in flight.

        A run that records no approval fails naming the payer: funding the
        payer is the deployment's, never the scenario's, so a payer that
        cannot pay is what the failure must point at.
        """
        require_state(deal_state, "seller_listing_id", "purchase_option_id",
                      "_settlement_imminent")
        run = purchase_cli.run(
            deal_driver.buy_arguments(deal_state.seller_listing_id, deal_state.purchase_option_id),
            background=True,
        )
        try:
            try:
                run.wait_for_event("payment_approved", timeout=deal_driver.buy_timeout_seconds)
            except AssertionError as error:
                raise AssertionError(
                    f"{deal_driver.buy_command} run {run.run_id} recorded no payment approved "
                    f"by payer {deal_state.payer_account}: {error}"
                ) from error
            run.wait_for_event(deal_driver.committed_event, timeout=deal_driver.buy_timeout_seconds)
        except BaseException:
            run.terminate()
            raise
        deal_state.purchase_run = run
        log.info("[p03] Buyer run %s committed its purchase (%s) of listing %s",
                 run.run_id, deal_driver.committed_event, deal_state.seller_listing_id)


class Purchase04_PurchaseCorrelated:
    def test_p04_the_runs_events_correlate_one_paid_deal(
        self, provisioning_client, deal_driver: PurchaseDriver, deal_state: PurchaseState,
    ):
        """The run's Agreement, settlement data, transaction and fulfillment name one deal.

        Read from the run-log events every domain's purchase command writes:
        the accepted negotiation, carrying the Agreement's exact bytes and the
        seller's settlement data, and the approval naming its transaction. The
        Agreement names the listing and option the buyer discovered, which a
        command selecting its listing by discovery must have bought.

        The fulfillment is the one the seller reports to the buyer, read in
        provisioning dispatched and not yet converged: fulfillment convergence
        is held for the module, so only ``Stage09a``'s advance moves it.
        """
        require_state(deal_state, "purchase_run", "seller_listing_id", "purchase_option_id")
        run = deal_state.purchase_run
        started, accepted, approved = ordered_events(
            run.read_events(), "run_started", "negotiation_completed", "payment_approved",
        )
        assert all(event["run_id"] == run.run_id for event in (started, accepted, approved))
        assert accepted["status"] == "agreed", accepted
        negotiation_id = accepted["negotiation_id"]
        agreement = agreement_from_bytes(base64.b64decode(accepted["agreement_bytes"], validate=True))
        data = PaymentSettlementData.parse(accepted["settlement_data"])
        data.require_bound_to(agreement)
        assert agreement["negotiation_id"] == negotiation_id, agreement
        assert agreement["listing_id"] == deal_state.seller_listing_id, agreement
        assert agreement["settlement"]["option_id"] == deal_state.purchase_option_id, agreement
        assert approved["transaction_id"] == data.transaction_id, approved

        status = deal_driver.purchase_fulfillment(negotiation_id)
        fulfillment_id = str(status.get("fulfillment_id") or "")
        assert fulfillment_id, f"the purchase's settlement began no fulfillment: {status}"
        dispatched = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert dispatched.get("state") == "dispatching", (
            f"Expected fulfillment dispatched and not yet converged, got: {dispatched}"
        )
        deal_state.negotiation_id = negotiation_id
        deal_state.settlement_id = data.transaction_id
        # The negotiation is what every storefront's settle wait resolves a
        # payments deal by, and what its hold names.
        deal_state.settlement_ref = negotiation_id
        deal_state.agreement = agreement
        deal_state.payment_settlement = data
        deal_state.fulfillment_id = fulfillment_id
        # Declared by the driver, never read from the lease 09c compares it with.
        deal_state.expected_host_id = deal_driver.declared_host_id
        # The window the Agreement's exact bytes commit, which 09c holds the
        # delivered lease to.
        deal_state.agreement_start = utc_instant(agreement["start_utc"])
        deal_state.agreement_end = deal_state.agreement_start + timedelta(
            seconds=int(agreement["duration_seconds"])
        )
        log.info("[p04] Run %s: Agreement %s, transaction %s, fulfillment %s; expected host %s",
                 run.run_id, negotiation_id, data.transaction_id, fulfillment_id,
                 deal_state.expected_host_id)


class Purchase05_PaymentRecordsChecked:
    def test_p05_the_transaction_matches_its_agreement_and_the_payers_debit(
        self, payments_config, deal_state: PurchaseState,
    ):
        """The transaction is the Agreement's, and the payer's balance fell by its debit.

        The snapshot and its receipt are verified against the receipt keys the
        payments configuration trusts and bound to the Agreement and its
        mandate; the receipt names
        the configured payer and payee, and its parts' gross is the Agreement's
        price for its duration. The balance drop since ``Purchase01`` equals
        that debit only while nothing else spends from the payer account: the
        account is dedicated to the run, a topology guarantee this scenario
        cannot check, so it is logged beside the result.
        """
        require_state(deal_state, "settlement_id", "agreement", "payment_settlement",
                      "payer_available_before")
        payer = str(payment_setting("BUYER_ACCOUNT"))
        payee = str(payment_setting("SELLER_ACCOUNT"))
        agreement = deal_state.agreement
        mandate = deal_state.payment_settlement.mandate
        with buyer_payments_client(payments_config, payer) as client:
            signed = client.get_transaction(str(deal_state.settlement_id))
            after = _available(client.get_balance(payer))
        snapshot = signed.snapshot
        assert snapshot.transaction.root == deal_state.settlement_id, snapshot.transaction
        # The receipt keys the buyer and seller trust, retiring keys included.
        trust = payments_config.receipt_trust
        bound = {"mandate": mandate, "agreement_json": agreement,
                 "livemode": payments_config.livemode}
        assert verify_snapshot(signed, trust, **bound), (
            f"the snapshot of {deal_state.settlement_id} is not the pinned service's "
            "for this Agreement and mandate"
        )
        assert verify_receipt(snapshot.receipt, trust, **bound), (
            f"the receipt of {deal_state.settlement_id} does not cover the Agreement's mandate"
        )
        receipt = snapshot.receipt.receipt
        assert (receipt.from_.root, receipt.to.root) == (payer, payee), receipt
        debits: dict[str, int] = {}
        for part in receipt.parts:
            debits[part.asset.root] = debits.get(part.asset.root, 0) + int(part.gross)
        assert debits == {agreement["asset"]: int(str(agreement["amount"]))}, (
            f"the receipt's gross {debits} is not the Agreement's price "
            f"{agreement['amount']} {agreement['asset']} for {agreement['duration_seconds']}s"
        )
        before = deal_state.payer_available_before
        dropped = {
            asset: before.get(asset, 0) - after.get(asset, 0)
            for asset in sorted(set(before) | set(after))
            if before.get(asset, 0) != after.get(asset, 0)
        }
        log.info("[p05] Payer %s is assumed dedicated to this run (a topology guarantee); "
                 "available fell by %s, transaction %s debited %s",
                 payer, dropped, deal_state.settlement_id, debits)
        assert dropped == debits, (
            f"payer {payer}'s available balance fell by {dropped}; the scenario's own "
            f"transaction {deal_state.settlement_id} debited {debits}"
        )


# ===========================================================================
# After delivery
# ===========================================================================

class Purchase09_PurchaseRunEnded:
    def test_p09_the_buyers_purchase_command_ended_successfully(
        self, deal_driver: PurchaseDriver, deal_state: PurchaseState,
    ):
        """The purchase command ended successfully, recording the deal it bought.

        Run once the settlement reads ready (``Stage09b``): a command that
        polls its settlement until delivery ends at its next poll, and one
        that ended at its commit has ended already. What the command records
        as it ends is the domain's.
        """
        require_state(deal_state, "purchase_run", "negotiation_id", "settlement_id",
                      "fulfillment_id", "settlement_status")
        run = deal_state.purchase_run
        try:
            run.wait(timeout=PURCHASE_RUN_EXIT_SECONDS)
        except subprocess.TimeoutExpired:
            raise AssertionError(
                f"{deal_driver.buy_command} run {run.run_id} was still running "
                f"{PURCHASE_RUN_EXIT_SECONDS}s after its settlement read ready; last events "
                f"{[event.get('event') for event in run.events_or_empty()[-6:]]}"
            ) from None
        assert_market_run_succeeded(run, command=deal_driver.buy_command)
        (ended,) = ordered_events(run.read_events(), "run_ended")
        assert ended["run_id"] == run.run_id, ended
        assert ended["negotiation_id"] == deal_state.negotiation_id, ended
        deal_driver.check_run_ended(ended, deal_state)
        log.info("[p09] Buyer run %s ended %s for Agreement %s, transaction %s",
                 run.run_id, ended.get("status"), deal_state.negotiation_id,
                 deal_state.settlement_id)


# ===========================================================================
# The buyer-teardown ending
# ===========================================================================

class Purchase10_BuyerTeardown:
    def test_p10_the_buyers_teardown_begins_the_release(
        self, purchase_cli, provisioning_client, storefront_admin_client,
        deal_driver: PurchaseDriver, deal_state: PurchaseState,
    ):
        """The buyer's CLI ends delivery; the site releases through the lease lifecycle.

        The ending of a purchase whose lease the buyer ends, in place of the
        canonical deal's expiry stages: the teardown leaves the lease
        ``releasing``, never released, so ``Stage11b``'s own lease cycle is
        what releases it, and one convergence advance dispatches the teardown,
        the state ``Stage11b`` starts from. A lease released by the teardown
        itself is outside the shared ending's design, so it fails here.

        The command also files the delivery's end with the deal's dispute
        authority. Where the run names that authority (MEDIATION), the filing
        is accepted and each part held by the authority's extension, with no
        rule installed and so no ruling: a filed case, never a refund. Its
        outcome is no delivery or access-end evidence either, and where the
        run names no authority nothing here reads it.
        """
        require_state(deal_state, "purchase_run", "negotiation_id", "settlement_status",
                      "deal_lease", "lease_id", "reserved_resource_id")
        # The release is Stage11b's own lease cycle, not the timer's.
        assert_lease_watchdog_held(provisioning_client)
        deal_state._buyer_teardown_requested = True
        run = purchase_cli.run(deal_driver.teardown_arguments(deal_state.purchase_run.run_id))
        assert_market_run_succeeded(run, command=deal_driver.teardown_command)
        if mediation_if_configured() is not None:
            progress = EndDeliveryProgress.model_validate_json(run.stdout().strip().splitlines()[-1])
            case = progress.case
            assert isinstance(case, Accepted) and case.filing is not None, progress
            assert case.filing.parts and all(
                part.status == "held" and part.extension_ref for part in case.filing.parts
            ), case.filing
            log.info("[p10] Buyer run %s filed case %s, every part held",
                     deal_state.purchase_run.run_id, case.filing.case_ref)

        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") != "leased", (
            f"the buyer's teardown did not end the seller's delivery; the lease is still leased: {lease}"
        )
        assert lease.get("status") == "releasing", (
            "the buyer's teardown should leave the lease releasing for the lease "
            f"lifecycle's own cycle to release, not release it itself: {lease}"
        )
        status = deal_driver.purchase_fulfillment(deal_state.negotiation_id)
        fulfillment_id = str(status.get("fulfillment_id") or "")
        assert fulfillment_id and fulfillment_id == lease.get("fulfillment_id"), (status, lease)
        pending = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert pending.get("state") == "teardown_dispatch_pending", pending

        provisioning_client.advance_fulfillment_convergence_cycle()
        dispatched = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert dispatched.get("state") == "tearing_down", dispatched
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )
        deal_state.teardown_fulfillment_id = fulfillment_id
        log.info("[p10] Buyer run %s tore down Agreement %s: lease %s releasing, "
                 "fulfillment %s tearing down, resource %s still held",
                 deal_state.purchase_run.run_id, deal_state.negotiation_id,
                 deal_state.lease_id, fulfillment_id, deal_state.reserved_resource_id)
