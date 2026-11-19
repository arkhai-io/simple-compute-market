"""The signed lifecycle client retains exact receipts without denying an earlier end."""

import asyncio
import json
import runpy
import time
from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, call

import httpx
from market_deal_lifecycle_client import LifecycleClient, SellerLifecycleClient, SyncSellerLifecycleClient
from market_deal_lifecycle_contracts.models import ENDING_TEXT, ListDealsRequest
from market_deal_lifecycle_contracts.routes import lifecycle_route
from market_identity import Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, canonical_json, sign_response

# A storefront's decoded answer to the seller list: one deal still ending.
ENDING_PAGE = {"deals": [{
    "negotiation_id": "deal", "commitment_ref": "tx", "domain": "vms", "mechanism": "arkhai.payments.v1",
    "entitlements": {"payer": {"notice_seconds": 0}}, "state": "ending",
    "ending": ["payment_running", "case_open"], "deadline": 100, "parts": [],
    "has_open_extension": False, "open_cases": ["case"], "filings": [],
}], "continuation": "deal"}


def test_signed_commit_hint_read_and_capture_first_use():
    runpy.run_path(str(Path(__file__).parents[1] / "examples" / "first_use.py"))


def test_a_listed_ending_deal_yields_its_codes_and_their_text():
    route = lifecycle_route("lifecycle_list")
    request = ListDealsRequest(limit=10, continuation="after")
    expected = call(route["method"], route["path"], role="admin", operation="lifecycle_list",
                    resource="?continuation=after&limit=10", params={"continuation": "after", "limit": "10"})
    sync = MagicMock(authenticated_request=MagicMock(return_value=ENDING_PAGE))
    asynchronous = MagicMock(authenticated_request=AsyncMock(return_value=ENDING_PAGE))
    pages = [SyncSellerLifecycleClient(sync).list(request),
             asyncio.run(SellerLifecycleClient(asynchronous).list(request))]
    assert sync.authenticated_request.call_args_list == [expected]
    assert asynchronous.authenticated_request.call_args_list == [expected]
    for page in pages:
        [deal] = page.deals
        assert page.continuation == "deal" and deal.ending == ["payment_running", "case_open"]
        assert [text for _, text in deal.ending_reasons] == [ENDING_TEXT["payment_running"], ENDING_TEXT["case_open"]]


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
