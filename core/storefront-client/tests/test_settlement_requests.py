"""Settlement request contracts: agreement settlement, EVM settlement, and seller refund."""

import asyncio
import json

import httpx
import pytest
from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

from storefront_client.auth import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from storefront_client.client import StorefrontClient, SyncStorefrontClient

_BUYER = Ed25519Signer(bytes(range(32)))
_SELLER = Ed25519Signer(bytes(range(1, 33)))


class _Responder:
    """Answers every request with one body, signed by the seller for that request."""

    def __init__(self, operation: str, resource: str, body: dict) -> None:
        self.operation = operation
        self.resource = resource
        self.body = body
        self.requests: list[httpx.Request] = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        signed = sign_response(
            signer=_SELLER,
            envelope=ResponseEnvelope(
                role="seller",
                principal=_SELLER.identity,
                method=request.method,
                operation=self.operation,
                resource=self.resource,
                request_id=request.headers[REQUEST_ID_HEADER],
                timestamp=int(request.headers[TIMESTAMP_HEADER]),
                status=200,
                body_hash=canonical_body_hash(self.body),
            ),
        )
        headers = {
            SIGNATURE_VERSION_HEADER: signed.protocol,
            IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
            IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
            ROLE_HEADER: signed.role,
            REQUEST_ID_HEADER: signed.request_id,
            TIMESTAMP_HEADER: str(signed.timestamp),
            SIGNATURE_HEADER: signed.proof.value,
        }
        return httpx.Response(200, json=self.body, headers=headers, request=request)


class _Async(httpx.AsyncBaseTransport):
    def __init__(self, responder: _Responder) -> None:
        self.responder = responder

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return self.responder.respond(request)


class _Sync(httpx.BaseTransport):
    def __init__(self, responder: _Responder) -> None:
        self.responder = responder

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.responder.respond(request)


def _publishers():
    return TrustedIdentitySet(identities=(_SELLER.identity,))


def _both(signer, role, responder, call):
    """Run one call through the async and the sync client; return both results."""

    async def run_async():
        async with StorefrontClient(
            "http://test",
            signer=signer,
            caller_role=role,
            expected_publishers=_publishers(),
            transport=_Async(responder),
        ) as client:
            return await call(client)

    first = asyncio.run(run_async())
    with SyncStorefrontClient(
        "http://test",
        signer=signer,
        caller_role=role,
        expected_publishers=_publishers(),
        transport=_Sync(responder),
    ) as client:
        second = call(client)
    return first, second


def test_settle_agreement_sends_only_the_negotiation_and_buyer():
    responder = _Responder(
        "settle_escrow",
        "neg-1",
        {
            "negotiation_id": "neg-1",
            "escrow_uid": "neg-1",
            "settlement_ref": "f" * 64,
            "status": "pending",
            "retryable": True,
            "buyer_principal": _BUYER.identity.model_dump(mode="json"),
            "seller_principal": _SELLER.identity.model_dump(mode="json"),
        },
    )

    async def call_async(client):
        return await client.settle_agreement("neg-1")

    results = []
    for result in _both(
        _BUYER,
        "buyer",
        responder,
        lambda client: call_async(client) if isinstance(client, StorefrontClient)
        else client.settle_agreement("neg-1"),
    ):
        results.append(result)

    for request in responder.requests:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/settle/neg-1"
        assert request.headers[ROLE_HEADER] == "buyer"
        assert json.loads(request.content) == {
            "negotiation_id": "neg-1",
            "buyer_principal": _BUYER.identity.model_dump(mode="json"),
        }
    for result in results:
        assert result.pending and result.retryable
        assert result.settlement_ref == "f" * 64


def test_settle_evm_keeps_its_evm_inputs():
    responder = _Responder("settle_escrow", "0xabc", {"status": "provisioning", "escrow_uid": "0xabc"})

    async def call_async(client):
        return await client.settle_evm("0xabc", negotiation_id="neg-1", buyer_evm_address="0x1")

    _both(
        _BUYER,
        "buyer",
        responder,
        lambda client: call_async(client) if isinstance(client, StorefrontClient)
        else client.settle_evm("0xabc", negotiation_id="neg-1", buyer_evm_address="0x1"),
    )
    for request in responder.requests:
        body = json.loads(request.content)
        assert request.url.path == "/api/v1/settle/0xabc"
        assert body["buyer_evm_address"] == "0x1"
        assert body["negotiation_id"] == "neg-1"


def test_refund_settlement_is_a_seller_request_with_no_body():
    responder = _Responder(
        "refund_settlement",
        "neg-1",
        {"negotiation_id": "neg-1", "settlement_ref": "f" * 64, "status": "refunded"},
    )

    async def call_async(client):
        return await client.refund_settlement("neg-1")

    results = _both(
        _SELLER,
        "seller",
        responder,
        lambda client: call_async(client) if isinstance(client, StorefrontClient)
        else client.refund_settlement("neg-1"),
    )
    for request in responder.requests:
        assert request.method == "POST"
        assert request.url.path == "/api/v1/settlements/neg-1/refund"
        assert request.headers[ROLE_HEADER] == "seller"
        assert request.content in (b"", b"{}")
    assert [result.status for result in results] == ["refunded", "refunded"]


def test_a_buyer_client_cannot_refund():
    responder = _Responder("refund_settlement", "neg-1", {})
    with SyncStorefrontClient(
        "http://test",
        signer=_BUYER,
        caller_role="buyer",
        expected_publishers=_publishers(),
        transport=_Sync(responder),
    ) as client:
        with pytest.raises(ValueError, match="caller_role"):
            client.refund_settlement("neg-1")
    assert responder.requests == []


def _complete_settle_body() -> dict:
    return {
        "negotiation_id": "neg-1",
        "escrow_uid": "neg-1",
        "settlement_ref": "f" * 64,
        "status": "pending",
        "retryable": True,
        "buyer_principal": _BUYER.identity.model_dump(mode="json"),
        "seller_principal": _SELLER.identity.model_dump(mode="json"),
    }


@pytest.mark.parametrize("drift", ["missing", "renamed"])
def test_a_drifted_agreement_settle_response_is_a_client_error(drift):
    from storefront_client import StorefrontClientError

    body = _complete_settle_body()
    value = body.pop("settlement_ref")
    if drift == "renamed":
        body["settlementRef"] = value
    responder = _Responder("settle_escrow", "neg-1", body)
    with SyncStorefrontClient(
        "http://test",
        signer=_BUYER,
        caller_role="buyer",
        expected_publishers=_publishers(),
        transport=_Sync(responder),
    ) as client:
        with pytest.raises(StorefrontClientError, match="settlement_ref"):
            client.settle_agreement("neg-1")


def test_a_drifted_refund_response_is_a_client_error():
    from storefront_client import StorefrontClientError

    responder = _Responder("refund_settlement", "neg-1", {"negotiation_id": "neg-1", "status": "refunded"})
    with SyncStorefrontClient(
        "http://test",
        signer=_SELLER,
        caller_role="seller",
        expected_publishers=_publishers(),
        transport=_Sync(responder),
    ) as client:
        with pytest.raises(StorefrontClientError, match="settlement_ref"):
            client.refund_settlement("neg-1")
