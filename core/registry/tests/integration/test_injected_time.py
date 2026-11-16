"""The registry stamps what it stores from its process's time source.

Application integration: the running registry, in process, driven through the
canonical `RegistryClient`, with the process source injected; the API key's
store, which no client route reaches here, through its functions. The client
signs and checks responses on the wall clock, so the source is set 120 seconds
behind it: every signed hop stays within the 300-second skew while each stored
time is told apart from a wall read.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime, timezone

import injected_time
import pytest
from injected_time import InjectedTime

from core_registry.api.api_key_auth import mint_api_key, revoke_api_key
from core_registry.api.utils import effective_identity_status
from core_registry.db.models import (
    ApiKey,
    Listing,
    Publisher,
    PublisherIdentity,
    PublisherIdentityRotation,
    PublisherReplayReservation,
)
from registry_client import ListingRequest


@pytest.fixture
def source() -> Iterator[InjectedTime]:
    """The process time source, injected 120 seconds behind the wall clock."""
    before = injected_time.installed()
    installed = InjectedTime(start=int(time.time()) - 120)
    injected_time.install(installed)
    yield installed
    injected_time.install(before)


def _listing(listing_id: str, region: str) -> ListingRequest:
    return ListingRequest(
        listing_id=listing_id,
        listing_resource={"gpu_model": "H200", "region": region, "offering_mode": "vm"},
        accepted_escrows=[
            {
                "chain_name": "anvil",
                # Development fixture addresses; never used on a public network.
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
            }
        ],
        storefront_url="http://seller",
    )


def _naive_utc(instant: int) -> datetime:
    """An instant as the registry stores times: UTC with no zone."""
    return datetime.fromtimestamp(instant, timezone.utc).replace(tzinfo=None)


async def test_a_published_listing_holds_the_injected_instant(
    registry_client, db_session, source: InjectedTime
):
    published_at = source.now()
    await registry_client.publish_listing(_listing("injected-1", "us-west"))

    db_session.expire_all()
    listing = db_session.get(Listing, "injected-1")
    publisher = db_session.get(Publisher, listing.publisher_id)
    (binding,) = db_session.query(PublisherIdentity).filter_by(
        publisher_id=publisher.publisher_id
    ).all()
    replays = db_session.query(PublisherReplayReservation).all()
    assert (listing.created_at, listing.updated_at) == (
        _naive_utc(published_at),
        _naive_utc(published_at),
    )
    assert (publisher.created_at, binding.created_at) == (
        _naive_utc(published_at),
        _naive_utc(published_at),
    )
    assert {(row.created_at, row.completed_at) for row in replays} == {
        (_naive_utc(published_at), _naive_utc(published_at))
    }

    source.set(published_at + 60)
    await registry_client.publish_listing(_listing("injected-1", "eu-central"))

    db_session.expire_all()
    listing = db_session.get(Listing, "injected-1")
    assert (listing.created_at, listing.updated_at) == (
        _naive_utc(published_at),
        _naive_utc(published_at + 60),
    )


async def test_a_rotation_s_overlap_ends_at_the_injected_instant(
    registry_client, db_session, ed25519_signer, source: InjectedTime
):
    """A rotation is applied at the source's instant, its overlap deadline is
    stored from it, and the outgoing principal retires when the source reaches
    that deadline and not before."""
    published = await registry_client.publish_listing(_listing("injected-2", "us-west"))
    rotated_at = source.now()
    await registry_client.rotate_publisher_identity(
        published["publisher_id"],
        ed25519_signer,
        nonce="injected-rotation",
        overlap_seconds=300,
        expires_at=int(time.time()) + 300,
    )

    db_session.expire_all()
    (rotation,) = db_session.query(PublisherIdentityRotation).all()
    outgoing = (
        db_session.query(PublisherIdentity)
        .filter(PublisherIdentity.publisher_id == published["publisher_id"])
        .filter(PublisherIdentity.status == "overlap")
        .one()
    )
    assert (rotation.applied_at, rotation.retire_at) == (
        _naive_utc(rotated_at),
        _naive_utc(rotated_at + 300),
    )
    assert outgoing.active_until == _naive_utc(rotated_at + 300)

    source.set(rotated_at + 299)
    assert effective_identity_status(outgoing) == "overlap"
    source.set(rotated_at + 300)
    assert effective_identity_status(outgoing) == "retired"


def test_an_api_key_is_minted_and_revoked_at_the_injected_instant(
    db_session, source: InjectedTime
):
    minted_at = source.now()
    _, key = mint_api_key(db_session, name="injected", scope="read")
    source.set(minted_at + 60)
    revoke_api_key(db_session, key_id=key.id)

    db_session.expire_all()
    stored = db_session.get(ApiKey, key.id)
    assert (_utc(stored.created_at), _utc(stored.revoked_at)) == (
        _utc_instant(minted_at),
        _utc_instant(minted_at + 60),
    )


def _utc(value: datetime) -> datetime:
    """A stored time as the UTC instant it denotes: SQLite returns it naive."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _utc_instant(instant: int) -> datetime:
    return datetime.fromtimestamp(instant, timezone.utc)
