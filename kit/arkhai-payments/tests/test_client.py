"""Client response handling against a mocked HTTP boundary."""

from __future__ import annotations

import json
import ssl

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

from payment_terms import BUYER, OTHER, PAYEE, SERVICE, agreement, config, option

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


def test_a_ca_bundle_is_loaded_when_the_client_is_built(tmp_path):
    with pytest.raises(FileNotFoundError):
        PaymentsClient("https://payments.invalid", api_key="k", ca_bundle=str(tmp_path / "none.pem"))
    malformed = tmp_path / "malformed.pem"
    malformed.write_text("-----BEGIN CERTIFICATE-----\nnot a certificate\n", "utf-8")
    with pytest.raises(ssl.SSLError):
        PaymentsClient("https://payments.invalid", api_key="k", ca_bundle=str(malformed))


@pytest.mark.parametrize("bundle", ["", " "], ids=["empty", "blank"])
def test_an_empty_ca_bundle_is_refused_rather_than_read_as_the_default_store(bundle):
    with pytest.raises(ValueError, match="ca_bundle must name a file"):
        PaymentsClient("https://payments.invalid", api_key="k", ca_bundle=bundle)


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
    assert (
        client.ensure_agreement_attached(
            data.transaction_id,
            terms,
            PaymentsOptionParams.model_validate(option().settlement_params),
        )
        is None
    )
    assert seen == []
    client.ensure_agreement_attached(
        data.transaction_id,
        terms,
        PaymentsOptionParams.model_validate(option(deposit=True).settlement_params),
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


# A public test-only key value that authenticates to nothing; never use it on a
# public network.
_TEST_API_KEY = "balance-test-key"


def _bearer_client(handler, *, api_key=_TEST_API_KEY):
    return PaymentsClient(
        "https://127.0.0.1:9", api_key=api_key, transport=httpx.MockTransport(handler)
    )


def test_balance_read_sends_the_bearer_key_to_the_account_path_and_parses_the_body():
    seen = {}
    body = {
        "available": {"USD/2": "9750"},
        "held": [
            {
                "address": f"hold:{TXID}:0:1800604800",
                "transaction": TXID,
                "part": 0,
                "from": BUYER,
                "to": PAYEE,
                "asset": "USD/2",
                "balance": "10000",
                "fee": {"bps": 250},
                "releaseAt": "2027-01-22T08:00:00Z",
            }
        ],
    }

    def handler(request):
        seen["method"], seen["path"] = request.method, request.url.path
        seen["authorization"] = request.headers.get("Authorization")
        return httpx.Response(200, json=body)

    balance = _bearer_client(handler).get_balance(PAYEE)
    assert seen == {
        "method": "GET",
        "path": f"/balances/{PAYEE}",
        "authorization": f"Bearer {_TEST_API_KEY}",
    }
    assert balance.available["USD/2"].root == "9750"
    assert balance.held[0].root.address == f"hold:{TXID}:0:1800604800"


def test_balance_read_of_another_account_raises_the_service_refusal():
    client = _bearer_client(
        lambda request: httpx.Response(403, json={"error": "caller_not_authorized"})
    )
    with pytest.raises(PaymentsAPIError) as exc:
        client.get_balance(OTHER)
    assert (exc.value.status_code, exc.value.code) == (403, "caller_not_authorized")


def test_balance_body_outside_the_schema_is_a_protocol_error():
    client = _bearer_client(
        lambda request: httpx.Response(200, json={"available": {"USD/2": "1.5"}, "held": []})
    )
    with pytest.raises(PaymentsProtocolError):
        client.get_balance(PAYEE)


def test_balance_read_refuses_an_invalid_account_before_any_request():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"available": {}, "held": []})

    with pytest.raises(ValueError):
        _bearer_client(handler).get_balance("not-an-account")
    assert requests == []


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
            data.transaction_id,
            terms,
            PaymentsOptionParams.model_validate(option(deposit=True).settlement_params),
        )


def test_deposit_accepts_duplicate_matching_attachments_without_posting():
    terms = agreement(deposit=True)
    data, snapshot = _snapshot_json(terms, attachments=[_attachment(terms), _attachment(terms)])
    methods = []

    def handler(request):
        methods.append(request.method)
        return httpx.Response(200, json=snapshot)

    stored = _client(handler).ensure_agreement_attached(
        data.transaction_id,
        terms,
        PaymentsOptionParams.model_validate(option(deposit=True).settlement_params),
    )
    assert stored is not None and methods == ["GET"]
