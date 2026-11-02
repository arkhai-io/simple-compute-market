"""Run the signed lifecycle client against a local, in-process storefront seam."""

import asyncio
import json
import time

import httpx
from market_deal_lifecycle_client import LifecycleClient, LifecycleClientError
from market_deal_lifecycle_contracts.models import CommitMessage, HintMessage
from market_identity import (
    EMPTY_BODY, Ed25519Signer, RequestEnvelope, ResponseEnvelope, TrustedIdentitySet,
    canonical_body_hash, canonical_json, sign_response,
)


async def main():
    # Public deterministic development seeds; never use them on a public network.
    buyer = Ed25519Signer(bytes([1]) * 32)
    seller = Ed25519Signer(bytes([2]) * 32)
    trust = TrustedIdentitySet(identities=(seller.identity,))
    captures = []
    mode = "valid"
    calls = []

    def respond(request):
        calls.append(request)
        operation = "lifecycle_buyer_read" if request.method == "GET" else "lifecycle_peer"
        payload = {"outcome": {"status": "accepted"}}
        if request.method == "GET":
            payload = {"negotiation_id": "example", "commitment_ref": "example-commitment",
                       "authority": {"outcome": {"status": "rejected", "reason": "no adapter"}},
                       "delivery": {"progress": "active"}}
        body = json.loads(request.content) if request.content else None
        envelope = RequestEnvelope(
            role="buyer", principal=buyer.identity, method=request.method, operation=operation,
            resource="example", request_id=request.headers["X-Market-Request-ID"],
            timestamp=int(request.headers["X-Market-Timestamp"]), body_hash=canonical_body_hash(body) if body is not None else canonical_body_hash(EMPTY_BODY),
        )
        signed = sign_response(signer=seller, envelope=ResponseEnvelope(
            role="seller", principal=seller.identity, method=envelope.method, operation=operation,
            resource="example", request_id=envelope.request_id, timestamp=int(time.time()),
            status=200, body_hash=canonical_body_hash(payload),
        ))
        headers = {
            "X-Market-Signature-Version": signed.protocol,
            "X-Market-Identity-Scheme": signed.principal.scheme.value,
            "X-Market-Identity-Identifier": signed.principal.identifier,
            "X-Market-Role": signed.role, "X-Market-Request-ID": signed.request_id,
            "X-Market-Timestamp": str(signed.timestamp), "X-Market-Signature": signed.proof.value,
        }
        if mode == "tampered":
            payload = {"outcome": {"status": "rejected", "reason": "tampered"}}
        if mode == "unsigned":
            headers = {}
        return httpx.Response(200, content=canonical_json(payload), headers=headers)

    async with LifecycleClient("http://storefront.example", buyer, trust,
                               transport=httpx.MockTransport(respond), capture=captures.append) as client:
        message = CommitMessage(negotiation_id="example", operation_key="commit-example", commitment_ref="example-commitment")
        assert (await client.commit(message, request_id="commit-request")).outcome.status == "accepted"
        assert json.loads(calls[-1].content) == message.model_dump(mode="json")
        assert (await client.hint(HintMessage(negotiation_id="example", operation_key="hint-example"))).outcome.status == "accepted"
        assert (await client.read("example")).delivery.progress == "active"
        assert len(captures) == 6
        for mode in ("tampered", "unsigned"):
            try:
                await client.commit(message)
            except LifecycleClientError:
                pass
            else:
                raise AssertionError("unverified response was accepted")
        assert len(captures) == 6
        try:
            await client.commit(message.model_copy(update={"commitment_ref": "different"}), request_id="commit-request")
        except ValueError:
            pass
        else:
            raise AssertionError("changed retry reached transport")
        assert len(calls) == 5
    print("commit, hint and delivery read verified; tampering, unsigned answers and changed retries refused; exact envelopes captured")


asyncio.run(main())
