"""The lifecycle client signs and judges freshness by the process time source."""

import asyncio
import json
from collections.abc import Iterator

import httpx
import injected_time
import pytest
from injected_time import InjectedTime
from market_deal_lifecycle_client import LifecycleClient
from market_deal_lifecycle_client.client import LifecycleClientError
from market_identity import (
    Ed25519Signer, ResponseEnvelope, TrustedIdentitySet, canonical_body_hash, canonical_json,
    sign_response,
)

#: An instant the wall clock has left behind by far more than the signing skew,
#: so a read of the wall clock anywhere on the path fails the response's skew.
INSTANT = 1_794_822_300

# Public deterministic development seeds; never use on a public network.
_BUYER, _SELLER = Ed25519Signer(bytes([1]) * 32), Ed25519Signer(bytes([2]) * 32)


@pytest.fixture(autouse=True)
def source() -> Iterator[InjectedTime]:
    before = injected_time.installed()
    held = InjectedTime(start=INSTANT)
    injected_time.install(held)
    yield held
    injected_time.install(before)


def _respond_at(timestamp: int, seen: list[httpx.Request]):
    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        end = {"ended_at": INSTANT, "actor": _BUYER.identity.model_dump(mode="json"),
               "cause": "buyer_surrender", "source": "end_delivery"}
        payload = {"negotiation_id": "deal", "operation_key": body["operation_key"],
                   "receipt_at": INSTANT, "selected_end": end,
                   "delivery": {"recorded_end": end, "progress": "end_recorded"},
                   "signed_delivery_end_claim": None}
        signed = sign_response(signer=_SELLER, envelope=ResponseEnvelope(
            role="seller", principal=_SELLER.identity, method="POST", operation="lifecycle_peer",
            resource="deal", request_id=request.headers["X-Market-Request-ID"],
            timestamp=timestamp, status=200, body_hash=canonical_body_hash(payload)))
        return httpx.Response(200, content=canonical_json(payload), headers={
            "X-Market-Signature-Version": signed.protocol,
            "X-Market-Identity-Scheme": signed.principal.scheme.value,
            "X-Market-Identity-Identifier": signed.principal.identifier,
            "X-Market-Role": signed.role, "X-Market-Request-ID": signed.request_id,
            "X-Market-Timestamp": str(signed.timestamp), "X-Market-Signature": signed.proof.value,
        })
    return respond


async def _end(respond) -> None:
    async with LifecycleClient(
        "http://storefront.example", _BUYER, TrustedIdentitySet(identities=(_SELLER.identity,)),
        transport=httpx.MockTransport(respond),
    ) as client:
        await client.end_delivery("deal", operation_key="end")


def test_a_signed_request_carries_the_source_s_instant_and_its_answer_verifies() -> None:
    seen: list[httpx.Request] = []

    asyncio.run(_end(_respond_at(INSTANT, seen)))

    (request,) = seen
    assert request.headers["X-Market-Timestamp"] == str(INSTANT)


def test_an_answer_past_the_skew_from_the_source_is_refused(source: InjectedTime) -> None:
    source.set(INSTANT + 301)

    with pytest.raises(LifecycleClientError, match="timestamp_skew"):
        asyncio.run(_end(_respond_at(INSTANT, [])))
