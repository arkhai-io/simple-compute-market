"""VM's side of the compute family's delivery path.

The path owns the delivery order; VM contributes what only it knows: whether a
deal's settlement is verified, its capacity claim, its acceptance-time hold,
its exact fulfillment request, the ready evidence of an active VM, and its
continuation after availability, the selected settlement stage's step. Its
progress row is ``VmDeliveryProgress``. See
openspec/specs/compute-delivery/spec.md and
openspec/specs/vm-storefront-fulfillment/spec.md.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from compute_delivery import (
    AcceptedDeal,
    AcceptedHold,
    AgreementWindow,
    ComputeDeliveryPath,
    ContinuationState,
    DeliveryOutcome,
    HoldPlacement,
    OutcomeKind,
    ReserveClaim,
)
from compute_provisioning_client import ComputeProvisioningError
from core_storefront.stage_log import stage_event
from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentStatusResponse,
    LeaseView,
)
from market_core import SettlementEvidence, VersionedEnvelope
from market_deal_lifecycle.adapters import PaymentAdapterTable, PaymentBinding, PaymentSelector
from market_deal_lifecycle.delivery import ReadyEvidenceRef
from market_fulfillment import (
    FULFILLMENT_RESULT_KIND,
    FULFILLMENT_RESULT_SCHEMA_VERSION,
    FulfillmentResultPayload,
)
from market_identity import canonical_json

import market_storefront.container as _container
from market_storefront.payment_repository import VmDeliveryProgress
from market_storefront.services.capacity_client import (
    build_capacity_runtime,
    build_fulfillment_client,
    capacity_binding_for_listing,
)
from market_storefront.services.fulfillment_service import (
    VM_MARKET,
    fulfillment_result_connection,
)
from market_storefront.services.vm_fulfillment_planner import (
    VERIFIED_EVIDENCE_STATUSES,
    build_vm_fulfillment_plan,
)

logger = logging.getLogger(__name__)

#: The ready evidence a VM's delivery is billed and disclosed on: the
#: delivered endpoint and resources, never a credential.
READY_EVIDENCE_SCHEMA = "vm.connection-details.v1"
_CONTEXT_KIND = "vm.storefront.fulfillment-context"


def build_vm_fulfillment_context(evidence: SettlementEvidence) -> dict[str, Any]:
    """The deal's immutable fulfillment context, built from its verified evidence.

    No connectivity terms and no guest name: which relay a host dials is the
    pool's, recorded on the relay it references, and provisioning names the
    guest from the reservation and refuses a request that names one. The
    buyer's address and port come back in the fulfillment result.
    """
    plan = build_vm_fulfillment_plan(evidence=evidence)
    return {
        "kind": _CONTEXT_KIND,
        "schema_version": 1,
        "payload": {
            "negotiation_id": evidence.negotiation_id,
            "settlement_ref": evidence.settlement_ref,
            "agreement_sha256": evidence.evidence["agreement_sha256"],
            "listing_id": plan.order_id,
            "duration_seconds": plan.duration_seconds,
            "start_utc": plan.start_utc,
            "lease_end_utc": plan.lease_end_utc,
            "required_attributes": plan.required_attributes,
            "fulfillment_request": {
                "kind": "vm.fulfillment.request",
                "schema_version": 1,
                "payload": {"ssh_pubkey": plan.provision_terms.ssh_public_key},
            },
        },
    }


def _instant(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


class VmSiteFulfillment:
    """Provisioning's fulfillment surface at the deal's site.

    Provisioning accepts a fulfillment only for a reservation it has assigned
    a settlement resource, so a dispatch schedules first. Assignment is
    idempotent by reservation; when a repeated dispatch finds the reservation
    past assignment, begin's own answer, which names the fulfillment already
    accepted for it, is the one that counts.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody, *, site_id: str,
    ) -> FulfillmentAcceptanceResponse:
        try:
            await self._client.schedule_resource(
                FulfillmentScheduleRequest(
                    capacity_reservation_id=body.capacity_reservation_id, market=body.market,
                ),
                site_id=site_id,
            )
        except ComputeProvisioningError as exc:
            logger.info(
                "[DELIVERY] scheduling %s answered %s; beginning its fulfillment",
                body.capacity_reservation_id, exc,
            )
        return await self._client.begin_fulfillment(body, site_id=site_id)

    async def get_fulfillment_status(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> FulfillmentStatusResponse:
        return await self._client.get_fulfillment_status(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id, site_id=site_id,
        )

    async def get_fulfillment_result(
        self, fulfillment_id: str, *, capacity_reservation_id: str, site_id: str,
    ) -> VersionedEnvelope[Any]:
        return await self._client.get_fulfillment_result(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id, site_id=site_id,
        )

    async def get_lease(self, capacity_reservation_id: str, *, site_id: str) -> LeaseView:
        return await self._client.get_lease(capacity_reservation_id, site_id=site_id)


class VmDeliveryDomain:
    """What only VM knows about a deal's delivery, read from its own records.

    ``stages`` is the VM seller-stage table, whose selected entry runs the
    continuation; ``composition`` is the settlement composition an Alkahest
    continuation binds its claim through, or ``None`` where no stage needs it.
    """

    def __init__(
        self,
        db: Any,
        *,
        stages: Mapping[str, Any],
        payments: PaymentAdapterTable | None,
        fulfillment: VmSiteFulfillment,
        composition: Any = None,
    ) -> None:
        self._db = db
        self._stages = stages
        self._payments = payments
        self._fulfillment = fulfillment
        self._composition = composition

    async def _evidence(self, negotiation_id: str) -> SettlementEvidence | None:
        evidence = await self._db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
        if evidence is None or evidence.status not in VERIFIED_EVIDENCE_STATUSES:
            return None
        return evidence

    async def accepted_deal(self, negotiation_id: str) -> AcceptedDeal | None:
        """The deal's verified settlement evidence, as delivery acts on it.

        The selected stage revalidates that evidence against its authority
        before the resume pass drives a deal, as settlement verified it before
        the first drive; this reads only what was recorded.
        """
        evidence = await self._evidence(negotiation_id)
        if evidence is None:
            return None
        try:
            build_vm_fulfillment_plan(evidence=evidence)
        except (KeyError, ValueError):
            return None
        thread_binding = await self._db.load_thread_binding(negotiation_id=negotiation_id)
        binding = await capacity_binding_for_listing(self._db, thread_binding.listing_id)
        if binding.site_id != thread_binding.site_id:
            raise RuntimeError("accepted binding site disagrees with the listing binding")
        assert evidence.settlement_ref is not None
        payment = (
            self._payments.resolve(
                PaymentBinding(negotiation_id, PaymentSelector(evidence.mechanism))
            )
            if self._payments is not None
            else None
        )
        return AcceptedDeal(commitment_ref=evidence.settlement_ref, binding=binding, payment=payment)

    async def reserve_claim(self, negotiation_id: str) -> ReserveClaim:
        evidence = await self._evidence(negotiation_id)
        if evidence is None:
            raise ValueError("VM delivery requires verified settlement evidence")
        plan = build_vm_fulfillment_plan(evidence=evidence)
        thread_binding = await self._db.load_thread_binding(negotiation_id=negotiation_id)
        claim = dict(plan.required_attributes)
        claim["offering_mode"] = thread_binding.binding.offering_mode
        return ReserveClaim(
            claim=claim,
            deal_ref={"listing_id": plan.order_id, "negotiation_id": negotiation_id},
        )

    async def accepted_hold(self, negotiation_id: str) -> AcceptedHold | None:
        hold = await self._db.load_capacity_hold(negotiation_id=negotiation_id)
        if not hold or not hold.get("capacity_reservation_id"):
            return None
        payload = hold.get("payload") or {}
        recorded = payload.get("placement")
        placement = (
            HoldPlacement(
                claim=dict(recorded["claim"]),
                deal_ref=dict(recorded.get("deal_ref") or {}),
                ttl_seconds=recorded.get("ttl_seconds"),
                lease_start_utc=recorded.get("lease_start_utc"),
                lease_duration_seconds=recorded.get("lease_duration_seconds"),
            )
            if isinstance(recorded, Mapping)
            else None
        )
        return AcceptedHold(
            capacity_reservation_id=str(hold["capacity_reservation_id"]),
            placement=placement,
            expires_at=_instant(payload.get("hold_expires_at") or hold.get("expires_at")),
        )

    async def fulfillment_request(
        self, negotiation_id: str, *, capacity_reservation_id: str, window: AgreementWindow,
    ) -> FulfillmentRequestBody:
        """The deal's one request, from its stored context or its verified evidence.

        A context stored by an earlier attempt is the request provisioning
        accepted, so it is reused verbatim once it is shown to describe this
        deal's evidence; otherwise the context is built from the evidence and
        stored before it is sent.
        """
        evidence = await self._evidence(negotiation_id)
        if evidence is None:
            raise ValueError("VM delivery requires verified settlement evidence")
        built = build_vm_fulfillment_context(evidence)
        row = await self._db.load_vm_delivery(negotiation_id=negotiation_id) or {}
        stored = row.get("fulfillment_context")
        if stored:
            context = json.loads(stored)
            payload = context.get("payload") if isinstance(context, Mapping) else None
            if (
                not isinstance(payload, Mapping)
                or context.get("kind") != _CONTEXT_KIND
                or any(
                    payload.get(key) != built["payload"][key]
                    for key in ("negotiation_id", "settlement_ref", "agreement_sha256", "listing_id",
                                "start_utc", "duration_seconds")
                )
                or (payload.get("fulfillment_request") or {}).get("payload", {}).get("ssh_pubkey")
                != built["payload"]["fulfillment_request"]["payload"]["ssh_pubkey"]
            ):
                raise ValueError("stored fulfillment context differs from verified evidence")
        else:
            binding = await self._db.load_thread_binding(negotiation_id=negotiation_id)
            context = self._db.bind_fulfillment_context(built, thread_binding=binding)
            await self._db.update_vm_delivery(
                negotiation_id=negotiation_id,
                fulfillment_context=json.dumps(context, sort_keys=True, separators=(",", ":")),
            )
            payload = context["payload"]
        return FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market=VM_MARKET,
            fulfillment_request=VersionedEnvelope.model_validate(payload["fulfillment_request"]),
        )

    async def ready_evidence(
        self, negotiation_id: str, result: VersionedEnvelope[Any],
    ) -> ReadyEvidenceRef | None:
        connection = await self._connection(negotiation_id, result)
        if connection is None:
            return None
        digest = hashlib.sha256(canonical_json(connection)).hexdigest()
        row = await self._db.load_vm_delivery(negotiation_id=negotiation_id) or {}
        return ReadyEvidenceRef(
            schema_id=READY_EVIDENCE_SCHEMA, resource_ref=str(row["fulfillment_id"]), digest=digest,
        )

    async def _connection(
        self, negotiation_id: str, result: VersionedEnvelope[Any],
    ) -> dict[str, Any] | None:
        """The connection details an active result delivers for this deal, or ``None``.

        Only the endpoint, readiness and resource identities: the credentials
        a delivery carries are never part of them.
        """
        if (
            result.kind != FULFILLMENT_RESULT_KIND
            or result.schema_version != FULFILLMENT_RESULT_SCHEMA_VERSION
        ):
            return None
        row = await self._db.load_vm_delivery(negotiation_id=negotiation_id) or {}
        try:
            payload = FulfillmentResultPayload.model_validate(result.payload)
            connection = fulfillment_result_connection(result)
        except (RuntimeError, TypeError, ValueError):
            return None
        if (
            payload.state != "active"
            or payload.fulfillment_id != row.get("fulfillment_id")
            or payload.capacity_reservation_id != row.get("capacity_reservation_id")
        ):
            return None
        connection.pop("authentication", None)
        return connection

    async def continuation(self, negotiation_id: str) -> ContinuationState:
        """Run the selected stage's step after availability, and record the delivery.

        The stage's step is its own: an Alkahest stage publishes the
        fulfillment evidence and binds its claim, a payment stage has nothing
        to publish. The deal's connection details and the listing's fulfilled
        resource are recorded once that step is acknowledged. A failure leaves
        the continuation pending for the next drive, never the deal failed.
        """
        evidence = await self._evidence(negotiation_id)
        row = await self._db.load_vm_delivery(negotiation_id=negotiation_id)
        if evidence is None or row is None:
            return ContinuationState.PENDING
        binding = await self._db.load_thread_binding(negotiation_id=negotiation_id)
        result = await self._fulfillment.get_fulfillment_result(
            str(row["fulfillment_id"]),
            capacity_reservation_id=str(row["capacity_reservation_id"]),
            site_id=binding.site_id,
        )
        connection = await self._connection(negotiation_id, result)
        if connection is None:
            return ContinuationState.PENDING
        connection_json = json.dumps(connection, sort_keys=True)
        stage = self._stages[evidence.mechanism]
        try:
            fulfillment_uid = await stage.continue_delivery(
                evidence=evidence, db=self._db, delivery=row, connection_json=connection_json,
                composition=self._composition,
            )
        except Exception as exc:
            logger.warning(
                "[DELIVERY] %s is available; its %s continuation did not complete (%s) "
                "and is retried on the next drive",
                negotiation_id, evidence.mechanism, exc,
            )
            return ContinuationState.PENDING
        await self._db.update_vm_delivery(
            negotiation_id=negotiation_id,
            fulfillment_uid=str(fulfillment_uid),
            connection_details=connection_json,
        )
        listing_id = build_vm_fulfillment_plan(evidence=evidence).order_id
        try:
            await self._db.update_listing(listing_id=listing_id, fulfillment_resource=connection_json)
        except Exception:
            logger.exception("[DELIVERY] listing %s keeps its earlier fulfilled resource", listing_id)
        return ContinuationState.ACKNOWLEDGED


