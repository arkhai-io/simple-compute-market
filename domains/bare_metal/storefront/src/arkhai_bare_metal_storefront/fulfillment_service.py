"""Durable selected-site fulfillment lifecycle for bare-metal agreements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from arkhai_bare_metal import (
    BareMetalMaterialization,
    BareMetalReceipt,
    BareMetalResult,
)
from compute_provisioning_contracts import (
    ACCESS_DELIVERY_KIND,
    ACCESS_DELIVERY_SCHEMA_VERSION,
    AccessDelivery,
    AccessEndpoint,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
)
from core_storefront import StorefrontFulfillmentContext
from market_core import VersionedEnvelope
from market_identity import Identity

from .access_delivery import active_access_delivery, ssh_endpoint
from .claims import ClaimAttributesMissing, whole_machine_claim
from .lease_window import committed_lease_window

if TYPE_CHECKING:
    from .sqlite_client import SQLiteClient


# The lifecycle state recorded once teardown has asked the site to end the lease.
TERMINATING = "terminating"
_TEARDOWN_STATES = frozenset(
    {"teardown_dispatch_pending", "tearing_down", "teardown_failed", "torn_down"}
)


class BareMetalFulfillmentError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class BareMetalFulfillmentService:
    db: SQLiteClient
    capacity_client: Any
    fulfillment_client: Any

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

    async def _verified_escrow(
        self,
        *,
        negotiation_id: str,
        escrow_uid: str,
    ) -> None:
        escrow = await self.db.load_escrow(escrow_uid=escrow_uid)
        if (
            escrow is None
            or escrow.get("negotiation_id") != negotiation_id
            or escrow.get("status") != "settlement_verified"
        ):
            raise BareMetalFulfillmentError(
                "bare-metal settlement is not authoritatively verified"
            )

    async def _recover_reservation(
        self,
        *,
        site_id: str,
        negotiation_id: str,
        escrow_uid: str,
    ) -> dict[str, Any] | None:
        site_client = self.capacity_client.site(site_id)
        reservations = await site_client.list_reservations()
        matching = [
            reservation
            for reservation in reservations
            if reservation.get("deal_ref")
            == {
                "negotiation_id": negotiation_id,
                "escrow_uid": escrow_uid,
            }
        ]
        if len(matching) > 1:
            raise BareMetalFulfillmentError(
                "multiple capacity reservations match one bare-metal agreement"
            )
        if not matching:
            return None
        reservation = matching[0]
        reservation_id = str(reservation.get("capacity_reservation_id") or "")
        if not reservation_id:
            raise BareMetalFulfillmentError(
                "recovered capacity reservation has no identity"
            )
        self.capacity_client.reservation_sites[reservation_id] = site_id
        return {**reservation, "site": site_id}

    async def begin(
        self,
        *,
        negotiation_id: str,
        escrow_uid: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        context = await self._owned_context(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )
        await self._verified_escrow(
            negotiation_id=negotiation_id,
            escrow_uid=escrow_uid,
        )
        terms = await self.db.load_bare_metal_terms(negotiation_id=negotiation_id)
        if terms is None:
            raise BareMetalFulfillmentError("accepted bare-metal terms are missing")
        if (
            terms.host_id != context["host_id"]
            or terms.physical_host_id != context["physical_host_id"]
        ):
            raise BareMetalFulfillmentError(
                "accepted terms conflict with the trusted resource binding"
            )

        lifecycle = await self.db.ensure_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            escrow_uid=escrow_uid,
            site_id=str(context["site_id"]),
            physical_resource_id=str(context["physical_resource_id"]),
        )
        if lifecycle.get("fulfillment_id"):
            return lifecycle

        reservation_id = lifecycle.get("capacity_reservation_id")
        if reservation_id is None:
            recovered = await self._recover_reservation(
                site_id=str(context["site_id"]),
                negotiation_id=negotiation_id,
                escrow_uid=escrow_uid,
            )
            try:
                claim = whole_machine_claim(context)
            except ClaimAttributesMissing as exc:
                raise BareMetalFulfillmentError(str(exc)) from exc
            claim["resource_id"] = str(context["physical_resource_id"])
            reserved = recovered or await self.capacity_client.reserve(
                site=str(context["site_id"]),
                claim=claim,
                deal_ref={
                    "negotiation_id": negotiation_id,
                    "escrow_uid": escrow_uid,
                },
                lease_duration_seconds=terms.duration_seconds,
            )
            if reserved is None:
                raise BareMetalFulfillmentError(
                    "selected bare-metal capacity is no longer available"
                )
            if reserved.get("site") != context["site_id"]:
                raise BareMetalFulfillmentError(
                    "capacity reservation returned a conflicting site binding"
                )
            reservation_id = str(reserved.get("capacity_reservation_id") or "")
            if not reservation_id:
                raise BareMetalFulfillmentError(
                    "capacity reservation response has no identity"
                )
            lifecycle = await self.db.update_bare_metal_fulfillment_lifecycle(
                negotiation_id=negotiation_id,
                state="reserved",
                capacity_reservation_id=reservation_id,
            )

        settlement_resource_id = lifecycle.get("settlement_resource_id")
        if settlement_resource_id is None:
            scheduled = await self.fulfillment_client.schedule_resource(
                FulfillmentScheduleRequest(
                    capacity_reservation_id=str(reservation_id),
                    market="bare_metal",
                    requirements={"resource_kind": "compute.bare-metal"},
                    resource_id=str(context["physical_resource_id"]),
                )
            )
            if (
                scheduled.resource_kind != "compute.bare-metal"
                or scheduled.provider != "bare_metal.ansible"
                or (
                    context.get("pool_id") is not None
                    and scheduled.pool_id != context["pool_id"]
                )
            ):
                raise BareMetalFulfillmentError(
                    "selected bare-metal resource resolved to an unexpected executor"
                )
            publication = scheduled.attributes.get("bare_metal_publication")
            if (
                not isinstance(publication, dict)
                or publication.get("enabled") is not True
                or publication.get("host_id") != terms.host_id
                or publication.get("physical_host_id") != terms.physical_host_id
            ):
                raise BareMetalFulfillmentError(
                    "scheduled resource conflicts with accepted bare-metal terms"
                )
            settlement_resource_id = scheduled.settlement_resource_id
            lifecycle = await self.db.update_bare_metal_fulfillment_lifecycle(
                negotiation_id=negotiation_id,
                state="scheduled",
                settlement_resource_id=settlement_resource_id,
            )

        # The lease begins at commit, and its window is the one commit
        # returns. Committed until the fulfillment begins: the first commit
        # records the window and the deal's escrow, and a repeat returns the
        # window unchanged.
        lease_start = datetime.now(timezone.utc)
        committed_window = committed_lease_window(
            await self.capacity_client.commit(
                capacity_reservation_id=str(reservation_id),
                lease_start_utc=lease_start.isoformat(),
                lease_end_utc=(
                    lease_start + timedelta(seconds=terms.duration_seconds)
                ).isoformat(),
                idempotency_ref=escrow_uid,
                deal_ref={"escrow_uid": escrow_uid},
                site_id=str(context["site_id"]),
            )
        )
        materialization = await self.db.load_bare_metal_materialization(
            negotiation_id=negotiation_id
        )
        # A saved materialization keeps its window: it is the fulfillment
        # request, which a retry must repeat exactly.
        lease_start_utc, lease_end_utc = (
            (materialization.lease_start_utc, materialization.lease_end_utc)
            if materialization is not None
            else committed_window
        )
        expected_materialization = BareMetalMaterialization(
            escrow_uid=escrow_uid,
            host_id=terms.host_id,
            physical_host_id=terms.physical_host_id,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            access_method=terms.access_method,
            ssh_public_key=terms.ssh_public_key,
            access_ref=terms.access_ref,
            listing_ref=terms.listing_ref,
            settlement_ref={
                "settlement_resource_id": settlement_resource_id,
            },
        )
        if materialization is None:
            materialization = expected_materialization
            await self.db.save_bare_metal_materialization(
                negotiation_id=negotiation_id,
                materialization=materialization,
            )
        elif materialization != expected_materialization:
            raise BareMetalFulfillmentError(
                "recorded materialization conflicts with accepted bare-metal terms"
            )
        accepted = await self.fulfillment_client.begin_fulfillment(
            FulfillmentRequestBody(
                capacity_reservation_id=str(reservation_id),
                market="bare_metal",
                fulfillment_request=VersionedEnvelope(
                    kind="bare_metal.v2",
                    schema_version=1,
                    payload=materialization.model_dump(
                        mode="json",
                        exclude_none=True,
                    ),
                ),
            )
        )
        return await self.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            state=str(accepted.state),
            fulfillment_id=accepted.fulfillment_id,
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
    ) -> dict[str, Any]:
        await self._owned_context(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )
        lifecycle = await self.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id
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
            delivery, endpoint = await self._active_delivery(
                capacity_reservation_id=str(reservation_id),
                fulfillment_id=str(fulfillment_id),
            )
            materialization = await self.db.load_bare_metal_materialization(
                negotiation_id=negotiation_id
            )
            if materialization is None:
                raise BareMetalFulfillmentError(
                    "bare-metal materialization is missing during recovery"
                )
            # The stored result names no endpoint: where to connect is served
            # live by ``access`` while the lease is active.
            await self.db.save_bare_metal_result(
                negotiation_id=negotiation_id,
                result=BareMetalResult(
                    access_method=materialization.access_method,
                    ssh_user=str(endpoint.user),
                    ready_at=delivery.ready_at,
                    lease_end_utc=materialization.lease_end_utc,
                ),
            )
            await self.db.save_bare_metal_receipt(
                negotiation_id=negotiation_id,
                receipt=BareMetalReceipt(
                    escrow_uid=materialization.escrow_uid,
                    host_id=materialization.host_id,
                    physical_host_id=materialization.physical_host_id,
                    lease_start_utc=materialization.lease_start_utc,
                    lease_end_utc=materialization.lease_end_utc,
                    status="ready",
                    access_ref={"fulfillment_id": str(fulfillment_id)},
                    result_ref={
                        "kind": ACCESS_DELIVERY_KIND,
                        "schema_version": ACCESS_DELIVERY_SCHEMA_VERSION,
                    },
                ),
            )
        return lifecycle

    async def access(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        """Return transient SSH coordinates only to the accepted buyer."""

        lifecycle = await self.status(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )
        if lifecycle["state"] != "active":
            raise BareMetalFulfillmentError(
                "bare-metal access is unavailable outside an active lease"
            )
        reservation_id = lifecycle.get("capacity_reservation_id")
        fulfillment_id = lifecycle.get("fulfillment_id")
        if not reservation_id or not fulfillment_id:
            raise BareMetalFulfillmentError(
                "bare-metal fulfillment has no active access identity"
            )
        _, endpoint = await self._active_delivery(
            capacity_reservation_id=str(reservation_id),
            fulfillment_id=str(fulfillment_id),
        )
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

    async def teardown(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        lifecycle = await self.status(
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
        )
        if lifecycle["state"] in _TEARDOWN_STATES | {TERMINATING, "released"}:
            return lifecycle
        reservation_id = lifecycle.get("capacity_reservation_id")
        fulfillment_id = lifecycle.get("fulfillment_id")
        if not reservation_id or not fulfillment_id:
            raise BareMetalFulfillmentError("bare-metal fulfillment has not begun")
        return await self.end_lease(
            negotiation_id=negotiation_id,
            capacity_reservation_id=str(reservation_id),
            reason="buyer_teardown",
        )

    async def end_lease(
        self,
        *,
        negotiation_id: str,
        capacity_reservation_id: str,
        reason: str,
    ) -> dict[str, Any]:
        """Ask the reservation's site to end its lease, and record that it is ending.

        The site converges teardown through the lease's fulfillment and releases
        the capacity once; terminating a lease already ending returns it as it is.
        """
        await self.fulfillment_client.terminate_lease(
            capacity_reservation_id, reason=reason
        )
        return await self.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            state=TERMINATING,
        )

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
    """Invoke durable bare-metal fulfillment through caller-owned ports."""
    recorded_binding = await context.ports.repository.load_thread_binding(
        negotiation_id=context.negotiation_id,
    )
    if recorded_binding != context.thread_binding:
        raise BareMetalFulfillmentError(
            "fulfillment context conflicts with the durable negotiation binding"
        )
    service = BareMetalFulfillmentService(
        db=context.ports.repository,
        capacity_client=context.ports.capacity_client,
        fulfillment_client=context.ports.fulfillment_client,
    )
    return await service.begin(
        negotiation_id=context.negotiation_id,
        escrow_uid=context.escrow_uid,
        buyer_principal=context.buyer_principal,
    )
