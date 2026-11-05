"""The signed lifecycle client retains exact receipts without denying an earlier end."""

import asyncio
import json
import runpy
import time
from pathlib import Path

import httpx
from market_deal_lifecycle_client import LifecycleClient
from market_identity import Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, canonical_json, sign_response


def test_signed_commit_hint_read_and_capture_first_use():
    runpy.run_path(str(Path(__file__).parents[1] / "examples" / "first_use.py"))


def test_retry_can_withdraw_concurrence_for_a_newly_selected_earlier_end():
    async def drive():
        # Public deterministic development seeds; never use on a public network.
        buyer, seller = Ed25519Signer(bytes([1]) * 32), Ed25519Signer(bytes([2]) * 32)
        earlier = False
        def respond(request):
            body = json.loads(request.content)
            end = {"ended_at": 99 if earlier else 100,
                   "actor": seller.identity.model_dump(mode="json") if earlier else buyer.identity.model_dump(mode="json"),
                   "cause": "operator_end" if earlier else "buyer_surrender", "source": "end_delivery"}
            payload = {"negotiation_id": "deal", "operation_key": body["operation_key"], "receipt_at": 100,
                       "selected_end": end, "delivery": {"recorded_end": end, "progress": "end_recorded"},
                       "signed_delivery_end_claim": None if earlier else {"claim": "payer"}}
            signed = sign_response(signer=seller, envelope=ResponseEnvelope(
                role="seller", principal=seller.identity, method="POST", operation="lifecycle_peer",
                resource="deal", request_id=request.headers["X-Market-Request-ID"], timestamp=int(time.time()),
                status=200, body_hash=canonical_body_hash(payload)))
            return httpx.Response(200, content=canonical_json(payload), headers={
                "X-Market-Signature-Version": signed.protocol,
                "X-Market-Identity-Scheme": signed.principal.scheme.value,
                "X-Market-Identity-Identifier": signed.principal.identifier,
                "X-Market-Role": signed.role, "X-Market-Request-ID": signed.request_id,
                "X-Market-Timestamp": str(signed.timestamp), "X-Market-Signature": signed.proof.value,
            })
        async with LifecycleClient("http://storefront.example", buyer,
            TrustedIdentitySet(identities=(seller.identity,)), transport=httpx.MockTransport(respond)) as client:
            first = await client.end_delivery("deal", operation_key="end")
            assert first.signed_delivery_end_claim is not None
            earlier = True
            revised = await client.end_delivery("deal", operation_key="end")
            assert revised.receipt_at == first.receipt_at
            assert revised.selected_end.ended_at < first.selected_end.ended_at
            assert revised.signed_delivery_end_claim is None
    asyncio.run(drive())
