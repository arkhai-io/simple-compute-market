"""Bare metal's side of the compute family's delivery path.

The path owns the delivery order; bare metal contributes what only it knows:
whether a deal's settlement is verified, its whole-machine claim, its exact
fulfillment request (the materialization over the scheduled resource), the
ready evidence of an active host, and its continuation after availability: the
delivered result and receipt it records, and, for an Alkahest deal, whether its
evidence publication is acknowledged. Its progress row is
``bare_metal_fulfillment_lifecycle``, read and written by
``BareMetalDeliveryProgress``. Bare metal places no acceptance-time hold. See
openspec/specs/compute-delivery/spec.md and
openspec/specs/physical-provisioning/spec.md.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from typing import Any

from arkhai_bare_metal import BareMetalMaterialization, BareMetalReceipt, BareMetalResult
from compute_delivery import (
    AcceptedDeal,
    AcceptedHold,
    AgreementWindow,
    ComputeDeliveryPath,
    ContinuationState,
    DeliveryStep,
    RecordedProgress,
    ReserveClaim,
)
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentStatusResponse,
    LeaseView,
)
from core_storefront.domain_registry import StorefrontDomainBindingError
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_capacity_publication import CapacityEffects
from market_core import VersionedEnvelope
from market_core.schemas import Agreement
from market_deal_lifecycle.adapters import PaymentBinding, PaymentSelector
from market_deal_lifecycle.delivery import ReadyEvidenceRef
from market_identity import canonical_json

from .access_delivery import active_access_delivery, ssh_endpoint
from .claims import ClaimAttributesMissing, whole_machine_claim
from .listing_binding import bare_metal_listing_binding
from .settlement_evidence import EvidencePayload

logger = logging.getLogger(__name__)

#: The ready evidence a bare-metal delivery is billed and disclosed on: the
#: delivered SSH endpoint and tenant account, never a credential.
READY_EVIDENCE_SCHEMA = "bare_metal.ssh-access.v1"
#: The lifecycle state recording that fulfillment is about to begin and its
#: identity is not yet known.
DISPATCH_STATE = "dispatch"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BareMetalDeliveryRefused(ValueError):
    """The deal's own records refuse a delivery step: what was sold cannot be delivered as asked."""