class _BuiltOnUse:
    """A storefront client built from the runtime only when first used.

    The site and provisioning clients need the storefront's configured sites;
    a drive that stops before any site call, and an access read refused
    before its fetch, use neither.
    """

    def __init__(self, build: Callable[[], Any]) -> None:
        self._build = build
        self._built: Any = None

    def __getattr__(self, name: str) -> Any:
        if self._built is None:
            self._built = self._build()
        return getattr(self._built, name)


def vm_delivery_path(
    db: Any,
    *,
    capacity: Any = None,
    fulfillment: Any = None,
    composition: Any = None,
) -> ComputeDeliveryPath:
    """The delivery path over VM's ports, composed from the storefront's runtime.

    ``capacity`` is the guarded capacity effects and ``fulfillment`` the
    per-site fulfillment client; the fulfillment client defaults to the deal
    lifecycle's, and each is otherwise built from the storefront's runtime.
    ``composition`` is the settlement composition, by default the one the
    storefront resolved: its deal lifecycle supplies end service and the
    payment-adapter table, and its stages the continuation.
    """
    composition = composition if composition is not None else _container.resolved_settlement_composition
    lifecycle = getattr(composition, "lifecycle", None)
    if lifecycle is None:
        raise RuntimeError("VM delivery requires the storefront's deal lifecycle")
    if capacity is None:
        capacity = _BuiltOnUse(lambda: build_capacity_runtime(lambda: db).effects())
    if fulfillment is None:
        fulfillment = lifecycle.fulfillment or _BuiltOnUse(
            lambda: build_fulfillment_client(build_capacity_runtime(lambda: db).client())
        )
    site_fulfillment = VmSiteFulfillment(fulfillment)
    domain = VmDeliveryDomain(
        db,
        stages=composition.seller_stages,
        payments=lifecycle.seller.payments,
        fulfillment=site_fulfillment,
        composition=composition,
    )
    return ComputeDeliveryPath(
        end=lifecycle.end,
        progress=VmDeliveryProgress(),
        domain=domain,
        capacity=capacity,
        fulfillment=site_fulfillment,
    )


