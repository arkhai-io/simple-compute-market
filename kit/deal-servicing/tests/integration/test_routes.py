import asyncio
import time
import uuid

import httpx
import pytest
from fastapi import FastAPI
from market_deal_lifecycle.acknowledgements import verify_end_acknowledgement
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, HintMessage, SubmitResponse
from market_identity import (
    RequestEnvelope, TrustedIdentitySet,
    canonical_body_hash, canonical_json, sign_request,
)
from market_deal_servicing import (
    Classification, DeliveryIngress, EndService, EndSession, LifecycleRouteBinding,
    LifecycleRouteServices, PhysicalResult, VerifiedSiteEnd, create_lifecycle_router,
)
from market_deal_servicing.evidence import transaction


@pytest.fixture
def routes(rig):
    now = int(time.time())
    rig["clock"][0] = now
    with transaction(rig["path"]) as conn:
        conn.execute("UPDATE servicing_seller_deals SET deal=? WHERE negotiation_id='deal'",
                     (rig["deal"].model_copy(update={"dispute": None}).model_dump_json(),))
    api = rig["service"]()
    peers = []

    async def peer(message):
        peers.append(message.kind)
        return SubmitResponse(outcome=Accepted())

    physical = rig["physical"]
    physical.apply_end.return_value = PhysicalResult(done=True, progress="tearing_down")
    ingress = DeliveryIngress(
        rig["path"], clock=lambda: rig["clock"][0],
        verify_site=lambda nid, body, headers: VerifiedSiteEnd(
            event_id="report", capacity_reservation_id="reservation", ended_at=now,
            actor=rig["authority_signer"].identity, cause="site_failure",
        ),
        classify_site=lambda event, _: Classification(
            kind="provisioning_failure", evidence_refs=["site-event:" + event.event_id],
        ),
    )

    def binding(nid):
        if nid not in {"deal", "introduction"}:
            raise KeyError(nid)
        return LifecycleRouteBinding(buyer=rig["buyer"].identity, seller=rig["seller"].identity,
                                     settlement=nid != "introduction")

    services = LifecycleRouteServices(
        seller=api, binding=binding, signer=rig["seller"],
        administrators=TrustedIdentitySet(identities=(rig["authority_signer"].identity,)),
        peer=peer, ingress=ingress, end=rig["end"],
    )
    app = FastAPI()
    app.include_router(create_lifecycle_router(lambda _: services))
    transport = httpx.ASGITransport(app=app)
    trust = TrustedIdentitySet(identities=(rig["seller"].identity,))

    async def raw(body, *, nid="deal", signer=rig["buyer"], role="buyer", operation="lifecycle_peer"):
        # Raw requests only exercise inputs the typed client deliberately cannot encode.
        request = sign_request(signer=signer, envelope=RequestEnvelope(
            role=role, principal=signer.identity, method="POST", operation=operation, resource=nid,
            request_id=uuid.uuid4().hex, timestamp=now, body_hash=canonical_body_hash(body),
        ))
        headers = {
            "X-Market-Signature-Version": request.protocol,
            "X-Market-Identity-Scheme": request.principal.scheme.value,
            "X-Market-Identity-Identifier": request.principal.identifier,
            "X-Market-Role": role, "X-Market-Request-ID": request.request_id,
            "X-Market-Timestamp": str(now), "X-Market-Signature": request.proof.value,
        }
        url = f"/api/v1/negotiations/{nid}/lifecycle" if role == "buyer" else f"/api/v1/admin/lifecycle/{nid}"
        async with httpx.AsyncClient(transport=transport, base_url="http://fixture") as http:
            return await http.post(url, content=canonical_json(body), headers=headers)

    return locals()


async def test_typed_peer_read_authentication_and_signature_binding(routes, rig):
    env = routes
    async with LifecycleClient("http://fixture", rig["buyer"], env["trust"], transport=env["transport"]) as client:
        assert (await client.commit(CommitMessage(
            negotiation_id="deal", operation_key="commit", commitment_ref="commitment",
        ))).outcome.status == "accepted"
        assert (await client.hint(HintMessage(negotiation_id="deal", operation_key="hint"))).outcome.status == "accepted"
        assert (await client.read("deal")).commitment_ref == "commitment"
        receipt = await client.end_delivery("deal", operation_key="end")
        verified = verify_end_acknowledgement(
            client.end_receipt("deal", "end"), negotiation_id="deal",
            buyer=rig["buyer"].identity, seller=rig["seller"].identity,
        )
        assert verified.receipt_at == receipt.receipt_at
    assert env["peers"] == ["commit", "hint"]
    async with LifecycleClient("http://fixture", rig["authority_signer"], env["trust"], transport=env["transport"]) as wrong:
        with pytest.raises(LifecycleClientError, match="403"):
            await wrong.read("deal")
        with pytest.raises(LifecycleClientError, match="403"):
            await wrong.hint(HintMessage(negotiation_id="deal", operation_key="forged-hint"))
    async with LifecycleClient(
        "http://fixture", rig["buyer"], TrustedIdentitySet(identities=(rig["buyer"].identity,)),
        transport=env["transport"],
    ) as distrust:
        with pytest.raises(LifecycleClientError, match="authentication"):
            await distrust.read("deal")


async def test_refuses_relay_backdating_future_and_introduction_before_any_effect(routes, rig):
    raw, now = routes["raw"], routes["now"]
    request = {"kind": "end_delivery", "negotiation_id": "deal", "operation_key": "end"}
    for at in (now - 3600, now + 3600):
        assert (await raw({**request, "at": at})).status_code == 422
    assert (await raw({"kind": "stop", "negotiation_id": "deal", "operation_key": "relay"})).status_code == 422
    assert (await raw({**request, "negotiation_id": "introduction"}, nid="introduction")).status_code == 409
    assert (await raw({
        "kind": "delivery_end", "negotiation_id": "deal", "operation_key": "admin",
    }, role="admin", operation="lifecycle_submit")).status_code == 403
    rig["physical"].apply_end.assert_not_called()
    rig["payment"].submit.assert_not_called()
    rig["payment"].read.assert_not_called()


async def test_outage_receipt_before_fulfillment_retry_and_owner_only_exact_reports(routes, rig):
    env = routes
    rig["payment"].read.side_effect = AssertionError("surrender must not read payments")
    async with LifecycleClient("http://fixture", rig["buyer"], env["trust"], transport=env["transport"]) as client:
        first = await client.end_delivery("deal", operation_key="end")
        rig["clock"][0] += 1
        second = await client.end_delivery("deal", operation_key="end")
        assert first.receipt_at == second.receipt_at == env["now"]
        assert second.delivery.progress == "tearing_down"
        assert rig["physical"].apply_end.await_count == 1
        report = b'{"site": "exact opaque bytes", "proof": "fixture proof"}'
        await asyncio.to_thread(env["ingress"].site_report, "deal", body=report, headers={"proof": "exact"})
        read = await client.read("deal")
        assert read.delivery.site_reports[0].body == report
        assert read.delivery.site_reports[0].headers == {"proof": "exact"}
    async with LifecycleClient("http://fixture", rig["authority_signer"], env["trust"], transport=env["transport"]) as wrong:
        with pytest.raises(LifecycleClientError, match="403"):
            await wrong.read("deal")
