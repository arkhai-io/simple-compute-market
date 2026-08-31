"""Durable selected-site fulfillment lifecycle for bare-metal agreements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from arkhai_bare_metal import (
    BareMetalMaterialization,
    BareMetalReceipt,
)
from compute_provisioning import (
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
)
from core_storefront import StorefrontFulfillmentContext
from market_fulfillment import VersionedEnvelope
from market_identity import Identity

if TYPE_CHECKING:
    from .sqlite_client import SQLiteClient


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
            terms.machine_id != context["machine_id"]
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
            reserved = recovered or await self.capacity_client.reserve(
                site=str(context["site_id"]),
                claim={
                    "resource_id": str(context["physical_resource_id"]),
                    "dimensions": {"units": 1},
                    "executor_kind": "bare_metal",
                },
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
                or publication.get("machine_id") != terms.machine_id
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

        materialization = await self.db.load_bare_metal_materialization(
            negotiation_id=negotiation_id
        )
        materialization_start = (
            materialization.lease_start_utc
            if materialization is not None
            else datetime.now(timezone.utc)
        )
        expected_materialization = BareMetalMaterialization(
            escrow_uid=escrow_uid,
            machine_id=terms.machine_id,
            physical_host_id=terms.physical_host_id,
            lease_start_utc=materialization_start,
            lease_end_utc=materialization_start
            + timedelta(seconds=terms.duration_seconds),
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
                    kind="bare_metal.v1",
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

    async def _active_access_result(
        self,
        *,
        capacity_reservation_id: str,
        fulfillment_id: str,
    ) -> Any:
        result_envelope = await self.fulfillment_client.get_fulfillment_result(
            fulfillment_id,
            capacity_reservation_id=capacity_reservation_id,
        )
        if (
            result_envelope.kind != "fulfillment.result.v1"
            or result_envelope.schema_version != 1
            or not isinstance(result_envelope.payload, dict)
            or result_envelope.payload.get("state") != "active"
        ):
            raise BareMetalFulfillmentError(
                "provisioning returned an unsupported fulfillment result"
            )
        try:
            domain_envelope = VersionedEnvelope.model_validate(
                result_envelope.payload["domain_result"]
            )
        except Exception as exc:
            raise BareMetalFulfillmentError(
                "active fulfillment returned no bare-metal result"
            ) from exc
        if (
            domain_envelope.kind != "bare_metal.fulfillment.result.v1"
            or domain_envelope.schema_version != 1
        ):
            raise BareMetalFulfillmentError(
                "provisioning returned an unsupported bare-metal result envelope"
            )
        return self.db._market_domain.codecs.result(domain_envelope.payload)

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

        teardown_pending = lifecycle["state"] in {
            "teardown_dispatch_pending",
            "tearing_down",
            "teardown_failed",
            "torn_down",
        }
        remote = await self.fulfillment_client.get_fulfillment_status(
            str(fulfillment_id),
            capacity_reservation_id=str(reservation_id),
        )
        if teardown_pending and remote.state not in {
            "teardown_dispatch_pending",
            "tearing_down",
            "teardown_failed",
            "torn_down",
        }:
            raise BareMetalFulfillmentError(
                "provisioning returned a conflicting teardown state"
            )
        lifecycle = await self.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            state=str(remote.state),
            failure_reason=remote.failure_reason or remote.failure_message,
        )
        if lifecycle["state"] == "torn_down":
            await self.capacity_client.site(lifecycle["site_id"]).release(
                capacity_reservation_id=str(reservation_id),
                deal_ref={
                    "negotiation_id": negotiation_id,
                    "escrow_uid": lifecycle["escrow_uid"],
                },
            )
            self.capacity_client.reservation_sites.pop(
                str(reservation_id),
                None,
            )
            return await self.db.update_bare_metal_fulfillment_lifecycle(
                negotiation_id=negotiation_id,
                state="released",
            )

        if remote.state == "active":
            result = (
                await self._active_access_result(
                    capacity_reservation_id=str(reservation_id),
                    fulfillment_id=str(fulfillment_id),
                )
            ).model_copy(update={"details": None, "host": None, "port": None})
            await self.db.save_bare_metal_result(
                negotiation_id=negotiation_id,
                result=result,
            )
            materialization = await self.db.load_bare_metal_materialization(
                negotiation_id=negotiation_id
            )
            if materialization is None:
                raise BareMetalFulfillmentError(
                    "bare-metal materialization is missing during recovery"
                )
            await self.db.save_bare_metal_receipt(
                negotiation_id=negotiation_id,
                receipt=BareMetalReceipt(
                    escrow_uid=materialization.escrow_uid,
                    machine_id=materialization.machine_id,
                    physical_host_id=materialization.physical_host_id,
                    lease_start_utc=materialization.lease_start_utc,
                    lease_end_utc=materialization.lease_end_utc,
                    status="ready",
                    access_ref={"fulfillment_id": str(fulfillment_id)},
                    result_ref={
                        "kind": "bare_metal.fulfillment.result.v1",
                        "schema_version": 1,
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
        result = await self._active_access_result(
            capacity_reservation_id=str(reservation_id),
            fulfillment_id=str(fulfillment_id),
        )
        if (
            result.action != "node_grant_access"
            or result.status != "success"
            or result.ssh_user is None
            or result.host is None
            or result.port is None
        ):
            raise BareMetalFulfillmentError(
                "bare-metal fulfillment has no buyer-ready SSH access"
            )
        return {
            "negotiation_id": negotiation_id,
            "method": "ssh",
            "host": result.host,
            "port": result.port,
            "username": result.ssh_user,
            "expires_at": result.lease_expires_at,
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
        if lifecycle["state"] in {
            "teardown_dispatch_pending",
            "tearing_down",
            "teardown_failed",
            "torn_down",
            "released",
        }:
            return lifecycle
        reservation_id = lifecycle.get("capacity_reservation_id")
        fulfillment_id = lifecycle.get("fulfillment_id")
        if not reservation_id or not fulfillment_id:
            raise BareMetalFulfillmentError("bare-metal fulfillment has not begun")
        accepted = await self.fulfillment_client.begin_fulfillment_teardown(
            str(fulfillment_id),
            capacity_reservation_id=str(reservation_id),
        )
        return await self.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id,
            state=str(accepted.state),
            fulfillment_id=accepted.fulfillment_id,
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
