"""Two-proof publisher principal rotation integration coverage.

Rotation and retirement re-run an exact retry, so each is proven by a
double-dispatch case: the request, a later rotation, the intent's expiry, then
the request's exact retry, which must change nothing and answer what the
rotation read answers now. A completeness test fails on any re-run mutation of
the registry's no case proves.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Iterator

import httpx
import injected_time
import pytest
from fastapi.routing import APIRoute
from injected_time import InjectedTime
from market_authenticated_requests import REPLAY_TABLE, RouteAdmission
from market_identity import ExactRetry, Signer, TrustedIdentitySet
from request_replay.harness import DoubleDispatchCase, assert_complete, run_double_dispatch, sqlite_snapshot
from sqlalchemy.engine import make_url

from registry_client import RegistryClient, RegistryClientError
from registry_client.models import ListingRequest, UpdateListingRequest, ValidatePublishRequest
from core_registry.main import api, app

pytestmark = pytest.mark.asyncio

def _listing(listing_id: str) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        storefront_url="http://seller.example/",
        listing_resource={"gpu_model": "A100", "region": "us"},
        accepted_escrows=[],
        settlement_options=[{
            "option_id": "a" * 64,
            "settlement": {"schema": "example.payment.v1"},
        }],
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
    async with httpx.AsyncClient(
        base_url="http://test",
        transport=httpx.ASGITransport(app=app),
    ) as raw:
        response = await raw.post(f"/publishers/{publisher_id}/identity-rotations", json=body)
    assert response.status_code == 400


@pytest.fixture
def held_time() -> Iterator[InjectedTime]:
    """The process source, held at the wall clock's instant for the test to move."""

    before = injected_time.installed()
    source = injected_time.install(InjectedTime(int(time.time())))
    yield source
    injected_time.install(before)


def _client(signer: Signer, registry_authority: Signer) -> RegistryClient:
    return RegistryClient(
        "http://test",
        transport=httpx.ASGITransport(app=app),
        signer=signer,
        caller_role="seller",
        expected_registries=TrustedIdentitySet(identities=(registry_authority.identity,)),
        registry_authority="test-registry",
    )


def _snapshot(registry_database: str):
    path = make_url(registry_database).database

    def snapshot() -> object:
        with sqlite3.connect(path) as connection:
            return sqlite_snapshot(connection, exclude={REPLAY_TABLE})

    return snapshot


def _rotation_case(
    publisher: RegistryClient, replacement: RegistryClient, successor: Signer,
    replacement_signer: Signer, publisher_id: int, source: InjectedTime,
) -> DoubleDispatchCase:
    """registry-discovery "A rotation is retried after its intent expired"."""

    origin, expires_at = source.now(), source.now() + 300

    async def rotate():
        return await publisher.rotate_publisher_identity(
            publisher_id, replacement_signer, nonce="first-rotation", overlap_seconds=0,
            expires_at=expires_at, request_id="rotate-1", origin=origin,
        )

    async def later_write():
        await replacement.rotate_publisher_identity(
            publisher_id, successor, nonce="later-rotation", overlap_seconds=0
        )
        source.set(source.now() + 301)

    async def current_answer():
        return await publisher.get_publisher_rotation(publisher_id, "first-rotation")

    return DoubleDispatchCase("publisher.identity.rotate", rotate, later_write, rotate, current_answer)


def _retirement_case(
    replacement: RegistryClient, successor: Signer, publisher_id: int, source: InjectedTime
) -> DoubleDispatchCase:
    """registry-discovery "A retirement is retried after a later rotation"."""

    origin = source.now()

    async def retire():
        return await replacement.retire_publisher_identity(
            publisher_id, "overlapping", request_id="retire-1", origin=origin
        )

    async def later_write():
        await replacement.rotate_publisher_identity(
            publisher_id, successor, nonce="after-retirement", overlap_seconds=0
        )
        source.set(source.now() + 301)

    async def current_answer():
        return await replacement.get_publisher_rotation(publisher_id, "overlapping")

    return DoubleDispatchCase("publisher.identity.retire", retire, later_write, retire, current_answer)


def _validation_case(publisher) -> DoubleDispatchCase:
    """Validation writes nothing, so its retry after a publication changes nothing."""

    listing = _listing("validated")
    candidate = ValidatePublishRequest(
        listing_id=listing.listing_id,
        listing_resource=listing.listing_resource,
        accepted_escrows=listing.accepted_escrows,
        settlement_options=listing.settlement_options,
        storefront_url=listing.storefront_url,
    )

    async def validate():
        return await publisher.validate_publish_listing(candidate)

    async def later_write():
        await publisher.publish_listing(_listing("validated"))

    return DoubleDispatchCase("listing.validate", validate, later_write, validate, validate)


async def _published(client: RegistryClient, listing_id: str) -> int:
    return (await client.publish_listing(_listing(listing_id)))["publisher_id"]


async def test_a_rotation_retried_after_its_intent_expired_and_a_later_rotation_changes_nothing(
    maker_signer, ed25519_signer, taker_signer, registry_authority, registry_database, held_time
):
    async with (
        _client(maker_signer, registry_authority) as publisher,
        _client(ed25519_signer, registry_authority) as replacement,
    ):
        publisher_id = await _published(publisher, "rotated-then-retried")
        case = _rotation_case(publisher, replacement, taker_signer, ed25519_signer, publisher_id, held_time)

        await run_double_dispatch(case, snapshot=_snapshot(registry_database))


async def test_a_retirement_retried_after_a_later_rotation_changes_nothing(
    maker_signer, ed25519_signer, taker_signer, registry_authority, registry_database, held_time
):
    async with (
        _client(maker_signer, registry_authority) as publisher,
        _client(ed25519_signer, registry_authority) as replacement,
    ):
        publisher_id = await _published(publisher, "retired-then-retried")
        await publisher.rotate_publisher_identity(
            publisher_id, ed25519_signer, nonce="overlapping", overlap_seconds=300
        )
        case = _retirement_case(replacement, taker_signer, publisher_id, held_time)

        await run_double_dispatch(case, snapshot=_snapshot(registry_database))


async def test_a_validation_retried_after_a_publication_changes_nothing(
    maker_signer, registry_authority, registry_database
):
    async with _client(maker_signer, registry_authority) as publisher:
        await run_double_dispatch(_validation_case(publisher), snapshot=_snapshot(registry_database))


def _rerun_mutations() -> set[str]:
    """Every operation of the registry's that re-runs an exact retry and is not a read."""

    operations = set()
    for route in api.routes:
        if not isinstance(route, APIRoute) or route.methods == {"GET"}:
            continue
        for dependency in route.dependant.dependencies:
            admission = dependency.call
            if isinstance(admission, RouteAdmission) and admission.exact_retry is ExactRetry.RERUN:
                operations.add(admission.operation)
    return operations


async def test_every_rerun_mutation_has_a_double_dispatch_case(
    maker_signer, ed25519_signer, taker_signer, registry_authority
) -> None:
    async with (
        _client(maker_signer, registry_authority) as publisher,
        _client(ed25519_signer, registry_authority) as replacement,
    ):
        source = InjectedTime(0)
        cases = [
            _rotation_case(publisher, replacement, taker_signer, ed25519_signer, 1, source),
            _retirement_case(replacement, taker_signer, 1, source),
            _validation_case(publisher),
        ]

    assert _rerun_mutations() == {"publisher.identity.rotate", "publisher.identity.retire", "listing.validate"}
    assert_complete(_rerun_mutations(), cases)
