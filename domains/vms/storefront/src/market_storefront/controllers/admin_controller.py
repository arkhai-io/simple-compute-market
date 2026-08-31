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
import uuid
from datetime import datetime, timezone
from typing import Any

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
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi_utils.cbv import cbv
from market_identity import RotationRequest

import market_storefront.container as _container
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
    ImportResourcesResponse,
    ImportRowError,
    InterruptDealRequest,
    InterruptDealResponse,
    ReleaseReservationsResponse,
    ReleaseStartedEventRequest,
    ReserveCapacityRequest,
    ReserveCapacityResponse,
    ResourcePatchRequest,
    ResourcePatchResponse,
    UsageStartedEventRequest,
)
from market_storefront.server import _set_globally_paused
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
    remote_site_clients,
)
from market_storefront.settlement_composition import (
    build_storefront_publication_clause_compiler,
)
from market_storefront.utils.config import ESCROW_TEMPLATES

logger = logging.getLogger(__name__)

# States that the release-reservations endpoints transition back to
# ``available``. ``reserved`` is the in-flight provisioning hold;
# ``leased`` is the post-fulfillment hold for the duration of the lease.
# Anything else (``available``, ``deleted``, etc.) is a no-op.
_HELD_STATES = frozenset({"reserved", "leased"})
_INTERRUPTIBLE_HELD_STATES = frozenset(
    {"reserved", "provisioning", "leased", "releasing"}
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


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
        _set_globally_paused(True)
        return AdminPauseResponse(
            paused=True, message="Storefront paused. New negotiations will receive 503."
        )

    @router.post(
        "/resume",
        response_model=AdminPauseResponse,
        summary="Resume new negotiations globally (admin)",
    )
    async def resume(self) -> AdminPauseResponse:
        _set_globally_paused(False)
        return AdminPauseResponse(paused=False, message="Storefront resumed.")

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

    @router.post(
        "/portfolio/resources/import",
        response_model=ImportResourcesResponse,
        summary="Bulk-import compute resources from a CSV file (admin)",
    )
    async def import_resources(
        self,
        file: UploadFile = File(  # noqa: B008
            ..., description="Compute resource CSV file."
        ),
    ) -> ImportResourcesResponse:
        """Upload a CSV file and upsert resource rows into the portfolio.

        Upsert semantics: rows present in the file are inserted or updated;
        rows absent from the file are not touched. Always upserts regardless
        of whether the table is already populated — use this to force a
        clobber of the current inventory.

        The CSV must contain at minimum a ``resource_type`` column. Rows that
        fail schema validation are counted in ``failed_count`` and skipped
        without rolling back successfully imported rows. The first failing
        rows surface via ``errors[]`` (capped at 50) so the caller doesn't
        have to attach a debugger to see what went wrong.

        Example::

            curl -X POST http://localhost:8001/api/v1/admin/portfolio/resources/import \\
                 -H "X-Admin-Key: <key>" \\
                 -F "file=@/path/to/resources.csv"
        """
        try:
            csv_content = (await file.read()).decode("utf-8")
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not read uploaded file: {exc}"
            ) from exc
        try:
            report = await self._db.upsert_resources_from_csv_content(
                csv_content=csv_content,
                source_label=f"admin-import:{file.filename or 'upload'}",
                templates=ESCROW_TEMPLATES,
                settlement_compiler=build_storefront_publication_clause_compiler(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        logger.info(
            "[ADMIN] Resource import: %d imported, %d failed, %d total rows (file=%s)",
            report.get("imported_count", 0),
            report.get("failed_count", 0),
            report.get("total_rows", 0),
            file.filename,
        )
        # Surface up to 50 per-row failures so operators can see what's
        # wrong without shell access. The full report.rows[] is also
        # logged below, capped lower per line.
        failed_rows = [
            row for row in report.get("rows") or [] if not row.get("imported")
        ]
        errors_payload = [
            ImportRowError(
                row_number=int(row.get("row_number") or 0),
                resource_id=row.get("resource_id"),
                resource_type=row.get("resource_type"),
                errors=list(row.get("errors") or []),
            )
            for row in failed_rows[:50]
        ]
        for row in failed_rows[:20]:
            logger.warning(
                "[ADMIN] CSV row %s (%s) failed: %s",
                row.get("row_number"),
                row.get("resource_id") or "<no id>",
                "; ".join(row.get("errors") or []),
            )
        if report.get("imported_count"):
            await self._mirror_resources_to_site_authority("import")
        return ImportResourcesResponse(
            imported_count=report.get("imported_count", 0),
            failed_count=report.get("failed_count", 0),
            total_rows=report.get("total_rows", 0),
            errors=errors_payload,
        )

    @router.get(
        "/portfolio/resources/{resource_id}",
        response_model=ResourcePatchResponse,
        summary="Get a compute resource by ID (admin)",
    )
    async def get_resource(self, resource_id: str) -> ResourcePatchResponse:
        """Fetch the current state of a single resource row.

        Returns the same shape as PATCH so callers can use one model for
        both reads and writes.

        404 if the resource_id does not exist.
        """
        row = await self._db.get_resource(resource_id=resource_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Resource {resource_id!r} not found",
            )
        attrs_raw = row.get("attributes") or {}
        if isinstance(attrs_raw, str):
            try:
                attrs = json.loads(attrs_raw)
            except (json.JSONDecodeError, TypeError):
                attrs = {}
        else:
            attrs = attrs_raw
        return ResourcePatchResponse(
            resource_id=resource_id,
            state=row.get("state"),
            attributes=attrs,
            updated=False,  # read-only — no write happened
        )

    @router.patch(
        "/portfolio/resources/{resource_id}",
        response_model=ResourcePatchResponse,
        summary="Partial update of a compute resource (admin)",
    )
    async def patch_resource(
        self, resource_id: str, body: ResourcePatchRequest
    ) -> ResourcePatchResponse:
        """Partially update a resource row.

        Only fields present in the request body (non-None) are written;
        unspecified fields are left unchanged. Idempotent: calling with the
        same state the resource is already in returns ``updated=False`` rather
        than erroring.

        Primary use cases:

        * **Lease expiry** — the provisioning service's LeaseWatchdog calls
          this with ``{"state": "available", "attributes": {"lease_end_utc": null}}``
          when a VM has been cleaned up.
        * **Manual operator intervention** — release a stuck resource, force a
          state transition for debugging, or patch attributes for testing.
        * **Test scenarios** — set arbitrary state without going through the
          full settlement flow.

        Returns the full resource row after the patch so callers can confirm
        what was written without a second GET.

        404 if the resource_id does not exist.
        """
        row = await self._db.get_resource(resource_id=resource_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Resource {resource_id!r} not found",
            )

        old_state = row.get("state")
        old_attrs_raw = row.get("attributes") or {}
        if isinstance(old_attrs_raw, str):
            try:
                old_attrs = json.loads(old_attrs_raw)
            except (json.JSONDecodeError, TypeError):
                old_attrs = {}
        else:
            old_attrs = old_attrs_raw

        # Determine what actually needs to change.
        new_state = body.state
        new_attrs: dict | None = None
        if body.attributes is not None:
            # Merge: existing attrs overwritten by supplied keys; None values
            # clear individual keys.
            merged = {**old_attrs}
            for k, v in body.attributes.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            new_attrs = merged

        state_changed = new_state is not None and new_state != old_state
        attrs_changed = new_attrs is not None and new_attrs != old_attrs

        if not state_changed and not attrs_changed:
            return ResourcePatchResponse(
                resource_id=resource_id,
                state=old_state,
                attributes=old_attrs,
                updated=False,
            )

        event_parts = []
        if state_changed:
            event_parts.append(f"state:{old_state}->{new_state}")
        if attrs_changed:
            event_parts.append("attrs_updated")
        event_type = "admin_resource_patch:" + ",".join(event_parts)

        # Each admin PATCH is an independent operation — the inputs
        # (resource_id, new_state, new_attrs) repeat across calls
        # (lease watchdog issues the same {state:available,
        # lease_end_utc:null} every time a lease expires), but each
        # call is a real transition that must apply, not a retry of a
        # past one. Idempotency-key dedup is only useful at the HTTP
        # retry layer; we generate a fresh uuid here so each call hits
        # the resources table.
        result = await self._db.apply_resource_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=f"admin-patch:{resource_id}:{uuid.uuid4()}",
            set_state=new_state if state_changed else None,
            set_attribute=(
                {f"$.{k}": v for k, v in body.attributes.items()}
                if body.attributes is not None
                else None
            ),
        )
        applied = bool(result.get("applied"))

        if state_changed and applied:
            logger.info(
                "[ADMIN] Resource %s state: %s → %s", resource_id, old_state, new_state
            )
        if attrs_changed and applied:
            logger.info("[ADMIN] Resource %s attributes patched", resource_id)

        # Emit a wait-able event when the lease watchdog releases a
        # resource. The provisioning service calls this endpoint with
        # state=available after a lease ends; tests and operators need a
        # synchronization point because the PATCH completes after the
        # /lifecycle/check-leases response returns. Other state
        # transitions (manual ops, init bookkeeping) don't produce this
        # event — it's specifically the leased→available edge.
        if (
            applied
            and state_changed
            and old_state == "leased"
            and new_state == "available"
        ):
            stage_event(
                "lease_lifecycle",
                "resource_released",
                resource_id=resource_id,
            )

        await self._mirror_resources_to_site_authority("patch")

        # Re-fetch the updated row to return accurate state.
        updated_row = await self._db.get_resource(resource_id=resource_id)
        attrs_out = updated_row.get("attributes") or {}
        if isinstance(attrs_out, str):
            try:
                attrs_out = json.loads(attrs_out)
            except (json.JSONDecodeError, TypeError):
                attrs_out = {}
        return ResourcePatchResponse(
            resource_id=resource_id,
            state=updated_row.get("state"),
            attributes=attrs_out,
            updated=True,
        )

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
        offer = self._json_object(listing.get("offer_resource"))
        if offer.get("interruptible") is True:
            return True

        proposal = (thread or {}).get("buyer_escrow_proposal")
        if not isinstance(proposal, dict):
            return False
        try:
            from domains.vms.settlement.proposals import proposal_is_splitter_gated

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
    ) -> tuple[dict[str, Any] | None, CapacityBinding, str | None]:
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
        source_id = str((reservation or {}).get("resource_id") or capacity_reservation_id)
        return reservation, CapacityBinding(site_id, "vm", source_id), None

    async def _mirror_resources_to_site_authority(self, source: str) -> None:
        """Compatibility no-op for callers completing local admin mutations.

        Provisioning inventory is authoritative and storefront projections are
        pull-synchronized. Storefront admin mutations must not push inventory
        into the provisioning ledger.
        """
        logger.debug(
            "[ADMIN] Skipping deprecated storefront inventory push after %s",
            source,
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
        except CapacityBindingError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach site {site_id!r} for reservation "
                f"{capacity_reservation_id!r}: {exc}",
            ) from exc
        closed_listing_ids = (
            await self._close_oversized_compute_listings() if close_oversized else []
        )
        reopened_listing_ids = (
            await self._reopen_available_compute_listings() if reopen_available else []
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

    def _site_topology(self) -> tuple[str | None, int]:
        """Return the configured home site and exact site count."""
        sites = self._runtime().site_ids
        return next(iter(sites), None), len(sites)

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

    async def _close_oversized_compute_listings(self) -> list[str]:
        from domains.vms.listings.reconciler import (
            mark_derived_listings_closed,
            stale_open_listing_ids,
        )

        home_site, configured_site_count = self._site_topology()
        if home_site is None:
            return []
        availability = await self._member_availability()
        if availability is None:
            return []
        closed_listing_ids = stale_open_listing_ids(
            self._db.db_path,
            home_site=home_site,
            configured_site_count=configured_site_count,
            member_availability=availability,
        )
        for listing_id in closed_listing_ids:
            await self._db.update_listing(listing_id=listing_id, status="closed")
        mark_derived_listings_closed(
            self._db.db_path,
            closed_listing_ids,
            home_site=home_site,
            configured_site_count=configured_site_count,
        )
        return closed_listing_ids

    async def _reopen_available_compute_listings(self) -> list[str]:
        from domains.vms.listings.reconciler import (
            closed_available_listing_ids,
            mark_derived_listings_open,
        )

        home_site, _ = self._site_topology()
        if home_site is None:
            return []
        availability = await self._member_availability()
        if availability is None:
            return []
        reopened_listing_ids = closed_available_listing_ids(
            self._db.db_path,
            home_site=home_site,
            member_availability=availability,
        )
        for listing_id in reopened_listing_ids:
            await self._db.update_listing(listing_id=listing_id, status="open")
        mark_derived_listings_open(self._db.db_path, reopened_listing_ids)
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
            vm_host=body.vm_host,
            vm_target=body.vm_target,
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
            vm_remove_job_id=body.vm_remove_job_id,
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
        return await self._apply_fulfillment_event(
            capacity_reservation_id=body.capacity_reservation_id,
            site_id=body.site_id,
            event_name="capacity_released",
            state="released",
            close_oversized=False,
            reopen_available=True,
            release_reservation=True,
            provider_lease_id=body.provider_lease_id,
            provider_resource_id=body.resource_id,
            released_at=body.released_at,
        )

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
        result = await apply_fulfillment_failure_policy(
            self._db,
            FulfillmentFailureContext(
                capacity_reservation_id=body.capacity_reservation_id,
                escrow_uid=body.escrow_uid or deal_ref.get("escrow_uid"),
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

        if not body.listing_id:
            raise HTTPException(
                status_code=400,
                detail="A durable VM listing binding is required",
            )
        open_listing_ids = await self._open_bound_vm_listing_ids()
        try:
            binding = await capacity_binding_for_listing(self._db, body.listing_id)
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        claim = dict(body.required_attributes or {})
        claim["executor_kind"] = binding.offering_mode
        try:
            reserved = await self._runtime().reserve(
                binding,
                claim=claim,
                deal_ref={
                    "listing_id": body.listing_id,
                    "escrow_uid": body.escrow_uid,
                    "reserved_by": "admin",
                },
            )
        except CapacityBindingError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Listing {body.listing_id!r} is mapped to site "
                f"{binding.site_id!r}, which is not currently configured",
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Could not reach site {binding.site_id!r} for listing "
                f"{body.listing_id!r}: {exc}",
            ) from exc
        if not reserved:
            raise HTTPException(
                status_code=409,
                detail="No available compute VM matched required attributes",
            )
        closed_listing_ids = await self._close_oversized_compute_listings()
        # The capacity-delta subscriber can race this inline reconciliation.
        # Include listings that were open when reservation began but that the
        # subscriber closed first, so the response reports the full effect of
        # this reservation rather than only the inline worker's share.
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
            listing_id=body.listing_id,
            escrow_uid=body.escrow_uid,
            closed_listing_ids=closed_listing_ids,
        )
        # Pools are the aggregator's concept, not the ledger's — surface
        # the membership from the resource attributes the sync mirrored.
        pool_id = reserved.get("pool_id") or (reserved.get("attributes") or {}).get(
            "pool_id"
        )
        return ReserveCapacityResponse(
            capacity_reservation_id=str(reserved["capacity_reservation_id"]),
            pool_id=str(pool_id) if pool_id else None,
            member_id=str(reserved["member_id"]) if reserved.get("member_id") else None,
            resource_id=str(reserved["resource_id"]),
            gpu_count=int(reserved.get("allocated_gpu_count") or 1),
            resource_state=reserved.get("state") or "available",
            closed_listing_ids=closed_listing_ids,
        )

    @router.post(
        "/portfolio/release-reservations",
        response_model=ReleaseReservationsResponse,
        summary="Release every held compute resource back to available (admin)",
    )
    async def release_reservations(self) -> ReleaseReservationsResponse:
        """Force every resource in a held state back to ``available``.

        "Held" means ``reserved`` (during provisioning) OR ``leased`` (during
        an active lease). Both are forms of bookkeeping that the storefront
        normally clears via the provisioning service's LeaseWatchdog once the
        lease expires; under mocked or short-circuited flows the watchdog has
        nothing to do, so this endpoint is the explicit cleanup.

        Use cases:
          - e2e test teardown between back-to-back runs against the same stack
            (mocked provisioning never reaches lease end, so leased resources
            otherwise leak across runs).
          - Operator recovery after a fleet-wide provisioner crash: when the
            storefront thinks resources are held but the actual workloads
            are gone, this clears the bookkeeping without touching
            value/inventory data.

        Sledgehammer — for surgical single-row release, use
        ``PATCH /portfolio/resources/{resource_id}`` with ``state=available``
        instead. Production operators should prefer the targeted variant.

        Does not touch resources in any other state (e.g. ``available`` or
        ``deleted``). Idempotent — safe to call repeatedly.
        """
        released = list(await self._release_site_ledger_holds())

        # Normalize any legacy aggregate state left on local rows so the
        # market view doesn't advertise stale "leased" resources.
        for r in await self._db.list_resources():
            if r.get("state") not in _HELD_STATES:
                continue
            resource_id = str(r["resource_id"])
            await self._db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="reservation_released_by_admin",
                idempotency_key=f"admin-release:{resource_id}:{r.get('updated_at', '')}",
                set_state="available",
            )
            released.append(resource_id)

        if released:
            logger.info(
                "[ADMIN] Released %d held resource(s): %s",
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