class BareMetalDeliveryProgress:
    """The delivery path's progress port over ``bare_metal_fulfillment_lifecycle``.

    The step is read from what the row records: an activation instant, then a
    fulfillment identity, then a recorded dispatch, then a reservation. Every
    write is in the transaction the path hands it, so a record commits with the
    admission that permits it; each identity is written once, and a different
    value is refused.
    """

    def load(self, conn: sqlite3.Connection, negotiation_id: str) -> RecordedProgress | None:
        row = conn.execute(
            "SELECT capacity_reservation_id, fulfillment_id, activated_at_utc, state "
            "FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        if row is None:
            return None
        reservation, fulfillment, activated_at, state = row
        if activated_at is not None:
            step = DeliveryStep.ACTIVATED
        elif fulfillment is not None:
            step = DeliveryStep.FULFILLMENT
        elif state == DISPATCH_STATE:
            step = DeliveryStep.DISPATCH
        elif reservation is not None:
            step = DeliveryStep.COMMIT
        else:
            step = DeliveryStep.RESERVE
        return RecordedProgress(
            step=step.value, capacity_reservation_id=reservation, fulfillment_id=fulfillment,
            activated_at=activated_at,
        )

    def create(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        """Start the deal's delivery, ordered against refund intent.

        The row is the delivery-start marker a seller refund reads in its own
        transaction, so it is inserted only while the settlement record is
        still verified: a refund recorded first stops delivery here.
        """
        record = conn.execute(
            "SELECT status, settlement_ref FROM bare_metal_settlement_records WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        if record is None or record[0] != "settlement_verified" or not record[1]:
            raise BareMetalDeliveryRefused(
                "the settlement was refunded or never verified; delivery cannot start"
            )
        binding = conn.execute(
            "SELECT b.site_id, b.physical_resource_id FROM negotiation_threads t "
            "JOIN storefront_listing_bindings b ON b.listing_id = t.our_listing_id "
            "WHERE t.negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        if binding is None or not binding[0] or not binding[1]:
            raise BareMetalDeliveryRefused("accepted bare-metal agreement has no trusted resource binding")
        conn.execute(
            "INSERT OR IGNORE INTO bare_metal_fulfillment_lifecycle("
            "negotiation_id, settlement_ref, site_id, physical_resource_id, state"
            ") VALUES (?, ?, ?, ?, 'planning')",
            (negotiation_id, record[1], binding[0], binding[1]),
        )

    def _once(
        self, conn: sqlite3.Connection, negotiation_id: str, column: str, value: Any, state: str,
    ) -> None:
        current = conn.execute(
            f"SELECT {column} FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        if current is None:
            raise BareMetalDeliveryRefused("bare-metal fulfillment lifecycle is missing")
        if current[0] == value:
            return
        if current[0] is not None:
            raise BareMetalDeliveryRefused(f"bare-metal delivery {column} cannot change once recorded")
        conn.execute(
            f"UPDATE bare_metal_fulfillment_lifecycle SET {column}=?, state=?, "
            "updated_at=STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE negotiation_id=?",
            (value, state, negotiation_id),
        )

    def record_reservation(
        self, conn: sqlite3.Connection, negotiation_id: str, capacity_reservation_id: str,
    ) -> None:
        self._once(conn, negotiation_id, "capacity_reservation_id", capacity_reservation_id, "reserved")

    def record_dispatch(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        conn.execute(
            "UPDATE bare_metal_fulfillment_lifecycle SET state=?, "
            "updated_at=STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now') "
            "WHERE negotiation_id=? AND fulfillment_id IS NULL",
            (DISPATCH_STATE, negotiation_id),
        )

    def record_fulfillment(
        self, conn: sqlite3.Connection, negotiation_id: str, fulfillment_id: str,
    ) -> None:
        # Provisioning's own state replaces this one as the status is read.
        self._once(conn, negotiation_id, "fulfillment_id", fulfillment_id, "dispatch_pending")

    def record_activation(
        self, conn: sqlite3.Connection, negotiation_id: str, activated_at: int,
    ) -> None:
        current = conn.execute(
            "SELECT state FROM bare_metal_fulfillment_lifecycle WHERE negotiation_id=?",
            (negotiation_id,),
        ).fetchone()
        if current is None:
            raise BareMetalDeliveryRefused("bare-metal fulfillment lifecycle is missing")
        # Activation is the site's lease fact; provisioning's state stays as read.
        self._once(conn, negotiation_id, "activated_at_utc", activated_at, current[0])

    def release_claim(self, conn: sqlite3.Connection, negotiation_id: str) -> None:
        """Nothing to release: bare metal's workers serialize a deal by its lock, not a claim."""


class BareMetalSiteFulfillment:
    """Provisioning's fulfillment surface at the deal's site.

    Bare metal's fulfillment client routes every verb by the reservation's
    durable site binding, recorded when the site admitted the reservation at
    the binding's site, so the site the path names is already the one it
    reaches.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, site_id: str,
    ) -> FulfillmentAcceptanceResponse:
        return await self._client.begin_fulfillment(body)

    async def get_fulfillment_status(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> FulfillmentStatusResponse:
        return await self._client.get_fulfillment_status(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id,
        )

    async def get_fulfillment_result(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> VersionedEnvelope[Any]:
        return await self._client.get_fulfillment_result(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id,
        )

    async def get_lease(self, capacity_reservation_id: str, *, site_id: str) -> LeaseView:
        return await self._client.get_lease(capacity_reservation_id)


class BareMetalDeliveryDomain:
    """What only bare metal knows about a deal's delivery, read from its own records.

    ``lifecycle`` is the storefront's ``BareMetalLifecycle``: its payment-adapter
    table resolves the deal's mechanism, and it derives the commitment its
    servicing record was registered under.
    """

    def __init__(self, db: Any, *, lifecycle: Any, fulfillment: Any) -> None:
        self._db = db
        self._lifecycle = lifecycle
        self._fulfillment = fulfillment

    async def _settled(self, negotiation_id: str) -> tuple[dict[str, Any], EvidencePayload] | None:
        """The deal's settlement record and evidence, while delivery may act on them.

        A delivery that has not started needs currently verified evidence; one
        that has started is still carried, ended and torn down under the
        evidence it began with, as a seller refund leaves it.
        """
        thread = await self._db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        record = await self._db.load_bare_metal_settlement_record(negotiation_id=negotiation_id)
        if thread is None or record is None or thread.get("terminal_state") != "success":
            return None
        started = await self._db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        admitted = {"settlement_verified"} | ({"refunding", "refunded"} if started else set())
        if record["status"] not in admitted or not record["settlement_ref"]:
            return None
        agreement = Agreement.model_validate_json(thread["agreement_bytes"])
        if (
            agreement.settlement is None
            or record["mechanism"] != agreement.settlement.settlement_schema
            or record["agreement_sha256"] != _sha256(thread["agreement_bytes"])
        ):
            return None
        payload = EvidencePayload.model_validate(record["evidence"])
        if payload.delivery is None:
            return None
        return record, payload

    async def accepted_deal(self, negotiation_id: str) -> AcceptedDeal | None:
        """The deal's verified settlement, as delivery acts on it.

        The caller revalidates that settlement against its authority before
        delivery runs; this reads only what was recorded.
        """
        settled = await self._settled(negotiation_id)
        if settled is None:
            return None
        record, payload = settled
        commitment = await asyncio.to_thread(self._lifecycle.commitment_ref, negotiation_id)
        if record["mechanism"] == ARKHAI_PAYMENTS_MECHANISM and commitment != record["settlement_ref"]:
            return None
        thread = await self._db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        binding = await bare_metal_listing_binding(self._db, str(thread["our_listing_id"]))
        if binding is None or binding.site_id != payload.delivery.site_id:
            return None
        payments = self._lifecycle.seller.payments
        payment = payments.resolve(
            PaymentBinding(negotiation_id, PaymentSelector(str(record["mechanism"])))
        )
        return AcceptedDeal(commitment_ref=commitment, binding=binding, payment=payment)

    async def _context(self, negotiation_id: str) -> dict[str, Any]:
        context = await self._db.load_bare_metal_fulfillment_context(negotiation_id=negotiation_id)
        if context is None:
            raise BareMetalDeliveryRefused("accepted bare-metal agreement has no trusted resource binding")
        return context

    async def reserve_claim(self, negotiation_id: str) -> ReserveClaim:
        """One whole unit of the listing's Physical Resource, under the deal's escrow.

        The escrow reference stays beside the placement key the path adds, so a
        reservation the site holds under the escrow alone is adopted under the
        key.
        """
        context = await self._context(negotiation_id)
        row = await self._db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        if row is None:
            raise BareMetalDeliveryRefused("bare-metal delivery has not started")
        try:
            claim = whole_machine_claim(context)
        except ClaimAttributesMissing as exc:
            raise BareMetalDeliveryRefused(str(exc)) from exc
        claim["resource_id"] = str(context["physical_resource_id"])
        return ReserveClaim(claim=claim, deal_ref={"escrow_uid": str(row["settlement_ref"])})

    async def accepted_hold(self, negotiation_id: str) -> AcceptedHold | None:
        return None

    async def fulfillment_request(
        self, negotiation_id: str, *, capacity_reservation_id: str, window: AgreementWindow,
    ) -> FulfillmentRequestBody:
        """The deal's one request: its materialization over the scheduled resource.

        Scheduling binds the reservation to the Physical Resource the terms
        sold and is idempotent by reservation; a saved materialization is the
        request provisioning accepted, so a retry repeats it exactly.
        """
        context = await self._context(negotiation_id)
        terms = await self._db.load_bare_metal_terms(negotiation_id=negotiation_id)
        row = await self._db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        if terms is None or row is None:
            raise BareMetalDeliveryRefused("accepted bare-metal terms are missing")
        settlement_resource_id = row.get("settlement_resource_id") or await self._schedule(
            negotiation_id, context, terms, capacity_reservation_id,
        )
        expected = BareMetalMaterialization(
            escrow_uid=str(row["settlement_ref"]),
            host_id=terms.host_id,
            physical_host_id=terms.physical_host_id,
            lease_start_utc=datetime.fromtimestamp(window.start, timezone.utc),
            lease_end_utc=datetime.fromtimestamp(window.end, timezone.utc),
            access_method=terms.access_method,
            ssh_public_key=terms.ssh_public_key,
            access_ref=terms.access_ref,
            listing_ref=terms.listing_ref,
            settlement_ref={"settlement_resource_id": settlement_resource_id},
        )
        saved = await self._db.load_bare_metal_materialization(negotiation_id=negotiation_id)
        if saved is None:
            await self._db.save_bare_metal_materialization(
                negotiation_id=negotiation_id, materialization=expected,
            )
            saved = expected
        elif saved != expected:
            raise BareMetalDeliveryRefused("recorded materialization conflicts with accepted bare-metal terms")
        return FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market="bare_metal",
            fulfillment_request=VersionedEnvelope(
                kind="bare_metal.v2",
                schema_version=1,
                payload=saved.model_dump(mode="json", exclude_none=True),
            ),
        )

    async def _schedule(
        self, negotiation_id: str, context: dict[str, Any], terms: Any, reservation_id: str,
    ) -> str:
        scheduled = await self._fulfillment.schedule_resource(
            FulfillmentScheduleRequest(
                capacity_reservation_id=reservation_id,
                market="bare_metal",
                requirements={"resource_kind": "compute.bare-metal"},
                resource_id=str(context["physical_resource_id"]),
            )
        )
        if (
            scheduled.resource_kind != "compute.bare-metal"
            or scheduled.provider != "bare_metal.ansible"
            or (context.get("pool_id") is not None and scheduled.pool_id != context["pool_id"])
        ):
            raise BareMetalDeliveryRefused("selected bare-metal resource resolved to an unexpected executor")
        # The scheduled resource's own identity: the host its declaration names,
        # and the machine among its top-level attributes. A resource naming no
        # host, or another host or machine, is not the one the terms sold.
        if (
            scheduled.host_id is None
            or scheduled.host_id != terms.host_id
            or scheduled.attributes.get("physical_host_id") != terms.physical_host_id
        ):
            raise BareMetalDeliveryRefused("scheduled resource conflicts with accepted bare-metal terms")
        await self._db.record_bare_metal_settlement_resource(
            negotiation_id=negotiation_id,
            settlement_resource_id=scheduled.settlement_resource_id,
        )
        return str(scheduled.settlement_resource_id)

    async def _delivered(
        self, negotiation_id: str, result: VersionedEnvelope[Any],
    ) -> tuple[Any, Any] | None:
        """The access an active result delivers for this deal's recorded fulfillment."""
        row = await self._db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id) or {}
        payload = result.payload if isinstance(result.payload, dict) else {}
        if (
            payload.get("fulfillment_id") != row.get("fulfillment_id")
            or payload.get("capacity_reservation_id") != row.get("capacity_reservation_id")
        ):
            return None
        try:
            delivery = active_access_delivery(result)
            return delivery, ssh_endpoint(delivery)
        except ValueError:
            return None

    async def ready_evidence(
        self, negotiation_id: str, result: VersionedEnvelope[Any],
    ) -> ReadyEvidenceRef | None:
        delivered = await self._delivered(negotiation_id, result)
        if delivered is None:
            return None
        delivery, endpoint = delivered
        fulfillment_id = str(result.payload["fulfillment_id"])
        digest = _sha256(canonical_json({
            "fulfillment_id": fulfillment_id,
            "capacity_reservation_id": result.payload["capacity_reservation_id"],
            "protocol": endpoint.protocol,
            "host": endpoint.host,
            "port": endpoint.port,
            "user": endpoint.user,
            "ready_at": delivery.ready_at.isoformat(),
        }))
        return ReadyEvidenceRef(schema_id=READY_EVIDENCE_SCHEMA, resource_ref=fulfillment_id, digest=digest)

    async def continuation(self, negotiation_id: str) -> ContinuationState:
        """Record the delivered result and receipt, then report the mechanism's step.

        The result and receipt are written once, from provisioning's live
        result; the endpoint itself is never stored, since ``access`` serves it
        live. An Alkahest deal's step is publishing its lease-ready evidence,
        which the settlement worker owns and runs once delivery is available;
        it is acknowledged once settlement records the obligation's
        fulfillment. A payment deal has no further step. A failure leaves the
        continuation pending for the next drive, never the deal failed.
        """
        try:
            await self._record_delivery(negotiation_id)
        except Exception as exc:
            logger.warning(
                "[DELIVERY] %s is available; recording its result did not complete (%s) "
                "and is retried on the next drive", negotiation_id, exc,
            )
            return ContinuationState.PENDING
        record = await self._db.load_bare_metal_settlement_record(negotiation_id=negotiation_id)
        if record is None or record["mechanism"] != ALKAHEST_MECHANISM_ID:
            return ContinuationState.ACKNOWLEDGED
        status = await self._lifecycle.runtime.settlement_runtime.get_status(negotiation_id)
        published = any(
            obligation.mechanism_ref == record["settlement_ref"]
            and obligation.obligation.get("mechanism") == ALKAHEST_MECHANISM_ID
            and obligation.fulfillment_ref
            for obligation in status.obligations
        )
        return ContinuationState.ACKNOWLEDGED if published else ContinuationState.PENDING

    async def _record_delivery(self, negotiation_id: str) -> None:
        if (
            await self._db.load_bare_metal_result(negotiation_id=negotiation_id) is not None
            and await self._db.load_bare_metal_receipt(negotiation_id=negotiation_id) is not None
        ):
            return
        row = await self._db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        materialization = await self._db.load_bare_metal_materialization(negotiation_id=negotiation_id)
        if row is None or materialization is None:
            raise RuntimeError("an available bare-metal delivery has no materialization")
        result = await self._fulfillment.get_fulfillment_result(
            str(row["fulfillment_id"]), capacity_reservation_id=str(row["capacity_reservation_id"]),
        )
        delivered = await self._delivered(negotiation_id, result)
        if delivered is None:
            raise RuntimeError("provisioning no longer reports the delivered access")
        delivery, endpoint = delivered
        result_record = BareMetalResult(
            access_method=materialization.access_method,
            ssh_user=str(endpoint.user),
            ready_at=delivery.ready_at,
            lease_end_utc=materialization.lease_end_utc,
        )
        try:
            await self._db.save_bare_metal_result(negotiation_id=negotiation_id, result=result_record)
        except StorefrontDomainBindingError:
            # Written once: a later read reporting another delivery leaves the
            # recorded result standing.
            recorded = await self._db.load_bare_metal_result(negotiation_id=negotiation_id)
            if recorded is None:
                raise
        await self._db.save_bare_metal_receipt(
            negotiation_id=negotiation_id,
            receipt=BareMetalReceipt(
                escrow_uid=materialization.escrow_uid,
                host_id=materialization.host_id,
                physical_host_id=materialization.physical_host_id,
                lease_start_utc=materialization.lease_start_utc,
                lease_end_utc=materialization.lease_end_utc,
                status="ready",
                access_ref={"fulfillment_id": str(row["fulfillment_id"])},
                result_ref={
                    "kind": ACCESS_DELIVERY_KIND,
                    "schema_version": ACCESS_DELIVERY_SCHEMA_VERSION,
                },
            ),
        )


def bare_metal_delivery_path(
    lifecycle: Any, *, db: Any, capacity_client: Any, fulfillment_client: Any,
) -> ComputeDeliveryPath:
    """The delivery path over bare metal's ports and the clients a caller supplies.

    ``lifecycle`` supplies end service, whose database the path's transactions
    open on, and the payment-adapter table; every capacity effect goes through
    the guarded ``CapacityEffects`` over ``capacity_client``.
    """
    return ComputeDeliveryPath(
        end=lifecycle.end,
        progress=BareMetalDeliveryProgress(),
        domain=BareMetalDeliveryDomain(db, lifecycle=lifecycle, fulfillment=fulfillment_client),
        capacity=CapacityEffects(capacity_client),
        fulfillment=BareMetalSiteFulfillment(fulfillment_client),
    )


__all__ = [
    "BareMetalDeliveryDomain",
    "BareMetalDeliveryRefused",
    "BareMetalDeliveryProgress",
    "BareMetalSiteFulfillment",
    "DISPATCH_STATE",
    "READY_EVIDENCE_SCHEMA",
    "bare_metal_delivery_path",
]