async def read_vm_credentials(
    db: Any, negotiation_id: str, *, composition: Any = None,
) -> dict[str, Any] | None:
    """The deal's tenant credentials, read live through the path's access check.

    The credentials come from provisioning's fulfillment result, fetched only
    while the deal is available, started and admitted, and discarded if an
    end is admitted during the fetch; nothing stores them. ``None`` means the
    delivery carries no tenant credential. Raises the path's ``AccessRefused``
    when the read is refused.
    """
    composition = composition if composition is not None else _container.resolved_settlement_composition
    lifecycle = getattr(composition, "lifecycle", None)
    if lifecycle is None:
        raise RuntimeError("VM delivery requires the storefront's deal lifecycle")
    client = lifecycle.fulfillment or _BuiltOnUse(
        lambda: build_fulfillment_client(build_capacity_runtime(lambda: db).client())
    )
    path = vm_delivery_path(db, fulfillment=client, composition=composition)
    binding = await db.load_thread_binding(negotiation_id=negotiation_id)

    async def fetch(fulfillment_id: str, capacity_reservation_id: str) -> dict[str, Any] | None:
        result = await client.get_fulfillment_result(
            fulfillment_id, capacity_reservation_id=capacity_reservation_id, site_id=binding.site_id,
        )
        tenant = (fulfillment_result_connection(result).get("authentication") or {}).get("tenant")
        return dict(tenant) if tenant else None

    return await path.read_access(negotiation_id, fetch)


