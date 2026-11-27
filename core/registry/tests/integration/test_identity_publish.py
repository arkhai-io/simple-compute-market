"""Body-bound EIP-191 and Ed25519 registry mutation coverage, and how the
registry's admission resolves a replay, an exact retry, and a request no route
serves or that states another operation.

Application integration: the running registry through the typed client; raw
requests only on rejection paths the typed client cannot construct, each signed
by ``kit/identity``'s profile over the exact bytes it carries.
"""

from __future__ import annotations

import json

import httpx
import injected_time
import pytest

from market_authenticated_requests import REPLAY_TABLE, ROUTE_FAILURE_DETAIL
from market_identity import (
    MarketRequest,
    RequestBinding,
    TrustedIdentitySet,
    sign_market_request,
    verify_market_response,
)
from registry_client import RegistryClient, RegistryClientError, sign_registry_request
from registry_client.models import ListingRequest, UpdateListingRequest
from sqlalchemy import text
from core_registry.main import app

pytestmark = pytest.mark.asyncio


def _signed(signer, registry, method: str, path: str, document: dict | None = None):
    """A raw request the typed client would sign: its target, headers and the
    exact body bytes its signature covers."""

    body = b"" if document is None else json.dumps(document, separators=(",", ":")).encode()
    signed = sign_registry_request(
        signer=signer,
        role="seller",
        method=method,
        path=path,
        body=body,
        audience=TrustedIdentitySet(identities=(registry.identity,)),
    )
    return signed, body


def _raw() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url="http://test", transport=httpx.ASGITransport(app=app))


def _signed_by(response: httpx.Response, binding: RequestBinding, registry) -> bool:
    return verify_market_response(
        status=response.status_code,
        headers=response.headers,
        body=response.content,
        request=binding,
        expected_principals=TrustedIdentitySet(identities=(registry.identity,)),
        now=injected_time.now(),
        max_skew=300,
    ).verified


def _replay_rows(db_session) -> list[tuple]:
    return [
        tuple(row)
        for row in db_session.execute(
            text(f"SELECT request_id, resolution, outcome_status FROM {REPLAY_TABLE} ORDER BY request_id")
        )
    ]


