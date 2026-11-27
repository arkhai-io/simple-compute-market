"""The gateway's request ordering against a scripted authority and a fake model server."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from arkhai_api_gate import ConsumeResult, GateConfig, PurchasePointer, VerifyResult
from arkhai_api_gateway import (
    INVALID_REQUEST,
    MODEL_NOT_FOUND,
    UPSTREAM_UNAVAILABLE,
    GatewayOffering,
    VerificationRefusal,
    create_gateway_app,
)

SERVICE = "served-model"
RESOURCE = "quota-1"
DEFAULT_CHARGE = 5
BUYER_SECRET = "k_1.buyer-secret"
UPSTREAM_SECRET = "upstream-secret"
INFERENCE_TERMS = {"rate_card": {"request_credits": "1"}, "attestation": {"kind": None}}
PINNED_DIGEST = "sha256:" + "a" * 64
BASE_CONFIG = GateConfig(service_url="http://authority", authority_label="authority")
PURCHASE_BODY = {"purchase": {"service_name": SERVICE}}


class Authority:
    """Answers the gate's verify and consume with fixed results, recording each call."""

    def __init__(
        self,
        verified: VerifyResult | None = None,
        consumed: ConsumeResult | None = None,
    ) -> None:
        self.verified = verified or VerifyResult(valid=True, status="active", balance=100)
        self.consumed = consumed or ConsumeResult(ok=True, balance=99, consumed=1)
        self.verify_calls: list[dict[str, Any]] = []
        self.consume_calls: list[dict[str, Any]] = []

    async def verify(self, **call: Any) -> VerifyResult:
        self.verify_calls.append(call)
        return self.verified

    async def consume(self, **call: Any) -> ConsumeResult:
        self.consume_calls.append(call)
        return self.consumed


