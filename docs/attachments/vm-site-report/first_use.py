"""Drive VM signed site push, authenticated pull and capacity-return progress.

All principals are deterministic public development fixtures; never use them on
a public network. State is invocation-owned SQLite and HTTP is in process.
"""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import patch
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
import tests.conftest  # noqa: F401 - explicit public storefront domain selection
import market_storefront.server  # noqa: F401 - controller composition order
from compute_provisioning_client import ComputeProvisioningClient
from compute_provisioning_contracts import LeaseEndedEvent, sign_lease_end
from core_storefront.auth import signed_response_headers
from core_storefront.service_peers import ServicePeerTrust
from fastapi import FastAPI
from core_buyer.buyer_config import ResolvedBuyerIdentity
from typer.testing import CliRunner
from arkhai_vms_buyer import arkhai_payments, end_cli, lifecycle as vm_buyer_lifecycle, settlement_stages
from arkhai_vms_buyer.cli import app as buyer_app
from arkhai_vms_buyer.settlement_composition import resolve_buyer_settlement_policy
from market_deal_lifecycle_client import LifecycleClient
from market_arkhai_payments import PaymentApproval
from market_deal_lifecycle_buyer import FileEvidenceStore
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage
from arkhai_vms_buyer.lifecycle import buyer_lifecycle
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json
from market_storefront import container
from market_storefront.controllers.lease_reports import router
from market_storefront.middleware.service_peer_auth import service_peer_callback_middleware
from market_storefront.services.capacity_client import AggregateFulfillmentClient
from storefront_client import StorefrontClientError
from tests.integration.test_payment_settlement import (
    _client, _config, _harness, BUYER, LISTING, NEGOTIATION, PAYER, SELLER,
)

SITE = Ed25519Signer(b"\x51" * 32)
RESERVATION = "fixture-vm-reservation"
SITE_ID = "site-test"


async def main():
    with tempfile.TemporaryDirectory() as root:
        h = await _harness(Path(root))
        h.serve()
        store = FileEvidenceStore(Path(root) / "buyer-evidence")
        agreement, _ = h.lifecycle.accepted(NEGOTIATION)
        approval = PaymentApproval(_config(), PAYER, client_for_owner=h.payments)

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
                # Exercise the real CLI and stage with an injected recovered
                # run context. HTTP, signatures, evidence and end journal stay
                # real; there is no resident registry or buyer-profile fixture.
                store.remember_commitment(NEGOTIATION, h.data.transaction_id)
                document = {
                    "Settlement": {"schema_version": 1, "priority": ["arkhai.payments.v1"],
                                   "arkhai_payments": _config().model_dump(mode="json")},
                    "vms": {"payer_account": PAYER},
                }
                deal = SimpleNamespace(
                    agreement_bytes=base64.b64encode(canonical_json(agreement)).decode(),
                    agreement=agreement, negotiation_id=NEGOTIATION,
                    settlement_data=h.data.to_wire(), settlement_ref=h.data.transaction_id,
                    escrow_uid=None, settlement_selection=None, settlement_plan=None,
                    seller_url="http://test",
                )
                identity = ResolvedBuyerIdentity(
                    profile_id="fixture", principal=BUYER.identity, signer=BUYER, source="recovery",
                )
                original = LifecycleClient.__init__

                def peer_transport(self, *args, **kwargs):
                    kwargs["transport"] = h.transport
                    return original(self, *args, **kwargs)

                with patch.object(end_cli, "load_deal_context", return_value=deal), \
                     patch.object(end_cli, "open_run_log", return_value=SimpleNamespace(event=lambda *a, **k: None)), \
                     patch.object(end_cli, "make_deal_publisher_trust_resolver", return_value=lambda: TrustedIdentitySet(identities=(SELLER.identity,))), \
                     patch.object(end_cli.common, "resolve_recovery_buyer_identity", return_value=identity), \
                     patch.object(end_cli, "resolve_buyer_settlement_policy", return_value=resolve_buyer_settlement_policy(document)), \
                     patch.object(arkhai_payments, "load_user_config", return_value=document), \
                     patch.object(vm_buyer_lifecycle, "evidence_store", return_value=store), \
                     patch.object(settlement_stages, "evidence_store", return_value=store), \
                     patch.object(LifecycleClient, "__init__", peer_transport):
                    invoked = CliRunner().invoke(buyer_app, ["end", "--from", "fixture", "--wait-timeout", "1"])
                    assert invoked.exit_code == 0, (invoked.output, invoked.exception)
                    assert json.loads(invoked.output)["capacity_released"] is True
                    with patch.object(end_cli, "resolve_buyer_settlement_policy", side_effect=ValueError("financial configuration removed")):
                        removed = CliRunner().invoke(buyer_app, ["end", "--from", "fixture"])
                        assert removed.exit_code == 0, (removed.output, removed.exception)
                changed = sign_lease_end(event.model_copy(update={"reason": "changed"}), SITE)
                try:
                    await send(changed.model_dump(mode="json"))
                except StorefrontClientError as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError("same event with changed signed payload accepted")
                print("signed push and duplicate: one report; forged proof and mutated event rejected")
                print("authenticated typed pull: earlier source retained once; first push bytes/headers preserved")
                print("buyer half and market end: canonical commit, signed surrender/retry and exact site proof kept")
                print("once-only has no stop; earlier seller end suppresses a payer case; capacity return alone marks released")
        finally:
            await h.coordinator.stop()
            await h.lifecycle.close()
            await h.buyer.close()
            await h.seller.close()
            await h.administrator.close()
            container.resolved_service_peer_trust = None


if __name__ == "__main__":
    asyncio.run(main())
