"""The evidence route's contract, route service, and typed client, without HTTP.

The route service is exercised over an in-memory store and signer; the client
over a recording transport standing where a storefront client's generic
``authenticated_request`` stands. The route bound in a storefront is exercised
through this client in that storefront's own integration tests.
"""

from __future__ import annotations

import asyncio
import base64
import json

import pytest

from arkhai_bare_metal import CanonicalPrincipal
from arkhai_bare_metal.evidence_routes import (
    EVIDENCE_OPERATION,
    BareMetalEvidenceClient,
    BareMetalEvidenceContractError,
    BareMetalEvidenceRouteError,
    BareMetalEvidenceRouteService,
    SyncBareMetalEvidenceClient,
    evidence_path,
    evidence_resource,
)

from test_evidence import alkahest_binding, lease_ready_result
from arkhai_bare_metal import build_bare_metal_lease_ready_evidence

SELLER = CanonicalPrincipal(scheme="ed25519", identifier="seller")
ADMIN = CanonicalPrincipal(scheme="ed25519", identifier="admin")
DIGEST = "sha256:" + "ab" * 32


def _alkahest():
    binding = alkahest_binding()
    return build_bare_metal_lease_ready_evidence(
        binding=binding, condition_anchor=binding.escrow_uid, result=lease_ready_result()
    )


def _service(*stored):
    by_digest = {evidence.evidence_digest: evidence for evidence in stored}

    async def load(digest):
        return by_digest.get(digest)

    return BareMetalEvidenceRouteService(
        load_evidence=load,
        seller_principal=SELLER,
        sign=lambda material: b"signed:" + material,
        admin_principals=(ADMIN,),
    )


def test_the_resource_is_the_digest_with_or_without_its_prefix():
    assert evidence_resource(DIGEST) == "ab" * 32
    assert evidence_resource("ab" * 32) == "ab" * 32
    assert evidence_path(DIGEST) == "/api/v1/evidence/bare-metal/" + "ab" * 32
    for malformed in ("sha256:AB" + "ab" * 31, "ab" * 31, "sha256:"):
        with pytest.raises(BareMetalEvidenceContractError):
            evidence_resource(malformed)


def test_unknown_or_malformed_evidence_is_not_found():
    service = _service()
    for digest in (DIGEST, "not-a-digest"):
        with pytest.raises(BareMetalEvidenceRouteError) as refused:
            asyncio.run(service.evidence(digest))
        assert refused.value.status_code == 404


def test_readers_follow_the_evidence_binding():
    evidence = _alkahest()
    service = _service(evidence)

    readers = service.readers(asyncio.run(service.evidence(evidence.evidence_digest)))

    assert readers == {
        "buyer": (evidence.buyer_principal,),
        "seller": (evidence.claimant_principal,),
        "admin": (ADMIN,),
    }


def test_the_response_carries_the_sellers_proof_over_the_canonical_body():
    evidence = _alkahest()

    signed = _service(evidence).respond(evidence)

    padded = signed.proof + "=" * (-len(signed.proof) % 4)
    assert base64.urlsafe_b64decode(padded) == (
        b"signed:" + evidence.canonical_json().encode("utf-8")
    )
    assert signed.seller_principal == SELLER
    assert signed.evidence == evidence


class _Recording:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def authenticated_request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response


class _AsyncRecording(_Recording):
    async def authenticated_request(self, method, path, **kwargs):
        return super().authenticated_request(method, path, **kwargs)


def test_both_clients_sign_the_contracts_operation_and_resource():
    evidence = _alkahest()
    payload = json.loads(_service(evidence).respond(evidence).model_dump_json())
    sync_transport = _Recording(payload)
    async_transport = _AsyncRecording(payload)

    from_sync = SyncBareMetalEvidenceClient(sync_transport, role="seller").lease_ready_evidence(
        evidence.evidence_digest
    )
    from_async = asyncio.run(
        BareMetalEvidenceClient(async_transport, role="seller").lease_ready_evidence(
            evidence.evidence_digest, request_id="request-1"
        )
    )

    assert from_sync.evidence == from_async.evidence == evidence
    resource = evidence.evidence_digest.removeprefix("sha256:")
    assert sync_transport.calls == [
        (
            "GET",
            f"/api/v1/evidence/bare-metal/{resource}",
            {
                "role": "seller",
                "operation": EVIDENCE_OPERATION,
                "resource": resource,
                "request_id": None,
            },
        )
    ]
    assert async_transport.calls[0][2]["request_id"] == "request-1"


def test_a_client_refuses_a_role_no_reader_signs_as():
    with pytest.raises(BareMetalEvidenceContractError):
        SyncBareMetalEvidenceClient(_Recording({}), role="service").lease_ready_evidence(
            DIGEST
        )

