"""Drive VM signed site push, authenticated pull and capacity-return progress.

All principals are deterministic public development fixtures; never use them on
a public network. State is invocation-owned SQLite and HTTP is in process.
"""

import json
import threading
import time
from datetime import datetime, timezone

import httpx
import pytest
from arkhai_vms import make_vm_provision_terms
from arkhai_vms_buyer.lifecycle import buyer_lifecycle
from compute_provisioning_client import ComputeProvisioningClient
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.auth import signed_response_headers
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_payments import PaymentApproval, PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle.terms import decode_terms
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from pydantic import SecretStr
from storefront_client import StorefrontClientError

import market_storefront.server  # noqa: F401 - controller composition order
from market_storefront import container
from market_storefront.controllers.lease_reports import router
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
from market_storefront.failure_actions import FulfillmentFailureContext, apply_fulfillment_failure_policy
from market_storefront.services.capacity_client import AggregateFulfillmentClient
from tests._settings_overrides import settings_overrides
from tests.integration.test_rate_delivery import PAYER as RATE_PAYER
from tests.integration.test_rate_delivery import _published, accepted_recurring_deal, approve
from tests.integration.test_payment_settlement import (
    BUYER,
    LISTING,
    NEGOTIATION,
    PAYER,
    SELLER,
    _client,
    _config,
)
from tests.integration.test_payment_settlement import make as make
from tests.recurring_world import MECHANISM, PAYMENTS_SERVICE, delivery_capacity, recurring_world, settlement

SITE = Ed25519Signer(b"\x51" * 32)
RESERVATION = "fixture-vm-reservation"
SITE_ID = "site-test"


