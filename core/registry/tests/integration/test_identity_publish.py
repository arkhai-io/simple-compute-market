"""Body-bound EIP-191 and Ed25519 registry mutation coverage."""

from __future__ import annotations

import time
from datetime import datetime, timedelta
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



def _listing(listing_id: str, *, region: str = "us") -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        storefront_url="http://seller.example/",
        offer={"gpu_model": "H200", "region": region},
        accepted_escrows=[],
        settlement_options=[
            {
                "option_id": "a" * 64,
                "mechanism": "fiat.stripe.v1",
                "asset": "usd",
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                "params": {"account_ref": "seller-account"},
            }
        ],
        max_duration_seconds=3600,
    )


async def test_ed25519_lazily_publishes_updates_and_deletes(
    registry_client,
    ed25519_signer,
    db_session,
    registry_authority,
):
    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=ed25519_signer,
        caller_role="seller",
        expected_registries=TrustedIdentitySet(
            identities=(registry_authority.identity,)
        ),
        registry_authority="test-registry",
    ) as client:
        published = await client.publish_listing(_listing("ed-listing"))
        assert published["publisher_principals"] == {
            "identities": [ed25519_signer.identity.model_dump(mode="json")]
        }
        updated = await client.update_listing(
            "ed-listing",
            UpdateListingRequest(updates={"status": "closed"}),
        )
        assert updated["status"] == "closed"
        await client.delete_listing("ed-listing")

    from src.db.models import Listing, PublisherIdentity

    binding = db_session.query(PublisherIdentity).one()
    assert binding.scheme == "ed25519"
    assert binding.identifier == ed25519_signer.identity.identifier
    assert db_session.query(Listing).count() == 0


async def test_eip191_publisher_remains_supported(registry_client, maker_signer):
    published = await registry_client.publish_listing(_listing("eip-listing"))
    assert published["publisher_principals"] == {
        "identities": [maker_signer.identity.model_dump(mode="json")]
    }


async def test_body_mutation_after_signing_is_rejected(
    registry_client,
    ed25519_signer,
):
    original = _listing("mutated-listing").to_dict()
    headers = _signed_headers(
        signer=ed25519_signer,
        method="POST",
        operation="listing.publish",
        resource="listings",
        body=original,
    )
    mutated = {**original, "offer_resource": {"gpu_model": "H200", "region": "eu"}}
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ) as raw:
        response = await raw.post(
            "/listings",
            json=mutated,
            headers=headers,
        )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_proof"


async def test_exact_request_replay_returns_recorded_outcome_once(
    registry_client,
    db_session,
):
    request_id = "same-request"
    timestamp = int(time.time())
    first = await registry_client.publish_listing(
        _listing("replay-listing"),
        request_id=request_id,
        timestamp=timestamp,
    )
    second = await registry_client.publish_listing(
        _listing("replay-listing"),
        request_id=request_id,
        timestamp=timestamp,
    )
    assert second == first

    from src.db.models import Listing, PublisherReplayReservation

    assert db_session.query(Listing).count() == 1
    assert db_session.query(PublisherReplayReservation).count() == 1


async def test_changed_reuse_of_request_id_is_rejected(
    registry_client,
):
    request_id = "changed-request"
    timestamp = int(time.time())
    await registry_client.publish_listing(
        _listing("changed-a", region="us"),
        request_id=request_id,
        timestamp=timestamp,
    )
    with pytest.raises(RegistryClientError) as exc_info:
        await registry_client.publish_listing(
            _listing("changed-b", region="eu"),
            request_id=request_id,
            timestamp=timestamp,
        )
    assert exc_info.value.status_code == 409


async def test_cross_scheme_owner_cannot_mutate_listing(
    registry_client,
    ed25519_signer,
    registry_authority,
):
    await registry_client.publish_listing(_listing("owned-by-eip"))
    async with RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=ed25519_signer,
        caller_role="seller",
        expected_registries=TrustedIdentitySet(
            identities=(registry_authority.identity,)
        ),
        registry_authority="test-registry",
    ) as other:
        with pytest.raises(RegistryClientError) as exc_info:
            await other.update_listing(
                "owned-by-eip",
                UpdateListingRequest(updates={"status": "closed"}),
            )
    assert exc_info.value.status_code == 403


async def test_legacy_query_signature_cannot_delete(
    registry_client,
):
    await registry_client.publish_listing(_listing("legacy-delete"))
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ) as raw:
        response = await raw.delete(
            "/listings/legacy-delete",
            params={"signature": "0x" + "00" * 65, "timestamp": int(time.time())},
            headers={"X-Test-Unsigned": "1"},
        )
    assert response.status_code == 401
    assert (await registry_client.get_listing("legacy-delete")).id == "legacy-delete"


async def test_version_one_header_is_rejected(
    registry_client,
    maker_signer,
):
    body = _listing("old-version").to_dict()
    headers = _signed_headers(
        signer=maker_signer,
        method="POST",
        operation="listing.publish",
        resource="listings",
        body=body,
    )
    headers["X-Market-Signature-Version"] = "arkhai.market-request-signature.v1"
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ) as raw:
        response = await raw.post("/listings", json=body, headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] == "unsupported_version"

async def test_deterministic_four_xx_is_cached_for_exact_retry(
    registry_client,
    db_session,
):
    request_id = "cached-not-found"
    timestamp = int(time.time())
    outcomes = []
    for _ in range(2):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.update_listing(
                "missing-listing",
                UpdateListingRequest(updates={"status": "closed"}),
                request_id=request_id,
                timestamp=timestamp,
            )
        outcomes.append((exc_info.value.status_code, exc_info.value.body))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == 404

    from src.db.models import PublisherReplayReservation

    replay = db_session.query(PublisherReplayReservation).filter_by(
        request_id=request_id
    ).one()
    assert replay.completed_at is not None
    assert replay.response_status == 404


async def test_active_lease_blocks_then_expired_lease_resumes(
    registry_client,
    db_session,
    monkeypatch,
):
    from src.api import listing_routes
    from src.db.models import PublisherReplayReservation

    original = listing_routes.ensure_publisher_for_identity

    def crash(*_args, **_kwargs):
        raise RuntimeError("simulated worker crash")

    monkeypatch.setattr(listing_routes, "ensure_publisher_for_identity", crash)
    request_id = "lease-restart"
    timestamp = int(time.time())
    with pytest.raises(RuntimeError, match="simulated worker crash"):
        await registry_client.publish_listing(
            _listing("lease-listing"),
            request_id=request_id,
            timestamp=timestamp,
        )
    with pytest.raises(RegistryClientError) as exc_info:
        await registry_client.publish_listing(
            _listing("lease-listing"),
            request_id=request_id,
            timestamp=timestamp,
        )
    assert exc_info.value.status_code == 409
    assert "request_in_progress" in exc_info.value.body

    replay = db_session.query(PublisherReplayReservation).filter_by(
        request_id=request_id
    ).one()
    replay.lease_expires_at = datetime.utcnow() - timedelta(seconds=1)
    db_session.commit()
    monkeypatch.setattr(
        listing_routes,
        "ensure_publisher_for_identity",
        original,
    )
    resumed = await registry_client.publish_listing(
        _listing("lease-listing"),
        request_id=request_id,
        timestamp=timestamp,
    )
    assert resumed["listing_id"] == "lease-listing"
