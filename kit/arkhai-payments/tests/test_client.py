"""Client response handling against a mocked HTTP boundary."""

from __future__ import annotations

import json

import httpx
import pytest

from market_arkhai_payments import (
    PaymentSettlementData,
    PaymentsOptionParams,
    PaymentsAPIError,
    PaymentsClient,
    PaymentsProtocolError,
    PaymentsTransportError,
)
from market_arkhai_payments.fixtures import build_signed_receipt
from market_arkhai_payments.fixtures.payments_client import FakePaymentsClient

from payment_terms import BUYER, SERVICE, agreement, config, option

TXID = "c" * 64


def _client(handler):
    return PaymentsClient(
        "http://127.0.0.1:9", development_account=BUYER, transport=httpx.MockTransport(handler)
    )


def _snapshot_json(terms, *, attachments=()):
    data = PaymentSettlementData.for_agreement(terms, config())
    fake = FakePaymentsClient()
    fake.serve(build_signed_receipt(signer=SERVICE, mandate=data.mandate))
    for attachment in attachments:
        fake.attachments.append(attachment)
    snapshot = fake.get_transaction(data.transaction_id)
    return data, snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)


def test_service_error_codes_surface_as_api_errors():
    client = _client(lambda request: httpx.Response(404, json={"error": "transaction_not_found"}))
    with pytest.raises(PaymentsAPIError) as exc:
        client.get_transaction(TXID)
    assert exc.value.code == "transaction_not_found"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(302, headers={"location": "https://elsewhere"}),
    ],
)
def test_responses_outside_the_contract_are_protocol_errors(response):
    with pytest.raises(PaymentsProtocolError):
        _client(lambda request: response).get_transaction(TXID)


def test_transport_failures_are_transport_errors():
    def fail(request):
        raise httpx.ConnectError("down", request=request)

    with pytest.raises(PaymentsTransportError):
        _client(fail).get_transaction(TXID)


def test_poll_waits_through_not_found_then_returns_the_snapshot():
    terms = agreement()
    data, snapshot = _snapshot_json(terms)
    responses = iter(
        [httpx.Response(404, json={"error": "transaction_not_found"}), httpx.Response(200, json=snapshot)]
    )
    result = _client(lambda request: next(responses)).poll(
        data.transaction_id, timeout=5, interval=0.001
    )
    assert result.snapshot.transaction.root == data.transaction_id


def test_deposit_posts_only_when_advertised_and_absent():
    terms = agreement(deposit=True)
    data, snapshot = _snapshot_json(terms)
    seen = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=snapshot)
        return httpx.Response(200, json=json.loads(request.content) | _stored(terms))

    client = _client(handler)
    assert client.ensure_agreement_attached(
        data.transaction_id, terms, PaymentsOptionParams.model_validate(option().params)
    ) is None
    assert seen == []
    client.ensure_agreement_attached(
        data.transaction_id, terms, PaymentsOptionParams.model_validate(option(deposit=True).params)
    )
    assert seen[-1] == ("POST", f"/transactions/{data.transaction_id}/attachments")


def test_reverse_uses_a_stable_idempotency_key():
    seen = {}

    def handler(request):
        seen["key"] = request.headers.get("Idempotency-Key")
        return httpx.Response(
            200,
            json={
                "account": BUYER,
                "requestId": f"reverse-{TXID}",
                "event": {"kind": "reverse"},
                "receivedAt": 1,
            },
        )

    _client(handler).reverse(TXID)
    assert seen["key"] == f"reverse-{TXID}"


def _stored(terms):
    from market_arkhai_payments.canonical import jcs_bytes
    import hashlib

    canonical = jcs_bytes(terms)
    return {
        "sha256": hashlib.sha256(canonical).hexdigest(),
        "name": "deal.json",
        "mediaType": "application/json",
        "size": len(canonical),
        "uploader": BUYER,
    }


def _attachment(content):
    return {"kind": "deal", "content": content, **_stored(content)}


@pytest.mark.parametrize("order", ["foreign_first", "foreign_last"])
def test_deposit_refuses_an_attachment_for_another_deal_in_any_position(order):
    terms = agreement(deposit=True)
    foreign, mine = _attachment({"other": "deal"}), _attachment(terms)
    attachments = [foreign, mine] if order == "foreign_first" else [mine, foreign]
    data, snapshot = _snapshot_json(terms, attachments=attachments)
    client = _client(lambda request: httpx.Response(200, json=snapshot))
    with pytest.raises(PaymentsProtocolError):
        client.ensure_agreement_attached(
            data.transaction_id, terms, PaymentsOptionParams.model_validate(option(deposit=True).params)
        )


def test_deposit_accepts_duplicate_matching_attachments_without_posting():
    terms = agreement(deposit=True)
    data, snapshot = _snapshot_json(terms, attachments=[_attachment(terms), _attachment(terms)])
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json=snapshot)

    stored = _client(handler).ensure_agreement_attached(
        data.transaction_id, terms, PaymentsOptionParams.model_validate(option(deposit=True).params)
    )
    assert stored is not None and methods == ["GET"]