FailurePolicy = Callable[..., Awaitable[Any]]


async def drive_vm_delivery(
    path: ComputeDeliveryPath,
    db: Any,
    negotiation_id: str,
    *,
    failure_policy: FailurePolicy | None = None,
) -> DeliveryOutcome | None:
    """Drive one deal and record where it stands in VM's delivery record.

    ``None`` means the drive stopped on an exception: every step before it is
    recorded, and the next drive resumes there, so the deal is deferred, never
    failed. A converged deal is ``ready``; an ended one is ``ended``. When the
    end is the path's own record of a delivery failure, the seller's
    configured failure policy runs once, as the delivery record first becomes
    terminal. The ``provision`` stage events report the deal's reservation, a
    fulfillment's acceptance and the delivery's outcome, each once, as the
    records first show them.
    """
    before = await db.load_vm_delivery(negotiation_id=negotiation_id) or {}
    try:
        outcome = await path.drive(negotiation_id)
    except Exception:
        logger.exception("[DELIVERY] %s is deferred; the next drive resumes it", negotiation_id)
        return None
    after = await db.load_vm_delivery(negotiation_id=negotiation_id) or {}
    evidence = await db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
    listing_id = build_vm_fulfillment_plan(evidence=evidence).order_id if evidence is not None else None
    identities = {
        "listing_id": listing_id,
        "negotiation_id": negotiation_id,
        "capacity_reservation_id": outcome.capacity_reservation_id,
        "fulfillment_id": outcome.fulfillment_id,
    }
    if after.get("capacity_reservation_id") and not before.get("capacity_reservation_id"):
        stage_event("provision", "reserved", **identities)
    if after.get("fulfillment_id") and not before.get("fulfillment_id"):
        stage_event("provision", "job_submitted", **identities)
    if outcome.kind is OutcomeKind.CONVERGED:
        if await db.record_vm_delivery_outcome(negotiation_id=negotiation_id, status="ready"):
            stage_event("provision", "fulfilled", **identities, fulfillment_uid=after.get("fulfillment_uid"))
    elif outcome.kind is OutcomeKind.ENDED:
        changed = await db.record_vm_delivery_outcome(
            negotiation_id=negotiation_id, status="ended", reason=outcome.detail,
        )
        failed = (outcome.evidence_ref or "").startswith("delivery:")
        if changed and failed:
            stage_event("provision", "failed", **identities, error=outcome.detail)
        if changed and failed and failure_policy is not None:
            try:
                await failure_policy(
                    negotiation_id=negotiation_id,
                    listing_id=listing_id,
                    capacity_reservation_id=outcome.capacity_reservation_id,
                    reason=outcome.detail,
                    message=outcome.evidence_ref,
                    source="compute_delivery",
                )
            except Exception:
                logger.exception("[DELIVERY] failure policy for %s did not complete", negotiation_id)
    elif outcome.kind is OutcomeKind.REPAIR_REQUIRED:
        logger.warning(
            "[DELIVERY] %s needs repair (%s): %s [%s]",
            negotiation_id, outcome.reason.value if outcome.reason else None,
            outcome.detail, outcome.evidence_ref,
        )
    return outcome
