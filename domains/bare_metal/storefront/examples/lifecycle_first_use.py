"""Drive the mounted bare-metal lifecycle using the existing regression setup.

Run after make reinit, from the storefront directory:
PYTHONPATH=tests uv run --find-links ../../../.dist python examples/lifecycle_first_use.py
The setup is checkout-owned, uses public deterministic fixture identities, and
must never be deployed on a public network.
"""

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from compute_provisioning_contracts.lease_ends import LEASE_ENDED_CALLBACK, LeaseEndedEvent, sign_lease_end
from site_trust import seeded_sites
from storefront_client import StorefrontClient, StorefrontClientError

import httpx
from integration.test_payment_settlement_client import ADMIN, BUYER, SELLER, harness
from market_arkhai_mediation.claims import verify_claim
from market_arkhai_mediation.models import DeliveryEndClaim, SignedDeliveryEndClaim
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import CommitMessage, ListDealsRequest
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from market_identity import Ed25519Signer, TrustedIdentitySet, canonical_json


async def main():
    with TemporaryDirectory(prefix="bare-metal-lifecycle-") as root:
        setup = harness.__wrapped__(Path(root), True)
        state = await anext(setup)
        try:
            transport = httpx.ASGITransport(app=state.app)
            trust = TrustedIdentitySet(identities=(SELLER.identity,))
            async with LifecycleClient("http://test", BUYER, trust, transport=transport) as client:
                state.serve()
                message = CommitMessage(
                    negotiation_id=state.negotiation_id,
                    commitment_ref=state.data.transaction_id, operation_key="first-use-commit",
                )
                if len(sys.argv) > 1:
                    mode = sys.argv[1]
                    if mode not in {"before-dispatch", "create-in-flight"}:
                        raise ValueError("expected before-dispatch or create-in-flight")
                    started, release = asyncio.Event(), asyncio.Event()
                    releases = []
                    if mode == "create-in-flight":
                        state.provisioning.started, state.provisioning.release = started, release
                    else:
                        schedule = state.provisioning.schedule_resource

                        async def paused_schedule(request):
                            started.set()
                            await release.wait()
                            return await schedule(request)

                        async def release_reservation(**request):
                            releases.append(request)
                            return {"capacity_reservation_id": request["capacity_reservation_id"], "site": request["site_id"]}

                        state.provisioning.schedule_resource = paused_schedule
                        state.runtime.capacity_client.release = release_reservation
                    pending = asyncio.create_task(client.commit(message))
                    await asyncio.wait_for(started.wait(), timeout=5)
                    ack = await client.end_delivery(state.negotiation_id, operation_key="racing-end")
                    assert ack.delivery.progress == "end_recorded"
                    assert state.provisioning.terminated == []
                    release.set()
                    result = await asyncio.wait_for(pending, timeout=5)
                    assert result.outcome.status == ("rejected" if mode == "before-dispatch" else "accepted")
                    assert len(state.provisioning.begin_calls) == (0 if releases else 1)
                    assert len(state.provisioning.terminated) == (0 if releases else 1)
                    assert len(releases) == (1 if mode == "before-dispatch" else 0)
                    with transaction(state.runtime.db.db_path) as conn:
                        record = EndSession(conn).read(state.negotiation_id)
                    assert record.committed_at == 1_800_000_000
                    print(mode + ": durable surrender returns without waiting for create; adopted work ends once; no credential disclosure")
                    return
                assert (await client.commit(message)).outcome.status == "accepted"
                assert (await client.commit(message)).outcome.status == "accepted"
                assert len(state.provisioning.begin_calls) == 1
                kept = await state.runtime.lifecycle.evidence.read(state.negotiation_id)
                assert any(item.kind == "verified_market_envelope" for item in kept.items)
                deals = await state.runtime.lifecycle.seller.list(ListDealsRequest())
                assert state.negotiation_id in {deal.negotiation_id for deal in deals.deals}
                ack = await client.end_delivery(state.negotiation_id, operation_key="first-use-end")
                again = await client.end_delivery(state.negotiation_id, operation_key="first-use-end")
                assert ack.receipt_at == again.receipt_at
                assert again.delivery.progress == "tearing_down"
                assert len(state.provisioning.terminated) == 1
                assert ack.signed_delivery_end_claim is not None
                assert verify_claim(
                    SignedDeliveryEndClaim.model_validate(ack.signed_delivery_end_claim),
                    agreement=hashlib.sha256(canonical_json(json.loads(base64.b64decode(state.opened["agreement_bytes"])))).hexdigest(),
                    seller=SELLER.identity,
                    claim=DeliveryEndClaim(kind="delivery_end", ended_at=ack.receipt_at, delivered=True, cause="payer"),
                )
                read = await client.read(state.negotiation_id)
                assert read.delivery.recorded_end.cause == "buyer_surrender"
                # Deterministic public development site identity, never for a
                # public network. Its stored event does not prove access revoked.
                site = Ed25519Signer(bytes.fromhex("44" * 32))
                bindings, site_trust = seeded_sites(state.runtime.db.db_path, {"site-a": site.identity})
                object.__setattr__(state.runtime, "site_bindings", bindings)
                object.__setattr__(state.runtime, "service_peer_trust", site_trust)
                report = sign_lease_end(LeaseEndedEvent(
                    event_id="first-use-site-end", capacity_reservation_id="reservation-pay",
                    site_id="site-a", effective_at=ack.receipt_at, cause="termination",
                    source_state="active", reason="buyer-surrender:" + ack.operation_key,
                    caller=SELLER.identity,
                ), site)
                callback = LEASE_ENDED_CALLBACK["path"].format(capacity_reservation_id="reservation-pay")
                async with StorefrontClient("http://test", signer=site, caller_role="service",
                                            expected_publishers=trust, transport=transport) as sender:
                    for _ in range(2):
                        assert await sender.authenticated_request(
                            "POST", callback, role="service", operation="lease_ended",
                            resource="reservation-pay", body=report.model_dump(mode="json"),
                        ) == {"status": "recorded"}
                before = await client.read(state.negotiation_id)
                assert before.delivery.progress == "tearing_down"
                assert len(before.delivery.site_reports) == 1
                assert json.loads(before.delivery.site_reports[0].body) == report.model_dump(mode="json")

                async def lease(_):
                    return SimpleNamespace(end_reports=[report], status="releasing")

                state.provisioning.get_lease = lease
                await state.runtime.lifecycle.recover_site(state.negotiation_id)
                assert (await client.read(state.negotiation_id)).delivery.site_reports == before.delivery.site_reports
                async with StorefrontClient("http://test", signer=ADMIN, caller_role="service",
                                            expected_publishers=trust, transport=transport) as wrong_site:
                    try:
                        await wrong_site.authenticated_request(
                            "POST", callback, role="service", operation="lease_ended",
                            resource="reservation-pay", body=report.model_dump(mode="json"),
                        )
                    except StorefrontClientError as exc:
                        assert exc.status_code == 403
                    else:
                        raise AssertionError("wrong site was admitted")
                async with StorefrontClient("http://test", signer=site, caller_role="service",
                                            expected_publishers=trust, transport=transport) as sender:
                    await sender.notify_capacity_released("reservation-pay", site_id="site-a")
                after = await client.read(state.negotiation_id)
                assert after.delivery.progress == "released"
                assert after.delivery.site_reports == before.delivery.site_reports
            async with LifecycleClient("http://test", ADMIN, trust, transport=transport) as client:
                try:
                    await client.end_delivery(state.negotiation_id, operation_key="wrong-buyer")
                except LifecycleClientError as exc:
                    assert exc.status_code == 403
                else:
                    raise AssertionError("wrong buyer was admitted")
            print("hosted commit and surrender replay once; wrong buyer/site refuse; exact site report survives push retry/pull; only proven release advances capacity")
        finally:
            await setup.aclose()


if __name__ == "__main__":
    asyncio.run(main())
