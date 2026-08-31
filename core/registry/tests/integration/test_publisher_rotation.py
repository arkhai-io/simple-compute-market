"""Two-proof publisher principal rotation integration coverage."""

from __future__ import annotations

import time
import uuid

import httpx
import pytest

from market_identity import RequestEnvelope, TrustedIdentitySet, canonical_body_hash, sign_request
from registry_client import RegistryClient, RegistryClientError
from registry_client.models import ListingRequest, UpdateListingRequest
from src.main import app

pytestmark = pytest.mark.asyncio

def _signed_headers(
    *,
    signer,
    method: str,
    operation: str,
    resource: str,
    body,
) -> dict[str, str]:
    envelope = RequestEnvelope(
        role="seller",
        principal=signer.identity,
        method=method,
        operation=operation,
        resource=resource,
        request_id=uuid.uuid4().hex,
        timestamp=int(time.time()),
        body_hash=canonical_body_hash(body),
    )
    authenticated = sign_request(signer=signer, envelope=envelope)
    return {
        "Content-Type": "application/json",
        "X-Market-Signature-Version": authenticated.protocol,
        "X-Market-Identity-Scheme": authenticated.principal.scheme.value,
        "X-Market-Identity-Identifier": authenticated.principal.identifier,
        "X-Market-Role": authenticated.role,
        "X-Market-Request-ID": authenticated.request_id,
        "X-Market-Timestamp": str(authenticated.timestamp),
        "X-Market-Signature": authenticated.proof.value,
    }



def _listing(listing_id: str) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        storefront_url="http://seller.example/",
        offer={"gpu_model": "A100", "region": "us"},
        accepted_escrows=[],
    )


async def test_rotation_is_idempotent_and_retire_last_preserves_owner(
    registry_client,
    ed25519_signer,
    registry_authority,
    taker_signer,
):
    published = await registry_client.publish_listing(_listing("rotation-listing"))
    publisher_id = published["publisher_id"]
    nonce = "rotation-once"
    expires_at = int(time.time()) + 300

    first = await registry_client.rotate_publisher_identity(
        publisher_id,
        ed25519_signer,
        nonce=nonce,
        overlap_seconds=300,
        expires_at=expires_at,
    )
    second = await registry_client.rotate_publisher_identity(
        publisher_id,
        ed25519_signer,
        nonce=nonce,
        overlap_seconds=300,
        expires_at=expires_at,
    )
    assert second == first
    assert first["status"] == "overlap"
    with pytest.raises(RegistryClientError) as overlap_exc:
        await registry_client.rotate_publisher_identity(
            publisher_id,
            taker_signer,
            nonce="blocked-overlap",
            overlap_seconds=30,
        )
    assert overlap_exc.value.status_code == 409


    await registry_client.update_listing(
        "rotation-listing",
        UpdateListingRequest(updates={"status": "closed"}),
    )
    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=ed25519_signer,
        caller_role="seller",
        expected_registries=TrustedIdentitySet(
            identities=(registry_authority.identity,)
        ),
        registry_authority="test-registry",
    ) as replacement:
        reopened = await replacement.update_listing(
            "rotation-listing",
            UpdateListingRequest(updates={"status": "open"}),
        )
        assert reopened["status"] == "open"
        retired = await replacement.retire_publisher_identity(publisher_id, nonce)
        assert retired["status"] == "retired"
        status = await replacement.get_publisher_rotation(publisher_id, nonce)
        next_rotation = await replacement.rotate_publisher_identity(
            publisher_id,
            taker_signer,
            nonce="after-retirement",
            overlap_seconds=0,
        )
        assert next_rotation["status"] == "retired"
        assert status["status"] == "retired"

    with pytest.raises(RegistryClientError) as exc_info:
        await registry_client.update_listing(
            "rotation-listing",
            UpdateListingRequest(updates={"status": "closed"}),
        )
    assert exc_info.value.status_code == 403


async def test_rotation_without_replacement_proof_is_rejected(
    registry_client,
    maker_signer,
    ed25519_signer,
):
    published = await registry_client.publish_listing(_listing("rotation-proof"))
    publisher_id = published["publisher_id"]
    body = {
        "intent": {
            "protocol": "arkhai.market-identity-rotation.v1",
            "current": maker_signer.identity.model_dump(mode="json"),
            "replacement": ed25519_signer.identity.model_dump(mode="json"),
            "subject": f"publisher:{publisher_id}",
            "authority": "test-registry",
            "nonce": "missing-proof",
            "overlap_seconds": 60,
            "expires_at": int(time.time()) + 300,
        },
        "current_proof": {
            "scheme": "eip191",
            "value": "0x" + "00" * 65,
        },
    }
    headers = _signed_headers(
        signer=maker_signer,
        method="POST",
        operation="publisher.identity.rotate",
        resource=str(publisher_id),
        body=body,
    )
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ) as raw:
        response = await raw.post(
            f"/publishers/{publisher_id}/identity-rotations",
            json=body,
            headers=headers,
        )
    assert response.status_code == 400