def _listing(listing_id: str, *, region: str = "us") -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        storefront_url="http://seller.example/",
        listing_resource={"gpu_model": "H200", "region": region},
        accepted_escrows=[],
        settlement_options=[
            {
                "option_id": "a" * 64,
                "price": {
                    "asset": "usd",
                    "rates": [{"field": "amount", "per": "hour", "value": "100"}],
                },
                "settlement": {
                    "schema": "example.payment.v1",
                    **({"account_ref": "seller-account"} or {}),
                },
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

    from core_registry.db.models import Listing, PublisherIdentity

    binding = db_session.query(PublisherIdentity).one()
    assert binding.scheme == "ed25519"
    assert binding.identifier == ed25519_signer.identity.identifier
    assert db_session.query(Listing).count() == 0


async def test_eip191_publisher_remains_supported(registry_client, maker_signer):
    published = await registry_client.publish_listing(_listing("eip-listing"))
    assert published["publisher_principals"] == {
        "identities": [maker_signer.identity.model_dump(mode="json")]
    }


async def test_the_publish_route_refuses_a_retired_listing_shape(
    registry_client,
    ed25519_signer,
    registry_authority,
):
    """The mutation boundary: a correctly signed publisher is refused on its
    listing's shape, not on its authentication. Raw HTTP because the typed
    client cannot construct a retired key; a 401 here would prove nothing."""
    body = _listing("retired-at-publish").to_dict()
    body["listing_resource"] = {
        "gpu_model": "H200",
        "region": "us-west",
        "virtualization_type": "vm",
    }
    signed, content = _signed(ed25519_signer, registry_authority, "POST", "/listings", body)
    async with _raw() as raw:
        response = await raw.post(signed.target, content=content, headers=signed.headers)

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "retired_listing_shape"
    assert detail["retired_fields"] == ["listing_resource.virtualization_type"]


async def test_the_publish_route_refuses_the_retired_shape_key(
    registry_client,
    ed25519_signer,
    registry_authority,
):
    """`offer_resource` at the top level, same boundary."""
    body = _listing("retired-shape-at-publish").to_dict()
    body["offer_resource"] = body["listing_resource"]
    signed, content = _signed(ed25519_signer, registry_authority, "POST", "/listings", body)
    async with _raw() as raw:
        response = await raw.post(signed.target, content=content, headers=signed.headers)

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["retired_fields"] == ["offer_resource"]


async def test_body_mutation_after_signing_is_rejected(
    registry_client,
    ed25519_signer,
    registry_authority,
    db_session,
):
    """Rejection path: a body changed after signing, which the typed client
    never sends; refused signed, before anything is written."""
    original = _listing("mutated-listing").to_dict()
    signed, _ = _signed(ed25519_signer, registry_authority, "POST", "/listings", original)
    mutated = {**original, "listing_resource": {"gpu_model": "H200", "region": "eu"}}
    async with _raw() as raw:
        response = await raw.post(
            signed.target, content=json.dumps(mutated, separators=(",", ":")).encode(), headers=signed.headers
        )
    assert response.status_code == 401
    assert _signed_by(response, signed.binding, registry_authority)
    assert db_session.execute(text("SELECT COUNT(*) FROM listings")).scalar() == 0


async def test_an_exact_retry_of_a_publication_is_answered_with_its_recorded_outcome(
    registry_client,
    db_session,
):
    first = await registry_client.publish_listing(_listing("replay-listing"), request_id="same-request", origin=injected_time.now())
    origin = injected_time.now()
    second = await registry_client.publish_listing(_listing("replay-listing"), request_id="same-request", origin=origin)

    assert second == first
    assert db_session.execute(text("SELECT COUNT(*) FROM listings")).scalar() == 1
    assert _replay_rows(db_session) == [("same-request", "recorded", 201)]


async def test_a_delayed_publication_retry_after_a_later_update_keeps_the_update(registry_client, db_session):
    """registry-discovery "Completed publication is retried": the retry is
    answered with the publication's recorded outcome and runs nothing, so the
    update made since stands."""
    origin = injected_time.now()
    published = await registry_client.publish_listing(_listing("later-update"), request_id="publish-1", origin=origin)
    await registry_client.update_listing("later-update", UpdateListingRequest(updates={"status": "closed"}))

    retried = await registry_client.publish_listing(_listing("later-update"), request_id="publish-1", origin=origin)

    assert retried == published
    assert (await registry_client.get_listing("later-update")).status == "closed"


async def test_a_deletion_retried_after_a_republication_keeps_the_republished_listing(registry_client, db_session):
    """registry-discovery "A deletion is retried after the listing was
    republished"."""
    await registry_client.publish_listing(_listing("republished"))
    origin = injected_time.now()
    await registry_client.delete_listing("republished", request_id="delete-1", origin=origin)
    await registry_client.publish_listing(_listing("republished", region="eu"))

    await registry_client.delete_listing("republished", request_id="delete-1", origin=origin)

    republished = await registry_client.get_listing("republished")
    assert republished.listing_resource["region"] == "eu"
    assert ("delete-1", "recorded", 204) in _replay_rows(db_session)


async def test_changed_reuse_of_request_id_is_rejected(registry_client):
    origin = injected_time.now()
    await registry_client.publish_listing(_listing("changed-a", region="us"), request_id="changed-request", origin=origin)
    with pytest.raises(RegistryClientError) as exc_info:
        await registry_client.publish_listing(
            _listing("changed-b", region="eu"), request_id="changed-request", origin=origin
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


async def test_an_unsigned_request_cannot_delete(registry_client):
    """Rejection path: a request carrying no request identity is answered
    unsigned, as no identity may be invented to sign it."""
    await registry_client.publish_listing(_listing("legacy-delete"))
    async with _raw() as raw:
        response = await raw.delete(
            "/listings/legacy-delete",
            params={"signature": "0x" + "00" * 65},
            headers={"X-Test-Unsigned": "1"},
        )
    assert response.status_code == 400
    assert "Signature" not in response.headers
    assert (await registry_client.get_listing("legacy-delete")).id == "legacy-delete"


async def test_a_version_2_request_is_refused_unsigned(registry_client):
    """Rejection path: a version 2 request carries none of the version 3
    fields, so its refusal is unsigned."""
    async with _raw() as raw:
        response = await raw.post(
            "/listings",
            json=_listing("old-version").to_dict(),
            headers={
                "X-Test-Unsigned": "1",
                "X-Market-Signature-Version": "arkhai.market-request-signature.v2",
                "X-Market-Request-ID": "v2-request",
            },
        )
    assert response.status_code == 400
    assert "Signature" not in response.headers


async def test_a_refused_update_is_recorded_for_its_exact_retry(registry_client, db_session):
    outcomes = []
    origin = injected_time.now()
    for _ in range(2):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.update_listing(
                "missing-listing",
                UpdateListingRequest(updates={"status": "closed"}),
                request_id="cached-not-found",
                origin=origin,
            )
        outcomes.append((exc_info.value.status_code, exc_info.value.body))
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0] == 404
    assert _replay_rows(db_session) == [("cached-not-found", "recorded", 404)]


async def test_a_publication_raising_after_admission_is_a_recorded_signed_500(
    registry_client,
    db_session,
    monkeypatch,
):
    """A recorded route that raises is answered with a signed 500 whose effect
    is unknown, recorded, so its exact retry is answered the same and never
    dispatched again."""
    from core_registry.api import listing_routes

    dispatches = []

    def crash(*_args, **_kwargs):
        dispatches.append("publish")
        raise RuntimeError("simulated failure after admission")

    monkeypatch.setattr(listing_routes, "ensure_publisher_for_identity", crash)
    origin = injected_time.now()
    answers = []
    for _ in range(2):
        with pytest.raises(RegistryClientError) as exc_info:
            await registry_client.publish_listing(_listing("crashed"), request_id="crash", origin=origin)
        answers.append((exc_info.value.status_code, json.loads(exc_info.value.body)))

    assert answers == [(500, {"detail": ROUTE_FAILURE_DETAIL})] * 2
    assert dispatches == ["publish"]
    assert _replay_rows(db_session) == [("crash", "recorded", 500)]


async def test_a_path_no_route_serves_is_answered_signed(registry_authority, maker_signer):
    """Rejection path: the typed client has no method for an unknown path, so
    the signed request names an operation the registry does not serve, and the
    404 is signed over it."""
    now = injected_time.now()
    request = MarketRequest(
        method="GET", role="seller", operation="listing.search", request_id="unserved", origin=now
    )
    signed = sign_market_request(
        signer=maker_signer, request=request, body=b"", created=now,
        audience=TrustedIdentitySet(identities=(registry_authority.identity,)),
    )
    async with _raw() as raw:
        response = await raw.get("/listingz", headers=signed.headers)

    assert response.status_code == 404
    assert _signed_by(response, request.binding, registry_authority)


async def test_a_publication_stating_a_resource_is_an_operation_mismatch(
    registry_authority, maker_signer, db_session
):
    """Rejection path: publication has no target, so a request naming one is
    refused before dispatch; the typed client never names one."""
    body = json.dumps(_listing("stated-resource").to_dict(), separators=(",", ":")).encode()
    now = injected_time.now()
    request = MarketRequest(
        method="POST", role="seller", operation="listing.publish", resource="listings",
        request_id="stated-resource", origin=now,
    )
    signed = sign_market_request(
        signer=maker_signer, request=request, body=body, created=now,
        audience=TrustedIdentitySet(identities=(registry_authority.identity,)),
    )
    async with _raw() as raw:
        response = await raw.post(
            "/listings", content=body, headers={**signed.headers, "Content-Type": "application/json"}
        )

    assert response.status_code == 400
    # Signed over the route's own operation, which binds no resource.
    bound = RequestBinding(method="POST", operation="listing.publish", request_id="stated-resource")
    assert _signed_by(response, bound, registry_authority)
    assert db_session.execute(text("SELECT COUNT(*) FROM listings")).scalar() == 0
