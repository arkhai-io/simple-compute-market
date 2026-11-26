"""The storefront peer, and the capacity-released callback delivered to it.

Two consumers of the service's events deliver to the owning storefront: the
lease-end report consumer (``lease_end_reports``) and the capacity-released
consumer here. Each sends through a ``StorefrontPeer`` of its own, the
configured storefront's identity-pinned client, from a worker thread.

The capacity-released consumer delivers each ``site.capacity_released`` event,
recorded in the transaction of the release that freed the capacity, as the
signed capacity-released callback, retrying with backoff until the storefront
acknowledges it. Its one destination is the configured storefront, whichever
URL configures it, so a pending callback follows the storefront to a new URL.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx
import injected_time
from eventing import Consumer, Envelope, RetryPolicy
from market_identity import TrustedIdentitySet
from market_site.events import SITE_CAPACITY_RELEASED
from sqlalchemy.orm import Session, sessionmaker
from storefront_client import SyncStorefrontClient

from compute_provisioning_service.event_names import (
    CAPACITY_RELEASED_CONSUMER,
    CAPACITY_RELEASED_DESTINATION,
)
from compute_provisioning_service.identity import ProvisioningIdentityContext


def storefront_peer_url(settings: Any) -> str:
    """The configured storefront's base URL, without a trailing slash; empty
    when none is configured."""
    return str(getattr(settings, "storefront_url", "") or "").rstrip("/")


class StorefrontPeer:
    """The configured storefront, reached through one identity-pinned client.

    The client signs as this service and pins the storefront's responses to the
    seller principals the principal authority holds; it is rebuilt when those
    change. It is synchronous and serves one consumer, whose cycles run one at
    a time in a worker thread, so no two threads use or rebuild its client
    together. ``transport`` replaces the network for a test.
    """

    def __init__(
        self,
        url: str,
        identity: ProvisioningIdentityContext,
        principal_authority: Any,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url
        self._identity = identity
        self._principal_authority = principal_authority
        self._transport = transport
        self._client: SyncStorefrontClient | None = None
        self._expected_publishers: TrustedIdentitySet | None = None

    def client(self) -> SyncStorefrontClient:
        if not self.url:
            raise RuntimeError("storefront_url is required")
        expected_publishers = self._principal_authority.active_principals("seller")
        if self._client is None or self._expected_publishers != expected_publishers:
            self.close()
            self._client = SyncStorefrontClient(
                base_url=self.url,
                signer=self._identity.signer,
                caller_role="service",
                expected_publishers=expected_publishers,
                transport=self._transport,
            )
            self._expected_publishers = expected_publishers
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None


def capacity_release_request_id(capacity_reservation_id: str, released_at: str) -> str:
    """The callback's request identity, one per release: an uncertain
    acknowledgement is retried under it with the same body, which the
    storefront answers as the request it already took."""
    release = f"capacity_released:{capacity_reservation_id}:{released_at}"
    return "capacity-release-" + hashlib.sha256(release.encode("utf-8")).hexdigest()


class CapacityReleasedDestination:
    """Delivers a ``site.capacity_released`` event as the storefront's signed
    capacity-released callback; any failure is retried."""

    def __init__(self, peer: StorefrontPeer) -> None:
        self._peer = peer

    def deliver(self, envelope: Envelope) -> None:
        details = envelope.details
        capacity_reservation_id = str(details["capacity_reservation_id"])
        released_at = str(details["released_at"])
        self._peer.client().notify_capacity_released(
            capacity_reservation_id,
            site_id=str(details["site_id"]),
            released_at=released_at,
            request_id=capacity_release_request_id(capacity_reservation_id, released_at),
        )


def capacity_released_consumer(
    session_factory: sessionmaker[Session], peer: StorefrontPeer, *, runner: str
) -> Consumer:
    """The capacity-released consumer: each ``site.capacity_released`` event to
    the configured storefront, retried with backoff until acknowledged. With no
    storefront configured it has no destination and selects nothing."""
    destinations = (
        {CAPACITY_RELEASED_DESTINATION: CapacityReleasedDestination(peer)} if peer.url else {}
    )
    selected = tuple(destinations)

    def select(envelope: Envelope) -> tuple[str, ...]:
        return selected if envelope.kind == SITE_CAPACITY_RELEASED.name else ()

    return Consumer(
        CAPACITY_RELEASED_CONSUMER,
        session_factory=session_factory,
        destinations=destinations,
        clock=injected_time.now_datetime,
        retry=RetryPolicy(max_age=None),
        select=select,
        runner=runner,
    )


__all__ = [
    "CAPACITY_RELEASED_CONSUMER",
    "CAPACITY_RELEASED_DESTINATION",
    "CapacityReleasedDestination",
    "StorefrontPeer",
    "capacity_release_request_id",
    "capacity_released_consumer",
    "storefront_peer_url",
]