@pytest.mark.asyncio
async def test_hosted_buyer_commit_and_end_capture_signed_push_retry_and_pull(make, tmp_path):
    h = await make()
    loop_thread = threading.get_ident()
    verifier = h.lifecycle.ingress.verify_site
    verification_threads = []

    def verify(*args):
        verification_threads.append(threading.get_ident())
        return verifier(*args)

    h.lifecycle.ingress.verify_site = verify
    h.serve()
    store = FileEvidenceStore(tmp_path / "buyer-evidence")
    agreement, _ = h.lifecycle.accepted(NEGOTIATION)
    approval = PaymentApproval(_config(), PAYER, client_for_owner=h.payments)
    mediation = MediationContractFake()
    authority = decode_terms(agreement["settlement"]["lifecycle"]).adjudication.dispute
    h.lifecycle.clients[canonical_json(authority)] = MediationClient(
        authority, MediationCredential(authority.identity, token=SecretStr("fixture-payee")),
        transport=mediation.transport(),
    )
    h.lifecycle.credential_available = lambda candidate: candidate == authority
    h.lifecycle.seller.credential_available = h.lifecycle.credential_available

    def buyer_half():
        return buyer_lifecycle(
            agreement_bytes=canonical_json(agreement), settlement_data=h.data.to_wire(),
            seller_url="http://test", signer=BUYER,
            publishers=TrustedIdentitySet(identities=(SELLER.identity,)),
            approval=approval, store=store, transport=h.transport,
        )

    async with buyer_half() as buyer:
        outcome = await buyer.commit(CommitMessage(
            negotiation_id=NEGOTIATION, commitment_ref=h.data.transaction_id,
            operation_key="fixture-commit",
        ))
        assert isinstance(outcome, Accepted)
    await h.delivered()
    async with LifecycleClient(
        "http://test", SELLER, TrustedIdentitySet(identities=(SELLER.identity,)), transport=h.transport,
    ) as stranger:
        with pytest.raises(LifecycleClientError) as refused:
            await stranger.end_delivery(NEGOTIATION, operation_key="wrong-buyer")
        assert refused.value.status_code == 403
    with transaction(h.db.db_path) as conn:
        assert EndSession(conn).requests(NEGOTIATION) == []
    await h.db.save_capacity_hold(
        negotiation_id=NEGOTIATION, listing_id=LISTING, capacity_reservation_id=RESERVATION,
    )
    await h.db.update_vm_delivery(
        negotiation_id=NEGOTIATION, capacity_reservation_id=RESERVATION,
    )
    trust = ServicePeerTrust(h.db.db_path, {
        "fixture-provisioner": ("service", SITE_ID, TrustedIdentitySet(identities=(SITE.identity,))),
    })
    trust.seed()
    container.resolved_service_peer_trust = trust
    app = FastAPI()
    app.include_router(router)
    app.middleware("http")(service_peer_callback_middleware)
    now = h.lifecycle.clock()
    event = LeaseEndedEvent(
        event_id="fixture-site-end", capacity_reservation_id=RESERVATION, site_id=SITE_ID,
        effective_at=now, cause="force_release", source_state="leased",
        reason="development failure", caller=SITE.identity,
    )
    report = sign_lease_end(event, SITE)
    body = report.model_dump(mode="json")
    path = "/api/v1/capacity/reservations/" + RESERVATION + "/lease-ended"
    try:
        async with _client(BUYER, "service", httpx.ASGITransport(app=app)) as stranger:
            with pytest.raises(StorefrontClientError) as refused:
                await stranger.authenticated_request(
                    "POST", path, role="service", operation="lease_ended",
                    resource=RESERVATION, body=body,
                )
            assert refused.value.status_code == 403
        async with _client(SITE, "service", httpx.ASGITransport(app=app)) as site:
            async def send(value):
                return await site.authenticated_request(
                    "POST", path, role="service", operation="lease_ended",
                    resource=RESERVATION, body=value,
                )

            # A valid transport signature cannot authenticate a forged inner proof.
            forged = sign_lease_end(event, BUYER).model_dump(mode="json")
            try:
                await send(forged)
            except StorefrontClientError as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("forged inner report accepted")
            first = await send(body)
            second = await send(body)
            assert first["progress"] == second["progress"] == "tearing_down"
            assert len(second["site_reports"]) == 1
            kept = second["site_reports"][0]
            filings = await h.lifecycle.seller.dispatch_filings(NEGOTIATION)
            assert len(filings) == 1 and filings[0].outcome.status == "accepted"
            assert len(mediation.cases) == 1
            assert mediation.entries[0]["entry"]["filing"]["request"]["cause"] == "payee"
            assert h.payments.count("reverse") == 0
            # Pull repeats the site statement through different transport.
            # The typed client verifies the signed HTTP response at this seam.
            other = sign_lease_end(event.model_copy(update={
                "event_id": "fixture-earlier-end", "effective_at": now - 1,
            }), SITE)
            reports = [report, other]
            lease = {
                "version": 1, "capacity_reservation_id": RESERVATION,
                "deal_ref": {"negotiation_id": NEGOTIATION}, "offering_mode": "vm",
                "executor_target": "fixture", "lease_end_utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                "status": "releasing", "end_reports": [value.model_dump(mode="json") for value in reports],
            }

            def read(request):
                headers = signed_response_headers(
                    signer=SITE, role="service", method="GET", operation="provisioning_lease_get",
                    resource=RESERVATION, request_id=request.headers["X-Market-Request-ID"],
                    status=200, body=lease,
                )
                return httpx.Response(200, json=lease, headers=headers)

            async with ComputeProvisioningClient(
                "http://site", signer=SELLER, caller_role="seller",
                expected_authorities=TrustedIdentitySet(identities=(SITE.identity,)),
                transport=httpx.MockTransport(read),
            ) as provisioner:
                h.lifecycle.fulfillment = AggregateFulfillmentClient(
                    {SITE_ID: provisioner}, reservation_sites={},
                )
                await h.lifecycle.recover_site_reports(NEGOTIATION)
                await h.lifecycle.recover_site_reports(NEGOTIATION)
            assert verification_threads and all(value != loop_thread for value in verification_threads)
            with transaction(h.db.db_path) as conn:
                view = EndSession(conn).view(NEGOTIATION)
                assert view.recorded_end.ended_at == now - 1
                assert len(view.site_reports) == 2
                assert view.site_reports[0].headers == kept["headers"]
                assert json.loads(view.site_reports[0].body) == body
                assert view.progress == "tearing_down"
            async with buyer_half() as buyer:
                observed = await buyer.peer.read(NEGOTIATION)
                assert len(observed.delivery.site_reports) == 2
                assert json.loads(observed.delivery.site_reports[0].body) == body
                progress = await buyer.end_delivery(NEGOTIATION)
                assert isinstance(progress.delivery, Accepted)
                retry = await buyer.end_delivery(NEGOTIATION)
                assert retry.acknowledgement.receipt_at == progress.acknowledgement.receipt_at
                assert retry.payment.status == "rejected"  # Once-only has no stop.
                assert retry.case.status == "rejected"  # The earlier seller end must not become a payer claim.
            evidence = await store.read(NEGOTIATION)
            assert len([item for item in evidence.items if item.kind == "lease_ended"]) == 2
            assert any(item.kind == "end_delivery_receipt" for item in evidence.items)
            # Only the already authenticated capacity-return callback's local
            # effect is invoked here; its HTTP route has existing regressions.
            h.lifecycle.capacity_released(RESERVATION, SITE_ID)
            with transaction(h.db.db_path) as conn:
                assert EndSession(conn).view(NEGOTIATION).progress == "released"
            changed = sign_lease_end(event.model_copy(update={"reason": "changed"}), SITE)
            try:
                await send(changed.model_dump(mode="json"))
            except StorefrontClientError as exc:
                assert exc.status_code == 400
            else:
                raise AssertionError("same event with changed signed payload accepted")

    finally:
        container.resolved_service_peer_trust = None


def recorded_end(path, negotiation_id):
    """The deal's selected end and its classification, ``None`` while pending."""
    with transaction(path) as conn:
        end = EndSession(conn)
        selected = end.selected_end(negotiation_id)
        return selected, end.classification(negotiation_id, selected.source_ref)


def filings(path, negotiation_id):
    with transaction(path) as conn:
        return [intent for intent in EndSession(conn).intents(negotiation_id) if intent.kind == "filing"]


