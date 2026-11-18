"""The watchdog stops a rate deal through the VM buyer's own lifecycle composition.

Library integration: VM's ``buyer_lifecycle`` composes the payments adapter over
the in-process payments engine, holding an approved rate mandate, with the
buyer's SQLite evidence store. The storefront is unreachable and the injected
probe fails, as when the resource is lost while the seller is down. Nothing here
runs a delivered deal: the probe stands for the disclosed access. The same
composition's payment-stop classifier, bound to the Agreement, is read against
authority views built here.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

import asyncio
from datetime import datetime, timezone
import json
import time

from market_arkhai_payments import PaymentApproval, PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient, dispute_lifecycle, recurring_options
from market_arkhai_payments.settlement_config import ArkhaiPaymentsConfig
from market_core.schemas import Agreement
from market_deal_lifecycle.configuration import DisputeEntry
from market_deal_lifecycle_buyer import FileEvidenceStore, WatchdogSettings, watch_deal
from market_deal_lifecycle_contracts.models import Accepted, AuthorityView, PaymentEvent, PaymentPartObservation
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_settlement_runtime.rate_servicing import RateServicing, RateServicingDeclaration

from arkhai_vms_buyer.lifecycle import buyer_lifecycle

MECHANISM = "arkhai.payments.v1"
PAYER = "11111111-1111-4111-8111-111111111111"
PAYEE = "22222222-2222-4222-8222-222222222222"
DISPUTE = "33333333-3333-4333-8333-333333333333"
BUYER = Ed25519Signer(bytes([1]) * 32)
SELLER = Ed25519Signer(bytes([2]) * 32)
PAYMENTS_SERVICE = Ed25519Signer(bytes([7]) * 32)
#: Nothing listens on the discard port, so every storefront call fails at once.
UNREACHABLE_STOREFRONT = "http://127.0.0.1:9"
#: The payer's stop charges its started period; the payee's stop and the term
#: end return the final partial one. Declared only for this fixture.
SERVICING = RateServicing({MECHANISM: RateServicingDeclaration(MECHANISM, frozenset({"charged", "returned"}))})


def approved_rate_deal():
    """An accepted on-demand Agreement and its rate mandate, approved at the engine."""
    now = int(time.time())
    authority = DisputeEntry.model_validate({
        **dispute_lifecycle(DISPUTE)["adjudication"]["dispute"],
        "advertisement": {"mechanisms": [MECHANISM], "minimum_dispute_window_seconds": 0,
                          "minimum_case_hold_seconds": None},
    })
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    agreement = Agreement.model_validate({
        "negotiation_id": "watchdog-deal", "listing_id": "listing", "listing_hash": "a" * 64,
        "buyer": BUYER.identity.model_dump(mode="json"), "seller": SELLER.identity.model_dump(mode="json"),
        "settlement": recurring_options(authority, payee=PAYEE)["on-demand"],
        "settlement_params": {"payer_account": PAYER},
        # One 15-minute period at the option's 60 USD/2 an hour.
        "amount": 1500, "asset": "USD/2", "duration_seconds": 3600,
        "accepted_at": stamp, "start_utc": stamp,
        "provision_terms": {"kind": "example.v1", "version": 1, "payload": {}},
    }).model_dump(mode="json", exclude_none=True)
    config = ArkhaiPaymentsConfig(enabled=True, service_url="http://127.0.0.1:9",
                                 service_identity=PAYMENTS_SERVICE.identity, fee_bps=250, development_auth=True)
    data = PaymentSettlementData.for_agreement(agreement, config, rate_servicing=SERVICING)
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE, observed_at=now)
    # The engine approves at its clock, now, so the term has not run out.
    payments.engine.fund(PAYER, "USD/2", 10**9)
    payments.receipt = payments.engine.approve(data.mandate, account=PAYER)
    return agreement, data, PaymentApproval(config, PAYER, client_for_owner=payments), payments


async def no_wait(_seconds):
    return None


def test_the_watchdog_sends_one_payer_stop_and_a_restart_sends_nothing_more(tmp_path):
    agreement, data, approval, payments = approved_rate_deal()
    store = FileEvidenceStore(tmp_path / "evidence")
    negotiation_id = agreement["negotiation_id"]
    store.watchdog.opt_in(negotiation_id, WatchdogSettings(interval_seconds=1, threshold=3, probe_timeout_seconds=1))
    probes = []

    async def lost():
        probes.append(time.time())
        raise ConnectionRefusedError("host unreachable")

    async def watch():
        async with buyer_lifecycle(
            agreement_bytes=json.dumps(agreement), settlement_data=data.to_wire(),
            seller_url=UNREACHABLE_STOREFRONT, signer=BUYER,
            publishers=TrustedIdentitySet(identities=(SELLER.identity,)), approval=approval,
            store=store, timeout=2,
        ) as lifecycle:
            return await watch_deal(lifecycle, negotiation_id, journal=store.watchdog, probe=lost, sleep=no_wait)

    outcome = asyncio.run(watch())

    assert outcome.reason == "stopped"
    assert outcome.progress.mode == "normal_stop" and outcome.progress.payment.status == "accepted"
    # The storefront is down: the hint is lost, which never changes the stop.
    assert outcome.progress.hint.status == "unknown"
    assert len(probes) == 3
    # Exactly one payer stop reached the engine, and it ended the unstarted rate part.
    assert payments.count("submit_event") == 1
    (part,) = payments.engine.snapshot(data.transaction_id).snapshot.parts
    assert part.started is None and part.stop is not None and part.stop.cause.value == "payer"
    stop = store.watchdog.state(negotiation_id).stop
    assert [probe.detail for probe in stop.probes] == ["probe failed: ConnectionRefusedError"] * 3
    kept = asyncio.run(store.read(negotiation_id))
    assert [item.kind for item in kept.items if item.kind == "watchdog_probe_failures"] == ["watchdog_probe_failures"]

    restarted = asyncio.run(watch())

    assert restarted.reason == "stopped" and restarted.progress.payment.status == "accepted"
    assert len(probes) == 3 and payments.count("submit_event") == 1


def test_the_composition_tells_funds_running_out_from_the_term_end(tmp_path):
    agreement, data, approval, _ = approved_rate_deal()
    term_end = int(datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00")).timestamp()) + (
        agreement["duration_seconds"]
    )

    def ended(at):
        """The authority's view of the rate part stopped under ``terms`` at ``at``."""
        return AuthorityView(outcome=Accepted(), state="ended", parts=[PaymentPartObservation(
            part="0", evidence_ref="snapshot", final_stop=PaymentEvent(
                negotiation_id=agreement["negotiation_id"], commitment_ref=data.transaction_id, part="0",
                kind="stop", actor="terms", at=at, cause="terms", sequence=2,
                authority_record_ref=f"{data.transaction_id}:events:2",
            ),
        )])

    async def funding_stops():
        async with buyer_lifecycle(
            agreement_bytes=json.dumps(agreement), settlement_data=data.to_wire(),
            seller_url=UNREACHABLE_STOREFRONT, signer=BUYER,
            publishers=TrustedIdentitySet(identities=(SELLER.identity,)), approval=approval,
            store=FileEvidenceStore(tmp_path / "evidence"), timeout=2,
        ) as lifecycle:
            # One period before the Agreement's end the balance could not
            # reserve the next period; at its end the deal reached its term.
            return lifecycle.funding_stopped(ended(term_end - 900)), lifecycle.funding_stopped(ended(term_end))

    assert asyncio.run(funding_stops()) == (True, False)
