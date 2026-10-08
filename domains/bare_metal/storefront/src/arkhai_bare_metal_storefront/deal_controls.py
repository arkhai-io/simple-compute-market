"""Bare metal's hooks for the kit's deal-control route services.

The kit owns the routes' contracts, refusals, and wait semantics
(``market_settlement_runtime.SettlementAdminRouteService`` and
``market_capacity_publication.CapacityAdminRouteService``); this module supplies
what is bare metal's own: how an escrow is read against a listing's terms, what
fulfillment settlement would start, when a settlement is terminal, how a listing
is reserved administratively, and what a site's capacity-released callback
records. Verify and evaluate write nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from market_capacity_publication import CapacityAdminRouteService
from market_settlement_runtime import SettlementAdminRouteService

from .claims import ClaimAttributesMissing, whole_machine_claim
from .settlement_composition import ALKAHEST_MECHANISM

if TYPE_CHECKING:
    from .runtime import BareMetalStorefrontRuntime

# Settlement is terminal for a waiting administrator once its fulfillment is
# delivered or can no longer be.
_READY_STATES = frozenset({"active"})
_FAILED_STATES = frozenset({"failed", "torn_down", "released", "teardown_failed"})


async def _listing_context(
    runtime: "BareMetalStorefrontRuntime", listing_id: str
) -> dict[str, Any]:
    binding = await runtime.db.load_listing_binding(listing_id=listing_id)
    listing = await runtime.db.load_bare_metal_listing_payload(listing_id=listing_id)
    if binding is None or listing is None:
        raise LookupError(f"listing {listing_id!r} has no bare-metal binding")
    return {
        "listing_id": listing_id,
        "site_id": binding.site_id,
        "pool_id": binding.pool_id,
        "physical_resource_id": binding.physical_resource_id,
        "host_id": listing.host_id,
        "physical_host_id": listing.physical_host_id,
        "claimed_attributes": listing.claimed_attributes,
    }


def settlement_admin_routes(
    runtime: "BareMetalStorefrontRuntime",
) -> SettlementAdminRouteService:
    """Verify, evaluate, and wait, over this storefront's settlements."""

    async def verify(escrow_uid: str, request: Mapping[str, Any]) -> dict[str, Any]:
        listing = await runtime.db.load_listing(listing_id=str(request["listing_id"]))
        if listing is None:
            raise LookupError(f"listing {request['listing_id']!r} not found")
        composition = runtime.settlement_composition
        chain_name = str(request.get("chain_name") or "")
        clients = (
            composition.resources.get("clients") or {}
            if composition is not None and composition.configures(ALKAHEST_MECHANISM)
            else {}
        )
        client = clients.get(chain_name)
        if client is None:
            return {"valid": False, "reason": f"no Alkahest chain {chain_name!r} is configured"}
        try:
            await runtime.escrow_verifier(
                escrow_uid=escrow_uid,
                seller_wallet=str(request["seller_wallet"]),
                agreed_price=int(request["agreed_price"]),
                agreed_duration_seconds=int(request["agreed_duration_seconds"]),
                listing=listing,
                alkahest_client=client,
                chain_name=chain_name,
                alkahest_address_config_path=runtime.chain_config_paths.get(chain_name),
            )
        except Exception as exc:
            return {"valid": False, "reason": str(exc)}
        return {"valid": True}

    async def preview(escrow_uid: str, request: Mapping[str, Any]) -> dict[str, Any]:
        context = await _listing_context(runtime, str(request["listing_id"]))
        try:
            claim = whole_machine_claim(context)
        except ClaimAttributesMissing as exc:
            return {"would_submit": False, "reason": str(exc)}
        claim["resource_id"] = str(context["physical_resource_id"])
        return {
            "would_submit": True,
            "host_id": context["host_id"],
            "site_id": context["site_id"],
            "physical_resource_id": context["physical_resource_id"],
            "required_attributes": claim,
            "duration_seconds": int(request.get("duration_seconds") or 0),
        }

    async def settle_status(escrow_uid: str) -> dict[str, Any] | None:
        escrow = await runtime.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            return None
        lifecycle = await runtime.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=str(escrow["negotiation_id"])
        )
        state = str((lifecycle or {}).get("state") or "")
        if state in _READY_STATES:
            return {"status": "ready", "fulfillment_state": state}
        if state in _FAILED_STATES:
            return {"status": "failed", "fulfillment_state": state}
        return {"status": str(escrow.get("status") or ""), "fulfillment_state": state}

    return SettlementAdminRouteService(
        verify=verify,
        preview_fulfillment=preview,
        settle_status=settle_status,
        is_terminal=lambda status: status.get("status") in {"ready", "failed"},
    )


def capacity_admin_routes(
    runtime: "BareMetalStorefrontRuntime",
) -> CapacityAdminRouteService:
    """Reserve a listing administratively and record a site's release."""

    async def reserve(
        listing_id: str, required: Mapping[str, Any], deal_ref: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        context = await _listing_context(runtime, listing_id)
        if runtime.capacity_client is None:
            raise ConnectionError("no site is configured")
        try:
            claim = whole_machine_claim(context)
        except ClaimAttributesMissing as exc:
            raise LookupError(str(exc)) from exc
        # A whole machine is reserved as its listing describes it; an
        # administrator's required attribute it does not match finds nothing.
        if any(claim.get(str(name)) != str(value) for name, value in required.items()):
            return None
        claim["resource_id"] = str(context["physical_resource_id"])
        return await runtime.capacity_client.reserve(
            site=str(context["site_id"]), claim=claim, deal_ref=dict(deal_ref)
        )

    async def released(event: Mapping[str, Any]) -> dict[str, Any]:
        reservation_id = str(event["capacity_reservation_id"])
        lifecycle = await runtime.db.load_bare_metal_fulfillment_lifecycle_by_reservation(
            capacity_reservation_id=reservation_id
        )
        if lifecycle is None:
            hosted = await runtime.db.load_bare_metal_hosted_reservation_state(
                capacity_reservation_id=reservation_id
            )
            if hosted is None:
                raise LookupError(
                    f"capacity reservation {reservation_id!r} is not this storefront's"
                )
            # A hosted deal releases its reservation through its own lifecycle.
            return {"capacity_reservation_id": reservation_id, "state": hosted}
        if str(event.get("site_id") or "") != lifecycle["site_id"]:
            raise LookupError(
                f"capacity reservation {reservation_id!r} belongs to another site"
            )
        recorded = await runtime.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=str(lifecycle["negotiation_id"]),
            state="released",
        )
        if runtime.capacity_client is not None:
            runtime.capacity_client.reservation_sites.pop(reservation_id, None)
        return {"capacity_reservation_id": reservation_id, "state": recorded["state"]}

    return CapacityAdminRouteService(reserve=reserve, released=released)


__all__ = ["capacity_admin_routes", "settlement_admin_routes"]