async def accepted_once_deal(world):
    """Negotiate the world's once-only payments option to acceptance through the buyer's typed client."""
    listing = await _published(world)
    option = next(
        option for option in listing["settlement_options"]
        if option["settlement"]["schema"] == MECHANISM and "period" not in option["settlement"]
    )
    reply = await world.app.buyer.negotiate_new(
        listing_id=listing["listing_id"],
        # The whole hour at the clause's 2.5 an hour, in base units.
        initial_amount=2_500_000,
        provision_terms=make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 test",
        ).model_dump(mode="json"),
        settlement_selection={
            "option_id": option["option_id"], "expiration_unix": 2_147_483_647,
            "settlement": {"schema": MECHANISM, "payer_account": RATE_PAYER},
        },
        selection_only=True,
    )
    assert reply["action"] == "accept"
    negotiation_id = reply["agreement"]["negotiation_id"]
    thread = await world.app.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    raw = thread["settlement_data"]
    return negotiation_id, PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw)


@pytest.mark.asyncio
async def test_a_delivered_rate_deal_buyer_stop_is_an_entitled_stop_that_discharges_a_later_failure(tmp_path):
    async with recurring_world(tmp_path) as world, settlement(world) as settled:
        negotiation_id, data = await accepted_recurring_deal(world)
        approve(settled, data)
        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)

        # The on-demand buyer stops at the payment authority; the servicing
        # cycle reads it there and records the stop.
        settled.payments.observed_at = int(time.time())
        settled.payments.engine.submit(data.transaction_id, {
            "account": RATE_PAYER, "requestId": "buyer-stop", "event": {"kind": "stop"},
        })
        await world.app.client.admin_run_lifecycle_cycle("deal-servicing")
        stop, classification = recorded_end(world.app.db.db_path, negotiation_id)
        assert stop.cause == "payer"
        assert classification.kind == "entitled_stop"

        # Provisioning then reports the resource failed: the failure is
        # recorded under the buyer's classified end, and nothing is filed.
        with settings_overrides(**{"fulfillment.failure_policy.actions": ["release_capacity"]}):
            await apply_fulfillment_failure_policy(world.app.db, FulfillmentFailureContext(
                negotiation_id=negotiation_id, reason="provisioning_failed", source="settlement_provisioning",
            ), capacity=delivery_capacity(settled.site))
        source = "fulfillment-failure:" + negotiation_id
        with transaction(world.app.db.db_path) as conn:
            end = EndSession(conn)
            [failure] = [request for request in end.requests(negotiation_id) if request.source_ref == source]
            classification = end.classification(negotiation_id, source)
        assert failure.controlling_source_ref == stop.source_ref
        assert classification.kind == "entitled_stop"
        assert filings(world.app.db.db_path, negotiation_id) == []


@pytest.mark.asyncio
async def test_a_once_only_deal_term_end_is_recorded_classified_and_torn_down(tmp_path):
    """Past the Agreement's end, the storefront records its own term end and the
    payments service's term end, both classified the term end, and drives the
    deal's teardown."""
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments) as settled:
        negotiation_id, data = await accepted_once_deal(world)
        assert all(part.root.kind == "once" for part in data.mandate.parts)
        approve(settled, data)
        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)
        with transaction(world.app.db.db_path) as conn:
            record = EndSession(conn).read(negotiation_id)
    assert record.available_at is not None

    # Past the Agreement's end the payments service records the part's term
    # end; the storefront, restarted then, reads it in its servicing cycle.
    at = record.term_end + 60
    payments.observed_at = at
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments, clock=lambda: at):
        await world.app.client.admin_run_lifecycle_cycle("deal-servicing")
        with transaction(world.app.db.db_path) as conn:
            end = EndSession(conn)
            requests = {request.source_ref.partition(":")[0]: request for request in end.requests(negotiation_id)}
            classifications = {
                kind: end.classification(negotiation_id, request.source_ref) for kind, request in requests.items()
            }
            selected = end.selected_end(negotiation_id)
            terminations = [intent for intent in end.intents(negotiation_id) if intent.kind == "terminate"]
            progress = end.read(negotiation_id).progress
    assert set(requests) == {"payment-stop", "term-end"}
    stop, own = requests["payment-stop"], requests["term-end"]
    # The payments service ends the part at the whole second at or after the
    # Agreement's end; the storefront's own term end is the Agreement's end.
    assert (stop.cause, own.cause, own.ended_at) == ("terms", "terms", record.term_end)
    assert stop.ended_at >= record.term_end
    assert {kind: classification.kind for kind, classification in classifications.items()} == {
        "payment-stop": "terms", "term-end": "terms",
    }
    assert selected.ended_at == record.term_end
    assert filings(world.app.db.db_path, negotiation_id) == []
    # The teardown is commanded and acknowledged, and the deal released: the
    # restarted storefront's site holds no reservation, so the end completes
    # with nothing to release.
    # The authorities read records the payment stop before reconciliation
    # records the term end, so the cycle's first physical end commands the
    # termination at the stop's instant, and a termination is never restarted.
    [termination] = terminations
    assert termination.payload["at"] == stop.ended_at
    assert termination.result is not None
    assert progress == "released"
