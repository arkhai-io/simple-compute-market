"""What a compute storefront supplies to the delivery path.

The path owns the order of delivery and keeps no table. Each storefront
contributes two ports, implemented over what it already has:

- ``DeliveryProgress``, over the domain's existing progress row. Every method
  receives the connection of the transaction the path opened on the
  storefront's database, the same one end service's journal lives in, so a
  progress write and the admission that permits it commit or roll back
  together. Each record is written once; a repeat of the same value is a
  no-op and a different value is refused.
- ``ComputeDeliveryDomain``, what only the domain knows: whether the deal's
  settlement is verified, its reserve claim, its accepted acceptance-time hold
  if it places one, its exact fulfillment request, its ready evidence from a
  fulfillment result, and its continuation after availability.

``SiteFulfillment`` is the provisioning family's fulfillment surface, routed to
the deal's site. A third compute domain contributes its two port
implementations and changes nothing here.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentStatusResponse,
    LeaseView,
)
from market_capacity_publication import PublicationBinding
from market_core import VersionedEnvelope
from market_deal_lifecycle.adapters import PaymentAdapter
from market_deal_lifecycle.delivery import ReadyEvidenceRef

from .window import AgreementWindow


class DeliveryStep(str, Enum):
    """How far a deal's own progress row says delivery has gone.

    Each step after ``reserve`` is entered by the record that names it, so the
    step and the recorded identities must agree: a row that disagrees with
    itself is unreadable, not a step to guess from.
    """

    #: The row exists; no reservation is recorded.
    RESERVE = "reserve"
    #: A reservation is recorded; nothing is dispatched.
    COMMIT = "commit"
    #: The dispatch is recorded; ``begin_fulfillment`` may have run.
    DISPATCH = "dispatch"
    #: The fulfillment identity is recorded.
    FULFILLMENT = "fulfillment"
    #: The site's activation instant is recorded.
    ACTIVATED = "activated"


@dataclass(frozen=True)
class RecordedProgress:
    """A domain's progress row, as its port reads it.

    ``step`` is the port's rendering of its own row in the path's vocabulary;
    a value the path does not know is passed through, never mapped to a
    neighbour, so the path can refuse it.
    """

    step: str
    capacity_reservation_id: str | None = None
    fulfillment_id: str | None = None
    #: The instant the site returned when it activated the lease, in seconds.
    activated_at: int | None = None


class DeliveryProgress(Protocol):
    def load(self, conn: sqlite3.Connection, negotiation_id: str) -> RecordedProgress | None:
        """The deal's progress row, or ``None`` when delivery has not started."""
        ...

    def create(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        """Create the row, at step ``reserve``; called under admission for ``reserve``."""
        ...

    def record_reservation(
        self, conn: sqlite3.Connection, negotiation_id: str, capacity_reservation_id: str,
    ) -> None: ...

    def record_dispatch(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        """Record that fulfillment is about to begin; called before ``begin_fulfillment``."""
        ...

    def record_fulfillment(
        self, conn: sqlite3.Connection, negotiation_id: str, fulfillment_id: str,
    ) -> None: ...

    def record_activation(
        self, conn: sqlite3.Connection, negotiation_id: str, activated_at: int,
    ) -> None: ...

    def release_claim(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        """Release the domain worker's convergence claim on a deal that now waits."""
        ...


@dataclass(frozen=True)
class AcceptedDeal:
    """The domain's verified settlement of the deal, and what acts on it.

    ``binding`` is the listing's durable capacity binding, which selects the
    site every capacity effect and fulfillment call goes to. ``payment`` is the
    adapter the storefront's payment-adapter table resolves for the deal's
    selected mechanism; ``None`` means the mechanism has none, which never
    implies permission.
    """

    commitment_ref: str
    binding: PublicationBinding
    payment: PaymentAdapter | None


@dataclass(frozen=True)
class ReserveClaim:
    """The capacity claim a reservation for the deal is placed with.

    ``deal_ref`` carries the domain's own correlation, such as an escrow
    reference; the path adds the negotiation and the placement key.
    """

    claim: Mapping[str, Any]
    deal_ref: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HoldPlacement:
    """The exact reserve an acceptance-time hold was placed with, under its key."""

    claim: Mapping[str, Any]
    deal_ref: Mapping[str, Any] = field(default_factory=dict)
    ttl_seconds: float | None = None
    lease_start_utc: str | None = None
    lease_duration_seconds: int | None = None


@dataclass(frozen=True)
class AcceptedHold:
    """A reservation the domain placed at acceptance, which delivery adopts.

    A hold placed under ``<negotiation_id>:hold`` carries its ``placement``, so
    a replay of it reports whether it lapsed; one placed with no key carries
    only its recorded expiry.
    """

    capacity_reservation_id: str
    placement: HoldPlacement | None = None
    expires_at: int | None = None


class ContinuationState(str, Enum):
    #: The domain has nothing to do after availability.
    NONE = "none"
    ACKNOWLEDGED = "acknowledged"
    #: Not yet acknowledged; the next drive asks again.
    PENDING = "pending"


class ComputeDeliveryDomain(Protocol):
    async def accepted_deal(self, negotiation_id: str) -> AcceptedDeal | None:
        """The deal's verified settlement, or ``None`` when there is none."""
        ...

    async def reserve_claim(self, negotiation_id: str) -> ReserveClaim: ...

    async def accepted_hold(self, negotiation_id: str) -> AcceptedHold | None:
        """The deal's acceptance-time hold; ``None`` for a domain that places none."""
        ...

    async def fulfillment_request(
        self, negotiation_id: str, *, capacity_reservation_id: str, window: AgreementWindow,
    ) -> FulfillmentRequestBody:
        """The exact request for the reservation; a retry must build the same one."""
        ...

    async def ready_evidence(
        self, negotiation_id: str, result: VersionedEnvelope[Any],
    ) -> ReadyEvidenceRef | None:
        """Ready evidence from an active fulfillment's result, or ``None`` if it shows none.

        Its digest covers only what stays the same across reads of one
        fulfillment, since billing start compares the evidence on every retry.
        """
        ...

    async def continuation(self, negotiation_id: str) -> ContinuationState:
        """Run or resume the domain's step after availability, such as publishing evidence."""
        ...


class SiteFulfillment(Protocol):
    """The provisioning family's fulfillment and lease reads, at the deal's site."""

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, site_id: str,
    ) -> FulfillmentAcceptanceResponse: ...

    async def get_fulfillment_status(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> FulfillmentStatusResponse: ...

    async def get_fulfillment_result(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> VersionedEnvelope[Any]: ...

    async def get_lease(self, capacity_reservation_id: str, *, site_id: str) -> LeaseView: ...
