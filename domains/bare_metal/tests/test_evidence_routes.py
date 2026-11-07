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
import inspect

import pytest

from arkhai_bare_metal import CanonicalPrincipal, build_bare_metal_lease_ready_evidence
from arkhai_bare_metal.evidence import bare_metal_digest
from arkhai_bare_metal.evidence_routes import (
    EVIDENCE_OPERATION,
    BareMetalEvidenceClient,
    BareMetalEvidenceContractError,
    BareMetalEvidenceRouteError,
    BareMetalEvidenceRouteService,
    BareMetalSignedLeaseReadyEvidence,
    SyncBareMetalEvidenceClient,
    evidence_path,
    evidence_resource,
)

from test_evidence import alkahest_binding, lease_ready_result

SELLER = CanonicalPrincipal(scheme="ed25519", identifier="seller")
ADMIN = CanonicalPrincipal(scheme="ed25519", identifier="admin")
DIGEST = "sha256:" + "ab" * 32


def _alkahest():
    binding = alkahest_binding()
    return build_bare_metal_lease_ready_evidence(
        binding=binding,
        condition_anchor=binding.escrow_uid,
        result=lease_ready_result(),
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

    from_sync = SyncBareMetalEvidenceClient(
        sync_transport, role="seller"
    ).lease_ready_evidence(evidence.evidence_digest)
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
        SyncBareMetalEvidenceClient(
            _Recording({}), role="service"
        ).lease_ready_evidence(DIGEST)


@pytest.mark.parametrize("client_kind", ["sync", "async"])
def test_clients_refuse_a_valid_document_with_the_wrong_requested_digest(client_kind):
    payload = _service(_alkahest()).respond(_alkahest()).model_dump(mode="json")
    with pytest.raises(ValueError, match="expected digest"):
        if client_kind == "sync":
            SyncBareMetalEvidenceClient(
                _Recording(payload), role="buyer"
            ).lease_ready_evidence(DIGEST)
        else:
            asyncio.run(
                BareMetalEvidenceClient(
                    _AsyncRecording(payload), role="buyer"
                ).lease_ready_evidence(DIGEST)
            )


@pytest.mark.parametrize("client_kind", ["sync", "async"])
def test_clients_refuse_malformed_content(client_kind):
    payload = _service(_alkahest()).respond(_alkahest()).model_dump(mode="json")
    payload["evidence"]["result"].pop("expires_at")
    payload["evidence"]["result_digest"] = bare_metal_digest(
        payload["evidence"]["result"]
    )
    digest = bare_metal_digest(payload["evidence"])
    with pytest.raises(ValueError):
        if client_kind == "sync":
            SyncBareMetalEvidenceClient(
                _Recording(payload), role="buyer"
            ).lease_ready_evidence(digest)
        else:
            asyncio.run(
                BareMetalEvidenceClient(
                    _AsyncRecording(payload), role="buyer"
                ).lease_ready_evidence(digest)
            )


def test_signed_carrier_has_original_envelope_and_all_field_reads():
    evidence = _alkahest()
    signed = _service(evidence).respond(evidence)
    assert set(signed.model_dump(mode="json")) == {
        "protocol",
        "seller_principal",
        "evidence",
        "proof",
    }
    assert signed.model_dump(mode="json")["evidence"] == evidence.to_wire()
    for name in type(evidence.value).model_fields:
        if name == "result":
            continue
        assert getattr(signed.evidence, name) == getattr(evidence.value, name)
    for name in type(evidence.result.value).model_fields:
        assert getattr(signed.evidence.result, name) == getattr(
            evidence.result.value, name
        )
    assert inspect.signature(
        BareMetalEvidenceClient.lease_ready_evidence
    ) == inspect.signature(SyncBareMetalEvidenceClient.lease_ready_evidence)


def test_signed_carrier_schema_describes_existing_wire_in_both_modes():
    for mode in ("validation", "serialization"):
        schema = BareMetalSignedLeaseReadyEvidence.model_json_schema(mode=mode)
        assert set(schema["properties"]) == {
            "protocol",
            "seller_principal",
            "evidence",
            "proof",
        }
        assert schema["properties"]["evidence"]["properties"]["result"][
            "$ref"
        ].endswith("BareMetalLeaseReadyResult")


@pytest.mark.parametrize("client_kind", ["sync", "async"])
@pytest.mark.parametrize("access_ready", [1, 1.0])
def test_clients_refuse_numeric_readiness_with_matching_requested_digest(
    client_kind, access_ready
):
    payload = _service(_alkahest()).respond(_alkahest()).model_dump(mode="json")
    payload["evidence"]["result"]["access_ready"] = access_ready
    payload["evidence"]["result_digest"] = bare_metal_digest(
        payload["evidence"]["result"]
    )
    digest = bare_metal_digest(payload["evidence"])
    with pytest.raises(ValueError, match="access_ready must be JSON true"):
        if client_kind == "sync":
            SyncBareMetalEvidenceClient(
                _Recording(payload), role="buyer"
            ).lease_ready_evidence(digest)
        else:
            asyncio.run(
                BareMetalEvidenceClient(
                    _AsyncRecording(payload), role="buyer"
                ).lease_ready_evidence(digest)
            )
