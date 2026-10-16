"""Admin controller — global pause/resume, status, and resource maintenance.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from arkhai_vms_listings.reconciler import (
    ReconciliationScope,
    closed_available_listing_ids,
    stale_open_listing_ids,
)
from core_storefront.auth import AuthenticatedPrincipal
from core_storefront.identity_authority import (
    IdentityAuthorityError,
    StorefrontIdentityAuthority,
)
from core_storefront.identity_lifecycle import (
    inspect_identity,
    retire_rotated_identity,
    rotate_identity,
)
from core_storefront.models.system_models import (
    AdminPauseResponse,
    IdentityRetirementRequest,
    IdentityStatusResponse,
)
from core_storefront.stage_log import stage_event
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi_utils.cbv import cbv
from market_identity import RotationRequest

import market_storefront.container as _container
from market_storefront.services.capacity_client import (
    site_capacity_buckets,
    site_pool_projection,
    site_projection_status,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility
from market_storefront.failure_actions import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
    configured_failure_actions,
)
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.capacity_admin_models import (
    CapacityReleasedEventRequest,
    FulfillmentEventResponse,
    FulfillmentFailedEventRequest,
    FulfillmentStartedEventRequest,
    InterruptDealRequest,
    InterruptDealResponse,
    ReleaseReservationsResponse,
    ReleaseStartedEventRequest,
    ReserveCapacityRequest,
    ReserveCapacityResponse,
    UsageStartedEventRequest,
)
from market_storefront import lifecycle as _lifecycle
from market_storefront import lifecycle_steps as _lifecycle_steps  # noqa: F401 - registers the steps
from market_storefront_kit import (
    LifecycleRouteError,
    StorefrontLifecycleRouteService,
    TradingPauseRouteService,
)
from market_pool_overrides import (
    PoolOverrideDeleteResponse,
    PoolOverrideListResponse,
    PoolOverrideRecord,
    PoolOverrideResponse,
    PoolOverrideRouteError,
    PoolOverrideRouteService,
    PoolOverrideWriteResponse,
)
from market_capacity_publication import (
    CapacityAdminRouteError,
    CapacityAdminRouteService,
    CapacityBindingError,
    PublicationBinding,
    remote_site_clients,
)
from market_resource_pools_contracts.backing import (
    CapacityNotAdmittedError,
    admitted_backing,
)

logger = logging.getLogger(__name__)

# Site-ledger reservation states that still hold capacity.
_INTERRUPTIBLE_HELD_STATES = frozenset(
    {"reserved", "provisioning", "leased", "releasing"}
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


#: Route alias -> the loop's registered name. Aliases are hyphenated where loop
#: names are underscored, and `site-projections` does not transform into
#: `site_projection_poller` by any rule -- so the mapping is declared rather
#: than inferred. Declaring it makes the route's spelling and the registry's
#: agree by construction, which is the drift that let `claims` outlive the
#: claims engine.
#: Fields `ReserveCapacityResponse` cannot be built without.
#:
#: Deliberately not `resource_id`: `kit/site`'s reserve route strips physical
#: identity from every reservation response, so requiring it asked the site
#: authority for something it is designed never to return.
_REQUIRED_RESERVATION_FIELDS = ("capacity_reservation_id",)


def require_reservation_fields(
    reserved: Mapping[str, Any], *, site_id: str
) -> None:
    """Refuse a reservation payload this response cannot be built from.

    These fields were subscripted directly, two lines after the sibling stage
    event read the same payload with `.get`. When one was absent the `KeyError`
    reached the caller as `500 Storefront administrator request failed`, naming
    neither the field nor the authority that returned it -- a message that cost
    several rounds to trace back to one subscript.

    A `502`, not a `500`: the site authority returned something this storefront
    cannot use, which is a bad gateway rather than this service faulting. The
    payload's keys are reported because the useful question is what the
    authority *did* send -- a fungible pool reservation legitimately has no
    resource of its own to name, and whether it should carry one is a contract
    question this error surfaces instead of hiding.
    """
    missing = [f for f in _REQUIRED_RESERVATION_FIELDS if f not in reserved]
    if not missing:
        return
    raise HTTPException(
        status_code=502,
        detail=(
            f"site {site_id!r} returned a reservation without "
            f"{', '.join(missing)}; payload carried {sorted(reserved)}. This "
            "response requires those fields, so either the authority omitted "
            "them or the two disagree on the reservation shape."
        ),
    )


def _lifecycle_routes() -> StorefrontLifecycleRouteService:
    return StorefrontLifecycleRouteService(_lifecycle.controller())


@cbv(router)
class AdminController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),  # noqa: B008
        capacity_runtime=Depends(  # noqa: B008
            lambda: _container.resolved_capacity_runtime
        ),
        _key: None = Depends(require_admin_key),
    ) -> None:
        self._db = db
        self._capacity_runtime = capacity_runtime

    @staticmethod
    def _operator(request: Request) -> AuthenticatedPrincipal:
        authenticated = getattr(request.state, "marketplace_authenticated", None)
        if not isinstance(authenticated, AuthenticatedPrincipal):
            raise HTTPException(
                status_code=403,
                detail="Administrator principal authentication is required",
            )
        return authenticated

    @router.post(
        "/identity/rotations",
        response_model=IdentityStatusResponse,
        summary="Apply a two-proof marketplace identity rotation",
    )
    async def rotate_marketplace_identity(
        self,
        body: RotationRequest,
        request: Request,
    ) -> IdentityStatusResponse:
        operator = self._operator(request)
        try:
            return await asyncio.to_thread(
                rotate_identity,
                StorefrontIdentityAuthority(self._db.db_path),
                request=body,
                operator=operator.principal,
                now=int(time.time()),
            )
        except IdentityAuthorityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get(
        "/identity/status",
        response_model=IdentityStatusResponse,
        summary="Inspect one marketplace identity subject",
    )
    async def marketplace_identity_status(
        self,
        request: Request,
        authority: str = Query(min_length=1, max_length=256),
        subject: str = Query(min_length=1, max_length=256),
    ) -> IdentityStatusResponse:
        self._operator(request)
        try:
            return await asyncio.to_thread(
                inspect_identity,
                StorefrontIdentityAuthority(self._db.db_path),
                authority=authority,
                subject=subject,
                now=int(time.time()),
            )
        except IdentityAuthorityError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/identity/retirements",
        response_model=IdentityStatusResponse,
        summary="Retire the old principal from an applied rotation",
    )
    async def retire_marketplace_identity(
        self,
        body: IdentityRetirementRequest,
        request: Request,
    ) -> IdentityStatusResponse:
        operator = self._operator(request)
        try:
            return await asyncio.to_thread(
                retire_rotated_identity,
                StorefrontIdentityAuthority(self._db.db_path),
                request=body,
                operator=operator.principal,
                now=int(time.time()),
            )
        except IdentityAuthorityError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post(
        "/pause",
        response_model=AdminPauseResponse,
        summary="Pause new negotiations globally (admin)",
    )
    async def pause(self) -> AdminPauseResponse:
        return TradingPauseRouteService(_lifecycle.trading_pause()).pause()

    @router.post(
        "/resume",
        response_model=AdminPauseResponse,
        summary="Resume new negotiations globally (admin)",
    )
    async def resume(self) -> AdminPauseResponse:
        return TradingPauseRouteService(_lifecycle.trading_pause()).resume()

    @router.post(
        "/deals/{escrow_uid}/interrupt",
        response_model=InterruptDealResponse,
        summary="Interrupt an active interruptible compute deal (admin)",
    )
    async def interrupt_deal(
        self,
        escrow_uid: str,
        body: InterruptDealRequest,
    ) -> InterruptDealResponse:
        """End an interruptible deal's capacity lease early.

        This is the provider-control-plane half of spot interruption.
        It validates that the deal came from an interruptible listing,
        finds the live capacity reservation, and truncates that lease to
        the interruption timestamp. The splitter declaration remains a
        separate settlement action until the on-chain helper is wired.
        """
        escrow = await self._db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown escrow {escrow_uid!r}",
            )
        listing_id = await self._db.get_listing_id_by_escrow_uid(escrow_uid=escrow_uid)
        if not listing_id:
            raise HTTPException(
                status_code=404,
                detail=f"No listing found for escrow {escrow_uid!r}",
            )
        listing = await self._db.load_listing(listing_id=listing_id)
        if listing is None:
            raise HTTPException(
                status_code=404,
                detail=f"Listing {listing_id!r} not found",
            )
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=escrow["negotiation_id"]
        )
        if not self._deal_is_interruptible(listing=listing, thread=thread):
            raise HTTPException(
                status_code=409,
                detail=(
                    "Deal is not marked interruptible/splitter-backed; "
                    "refusing spot interruption."
                ),
            )

        interrupted_at = self._interrupt_time(body.interrupted_at_utc)
        reservation = await self._find_live_reservation_for_escrow(escrow_uid)
        if reservation is None:
            raise HTTPException(
                status_code=404,
                detail=f"No live reservation found for escrow {escrow_uid!r}",
            )
        capacity_reservation_id = str(reservation["capacity_reservation_id"])

        truncated: dict[str, Any] | None = None
        if not body.dry_run:
            from market_storefront.services.capacity_client import (
                capacity_binding_for_listing,
            )

            binding = await capacity_binding_for_listing(self._db, listing_id)
            truncated = await self._runtime().truncate_lease(
                binding,
                capacity_reservation_id=capacity_reservation_id,
                lease_end_utc=interrupted_at,
            )
            if truncated is None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Reservation {capacity_reservation_id!r} is no longer held "
                        "and could not be interrupted"
                    ),
                )
            await self._db.update_escrow(
                escrow_uid=escrow_uid,
                reason=body.reason or "interruptible_preemption",
            )
            stage_event(
                "admin",
                "deal_interrupted",
                escrow_uid=escrow_uid,
                listing_id=listing_id,
                capacity_reservation_id=capacity_reservation_id,
                interrupted_at_utc=interrupted_at,
                reason=body.reason,
                seller_amount=body.seller_amount,
                refund_amount=body.refund_amount,
                settlement_action="splitter_declaration_pending",
            )

        return InterruptDealResponse(
            escrow_uid=escrow_uid,
            status="dry_run" if body.dry_run else "interrupted",
            capacity_reservation_id=capacity_reservation_id,
            listing_id=listing_id,
            interrupted_at_utc=interrupted_at,
            lease_truncated=not body.dry_run,
            settlement_action="splitter_declaration_pending",
            seller_amount=body.seller_amount,
            refund_amount=body.refund_amount,
            reservation=truncated or reservation,
        )

    # ------------------------------------------------------------------
    # Holding the timer loops, and one cycle of one loop while they are held.
    #
    # Each step is the operation the loop's timer invokes, registered with the
    # loop controller beside the loop (`market_storefront.lifecycle_steps`), and
    # returns what that operation returns. Running while held is the purpose.
    # ------------------------------------------------------------------

    @router.delete(
        "/introductions/{obligation_ref}/payloads",
        summary="Delete one introduction's contact payloads now (admin)",
    )
    async def delete_introduction_payloads(self, obligation_ref: str) -> dict:
        """Delete one introduction's contact payloads, whatever the window says.

        The same deletion the retention sweep runs. The deal and its obligation
        record remain; repeating the request converges.
        """
        composition = _container.resolved_contact_exchange
        retention = composition.retention() if composition is not None else None
        if retention is None:
            raise HTTPException(status_code=404, detail="contact exchange is disabled")
        return await retention.delete_one(obligation_ref)

    @router.post(
        "/lifecycle/pause",
        summary="Hold every timer-driven loop idle (admin)",
    )
    async def pause_lifecycle_loops(self) -> dict:
        """Hold the timer loops idle. Trading is unaffected.

        Two controls, deliberately separate. `/admin/pause` stops the
        storefront accepting new negotiations; this stops the loops
        reconciling behind a caller's back. A scenario needs deterministic
        reconciliation *and* a deal to agree, so a control that did both would
        make the second impossible.

        Loops are held rather than stopped: nothing is torn down, no cycle is
        cut part-way, and a poller keeps its feed position. Each loop's work
        stays reachable through its own run-cycle route while held.
        """
        result = await _lifecycle_routes().pause()
        logger.info("[ADMIN] Timer loops paused: %s", result["loops"])
        return result

    @router.post(
        "/lifecycle/resume",
        summary="Return every timer-driven loop to work (admin)",
    )
    async def resume_lifecycle_loops(self) -> dict:
        """Return the loops to work; each performs its next cycle."""
        result = await _lifecycle_routes().resume()
        logger.info("[ADMIN] Timer loops resumed: %s", result["loops"])
        return result

    @router.post(
        "/lifecycle/{loop}/run-cycle",
        summary="Run one cycle of one lifecycle loop now (admin)",
    )
    async def run_lifecycle_cycle(self, loop: str) -> dict:
        """Run exactly the cycle the loop's timer runs, whether or not loops are held."""
        try:
            return dict(await _lifecycle_routes().run_cycle(loop))
        except LifecycleRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.post(
        "/lifecycle/{loop}/dry-run",
        summary="Report what one cycle of one lifecycle loop would do (admin)",
    )
    async def dry_run_lifecycle_cycle(self, loop: str) -> dict:
        """Report the loop's next cycle without applying it, where it offers a preview."""
        try:
            return dict(await _lifecycle_routes().dry_run(loop))
        except LifecycleRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @router.post(
        "/capacity/projections/refresh",
        summary="Pull site-authority projections now (admin)",
    )
    async def refresh_site_projections(self) -> dict[str, Any]:
        """Run the projection poller's cycle now and report what each site holds.

        Projections are pull-synchronized on a poller interval. A caller that
        has just declared capacity at the site authority would otherwise wait
        that interval out, and a caller holding the lifecycle loops paused
        would wait forever: the poller that would pull it is one of the loops
        being held. Neither is a wait a test may take. So this runs exactly the
        poller's cycle, held or not: every site's families are polled in place,
        a site that cannot be reached keeps its last generation as `stale`, and
        a resource-pool change wakes publication.

        Returns the per-site load state so a caller asserts the pull happened
        rather than assuming it. A site reporting `not_loaded`, `unavailable`,
        or `invalid` has not confirmed its projection and must not be read as
        an authoritative empty -- an unconfirmed projection and an empty one
        are indistinguishable downstream, which is how an inventory failure
        becomes a negotiation failure several stages away.
        """
        state = _container.site_projections()
        await state.poll_once()
        summary = site_projection_status(state)
        logger.info(
            "[ADMIN] Site projections polled on demand: %s",
            {
                site: {family: view.get("state") for family, view in families.items()}
                for site, families in summary.items()
            },
        )
        return {"sites": summary}

    # -- storefront pool overrides ------------------------------------------
    # Site and pool IDs are operator-chosen strings with no character
    # restriction, so they travel in the body or query, never the path.

    @staticmethod
    def _pool_overrides() -> PoolOverrideRouteService:
        return PoolOverrideRouteService(_container.resolved_pool_override_service)

    @staticmethod
    def _http(exc: PoolOverrideRouteError) -> HTTPException:
        return HTTPException(status_code=exc.status_code, detail=exc.detail)

    @router.put(
        "/pool-overrides",
        response_model=PoolOverrideWriteResponse,
        summary="Replace one pool override, checked against the live site (admin)",
    )
    async def put_pool_override(
        self, record: PoolOverrideRecord
    ) -> PoolOverrideWriteResponse:
        """Replace the whole override at the record's site, pool, and offering mode.

        Refused with 422 for an unconfigured site, a mode no market serves, or
        vocabulary or clauses that do not validate; 503 (retryable) when the site
        cannot answer usably; and 404 when its live projection lacks the pool. A
        shape no member is feasible for is reported, not refused.
        """
        try:
            return await self._pool_overrides().replace(record)
        except PoolOverrideRouteError as exc:
            raise self._http(exc) from exc

    @router.get(
        "/pool-overrides",
        response_model=PoolOverrideResponse | PoolOverrideListResponse,
        summary="Read one pool override, or list them (admin)",
    )
    async def get_pool_overrides(
        self,
        site_id: str | None = Query(default=None),  # noqa: B008
        pool_id: str | None = Query(default=None),  # noqa: B008
        offering_mode: str | None = Query(default=None),  # noqa: B008
    ) -> PoolOverrideResponse | PoolOverrideListResponse:
        """With a site, pool, and offering mode, one override; otherwise a list,
        optionally narrowed to a site or to one site's pool."""
        try:
            return await self._pool_overrides().read(
                site_id=site_id, pool_id=pool_id, offering_mode=offering_mode
            )
        except PoolOverrideRouteError as exc:
            raise self._http(exc) from exc

    @router.delete(
        "/pool-overrides",
        response_model=PoolOverrideDeleteResponse,
        summary="Delete one pool override; idempotent (admin)",
    )
    async def delete_pool_override(
        self,
        site_id: str = Query(),  # noqa: B008
        pool_id: str = Query(),  # noqa: B008
        offering_mode: str = Query(),  # noqa: B008
    ) -> PoolOverrideDeleteResponse:
        try:
            return await self._pool_overrides().delete(
                site_id=site_id, pool_id=pool_id, offering_mode=offering_mode
            )
        except PoolOverrideRouteError as exc:
            raise self._http(exc) from exc

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    @staticmethod
    def _interrupt_time(value: str | None) -> str:
        if not value:
            dt = datetime.now(timezone.utc)
        else:
            raw = value.strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "interrupted_at_utc must be an ISO-8601 UTC timestamp "
                        "or omitted"
                    ),
                ) from exc
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M")

    def _deal_is_interruptible(
        self,
        *,
        listing: dict[str, Any],
        thread: dict[str, Any] | None,
    ) -> bool:
        listing_resource = self._json_object(listing.get("listing_resource"))
        if listing_resource.get("interruptible") is True:
            return True

        proposal = (thread or {}).get("buyer_escrow_proposal")
        if not isinstance(proposal, dict):
            return False
        try:
            from arkhai_vms_settlement.proposals import proposal_is_splitter_gated

            from market_storefront.utils.config import CHAINS

            chain_config_paths = {
                name: chain.alkahest_address_config_path
                for name, chain in CHAINS.items()
            }
            return proposal_is_splitter_gated(
                proposal,
                chain_config_paths=chain_config_paths,
            )
        except Exception as exc:
            logger.warning(
                "[ADMIN] Could not inspect splitter posture for proposal: %s",
                exc,
            )
            return False

    async def _find_live_reservation_for_escrow(
        self,
        escrow_uid: str,
    ) -> dict[str, Any] | None:

        capacity = self._capacity()
        for client in remote_site_clients(capacity).values():
            try:
                rows = await client.list_reservations(escrow_uid=escrow_uid)
            except Exception as exc:
                logger.warning(
                    "[ADMIN] Could not list reservations for escrow %s: %s",
                    escrow_uid,
                    exc,
                )
                continue
            held = [
                row for row in rows if row.get("state") in _INTERRUPTIBLE_HELD_STATES
            ]
            if held:
                return held[0]
        return None

    def _runtime(self) -> Any:
        if self._capacity_runtime is None:
            raise RuntimeError("capacity runtime is unavailable")
        return self._capacity_runtime

    async def _reservation_binding(
        self,
        *,
        site_id: str,
        capacity_reservation_id: str,
    ) -> tuple[dict[str, Any] | None, PublicationBinding, str | None]:
        """Resolve one reservation through its supplied authority and durable listing."""
        from market_site_client import SiteCapacityClientError
        from market_storefront.services.capacity_client import (
            capacity_binding_for_listing,
        )

        try:
            reservation = await self._runtime().site_client(site_id).get_reservation(
                capacity_reservation_id
            )
        except SiteCapacityClientError as exc:
            if exc.status_code != 404:
                raise
            reservation = None
        deal_ref = (reservation or {}).get("deal_ref") or {}
        listing_id = deal_ref.get("listing_id")
        if isinstance(listing_id, str) and listing_id.strip():
            binding = await capacity_binding_for_listing(self._db, listing_id)
            if binding.site_id != site_id:
                raise CapacityBindingError(
                    "reservation authority disagrees with the durable listing binding"
                )
            return reservation, binding, listing_id
        # A reservation with no listing exists only because the site admitted
        # it, so its binding takes the backing an admitted reservation implies.
        source_id = str((reservation or {}).get("resource_id") or capacity_reservation_id)
        return (
            reservation,
            PublicationBinding(site_id, "vm", source_id, admitted_backing()),
            None,
        )

    async def _apply_fulfillment_event(
        self,
        *,
        capacity_reservation_id: str,
        site_id: str,
        event_name: str,
        state: str,
        close_oversized: bool = False,
        reopen_available: bool = False,
        release_reservation: bool = False,
        provider_resource_id: str | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        **_extra: Any,
    ) -> FulfillmentEventResponse:
        """Record an event against its exact site and reservation identity."""
        result: dict[str, Any] = {"resource_id": provider_resource_id}
        try:
            _reservation, binding, _listing_id = await self._reservation_binding(
                site_id=site_id,
                capacity_reservation_id=capacity_reservation_id,
            )
            if release_reservation:
                released = await self._runtime().release(
                    binding,
                    capacity_reservation_id=capacity_reservation_id,
                    failure_reason=failure_reason,
                    failure_message=failure_message,
                )
                if released is not None:
                    result = released
                    result.setdefault(
                        "gpu_count", released.get("allocated_gpu_count")
                    )
        except CapacityNotAdmittedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except CapacityBindingError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach site {site_id!r} for reservation "
                f"{capacity_reservation_id!r}: {exc}",
            ) from exc
        closed_listing_ids = (
            await self._close_oversized_compute_listings(site_id)
            if close_oversized
            else []
        )
        reopened_listing_ids = (
            await self._reopen_available_compute_listings(site_id)
            if reopen_available
            else []
        )
        stage_event(
            "fulfillment",
            event_name,
            capacity_reservation_id=capacity_reservation_id,
            resource_id=result.get("resource_id"),
            gpu_count=result.get("gpu_count"),
            closed_listing_ids=closed_listing_ids,
            reopened_listing_ids=reopened_listing_ids,
        )
        return FulfillmentEventResponse(
            capacity_reservation_id=capacity_reservation_id,
            state=state,
            resource_id=result.get("resource_id"),
            gpu_count=result.get("gpu_count"),
            resource_state=result.get("resource_state"),
            closed_listing_ids=closed_listing_ids,
            reopened_listing_ids=reopened_listing_ids,
        )

    def _capacity(self) -> Any:
        return self._runtime().client()

    async def _member_availability(self) -> dict | None:
        """Aggregated site availability, or None when unobtainable.

        None makes the close path a no-op and the reopen path skip — a
        transient authority outage must not close (or worse, reopen)
        everything on ignorance.
        """
        try:
            return await self._runtime().availability()
        except Exception as exc:
            logger.warning(
                "[ADMIN] Could not snapshot site-authority capacity: %s",
                exc,
            )
            return None

    async def _close_oversized_compute_listings(self, changed_site: str) -> list[str]:
        """Close the listings availability bounds that ``changed_site``'s change made stale.

        The site's cached projection predates the change this operation just made,
        so it is refreshed first; reconciling against it unrefreshed would report
        nothing now and let a later operation report these closes as its own.
        """
        if not self._runtime().site_ids:
            return []
        availability = await self._member_availability()
        if availability is None:
            return []
        site_projections = _container.site_projections()
        await site_projections.refresh_site(changed_site)
        projection = site_pool_projection(site_projections)
        closed_listing_ids = stale_open_listing_ids(
            self._db.db_path,
            configured_sites=self._runtime().site_ids,
            member_availability=availability,
            # The same source publication derives from, so reconciliation here
            # cannot close a listing publication would keep.
            site_pool_projection=projection,
            site_capacity_buckets=site_capacity_buckets(site_projections),
            scope=ReconciliationScope.AVAILABILITY,
            shape_feasible=vm_shape_feasibility(),
            admissibility_default=_container.resolved_admissibility_default,
        )
        for listing_id in closed_listing_ids:
            await self._db.update_listing(
                listing_id=listing_id,
                status="closed",
                closed_by="reconciliation",
            )
        return closed_listing_ids

    async def _reopen_available_compute_listings(self, changed_site: str) -> list[str]:
        """Reopen the listings availability bounds that ``changed_site``'s change
        made available again, after refreshing that site's cached projection."""
        if not self._runtime().site_ids:
            return []
        availability = await self._member_availability()
        if availability is None:
            return []
        site_projections = _container.site_projections()
        await site_projections.refresh_site(changed_site)
        projection = site_pool_projection(site_projections)
        reopened_listing_ids = closed_available_listing_ids(
            self._db.db_path,
            member_availability=availability,
            site_pool_projection=projection,
            site_capacity_buckets=site_capacity_buckets(site_projections),
            shape_feasible=vm_shape_feasibility(),
            configured_sites=self._runtime().site_ids,
            admissibility_default=_container.resolved_admissibility_default,
        )
        for listing_id in reopened_listing_ids:
            await self._db.update_listing(
                listing_id=listing_id, status="open", reopened_by="reconciliation"
            )
        return reopened_listing_ids

    @router.post(
        "/fulfillment/events/started",
        response_model=FulfillmentEventResponse,
        summary="Record provisioning fulfillment start (admin)",
    )
    async def fulfillment_started(
        self,
        body: FulfillmentStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            capacity_reservation_id=body.capacity_reservation_id,
            site_id=body.site_id,
            event_name="started",
            state="provisioning",
            close_oversized=True,
            provider_id=body.provider_id,
            provider_job_id=body.provider_job_id,
            provider_resource_id=body.resource_id,
        )

    @router.post(
        "/fulfillment/events/usage-started",
        response_model=FulfillmentEventResponse,
        summary="Record compute usage start (admin)",
    )
    async def usage_started(
        self,
        body: UsageStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            capacity_reservation_id=body.capacity_reservation_id,
            site_id=body.site_id,
            event_name="usage_started",
            state="leased",
            close_oversized=True,
            provider_id=body.provider_id,
            provider_lease_id=body.provider_lease_id,
            provider_resource_id=body.resource_id,
            lease_end_utc=body.lease_end_utc,
        )

    @router.post(
        "/fulfillment/events/release-started",
        response_model=FulfillmentEventResponse,
        summary="Record compute release start (admin)",
    )
    async def release_started(
        self,
        body: ReleaseStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            capacity_reservation_id=body.capacity_reservation_id,
            site_id=body.site_id,
            event_name="release_started",
            state="releasing",
            close_oversized=True,
            provider_lease_id=body.provider_lease_id,
        )

    @router.post(
        "/fulfillment/events/capacity-released",
        response_model=FulfillmentEventResponse,
        summary="Record compute capacity release (admin)",
    )
    async def capacity_released(
        self,
        body: CapacityReleasedEventRequest,
    ) -> FulfillmentEventResponse:
        try:
            recorded = await CapacityAdminRouteService(
                reserve=None, released=self._record_capacity_released
            ).capacity_released(body.model_dump(mode="python"))
        except CapacityAdminRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return FulfillmentEventResponse(**recorded)

    async def _record_capacity_released(self, event) -> dict:
        """Apply a site's capacity-released callback to this storefront's state."""
        applied = await self._apply_fulfillment_event(
            capacity_reservation_id=event["capacity_reservation_id"],
            site_id=event["site_id"],
            event_name="capacity_released",
            state="released",
            close_oversized=False,
            reopen_available=True,
            release_reservation=True,
            provider_lease_id=event.get("provider_lease_id"),
            provider_resource_id=event.get("resource_id"),
            released_at=event.get("released_at"),
        )
        return applied.model_dump(mode="python")

    @router.post(
        "/fulfillment/events/failed",
        response_model=FulfillmentEventResponse,
        summary="Record provisioning fulfillment failure (admin)",
    )
    async def fulfillment_failed(
        self,
        body: FulfillmentFailedEventRequest,
    ) -> FulfillmentEventResponse:
        try:
            reservation, _binding, listing_id = await self._reservation_binding(
                site_id=body.site_id,
                capacity_reservation_id=body.capacity_reservation_id,
            )
        except CapacityBindingError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach site {body.site_id!r} for reservation "
                f"{body.capacity_reservation_id!r}: {exc}",
            ) from exc
        if reservation is None or listing_id is None:
            raise HTTPException(
                status_code=404,
                detail=f"Reservation {body.capacity_reservation_id!r} not found",
            )
        deal_ref = reservation.get("deal_ref") or {}
        # The reservation's own escrow is the one commit recorded on a hold
        # placed before the deal had an escrow; its deal reference never
        # learns it.
        escrow_uid = (
            body.escrow_uid or reservation.get("escrow_uid") or deal_ref.get("escrow_uid")
        )
        result = await apply_fulfillment_failure_policy(
            self._db,
            FulfillmentFailureContext(
                capacity_reservation_id=body.capacity_reservation_id,
                escrow_uid=escrow_uid,
                listing_id=listing_id,
                provider_id=body.provider_id,
                provider_job_id=body.provider_job_id,
                provider_resource_id=body.resource_id,
                resource_id=body.resource_id,
                reason=body.reason,
                message=body.message,
                logs_ref=body.logs_ref,
                source="admin_event",
            ),
            capacity=self._runtime(),
        )
        if "release_capacity" in configured_failure_actions() and result.state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Reservation {body.capacity_reservation_id!r} not found",
            )
        return FulfillmentEventResponse(
            capacity_reservation_id=result.capacity_reservation_id
            or body.capacity_reservation_id,
            state=result.state or "unchanged",
            resource_id=result.resource_id,
            gpu_count=result.gpu_count,
            resource_state=result.resource_state,
            closed_listing_ids=[],
            reopened_listing_ids=result.reopened_listing_ids,
        )

    async def _open_bound_vm_listing_ids(self) -> set[str]:
        """Snapshot open listings with canonical durable VM bindings."""
        listing_ids: set[str] = set()
        rows = await self._db.list_listings(status="open", limit=10_000)
        for row in rows:
            listing_id = str(row["listing_id"])
            binding = await self._db.load_listing_binding(listing_id=listing_id)
            if binding is not None and binding.binding.offering_mode == "vm":
                listing_ids.add(listing_id)
        return listing_ids

    async def _closed_since_snapshot(self, listing_ids: set[str]) -> set[str]:
        closed: set[str] = set()
        for listing_id in listing_ids:
            row = await self._db.load_listing(listing_id=listing_id)
            if row and row.get("status") == "closed":
                closed.add(listing_id)
        return closed

    @router.post(
        "/portfolio/reservations",
        response_model=ReserveCapacityResponse,
        summary="Reserve compute capacity without negotiation (admin)",
    )
    async def reserve_capacity(
        self,
        body: ReserveCapacityRequest,
    ) -> ReserveCapacityResponse:
        """Force-reserve compute capacity using the reservation model.

        This is an operator/test hook for manual holds and recovery
        workflows. The hold lands in the site authority's ledger like
        every other reservation, so partial GPU capacity accounting and
        derived-listing reconciliation stay consistent across consumers.
        """
        from market_storefront.services.capacity_client import (
            capacity_binding_for_listing,
        )

        async def reserve(listing_id, claim, deal_ref):
            open_listing_ids = await self._open_bound_vm_listing_ids()
            try:
                binding = await capacity_binding_for_listing(self._db, listing_id)
            except RuntimeError as exc:
                raise CapacityBindingError(str(exc)) from exc
            claim = {**claim, "offering_mode": binding.offering_mode}
            try:
                reserved = await self._runtime().reserve(
                    binding, claim=claim, deal_ref=deal_ref
                )
            except CapacityNotAdmittedError:
                raise
            except CapacityBindingError as exc:
                raise CapacityBindingError(
                    f"Listing {listing_id!r} is mapped to site "
                    f"{binding.site_id!r}, which is not currently configured"
                ) from exc
            except Exception as exc:
                raise ConnectionError(
                    f"site {binding.site_id!r}: {exc}"
                ) from exc
            if not reserved:
                return None
            closed_listing_ids = await self._close_oversized_compute_listings(
                binding.site_id
            )
            # The capacity-delta subscriber can race this inline
            # reconciliation. Include listings that were open when reservation
            # began but that the subscriber closed first, so the response
            # reports the full effect of this reservation rather than only the
            # inline worker's share.
            closed_listing_ids = sorted(
                set(closed_listing_ids)
                | await self._closed_since_snapshot(open_listing_ids)
            )
            stage_event(
                "portfolio",
                "capacity_reserved_by_admin",
                capacity_reservation_id=reserved.get("capacity_reservation_id"),
                pool_id=reserved.get("pool_id"),
                member_id=reserved.get("member_id"),
                resource_id=reserved.get("resource_id"),
                gpu_count=reserved.get("allocated_gpu_count"),
                resource_state=reserved.get("state"),
                listing_id=listing_id,
                escrow_uid=deal_ref.get("escrow_uid"),
                closed_listing_ids=closed_listing_ids,
            )
            # Pools are the aggregator's concept, not the ledger's. The
            # reservation payload carries neither a `pool_id` nor pool-bearing
            # resource attributes -- the capacity boundary reports the hold and
            # withholds the topology the storefront published from -- so read
            # the membership from the durable listing binding, which is where
            # this storefront recorded it at publication time.
            durable = await self._db.load_listing_binding(listing_id=listing_id)
            pool_id = (
                reserved.get("pool_id")
                or (reserved.get("attributes") or {}).get("pool_id")
                or (durable.pool_id if durable is not None else None)
            )
            require_reservation_fields(reserved, site_id=binding.site_id)
            return {
                "capacity_reservation_id": str(reserved["capacity_reservation_id"]),
                "pool_id": str(pool_id) if pool_id else None,
                "member_id": (
                    str(reserved["member_id"]) if reserved.get("member_id") else None
                ),
                "gpu_count": int(reserved.get("allocated_gpu_count") or 1),
                "resource_state": reserved.get("state") or "available",
                "closed_listing_ids": closed_listing_ids,
            }

        try:
            result = await CapacityAdminRouteService(
                reserve=reserve, released=self._record_capacity_released
            ).reserve(body.model_dump(mode="python"))
        except CapacityAdminRouteError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
        return ReserveCapacityResponse(**result)

    @router.post(
        "/portfolio/release-reservations",
        response_model=ReleaseReservationsResponse,
        summary="Release every held site reservation (admin)",
    )
    async def release_reservations(self) -> ReleaseReservationsResponse:
        """Release every held reservation at every configured site.

        Releases each ``reserved``, ``provisioning``, ``leased``, or
        ``releasing`` reservation in each site's ledger. Repeating the call
        releases nothing new.

        This is fleet-wide cleanup: end-to-end teardown between runs against
        one stack, or operator recovery when every workload behind a site's
        holds is known to be gone. A single reservation is released by the
        provisioning service's ``capacity_released`` event instead.
        """
        released = await self._release_site_ledger_holds()

        if released:
            logger.info(
                "[ADMIN] Released %d site reservation(s): %s",
                len(released),
                released,
            )
        return ReleaseReservationsResponse(
            released_count=len(released),
            resource_ids=released,
        )

    async def _release_site_ledger_holds(self) -> list[str]:

        released: list[str] = []
        try:
            sites = remote_site_clients(self._capacity())
            for site_name, client in sites.items():
                for state in ("reserved", "provisioning", "leased", "releasing"):
                    for reservation in await client.list_reservations(state=state):
                        done = await client.release(
                            capacity_reservation_id=reservation.get(
                                "capacity_reservation_id"
                            ),
                        )
                        if done:
                            released.append(
                                f"ledger:{site_name}:"
                                f"{reservation.get('capacity_reservation_id')}",
                            )
        except Exception as exc:
            logger.warning(
                "[ADMIN] Could not release site-ledger holds: %s",
                exc,
            )
        return released