class Upstream:
    """A model server that records what reached it and answers a fixed completion."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            201, json={"object": "chat.completion", "path": request.url.path},
        )


def _offering(tmp_path: Path, **overrides: Any) -> GatewayOffering:
    credential = tmp_path / "upstream-credential"
    credential.write_text(UPSTREAM_SECRET + "\n", encoding="utf-8")
    values: dict[str, Any] = {
        "service": SERVICE,
        "scope_service": SERVICE,
        "scope_resource_id": RESOURCE,
        "default_charge": DEFAULT_CHARGE,
        "purchase": PurchasePointer(service_name=SERVICE),
        "upstream_base_url": "http://model/v1/",
        "upstream_credential_file": credential,
        "current_terms": INFERENCE_TERMS,
    }
    values.update(overrides)
    return GatewayOffering(**values)


async def _post(
    offering: GatewayOffering,
    authority: Authority,
    upstream: Upstream,
    body: Any,
    *,
    path: str = "/v1/chat/completions",
    verification: Any = None,
    gate_config: GateConfig = BASE_CONFIG,
) -> httpx.Response:
    http = httpx.AsyncClient(transport=httpx.MockTransport(upstream.handle))
    kwargs = {"verification": verification} if verification is not None else {}
    app = create_gateway_app(
        offering, gate_config, authority=authority, http=http, **kwargs,  # type: ignore[arg-type]
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway",
    ) as client:
        content = body if isinstance(body, bytes) else json.dumps(body).encode()
        return await client.post(
            path,
            content=content,
            headers={"authorization": f"Bearer {BUYER_SECRET}", "content-type": "application/json"},
        )


def _app(offering: GatewayOffering, authority: Authority, http: httpx.AsyncClient) -> Any:
    return create_gateway_app(offering, BASE_CONFIG, authority=authority, http=http)  # type: ignore[arg-type]


async def test_an_unlisted_model_is_refused_before_the_gate(tmp_path: Path) -> None:
    authority, upstream = Authority(), Upstream()

    response = await _post(_offering(tmp_path), authority, upstream, {"model": "other"})

    assert response.status_code == 404
    assert response.json() == {"error": MODEL_NOT_FOUND}
    assert authority.verify_calls == authority.consume_calls == []
    assert upstream.requests == []


@pytest.mark.parametrize("body", [b"not json", b"[]", {"messages": []}, {"model": 3}])
async def test_a_body_naming_no_model_is_refused_before_the_gate(tmp_path: Path, body: Any) -> None:
    authority, upstream = Authority(), Upstream()

    response = await _post(_offering(tmp_path), authority, upstream, body)

    assert response.status_code == 400
    assert response.json() == {"error": INVALID_REQUEST}
    assert authority.verify_calls == []
    assert upstream.requests == []


@pytest.mark.parametrize(
    ("verified", "status", "body"),
    [
        (VerifyResult(valid=False, status=None, balance=0), 401, {"error": "invalid_api_key"}),
        (
            VerifyResult(valid=False, status="revoked", balance=0),
            403, {"error": "key_revoked", **PURCHASE_BODY},
        ),
        (
            VerifyResult(valid=False, status="key_out_of_scope", balance=0),
            403, {"error": "key_out_of_scope", **PURCHASE_BODY},
        ),
    ],
)
async def test_a_verify_denial_is_returned_uncharged(
    tmp_path: Path, verified: VerifyResult, status: int, body: dict[str, Any],
) -> None:
    authority, upstream = Authority(verified), Upstream()

    response = await _post(_offering(tmp_path), authority, upstream, {"model": SERVICE})

    assert response.status_code == status
    assert response.json() == body
    assert [call["secret"] for call in authority.verify_calls] == [BUYER_SECRET]
    assert authority.consume_calls == []
    assert upstream.requests == []


async def test_the_hook_receives_current_and_accepted_terms_and_refuses_uncharged(
    tmp_path: Path,
) -> None:
    accepted = {"rate_card": {"request_credits": "2"}, "attestation": {"kind": None}}
    authority = Authority(
        VerifyResult(
            valid=True, status="active", balance=10,
            accepted_terms=accepted, terms_digest=PINNED_DIGEST,
        ),
    )
    upstream = Upstream()
    hook = AsyncMock(return_value=VerificationRefusal(status=409, error="terms_changed"))

    response = await _post(
        _offering(tmp_path), authority, upstream, {"model": SERVICE}, verification=hook,
    )

    assert response.status_code == 409
    assert response.json() == {"error": "terms_changed"}
    hook.assert_awaited_once_with(INFERENCE_TERMS, accepted, PINNED_DIGEST)
    assert authority.consume_calls == []
    assert upstream.requests == []


async def test_an_admitted_request_charges_the_pinned_charge_and_forwards(tmp_path: Path) -> None:
    authority = Authority(
        VerifyResult(
            valid=True, status="active", balance=10,
            accepted_terms={}, terms_digest=PINNED_DIGEST, request_charge=2,
        ),
    )
    upstream = Upstream()

    response = await _post(_offering(tmp_path), authority, upstream, {"model": SERVICE})

    assert response.status_code == 201
    assert response.json() == {"object": "chat.completion", "path": "/v1/chat/completions"}
    assert [(call["key_id"], call["amount"]) for call in authority.consume_calls] == [("k_1", 2)]
    assert len(upstream.requests) == 1


async def test_the_gate_takes_its_scope_charge_and_pointer_from_the_offering(
    tmp_path: Path,
) -> None:
    elsewhere = GateConfig(
        service_url="http://authority",
        authority_label="authority",
        scope_service="other-model",
        scope_resource_id="other-quota",
        amount_per_request=99,
        purchase=PurchasePointer(service_name="other-model"),
    )
    exhausted = ConsumeResult(ok=False, balance=0, reason="insufficient_credits")
    authority, upstream = Authority(consumed=exhausted), Upstream()

    response = await _post(
        _offering(tmp_path), authority, upstream, {"model": SERVICE}, gate_config=elsewhere,
    )

    scope = {"service": SERVICE, "resource_id": RESOURCE}
    assert [{k: call[k] for k in scope} for call in authority.verify_calls] == [scope]
    assert [{k: call[k] for k in scope} for call in authority.consume_calls] == [scope]
    assert authority.consume_calls[0]["amount"] == DEFAULT_CHARGE
    assert response.json() == {"error": "insufficient_credits", **PURCHASE_BODY}


async def test_completions_forward_under_the_upstream_base_url(tmp_path: Path) -> None:
    authority, upstream = Authority(), Upstream()

    response = await _post(
        _offering(tmp_path), authority, upstream, {"model": SERVICE}, path="/v1/completions",
    )

    assert response.status_code == 201
    assert str(upstream.requests[0].url) == "http://model/v1/completions"


async def test_an_exhausted_key_is_answered_with_the_charge_denial(tmp_path: Path) -> None:
    exhausted = ConsumeResult(ok=False, balance=0, reason="insufficient_credits")
    authority, upstream = Authority(consumed=exhausted), Upstream()

    response = await _post(_offering(tmp_path), authority, upstream, {"model": SERVICE})

    assert response.status_code == 402
    assert response.json() == {"error": "insufficient_credits", **PURCHASE_BODY}
    assert upstream.requests == []


async def test_the_upstream_receives_the_deployments_credential_never_the_buyers(
    tmp_path: Path,
) -> None:
    authority, upstream = Authority(), Upstream()
    body = {"model": SERVICE, "messages": [{"role": "user", "content": "hi"}]}

    await _post(_offering(tmp_path), authority, upstream, body)

    (sent,) = upstream.requests
    assert sent.headers["authorization"] == f"Bearer {UPSTREAM_SECRET}"
    assert BUYER_SECRET not in str(sent.headers)
    assert json.loads(sent.content) == body


async def test_an_upstream_without_a_credential_receives_no_authorization(tmp_path: Path) -> None:
    authority, upstream = Authority(), Upstream()

    await _post(
        _offering(tmp_path, upstream_credential_file=None), authority, upstream, {"model": SERVICE},
    )

    assert "authorization" not in upstream.requests[0].headers


async def test_an_unreachable_upstream_is_a_bad_gateway(tmp_path: Path) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app = _app(
        _offering(tmp_path), Authority(), httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway",
    ) as client:
        response = await client.post(
            "/v1/chat/completions",
            json={"model": SERVICE},
            headers={"authorization": f"Bearer {BUYER_SECRET}"},
        )

    assert response.status_code == 502
    assert response.json() == {"error": UPSTREAM_UNAVAILABLE}


async def test_models_lists_only_the_offerings_service_ungated(tmp_path: Path) -> None:
    authority = Authority()
    app = _app(_offering(tmp_path), authority, httpx.AsyncClient())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway",
    ) as client:
        models = await client.get("/v1/models")
        health = await client.get("/health")

    assert models.json() == {"object": "list", "data": [{"id": SERVICE, "object": "model"}]}
    assert health.json() == {"status": "ok"}
    assert authority.verify_calls == []


def test_a_missing_upstream_credential_fails_at_construction(tmp_path: Path) -> None:
    offering = _offering(tmp_path, upstream_credential_file=tmp_path / "absent")

    with pytest.raises(ValueError, match="regular file"):
        _app(offering, Authority(), httpx.AsyncClient())


async def test_two_domains_offerings_behave_alike_save_their_values(tmp_path: Path) -> None:
    """One offering projected as an API-credits root would, one as inference's."""
    credits = _offering(
        tmp_path,
        service="forecast",
        scope_service="forecast",
        scope_resource_id="forecast-quota",
        default_charge=3,
        current_terms=None,
    )
    inference = _offering(tmp_path)
    for offering in (credits, inference):
        authority, upstream = Authority(), Upstream()

        unlisted = await _post(offering, authority, upstream, {"model": "unlisted"})
        admitted = await _post(offering, authority, upstream, {"model": offering.service})

        assert unlisted.status_code == 404
        assert admitted.status_code == 201
        assert [call["amount"] for call in authority.consume_calls] == [offering.default_charge]
        assert len(upstream.requests) == 1


def test_a_gateway_without_a_signing_credential_refuses_to_start(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="signing credential"):
        create_gateway_app(_offering(tmp_path), BASE_CONFIG)
