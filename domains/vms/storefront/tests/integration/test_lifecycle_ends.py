"""Drive VM signed site push, authenticated pull and capacity-return progress.

All principals are deterministic public development fixtures; never use them on
a public network. State is invocation-owned SQLite and HTTP is in process.
"""

import json
import threading
from datetime import datetime, timezone

import httpx
import pytest
from arkhai_vms_buyer.lifecycle import buyer_lifecycle
from compute_provisioning_client import ComputeProvisioningClient
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.auth import signed_response_headers
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from market_arkhai_mediation.client import MediationClient, MediationCredential
from market_arkhai_mediation.fixtures.authority import MediationContractFake
from market_arkhai_payments import PaymentApproval
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
from market_storefront.services.capacity_client import AggregateFulfillmentClient
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
