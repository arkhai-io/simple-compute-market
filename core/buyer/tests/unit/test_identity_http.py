from __future__ import annotations

import json
from collections.abc import Callable
from io import BytesIO
from urllib.error import HTTPError

import pytest

from core_buyer.negotiation_client import _authenticated_json
from core_buyer.orchestration import submit_settlement_request
from market_identity import (
    Ed25519Signer,
    ResponseEnvelope,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
)

_NOW = 2_000_000_000


def _trust(*signers: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=tuple(signer.identity for signer in signers))


class _Response:
    def __init__(self, payload: dict, headers: dict[str, str]) -> None:
        self._payload = payload
        self.headers = headers
        self.status = 200

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _response_headers(
    *,
    signer: Ed25519Signer,
    payload: dict,
    request_id: str,
    operation: str,
    resource: str,
    status: int = 200,
) -> dict[str, str]:
    authenticated = sign_response(
        signer=signer,
        envelope=ResponseEnvelope(
            role="seller",
            principal=signer.identity,
            method="POST",
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=_NOW,
            status=status,
            body_hash=canonical_body_hash(payload),
        ),
    )
    return {
        "X-Market-Signature-Version": authenticated.protocol,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }


def _opener(
    *,
    seller: Ed25519Signer,
    signed_payload: dict,
    served_payload: dict | None = None,
    response_request_id: str = "request.1",
) -> Callable:
    def open_request(request, **_kwargs):
        return _Response(
            served_payload if served_payload is not None else signed_payload,
            _response_headers(
                signer=seller,
                payload=signed_payload,
                request_id=response_request_id,
                operation="negotiate_new",
                resource="listing-1",
            ),
        )

    return open_request


def test_ed25519_request_and_signed_response_need_no_wallet(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x01" * 32)
    seller = Ed25519Signer(b"\x02" * 32)
    response = {"action": "accept", "negotiation_id": "neg-1"}
    captured = {}

    def open_request(request, **kwargs):
        captured["request"] = request
        return _opener(seller=seller, signed_payload=response)(request, **kwargs)

    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        open_request,
    )

    body = {
        "listing_id": "listing-1",
        "buyer_principal": buyer.identity.model_dump(mode="json"),
    }
    result = _authenticated_json(
        "http://seller/api/v1/negotiate/new",
        body,
        signer=buyer,
        principal=buyer.identity,
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        request_id="request.1",
        timestamp=_NOW,
        expected_response_principals=_trust(seller),
    )

    request = captured["request"]
    headers = {key.lower(): value for key, value in request.header_items()}
    assert result == response
    assert headers["x-market-signature-version"] == "arkhai.market-request-signature.v2"
    assert headers["x-market-identity-scheme"] == "ed25519"
    assert headers["x-market-identity-identifier"] == buyer.identity.identifier
    assert headers["x-market-role"] == "buyer"
    assert json.loads(request.data)["buyer_principal"] == body["buyer_principal"]
    assert "buyer_address" not in json.loads(request.data)


def test_response_trust_accepts_overlap_and_rejects_retired_principal(
    monkeypatch,
) -> None:
    buyer = Ed25519Signer(b"\x16" * 32)
    old = Ed25519Signer(b"\x17" * 32)
    replacement = Ed25519Signer(b"\x18" * 32)
    payload = {"status": "ready"}
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        _opener(seller=old, signed_payload=payload),
    )
    request = dict(
        url="http://seller/api/v1/negotiate/new",
        body={},
        signer=buyer,
        principal=buyer.identity,
        method="POST",
        operation="negotiate_new",
        resource="listing-1",
        request_id="request.1",
        timestamp=_NOW,
    )

    assert (
        _authenticated_json(
            **request,
            expected_response_principals=_trust(replacement, old),
        )
        == payload
    )
    with pytest.raises(RuntimeError, match="wrong_principal"):
        _authenticated_json(
            **request,
            expected_response_principals=_trust(replacement),
        )


def test_signed_response_body_mutation_is_rejected(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x03" * 32)
    seller = Ed25519Signer(b"\x04" * 32)
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        _opener(
            seller=seller,
            signed_payload={"status": "ready"},
            served_payload={"status": "failed"},
        ),
    )

    with pytest.raises(RuntimeError, match="response authentication failed"):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {"buyer_principal": buyer.identity.model_dump(mode="json")},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )


def test_response_replay_under_another_request_id_is_rejected(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x05" * 32)
    seller = Ed25519Signer(b"\x06" * 32)
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        _opener(
            seller=seller,
            signed_payload={"status": "ready"},
            response_request_id="old.request",
        ),
    )

    with pytest.raises(RuntimeError, match="context_mismatch"):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )


def test_legacy_response_authentication_is_rejected(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x07" * 32)
    seller = Ed25519Signer(b"\x08" * 32)
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(
            {"status": "ready"},
            {"X-Signature": "legacy", "X-Timestamp": str(_NOW)},
        ),
    )

    # Version-1 headers are none of the version-2 ones, so from this side the
    # answer simply arrived unauthenticated -- and it says so, with its status.
    with pytest.raises(RuntimeError, match=r"HTTP 200 carried no response authentication"):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )


def test_authenticated_request_requires_a_response_trust_pin(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x0b" * 32)
    contacted = False

    def open_request(*_args, **_kwargs):
        nonlocal contacted
        contacted = True
        raise AssertionError("request must fail before transport")

    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        open_request,
    )

    with pytest.raises(ValueError, match="pinned response principal"):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            expected_response_principals=None,  # type: ignore[arg-type]
        )

    assert contacted is False


