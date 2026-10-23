"""Both clients against a scripted authority that reads the same declarations.

The authority here is an httpx transport handler: it matches each request to
the contracts' declaration the way the real authentication does, verifies the
seller's envelope over the resource that declaration binds, answers a script,
and signs its answer. A client that signed something else fails here as a
signature that cannot verify, which is how it would fail against the service.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_response,
    verify_request,
)

from arkhai_api.issuance import issuance_request
from arkhai_api_client import ADMIN_KEY_HEADER, AuthorityAuthenticationError, AuthorityClient, AuthorityError, SyncAuthorityClient
from arkhai_api_contracts.headers import (
    IDENTITY_IDENTIFIER_HEADER,
    IDENTITY_SCHEME_HEADER,
    REQUEST_ID_HEADER,
    ROLE_HEADER,
    SIGNATURE_HEADER,
    SIGNATURE_VERSION_HEADER,
    TIMESTAMP_HEADER,
)
from arkhai_api_contracts.models import IssuanceLabel, KeyDisposition
from arkhai_api_contracts.routes import AUTHORITY_ROUTES, SERVICE_ROLE

LABEL = IssuanceLabel("example")
OTHER_LABEL = IssuanceLabel("other")
# Deterministic development seeds for this test only; never used on any network.
AUTHORITY = Ed25519Signer(bytes(range(32)))
IMPOSTOR = Ed25519Signer(bytes(range(1, 33)))
SELLER = Ed25519Signer(bytes(range(2, 34)))
OWNER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")
TRUSTED_AUTHORITY = TrustedIdentitySet(identities=(AUTHORITY.identity,))

Script = Callable[[httpx.Request, Any], tuple[int, Any]]


def _request(quantity: int = 2, *, label: IssuanceLabel = LABEL):
    return issuance_request(
        label,
        negotiation_id="e1",
        owner=OWNER,
        service="service-main",
        resource_id="q1",
        quantity=quantity,
        key=KeyDisposition(mode="new"),
        capacity_reservation_id="r1",
    )


def _result(request, *, label: IssuanceLabel = LABEL) -> dict[str, Any]:
    return {
        "schema": label.issuance_result_schema,
        "fulfillment_id": request.fulfillment_id,
        "grant_id": request.fulfillment_id,
        "negotiation_id": request.negotiation_id,
        "owner": request.owner.model_dump(mode="json"),
        "service": request.service,
        "resource_id": request.resource_id,
        "quantity": request.quantity,
        "key_mode": "new",
        "key_id": "k1",
        "balance": request.quantity,
        "request_digest": request.request_digest,
        "committed_at_unix": 2_000_000_000,
        "capacity_reservation_id": "r1",
        "already_issued": False,
        "secret": "k1.private",
    }


def _declaration(method: str, path: str) -> dict:
    (declaration,) = [
        d for d in AUTHORITY_ROUTES if d["method"] == method and re.fullmatch(d["path"], path)
    ]
    return declaration


def _bound_resource(declaration: dict, path: str, body: Any) -> str:
    if (name := declaration.get("path_resource")) is not None:
        return re.fullmatch(declaration["path"], path).group(name)
    if (name := declaration.get("body_resource")) is not None:
        return str((body if isinstance(body, dict) else {}).get(name) or "")
    return ""


class ScriptedAuthority:
    """Records each request, verifies it as the authority would, and answers a script."""

    def __init__(
        self,
        script: Script,
        *,
        signer: Ed25519Signer | None = None,
        trusted_sellers: TrustedIdentitySet | None = None,
        sign_answers: bool = True,
    ) -> None:
        self.script = script
        self.signer = signer
        self.trusted_sellers = trusted_sellers
        self.sign_answers = sign_answers
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content) if request.content else EMPTY_BODY
        declaration = _declaration(request.method, request.url.path)
        resource = _bound_resource(declaration, request.url.path, body)
        if self.signer is None:
            status, payload = self.script(request, body)
            return httpx.Response(status, json=payload)
        headers = request.headers
        envelope = AuthenticatedRequest(
            protocol=headers[SIGNATURE_VERSION_HEADER],
            role=headers[ROLE_HEADER],
            principal=Identity(
                scheme=headers[IDENTITY_SCHEME_HEADER], identifier=headers[IDENTITY_IDENTIFIER_HEADER]
            ),
            method=request.method,
            operation=declaration["operation"],
            resource=resource,
            request_id=headers[REQUEST_ID_HEADER],
            timestamp=int(headers[TIMESTAMP_HEADER]),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(scheme=headers[IDENTITY_SCHEME_HEADER], value=headers[SIGNATURE_HEADER]),
        )
        verified = verify_request(
            envelope,
            body=body,
            now=int(time.time()),
            max_skew=300,
            expected_role=headers[ROLE_HEADER],
            expected_method=request.method,
            expected_operation=declaration["operation"],
            expected_resource=resource,
            expected_principals=self.trusted_sellers,
        )
        if not verified.verified or headers[ROLE_HEADER] not in declaration["roles"]:
            status, payload = 401, {"error": "unauthenticated", "detail": verified.code.value}
        else:
            status, payload = self.script(request, body)
        response = httpx.Response(status, json=payload)
        if not self.sign_answers:
            return response
        signed = sign_response(
            signer=self.signer,
            envelope=ResponseEnvelope(
                role=SERVICE_ROLE,
                principal=self.signer.identity,
                method=request.method,
                operation=declaration["operation"],
                resource=resource,
                request_id=headers[REQUEST_ID_HEADER],
                timestamp=int(time.time()),
                status=status,
                body_hash=canonical_body_hash(json.loads(response.content)),
            ),
        )
        response.headers.update(
            {
                SIGNATURE_VERSION_HEADER: signed.protocol,
                IDENTITY_SCHEME_HEADER: signed.principal.scheme.value,
                IDENTITY_IDENTIFIER_HEADER: signed.principal.identifier,
                ROLE_HEADER: signed.role,
                REQUEST_ID_HEADER: signed.request_id,
                TIMESTAMP_HEADER: str(signed.timestamp),
                SIGNATURE_HEADER: signed.proof.value,
            }
        )
        return response


def _shared_secret_clients(authority: ScriptedAuthority, admin_key: str = "secret"):
    return (
        AuthorityClient("http://authority", admin_key, label=LABEL, transport=authority.transport()),
        SyncAuthorityClient("http://authority", admin_key, label=LABEL, transport=authority.transport()),
    )


def _signed_clients(authority: ScriptedAuthority, *, trusted: TrustedIdentitySet = TRUSTED_AUTHORITY):
    return (
        AuthorityClient(
            "http://authority", label=LABEL, transport=authority.transport(),
            signer=SELLER, expected_authorities=trusted,
        ),
        SyncAuthorityClient(
            "http://authority", label=LABEL, transport=authority.transport(),
            signer=SELLER, expected_authorities=trusted,
        ),
    )


async def test_issuance_sends_the_request_and_reads_the_result_under_the_shared_secret():
    request = _request()
    authority = ScriptedAuthority(lambda _r, _b: (200, _result(request)))
    async_client, sync_client = _shared_secret_clients(authority)

    results = [await async_client.submit_issuance(request), sync_client.submit_issuance(request)]

    for sent in authority.requests:
        assert (sent.method, sent.url.path) == ("POST", "/api/v1/issuance")
        assert sent.headers[ADMIN_KEY_HEADER] == "secret"
        assert json.loads(sent.content) == request.model_dump(mode="json", exclude_none=True)
    for result in results:
        assert (result.key_id, result.secret) == ("k1", "k1.private")
        assert "secret" not in result.model_dump(mode="json")


async def test_a_result_under_another_label_is_refused():
    request = _request()
    authority = ScriptedAuthority(lambda _r, _b: (200, _result(request, label=OTHER_LABEL)))
    async_client, sync_client = _shared_secret_clients(authority)
    with pytest.raises(ValueError):
        await async_client.submit_issuance(request)
    with pytest.raises(ValueError):
        sync_client.submit_issuance(request)


async def test_a_refusal_carries_the_authoritys_reason():
    authority = ScriptedAuthority(lambda _r, _b: (409, {"error": "quota_exhausted", "detail": "full"}))
    async_client, sync_client = _shared_secret_clients(authority)
    with pytest.raises(AuthorityError) as refused:
        await async_client.submit_issuance(_request(quantity=1))
    assert (refused.value.reason, refused.value.detail, refused.value.status_code) == (
        "quota_exhausted", "full", 409,
    )
    with pytest.raises(AuthorityError) as refused_sync:
        sync_client.submit_issuance(_request(quantity=1))
    assert refused_sync.value.reason == "quota_exhausted"


async def test_an_unknown_key_or_issuance_reads_as_none():
    authority = ScriptedAuthority(lambda _r, _b: (404, {"error": "not_found"}))
    async_client, sync_client = _shared_secret_clients(authority)
    assert await async_client.get_key("missing") is None
    assert sync_client.get_key("missing") is None
    assert await async_client.get_issuance("f-missing") is None
    assert sync_client.get_issuance("f-missing") is None


async def test_key_administration_binds_paths_queries_and_bodies():
    seen: dict[str, Any] = {}

    def script(request: httpx.Request, body: Any) -> tuple[int, Any]:
        seen[request.url.path] = (dict(request.url.params), body)
        return 200, {"key_id": "k1", "status": "active", "balance": 5, "keys": [], "total": 0}

    authority = ScriptedAuthority(script)
    async_client, sync_client = _shared_secret_clients(authority)

    assert (await async_client.get_key("k1"))["status"] == "active"
    await async_client.list_keys(status="active", owner_id="0xabc")
    await async_client.list_key_usage("k1", after_id=7, limit=50)
    sync_client.list_key_grants("k1")
    assert (await async_client.revoke_key("k1"))["status"] == "active"
    sync_client.adjust_key_balance("k1", delta=-5, reason="rollback:p1")

    assert seen["/api/v1/keys"] == ({"status": "active", "owner_id": "0xabc"}, EMPTY_BODY)
    assert seen["/api/v1/keys/k1/usage"] == ({"after_id": "7", "limit": "50"}, EMPTY_BODY)
    assert seen["/api/v1/keys/k1/grants"] == ({}, EMPTY_BODY)
    assert seen["/api/v1/keys/k1/adjust"] == ({}, {"delta": -5, "reason": "rollback:p1"})
    assert [r.method for r in authority.requests if r.url.path.endswith("/revoke")] == ["POST"]


async def test_rollback_adjusts_then_revokes_a_new_key_and_spares_an_existing_one():
    authority = ScriptedAuthority(lambda _r, _b: (200, {"key_id": "k"}))
    async_client, sync_client = _shared_secret_clients(authority)

    rolled = await async_client.rollback_issuance(
        settlement_ref="payment-1", issuance={"key_id": "k", "quantity": 3}, key_mode="new"
    )
    assert [r.url.path for r in authority.requests] == ["/api/v1/keys/k/adjust", "/api/v1/keys/k/revoke"]
    assert json.loads(authority.requests[0].content) == {"delta": -3, "reason": "rollback:payment-1"}
    assert (rolled["rolled_back"], rolled["revoked"]) == (True, True)

    authority.requests.clear()
    spared = sync_client.rollback_issuance(
        settlement_ref="payment-2", issuance={"key_id": "k", "quantity": 3}, key_mode="existing"
    )
    assert [r.url.path for r in authority.requests] == ["/api/v1/keys/k/adjust"]
    assert spared == {"key_id": "k", "rolled_back": True}


async def test_a_refused_rollback_adjustment_is_reported_not_hidden():
    authority = ScriptedAuthority(lambda _r, _b: (409, {"error": "below_zero"}))
    async_client, _ = _shared_secret_clients(authority)
    outcome = await async_client.rollback_issuance(
        settlement_ref="payment-3", issuance={"key_id": "k", "quantity": 3}, key_mode="new"
    )
    assert outcome["rolled_back"] is False and outcome["reason"].startswith("adjust_failed")
    assert outcome["revoked"] is False


async def test_signed_calls_verify_against_the_declaration_on_both_sides():
    request = _request()
    authority = ScriptedAuthority(
        lambda r, _b: (200, _result(request) if r.url.path == "/api/v1/issuance" else {"key_id": "k1", "balance": 7}),
        signer=AUTHORITY,
        trusted_sellers=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    async_client, sync_client = _signed_clients(authority)

    assert (await async_client.get_key("k1"))["balance"] == 7
    assert sync_client.get_key("k1")["balance"] == 7
    assert (await async_client.submit_issuance(request)).key_id == "k1"
    assert sync_client.submit_issuance(request).key_id == "k1"
    assert all(ADMIN_KEY_HEADER not in r.headers for r in authority.requests)
    assert {r.headers[ROLE_HEADER] for r in authority.requests} == {"seller"}


async def test_a_signed_refusal_is_read_rather_than_failing_authentication():
    authority = ScriptedAuthority(
        lambda _r, _b: (404, {"error": "not_found"}),
        signer=AUTHORITY,
        trusted_sellers=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    async_client, sync_client = _signed_clients(authority)
    assert await async_client.get_issuance("f-missing") is None
    assert sync_client.get_issuance("f-missing") is None


async def test_an_untrusted_seller_is_refused_by_the_authority():
    authority = ScriptedAuthority(
        lambda _r, _b: (200, {"key_id": "k1"}),
        signer=AUTHORITY,
        trusted_sellers=TrustedIdentitySet(identities=(IMPOSTOR.identity,)),
    )
    async_client, _ = _signed_clients(authority)
    with pytest.raises(httpx.HTTPStatusError) as refused:
        await async_client.get_key("k1")
    assert refused.value.response.status_code == 401


async def test_an_unsigned_or_impostor_answer_is_refused_by_the_client():
    unsigned = ScriptedAuthority(
        lambda _r, _b: (200, {"key_id": "k1"}),
        signer=AUTHORITY,
        trusted_sellers=TrustedIdentitySet(identities=(SELLER.identity,)),
        sign_answers=False,
    )
    async_client, sync_client = _signed_clients(unsigned)
    with pytest.raises(AuthorityAuthenticationError) as missing:
        await async_client.get_key("k1")
    assert missing.value.reason == "missing_or_malformed_response_authentication"
    with pytest.raises(AuthorityAuthenticationError):
        sync_client.get_key("k1")

    impostor = ScriptedAuthority(
        lambda _r, _b: (200, {"key_id": "k1"}),
        signer=IMPOSTOR,
        trusted_sellers=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    async_client, _ = _signed_clients(impostor)
    with pytest.raises(AuthorityAuthenticationError) as forged:
        await async_client.get_key("k1")
    assert forged.value.reason == "response_authentication_failed"
