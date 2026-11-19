"""Bare metal's hooks for the kit's deal-control route services.

The kit owns the routes' contracts, refusals, and wait semantics, which
settlement a waited reference names among them
(``market_settlement_runtime.SettlementAdminRouteService`` and
``market_capacity_publication.CapacityAdminRouteService``); this module supplies
what is bare metal's own: how an escrow is read against an accepted deal's plan, what
fulfillment settlement would start, how its settlement records are found, what a
settlement's delivery status is, how a listing is reserved administratively, and
what a site's capacity-released callback records. Verify and evaluate write
nothing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction
from core_storefront.stage_log import stage_event
from market_capacity_publication import CapacityAdminRouteService, CapacityEffects
from market_core import SettlementEvidence
from market_core.schemas import EscrowProposal
from market_identity import Identity
from market_resource_pools_contracts.backing import CapacityNotAdmittedError
from market_settlement_runtime import (
    SettlementAdminRouteError,
    SettlementAdminRouteService,
    SettlementLookup,
)

from .claims import ClaimAttributesMissing, whole_machine_claim
from .fulfillment_service import BareMetalFulfillmentError
from .listing_binding import bare_metal_listing_binding
from .settlement_composition import ALKAHEST_MECHANISM

if TYPE_CHECKING:
    from .runtime import BareMetalStorefrontRuntime

# Settlement is terminal for a waiting administrator once its fulfillment is
# delivered or can no longer be.
_READY_STATES = frozenset({"active"})
_FAILED_STATES = frozenset({"failed", "torn_down", "released", "teardown_failed"})


def _settlement_evidence(record: Mapping[str, Any] | None) -> SettlementEvidence | None:
    """A settlement record as the evidence the kit resolves; one exists for every
    accepted deal from acceptance, whatever its mechanism."""
    if record is None:
        return None
    return SettlementEvidence(
        negotiation_id=record["negotiation_id"],
        mechanism=record["mechanism"],
        settlement_ref=record["settlement_ref"],
        status=record["status"],
        evidence=record["evidence"],
    )


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
    *,
    poll_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
) -> SettlementAdminRouteService:
    """Verify, evaluate, and wait, over this storefront's settlements.

    ``poll_seconds`` and ``clock`` replace the settle wait's own, as a test
    driving the wait in fake time does; left unset, the wait keeps its defaults.
    """

    async def verify(escrow_uid: str, request: Mapping[str, Any]) -> dict[str, Any]:
        # Checked as settlement verifies it: against the plan the accepted deal
        # committed, on the chain and escrow contract its proposal names.
        negotiation_id = str(request["negotiation_id"])
        thread = await runtime.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if thread is None or thread.get("terminal_state") != "success":
            raise LookupError(f"accepted negotiation {negotiation_id!r} not found")
        try:
            proposal = EscrowProposal.model_validate(thread.get("buyer_escrow_proposal"))
        except (TypeError, ValueError):
            return {"valid": False, "reason": "the accepted deal recorded no escrow proposal"}
        composition = runtime.settlement_composition
        chain_name = proposal.chain_name
        clients = (
            composition.chain_clients
            if composition is not None and composition.configures(ALKAHEST_MECHANISM)
            else {}
        )
        client = clients.get(chain_name)
        if client is None:
            return {"valid": False, "reason": f"no Alkahest chain {chain_name!r} is configured"}
        try:
            await runtime.escrow_verifier(
                escrow_uid=escrow_uid,
                settlement_plan=thread.get("settlement_plan"),
                alkahest_client=client,
                chain_name=chain_name,
                escrow_address=proposal.escrow_address,
                address_book=runtime.chain_config_paths.get(chain_name),
            )
        except Exception as exc:
            return {"valid": False, "reason": str(exc)}
        return {"valid": True}

    async def preview(escrow_uid: str, request: Mapping[str, Any]) -> dict[str, Any]:
        listing_id = str(request["listing_id"])
        context = await _listing_context(runtime, listing_id)
        binding = await bare_metal_listing_binding(runtime.db, listing_id)
        if binding is None:
            raise LookupError(f"listing {listing_id!r} has no bare-metal binding")
        try:
            # The preview answers as settlement would: no fulfillment starts for
            # a listing no admission authority stands behind.
            binding.backing.require_admission("a bare-metal fulfillment")
            claim = whole_machine_claim(context)
        except (CapacityNotAdmittedError, ClaimAttributesMissing) as exc:
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

    async def by_reference(settlement_ref: str) -> SettlementEvidence | None:
        return _settlement_evidence(
            await runtime.db.load_bare_metal_settlement_record_by_ref(
                settlement_ref=settlement_ref
            )
        )

    async def by_negotiation(negotiation_id: str) -> SettlementEvidence | None:
        return _settlement_evidence(
            await runtime.db.load_bare_metal_settlement_record(
                negotiation_id=negotiation_id
            )
        )

    async def delivery_status(evidence: SettlementEvidence) -> dict[str, Any]:
        negotiation_id = evidence.negotiation_id
        lifecycle = await runtime.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=negotiation_id
        )
        previously_available = lifecycle is not None and await runtime.lifecycle.delivery_available(
            negotiation_id
        )
        if lifecycle is not None and lifecycle.get("fulfillment_id"):
            # The site's convergence can advance while servicing is held; a
            # cached dispatch state cannot establish whether delivery is ready.
            thread = await runtime.db.load_negotiation_thread_row(
                negotiation_id=negotiation_id
            )
            if thread is None:
                raise LookupError("settled negotiation not found")
            try:
                lifecycle = await runtime.fulfillment_service().status(
                    negotiation_id=negotiation_id,
                    buyer_principal=Identity.model_validate(thread["buyer_principal"]),
                )
            except BareMetalFulfillmentError as exc:
                # A refused fulfillment read, a delivery conflict among them, is
                # the settlement's answer as the buyer's fulfillment routes give
                # it, not a failed read for the settle wait to poll past.
                raise SettlementAdminRouteError(
                    exc.status_code,
                    exc.detail
                    if exc.error is None
                    else {"error": exc.error, "reason": exc.detail},
                ) from exc
        state = str((lifecycle or {}).get("state") or "")
        if await runtime.lifecycle.ended_before_delivery(negotiation_id):
            # A deal ended before it was delivered, a settlement placement
            # that found no capacity among them, has no fulfillment state to
            # reach; its end is the settlement's outcome.
            return {"status": "ended", "fulfillment_state": state}
        # Physical readiness does not establish activation, billing start or
        # disclosure authorization; those must be durably available too.
        if state in _READY_STATES and await runtime.lifecycle.delivery_available(negotiation_id):
            # Delivery removes the reason servicing deferred an adopted
            # obligation. Only a mechanism the settlement runtime services
            # adopts one, and its evidence's source names it; an Arkhai
            # payments deal has none to wake.
            obligation_ref = (evidence.evidence.get("source") or {}).get(
                "obligation_ref"
            )
            if (
                not previously_available
                and obligation_ref
                and runtime.settlement_worker is not None
            ):
                # Woken through the worker, never stepped around it.
                await runtime.settlement_worker.wake(str(obligation_ref))
            return {"status": "ready", "fulfillment_state": state}
        if state in _FAILED_STATES:
            return {"status": "failed", "fulfillment_state": state}
        # Before a fulfillment decides, the settlement record's own status is
        # the report: accepted, verified and refund statuses keep the wait
        # polling, and failed evidence ends it, as a settlement never to be
        # delivered.
        return {"status": evidence.status, "fulfillment_state": state}

    timing: dict[str, Any] = {}
    if poll_seconds is not None:
        timing["poll_seconds"] = poll_seconds
    if clock is not None:
        timing["clock"] = clock
    return SettlementAdminRouteService(
        verify=verify,
        preview_fulfillment=preview,
        settlements=SettlementLookup(
            by_reference=by_reference, by_negotiation=by_negotiation
        ),
        delivery_status=delivery_status,
        **timing,
    )


def _claim_states(claimed: Any, required: Any) -> bool:
    """Whether a claim's value is exactly what an administrator required.

    Scalar attributes compare in the string form the claim holds them in.
    Structured values compare as JSON, so a type the claim does not hold never
    matches: Python's equality would take a required ``True`` for the claim's
    integer ``1``.
    """
    if isinstance(required, Mapping):
        return json.dumps(claimed, sort_keys=True) == json.dumps(required, sort_keys=True)
    return claimed == str(required)


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
        binding = await bare_metal_listing_binding(runtime.db, listing_id)
        if binding is None:
            raise LookupError(f"listing {listing_id!r} has no bare-metal binding")
        # A listing no admission authority stands behind constructs no claim:
        # its delegate refuses first, which the kit's route answers as a
        # conflict, whatever the administrator required.
        binding.backing.require_admission("a bare-metal reservation")
        try:
            claim = whole_machine_claim(context)
        except ClaimAttributesMissing as exc:
            raise LookupError(str(exc)) from exc
        claim["resource_id"] = str(context["physical_resource_id"])
        # A whole machine is reserved as its listing describes it; an
        # administrator's required attribute it does not match finds nothing.
        # The match is against the claim the site receives, its machine pinned
        # and its quantities structured under `dimensions`.
        if not all(
            _claim_states(claim.get(str(name)), value) for name, value in required.items()
        ):
            return None
        return await CapacityEffects(runtime.capacity_client).reserve(
            binding, claim=claim, deal_ref=dict(deal_ref)
        )

    async def released(event: Mapping[str, Any]) -> dict[str, Any]:
        reservation_id = str(event["capacity_reservation_id"])
        lifecycle = await runtime.db.load_bare_metal_fulfillment_lifecycle_by_reservation(
            capacity_reservation_id=reservation_id
        )
        if lifecycle is None:
            raise LookupError(
                f"capacity reservation {reservation_id!r} is not this storefront's"
            )
        if str(event.get("site_id") or "") != lifecycle["site_id"]:
            raise LookupError(
                f"capacity reservation {reservation_id!r} belongs to another site"
            )
        recorded = await runtime.db.update_bare_metal_fulfillment_lifecycle(
            negotiation_id=str(lifecycle["negotiation_id"]),
            state="released",
        )
        with transaction(runtime.db.db_path) as conn:
            EndSession(conn).physical_progress(str(lifecycle["negotiation_id"]), "released")
        # Retain the accepted site's routing identity for report pull recovery
        # after release, including when its independent callback was missed.
        # The release is observable in the stage-event log, as every storefront
        # records it, so a caller watching a lease sees it end the same way.
        stage_event(
            "fulfillment",
            "capacity_released",
            negotiation_id=str(lifecycle["negotiation_id"]),
            escrow_uid=lifecycle.get("settlement_ref"),
            capacity_reservation_id=reservation_id,
            site_id=lifecycle["site_id"],
        )
        return {"capacity_reservation_id": reservation_id, "state": recorded["state"]}

    return CapacityAdminRouteService(reserve=reserve, released=released)


__all__ = ["capacity_admin_routes", "settlement_admin_routes"]