def _error_response(
    *,
    payload: dict,
    headers: dict[str, str],
    status: int = 409,
) -> HTTPError:
    return HTTPError(
        "http://seller/api/v1/negotiate/new",
        status,
        "conflict",
        headers,
        BytesIO(json.dumps(payload).encode("utf-8")),
    )


def test_valid_signed_http_error_is_verified_before_status_propagation(
    monkeypatch,
) -> None:
    buyer = Ed25519Signer(b"\x11" * 32)
    seller = Ed25519Signer(b"\x12" * 32)
    payload = {"error": "negotiation conflict"}
    headers = _response_headers(
        signer=seller,
        payload=payload,
        request_id="request.1",
        operation="negotiate_new",
        resource="listing-1",
        status=409,
    )
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            _error_response(payload=payload, headers=headers)
        ),
    )

    with pytest.raises(RuntimeError, match="authenticated HTTP 409"):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )


@pytest.mark.parametrize(
    ("mode", "expected_error"),
    [
        ("unsigned", r"HTTP 409 carried no response authentication"),
        ("forged", "wrong_principal"),
        ("mutated", "invalid_proof"),
    ],
)
def test_untrusted_http_errors_are_rejected(
    monkeypatch,
    mode: str,
    expected_error: str,
) -> None:
    buyer = Ed25519Signer(b"\x13" * 32)
    seller = Ed25519Signer(b"\x14" * 32)
    attacker = Ed25519Signer(b"\x15" * 32)
    signed_payload = {"error": "signed"}
    served_payload = {"error": "mutated"} if mode == "mutated" else signed_payload
    if mode == "unsigned":
        headers = {}
    else:
        headers = _response_headers(
            signer=attacker if mode == "forged" else seller,
            payload=signed_payload,
            request_id="request.1",
            operation="negotiate_new",
            resource="listing-1",
            status=409,
        )
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            _error_response(payload=served_payload, headers=headers)
        ),
    )

    with pytest.raises(RuntimeError, match=expected_error):
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )


def test_settlement_retry_reuses_the_exact_authenticated_request(monkeypatch) -> None:
    buyer = Ed25519Signer(b"\x09" * 32)
    seller = Ed25519Signer(b"\x0a" * 32)
    calls: list[dict] = []

    def signed_json(*args, **kwargs):
        calls.append({**kwargs, "body": args[1]})
        if len(calls) < 3:
            raise RuntimeError("POST -> HTTP 400: Failed to read escrow")
        return {"status": "provisioning"}

    monkeypatch.setattr("core_buyer.orchestration._signed_json", signed_json)
    result = submit_settlement_request(
        seller_url="http://seller",
        escrow_uid="escrow-1",
        payload={"negotiation_id": "neg-1", "mechanism_input": {"value": "opaque"}},
        principal=buyer.identity,
        signer=buyer,
        max_attempts=3,
        retryable=lambda _exc: True,
        sleep=lambda _seconds: None,
        resolve_seller_principals=lambda: _trust(seller),
    )

    assert result == {"status": "provisioning"}
    assert len({call["request_id"] for call in calls}) == 1
    assert len({call["timestamp"] for call in calls}) == 1
    assert all(call["principal"] == buyer.identity for call in calls)
    assert all(call["body"]["mechanism_input"] == {"value": "opaque"} for call in calls)


def test_a_refused_response_names_its_status_without_quoting_it(monkeypatch) -> None:
    """The refusal is the same; what it says about the answer is not."""

    buyer = Ed25519Signer(b"\x1a" * 32)
    seller = Ed25519Signer(b"\x1b" * 32)
    secret = "sk_live_should_never_be_repeated"
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            _error_response(
                payload={"detail": f"Not Found {secret}"},
                headers={},
                status=404,
            )
        ),
    )

    with pytest.raises(RuntimeError) as refused:
        _authenticated_json(
            "http://seller/api/v1/settlements/esc-1",
            None,
            signer=buyer,
            principal=buyer.identity,
            method="GET",
            operation="settlement_status",
            resource="esc-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )

    message = str(refused.value)
    assert "HTTP 404" in message
    assert "carried no response authentication" in message
    # The body is what the refusal exists to distrust; it is never repeated.
    assert secret not in message
    assert "Not Found" not in message


def test_a_partly_authenticated_response_reads_differently(monkeypatch) -> None:
    """Missing one header is a protocol fault, not an unauthenticated answer."""

    buyer = Ed25519Signer(b"\x1c" * 32)
    seller = Ed25519Signer(b"\x1d" * 32)
    payload = {"status": "ready"}
    headers = _response_headers(
        signer=seller,
        payload=payload,
        request_id="request.1",
        operation="negotiate_new",
        resource="listing-1",
    )
    del headers["X-Market-Timestamp"]
    monkeypatch.setattr("core_buyer.negotiation_client.time.time", lambda: _NOW)
    monkeypatch.setattr(
        "core_buyer.negotiation_client.urllib.request.urlopen",
        lambda *_args, **_kwargs: _Response(payload, headers),
    )

    with pytest.raises(RuntimeError) as refused:
        _authenticated_json(
            "http://seller/api/v1/negotiate/new",
            {},
            signer=buyer,
            principal=buyer.identity,
            method="POST",
            operation="negotiate_new",
            resource="listing-1",
            request_id="request.1",
            timestamp=_NOW,
            expected_response_principals=_trust(seller),
        )

    message = str(refused.value)
    assert "incomplete response authentication" in message
    assert "X-Market-Timestamp" in message
    # A header name locates the fault; a header value fingerprints the exchange.
    assert headers["X-Market-Signature"] not in message
