"""Durable selected-site fulfillment lifecycle for bare-metal agreements.

Delivery runs through the compute family's delivery path, entered only through
core's fulfillment hook: ``fulfill_bare_metal`` builds the path from the
caller's ports and the storefront's lifecycle, and ``deliver`` is how every
bare-metal caller reaches it. See openspec/specs/physical-provisioning/spec.md,
"Bare-metal delivery enters through the core fulfillment hook".
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from arkhai_bare_metal import BareMetalResult
from compute_delivery import AccessRefused, OutcomeKind
from compute_provisioning_contracts import AccessDelivery, AccessEndpoint
from core_storefront import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentLifecycle,
    StorefrontFulfillmentPorts,
    fulfill_domain,
)
from market_capacity_publication import (
    CapacityBindingError,
    CapacityEffects,
    PublicationBinding,
)
from market_core import MarketDomainContract, SettlementEvidence
from market_identity import Identity
from market_deal_servicing import PhysicalResult
from market_resource_pools_contracts.backing import CapacityNotAdmittedError
from .settlement_evidence import EvidencePayload
from .settlement_stages import SettlementRequestError

from .access_delivery import active_access_delivery, ssh_endpoint
from .delivery_ports import DISPATCH_STATE, BareMetalDeliveryRefused, bare_metal_delivery_path
from .listing_binding import bare_metal_listing_binding

if TYPE_CHECKING:
    from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

# The lifecycle state recorded once teardown has asked the site to end the lease.
TERMINATING = "terminating"
_TEARDOWN_STATES = frozenset(
    {"teardown_dispatch_pending", "tearing_down", "teardown_failed", "torn_down"}
)


class BareMetalFulfillmentError(RuntimeError):
    """A fulfillment request refused with ``status_code``.

    ``error`` is the refusal's machine-readable code, when it has one; the
    routes then answer ``{"error": error, "reason": detail}`` as the detail,
    so a client tells refusals apart by their contract rather than by
    message text.
    """

    def __init__(
        self, detail: str, *, status_code: int = 409, error: str | None = None
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.error = error


@dataclass(frozen=True)
class BareMetalFulfillmentService:
    db: SQLiteClient
    capacity_client: Any
    fulfillment_client: Any
    read_verified_evidence: Callable[..., Awaitable[SettlementEvidence]]
    lifecycle: Any
    domain: MarketDomainContract

    async def _effect(
        self,
        effect: Callable[[CapacityEffects, PublicationBinding], Awaitable[Any]],
        context: Mapping[str, Any],
    ) -> Any:
        """Run one capacity effect through the kit's guard, with the listing's binding.

        The effect acts at the binding's site, which must be the site the
        accepted deal recorded; a listing no admission authority stands behind
        is refused before any site call.
        """
        binding = await bare_metal_listing_binding(self.db, str(context["listing_id"]))
        if binding is None or binding.site_id != str(context["site_id"]):
            raise BareMetalFulfillmentError(
                "accepted bare-metal agreement disagrees with its listing binding"
            )
        try:
            return await effect(CapacityEffects(self.capacity_client), binding)
        except (CapacityNotAdmittedError, CapacityBindingError) as exc:
            raise BareMetalFulfillmentError(str(exc)) from exc

    async def _owned_context(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        context = await self.db.load_bare_metal_fulfillment_context(
            negotiation_id=negotiation_id
        )
        if context is None:
            raise BareMetalFulfillmentError(
                "accepted bare-metal agreement has no trusted resource binding",
                status_code=404,
            )
        recorded_buyer = Identity(
            scheme=context["buyer_scheme"],
            identifier=context["buyer_identifier"],
        )
        if recorded_buyer != buyer_principal:
            raise BareMetalFulfillmentError(
                "negotiation buyer mismatch",
                status_code=403,
            )
        if context["terminal_state"] != "success":
            raise BareMetalFulfillmentError("bare-metal negotiation is not accepted")
        return context

    async def _verified_evidence(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
        context: dict[str, Any],
        delivery_started: bool = False,
    ) -> tuple[SettlementEvidence, Any]:
        # A seller refund, or the mechanism collecting its settlement, may follow
        # a delivery that had already started; that delivery is still read and
        # torn down under the evidence it began with. A delivery that has not
        # started requires currently verified, currently active evidence.
        try:
            evidence = await self.read_verified_evidence(
                negotiation_id=negotiation_id,
                buyer_principal=buyer_principal,
                include_refunds=delivery_started,
                delivery_started=delivery_started,
            )
            payload = EvidencePayload.model_validate(dict(evidence.evidence))
        except (SettlementRequestError, ValueError) as exc:
            raise BareMetalFulfillmentError(str(exc)) from exc
        delivery = payload.delivery
        admitted = (
            {"settlement_verified", "refunding", "refunded"}
            if delivery_started
            else {"settlement_verified"}
        )
        if (
            evidence.negotiation_id != negotiation_id
            or evidence.status not in admitted
            or not evidence.settlement_ref
            or delivery is None
        ):
            raise BareMetalFulfillmentError(
                "bare-metal settlement is not authoritatively verified"
            )
        if (
            delivery.site_id != context["site_id"]
            or delivery.physical_resource_id != context["physical_resource_id"]
            or delivery.pool_id != context.get("pool_id")
            or delivery.terms.host_id != context["host_id"]
            or delivery.terms.physical_host_id != context["physical_host_id"]
        ):
            raise BareMetalFulfillmentError(
                "settlement evidence conflicts with the trusted resource binding"
            )
        return evidence, delivery.terms

    async def deliver(
        self, *, negotiation_id: str, buyer_principal: Identity
    ) -> StorefrontFulfillmentLifecycle:
        """Drive the deal's delivery through core's fulfillment hook.

        Every drive may take a protected step, so the settlement is first
        revalidated against its authority as currently active, through the
        accepted entry's recovery gate (openspec/specs/physical-provisioning/
        spec.md, "Bare-metal evidence is independent of escrow rows"); the hook
        receives that evidence, the storefront's clients as ports, and its
        lifecycle as the domain input.
        """
        context = await self._owned_context(
            negotiation_id=negotiation_id, buyer_principal=buyer_principal
        )
        evidence, _ = await self._verified_evidence(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            context=context,
        )
        return await fulfill_domain(
            self.domain,
            StorefrontFulfillmentContext(
                thread_binding=await self.db.load_thread_binding(negotiation_id=negotiation_id),
                settlement_evidence=evidence,
                buyer_principal=buyer_principal,
                ports=StorefrontFulfillmentPorts(
                    repository=self.db,
                    capacity_client=self.capacity_client,
                    fulfillment_client=self.fulfillment_client,
                ),
                domain_input={"lifecycle": self.lifecycle},
            ),
        )

    async def _active_delivery(
        self,
        *,
        capacity_reservation_id: str,
        fulfillment_id: str,
    ) -> tuple[AccessDelivery, AccessEndpoint]:
        result_envelope = await self.fulfillment_client.get_fulfillment_result(
            fulfillment_id,
            capacity_reservation_id=capacity_reservation_id,
        )
        try:
            delivery = active_access_delivery(result_envelope)
            return delivery, ssh_endpoint(delivery)
        except ValueError as exc:
            raise BareMetalFulfillmentError(str(exc)) from exc

    async def status(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
        drive: bool = True,
    ) -> dict[str, Any]:
        """The deal's delivery as provisioning reports it now, to its buyer.

        It refreshes the recorded fulfillment state from provisioning. Once the
        fulfillment is active and the deal not yet available, it drives the
        deal through the fulfillment hook, unless ``drive`` is false, so the
        delivery path records activation, billing start and availability before
        the answer; the path alone records them, and a deal no one reads
        reaches them through its workers. A drive the settlement gate refuses
        leaves the read answering as provisioning reports.
        """
        context = await self._owned_context(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )
        lifecycle = await self.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id
        )
        evidence, _ = await self._verified_evidence(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            context=context,
            delivery_started=lifecycle is not None,
        )
        if lifecycle is not None and (
            lifecycle["settlement_ref"] != evidence.settlement_ref
            or lifecycle["site_id"] != context["site_id"]
            or lifecycle["physical_resource_id"] != context["physical_resource_id"]
        ):
            raise BareMetalFulfillmentError(
                "physical lifecycle conflicts with verified evidence"
            )
        if lifecycle is None:
            raise BareMetalFulfillmentError(
                "bare-metal fulfillment not found",
                status_code=404,
            )
        if lifecycle["state"] == "released":
            return lifecycle
        reservation_id = lifecycle.get("capacity_reservation_id")
        fulfillment_id = lifecycle.get("fulfillment_id")
        if not reservation_id or not fulfillment_id:
            raise BareMetalFulfillmentError("bare-metal fulfillment has not begun")

        remote = await self.fulfillment_client.get_fulfillment_status(
            str(fulfillment_id),
            capacity_reservation_id=str(reservation_id),
        )
        if lifecycle["state"] in _TEARDOWN_STATES and remote.state not in _TEARDOWN_STATES:
            raise BareMetalFulfillmentError(
                "provisioning returned a conflicting teardown state"
            )
        if lifecycle["state"] == TERMINATING and remote.state not in _TEARDOWN_STATES:
            # The lease is ending; the site has not begun the teardown it
            # converges through the fulfillment yet.
            return lifecycle
        # The site releases the capacity after an authoritative teardown and says
        # so through its capacity-released callback, which alone records
        # ``released``; a torn-down fulfillment is not yet a released lease.
        lifecycle = await self.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            state=str(remote.state),
            failure_reason=remote.failure_reason or remote.failure_message,
        )
        if remote.state == "active":
            if drive and not await self.lifecycle.delivery_available(negotiation_id):
                try:
                    await self.deliver(
                        negotiation_id=negotiation_id, buyer_principal=buyer_principal
                    )
                except BareMetalFulfillmentError as exc:
                    logger.info("[DELIVERY] %s was not driven on its status read: %s",
                                negotiation_id, exc.detail)
                lifecycle = await self.db.load_bare_metal_fulfillment_lifecycle(
                    negotiation_id=negotiation_id
                )
            await self._refuse_conflicting_delivery(
                negotiation_id=negotiation_id,
                capacity_reservation_id=str(reservation_id),
                fulfillment_id=str(fulfillment_id),
            )
        return lifecycle

    async def _refuse_conflicting_delivery(
        self, *, negotiation_id: str, capacity_reservation_id: str, fulfillment_id: str
    ) -> None:
        """Refuse a read when the site reports a delivery other than the recorded result.

        The result is written once, when delivery becomes available; a later
        report of another delivery leaves it standing and is named as a
        conflict. See openspec/specs/storefront-publication/spec.md, "A
        bare-metal delivery that conflicts with its recorded result is refused".
        """
        recorded = await self.db.load_bare_metal_result(negotiation_id=negotiation_id)
        materialization = await self.db.load_bare_metal_materialization(
            negotiation_id=negotiation_id
        )
        if recorded is None or materialization is None:
            return
        delivery, endpoint = await self._active_delivery(
            capacity_reservation_id=capacity_reservation_id,
            fulfillment_id=fulfillment_id,
        )
        reported = BareMetalResult(
            access_method=materialization.access_method,
            ssh_user=str(endpoint.user),
            ready_at=delivery.ready_at,
            lease_end_utc=materialization.lease_end_utc,
        )
        if reported != recorded:
            raise BareMetalFulfillmentError(
                "the site reports a delivery other than the recorded result",
                error="delivery_conflict",
            )

    async def access(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        """Return transient SSH coordinates only to the accepted buyer.

        The coordinates are read live through the delivery path's access check:
        only while the deal is available, started and admitted, and discarded
        if an end is admitted while they are read; that check refuses an end
        with 410. The read drives nothing, so it reaches no payment authority.
        """

        lifecycle = await self.status(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            drive=False,
        )
        if lifecycle["state"] != "active":
            raise BareMetalFulfillmentError(
                "bare-metal access is unavailable outside an active lease"
            )
        path = bare_metal_delivery_path(
            self.lifecycle,
            db=self.db,
            capacity_client=self.capacity_client,
            fulfillment_client=self.fulfillment_client,
        )

        async def fetch(fulfillment_id: str, capacity_reservation_id: str) -> AccessEndpoint:
            _, endpoint = await self._active_delivery(
                capacity_reservation_id=capacity_reservation_id,
                fulfillment_id=fulfillment_id,
            )
            return endpoint

        try:
            endpoint = await path.read_access(negotiation_id, fetch)
        except AccessRefused as exc:
            raise BareMetalFulfillmentError(
                f"bare-metal access is refused: {exc.detail}",
                status_code=410 if exc.reason == "ended" else 409,
            ) from exc
        materialization = await self.db.load_bare_metal_materialization(
            negotiation_id=negotiation_id
        )
        return {
            "negotiation_id": negotiation_id,
            "method": "ssh",
            "host": endpoint.host,
            "port": endpoint.port,
            "username": endpoint.user,
            "expires_at": (
                materialization.lease_end_utc if materialization is not None else None
            ),
        }

    async def apply_end(self, negotiation_id: str, *, terminate: bool, at: int, operation_key: str, reason: str) -> PhysicalResult:
        row = await self.db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
        if row is None or row.get("state") == "released":
            return PhysicalResult(progress="released", done=True)
        if row.get("state") in _TEARDOWN_STATES | {TERMINATING}:
            return PhysicalResult(progress="tearing_down", done=True)
        reservation = row.get("capacity_reservation_id")
        if not reservation:
            return PhysicalResult(progress="released", done=True)
        context = await self.db.load_bare_metal_fulfillment_context(negotiation_id=negotiation_id)
        if not terminate:
            await self._effect(lambda effects, binding: effects.truncate_lease(
                binding, capacity_reservation_id=reservation,
                lease_end_utc=datetime.fromtimestamp(at, timezone.utc).isoformat(),
            ), context)
            return PhysicalResult(progress="end_recorded", done=True)
        # The delivery path records the dispatch before fulfillment begins, so a
        # reservation with neither a dispatch nor a fulfillment recorded has had
        # nothing dispatched against it and is released; anything dispatched is
        # adopted and ended through the lease.
        if row.get("fulfillment_id") is None and row.get("state") != DISPATCH_STATE:
            await self._effect(lambda effects, binding: effects.release(
                binding, capacity_reservation_id=reservation, failure_reason=operation_key,
            ), context)
            await self.db.update_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id, state="released")
            return PhysicalResult(progress="released", done=True)
        else:
            await self.fulfillment_client.terminate_lease(reservation, reason=reason)
        await self.db.update_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id, state=TERMINATING)
        return PhysicalResult(progress="tearing_down", done=True)

    async def end_lease(
        self,
        *,
        negotiation_id: str,
        capacity_reservation_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Record the deal's end through end service, which ends the lease at its site.

        The site converges teardown through the lease's fulfillment and releases
        the capacity once; ending a lease already ending leaves it as it is.
        """
        await self.lifecycle.local_end(negotiation_id, cause=reason)
        return await self.db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)

    async def converge_teardown(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        return await self.status(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )


async def fulfill_bare_metal(
    *,
    context: StorefrontFulfillmentContext,
) -> dict[str, Any]:
    """Drive one bare-metal deal's delivery through the compute delivery path.

    The registered hook: it builds the path from the caller's clients in
    ``ports`` and the storefront's lifecycle in ``domain_input``, so every
    delivery passes end-service admission, and refuses before any capacity or
    fulfillment call without that lifecycle. The deal's lock serializes its
    drives; its physical end, which waits while the lock is held, is driven
    once the drive has released it. The bare-metal row is returned, with the
    path's outcome, the hook's disposition of it (fulfilled, deferred or
    failed), and whether the deal is available as the public result.
    """
    lifecycle = (
        context.domain_input.get("lifecycle")
        if isinstance(context.domain_input, Mapping)
        else None
    )
    if lifecycle is None:
        raise BareMetalFulfillmentError(
            "bare-metal fulfillment requires the storefront's lifecycle"
        )
    db = context.ports.repository
    negotiation_id = context.negotiation_id
    recorded_binding = await db.load_thread_binding(negotiation_id=negotiation_id)
    if recorded_binding != context.thread_binding:
        raise BareMetalFulfillmentError(
            "fulfillment context conflicts with the durable negotiation binding"
        )
    path = bare_metal_delivery_path(
        lifecycle,
        db=db,
        capacity_client=context.ports.capacity_client,
        fulfillment_client=context.ports.fulfillment_client,
    )
    try:
        async with lifecycle.lock(negotiation_id):
            outcome = await path.drive(negotiation_id)
    except (CapacityNotAdmittedError, CapacityBindingError, BareMetalDeliveryRefused) as exc:
        raise BareMetalFulfillmentError(str(exc)) from exc
    finally:
        await lifecycle.end.drive_physical(negotiation_id)
    if outcome.kind is OutcomeKind.REPAIR_REQUIRED:
        logger.warning(
            "[DELIVERY] %s needs repair (%s): %s [%s]",
            negotiation_id, outcome.reason.value if outcome.reason else None,
            outcome.detail, outcome.evidence_ref,
        )
    row = await db.load_bare_metal_fulfillment_lifecycle(negotiation_id=negotiation_id)
    if row is None:
        raise BareMetalFulfillmentError(
            outcome.detail or "bare-metal delivery has not started"
        )
    return {
        **row,
        "domain_result": dict(row),
        "public_result": {
            "outcome": outcome.kind.value,
            "disposition": outcome.hook_disposition,
            "available": await lifecycle.delivery_available(negotiation_id),
        },
    }
