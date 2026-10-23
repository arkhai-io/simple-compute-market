"""Request shaping: every call is bound from its route declaration and signed over it."""

from __future__ import annotations

import json
import re
import time

import httpx
import pytest
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    Ed25519Signer,
    Identity,
    SignatureProof,
    TrustedIdentitySet,
    canonical_json,
    verify_request,
)

from arkhai_api.issuance import issuance_request
from arkhai_api_client import ADMIN_KEY_HEADER, AuthorityClient, AuthorityError, SyncAuthorityClient
from arkhai_api_client import client as module
from arkhai_api_contracts import operations
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
from arkhai_api_contracts.routes import AUTHORITY_ROUTES, SELLER_ROLE, route

LABEL = IssuanceLabel("example")
# Deterministic development seed for this test only; never used on any network.
SELLER = Ed25519Signer(bytes(range(2, 34)))
OWNER = Identity(scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001")


def _request(quantity: int = 2):
    return issuance_request(
        LABEL,
        negotiation_id="e1",
        owner=OWNER,
        service="service-main",
        resource_id="q1",
        quantity=quantity,
        key=KeyDisposition(mode="new"),
        capacity_reservation_id="r1",
    )


ISSUANCE = _request()
CALLS = {
    operations.ISSUE: (module._issue(ISSUANCE, 30.0), ISSUANCE.fulfillment_id),
    operations.ISSUANCE_GET: (module._issuance_get("f-1", 10.0), "f-1"),
    operations.KEY_GET: (module._key_get("k1", 10.0), "k1"),
    operations.KEYS_LIST: (module._keys_list("active", None, 10.0), ""),
    operations.KEY_GRANTS_LIST: (module._key_grants_list("k1", 10.0), "k1"),
    operations.KEY_USAGE_LIST: (module._key_usage_list("k1", 7, 50, 10.0), "k1"),
    operations.KEY_REVOKE: (module._key_revoke("k1", 10.0), "k1"),
    operations.KEY_ADJUST: (module._key_adjust("k1", -3, "rollback:s1", 10.0), "k1"),
}


def test_every_seller_route_has_a_call_bound_from_its_declaration():
    # Verify admits the seller too, but spending and checking a key is the gate's call.
    seller_routes = {d["operation"] for d in AUTHORITY_ROUTES if SELLER_ROLE in d["roles"]}
    assert set(CALLS) == seller_routes - {operations.KEY_VERIFY}
    for operation, (call, resource) in CALLS.items():
        declaration = route(operation)
        assert call.method == declaration["method"]
        assert re.fullmatch(declaration["path"], call.path), (operation, call.path)
        assert call.resource == resource, operation


def test_the_issuance_resource_is_the_body_fulfillment_id_or_empty():
    assert module._call(operations.ISSUE, body={"quantity": 1}, timeout=1.0).resource == ""
    assert module._call(operations.ISSUE, body={"fulfillment_id": "f"}, timeout=1.0).resource == "f"


def test_a_path_parameter_that_does_not_bind_the_declaration_is_refused():
    with pytest.raises(ValueError, match="do not bind"):
        module._key_get("k1/revoke", 10.0)


def test_query_parameters_ride_outside_the_envelope():
    call, _ = CALLS[operations.KEY_USAGE_LIST]
    assert call.params == {"after_id": 7, "limit": 50}
    assert module._keys_list(None, None, 10.0).params is None


def _verified(call, prepared, body) -> bool:
    headers = prepared.headers
    envelope = AuthenticatedRequest(
        protocol=headers[SIGNATURE_VERSION_HEADER],
        role=headers[ROLE_HEADER],
        principal=Identity(
            scheme=headers[IDENTITY_SCHEME_HEADER], identifier=headers[IDENTITY_IDENTIFIER_HEADER]
        ),
        method=call.method,
        operation=call.operation,
        resource=call.resource,
        request_id=headers[REQUEST_ID_HEADER],
        timestamp=int(headers[TIMESTAMP_HEADER]),
        body_hash=module.canonical_body_hash(body),
        proof=SignatureProof(scheme=headers[IDENTITY_SCHEME_HEADER], value=headers[SIGNATURE_HEADER]),
    )
    result = verify_request(
        envelope,
        body=body,
        now=int(time.time()),
        max_skew=300,
        expected_role=SELLER_ROLE,
        expected_method=call.method,
        expected_operation=call.operation,
        expected_resource=call.resource,
        expected_principals=TrustedIdentitySet(identities=(SELLER.identity,)),
    )
    assert headers[REQUEST_ID_HEADER] == prepared.request_id
    return result.verified


def test_a_signed_request_verifies_against_its_declaration():
    call = module._key_adjust("k1", -3, "rollback:s1", 10.0)
    prepared = module._prepare(call, service_url="http://authority", admin_key="", signer=SELLER)

    assert prepared.url == "http://authority/api/v1/keys/k1/adjust"
    assert prepared.content == canonical_json(call.body)
    assert prepared.json is None
    assert ADMIN_KEY_HEADER not in prepared.headers
    assert prepared.headers["Content-Type"] == "application/json"
    assert _verified(call, prepared, json.loads(prepared.content))


def test_a_bodyless_signed_request_hashes_the_empty_body():
    call = module._key_get("k1", 10.0)
    prepared = module._prepare(call, service_url="http://authority", admin_key="", signer=SELLER)
    assert prepared.content is None and "Content-Type" not in prepared.headers
    assert _verified(call, prepared, EMPTY_BODY)
    assert not _verified(call, prepared, {"not": "empty"})


def test_the_shared_secret_path_sends_the_admin_header_and_json_body():
    call = module._key_adjust("k1", -3, "rollback:s1", 10.0)
    keyed = module._prepare(call, service_url="http://authority/", admin_key="secret", signer=None)
    assert keyed.headers == {ADMIN_KEY_HEADER: "secret"}
    assert keyed.json == call.body and keyed.content is None and keyed.request_id is None
    unkeyed = module._prepare(call, service_url="http://authority", admin_key="", signer=None)
    assert unkeyed.headers == {}


def test_a_refusal_maps_to_the_authoritys_reason_and_detail():
    refusal = module._service_error(
        httpx.Response(409, json={"error": "quota_exhausted", "detail": "full"})
    )
    assert (refusal.reason, refusal.detail, refusal.status_code) == ("quota_exhausted", "full", 409)
    assert isinstance(refusal, AuthorityError)
    plain = module._service_error(httpx.Response(502, text="bad gateway"))
    assert (plain.reason, plain.detail) == ("http_502", "bad gateway")


@pytest.mark.parametrize("client_class", [AuthorityClient, SyncAuthorityClient])
def test_signing_requires_both_halves(client_class):
    trusted = TrustedIdentitySet(identities=(SELLER.identity,))
    with pytest.raises(ValueError, match="together"):
        client_class("http://authority", label=LABEL, signer=SELLER)
    with pytest.raises(ValueError, match="together"):
        client_class("http://authority", label=LABEL, expected_authorities=trusted)
    assert client_class("http://authority", label=LABEL).signing_enabled is False
    assert client_class(
        "http://authority", label=LABEL, signer=SELLER, expected_authorities=trusted
    ).signing_enabled is True


def _no_http(request: httpx.Request) -> httpx.Response:
    raise AssertionError("no HTTP call should be made")


async def test_rollback_with_nothing_to_roll_back_makes_no_call():
    expected = {"key_id": "", "rolled_back": False, "reason": "nothing_to_roll_back"}
    client = AuthorityClient("http://authority", label=LABEL, transport=httpx.MockTransport(_no_http))
    assert await client.rollback_issuance(settlement_ref="p1", issuance={}, key_mode="new") == expected
    sync = SyncAuthorityClient("http://authority", label=LABEL, transport=httpx.MockTransport(_no_http))
    assert sync.rollback_issuance(settlement_ref="p1", issuance={"key_id": "k"}, key_mode="new") == {
        **expected, "key_id": "k",
    }
