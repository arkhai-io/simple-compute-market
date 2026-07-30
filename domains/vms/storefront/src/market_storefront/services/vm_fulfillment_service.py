"""VM fulfillment orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from market_storefront.services.vm_fulfillment_planner import build_vm_fulfillment_plan
from domains.vms.settlement import submit_compute_fulfillment

logger = logging.getLogger(__name__)

StageEventFn = Callable[..., Any]
SQLiteClientFactory = Callable[[], Any]


async def persist_escrow_fields_with_retry(
    get_sqlite_client: SQLiteClientFactory,
    *,
    escrow_uid: str,
    attempts: int = 3,
    backoff_seconds: float = 0.5,
    **fields: Any,
) -> bool:
    """Persist durable identity fields onto an escrow row, retrying a
    bounded number of times before giving up.

    Used for the fulfillment-identity fields (``capacity_reservation_id``,
    ``settlement_resource_id``, ``fulfillment_id``) this section added --
    a failed write here reopens exactly the orphaned-work window that
    persistence exists to close, so a single silent attempt is not
    sufficient. Returns True on success, False if every attempt failed.

    A caller that gets False should not abort an otherwise-successful
    fulfillment attempt over a failed metadata write -- a real VM and its
    credentials are not thrown away because a database write failed -- but
    the failure MUST be operator-visible (logged at ERROR, not WARNING),
    since a silently-swallowed failure here defeats the whole point of
    this persistence: this escrow's durable pointer to the fulfillment it
    initiated would otherwise be silently missing.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            await get_sqlite_client().update_escrow(escrow_uid=escrow_uid, **fields)
            return True
        except Exception as exc:
            last_exc = exc
            if attempt < attempts:
                await asyncio.sleep(backoff_seconds * attempt)
    logger.error(
        "[PROVISIONING] Failed to persist %s for escrow %s after %d attempts "
        "-- this fulfillment's durable identity is NOT recorded; restart/"
        "resume tracking for this escrow is degraded until reconciled "
        "manually. Last error: %s",
        sorted(fields), escrow_uid, attempts, last_exc,
    )
    return False


def _hold_lapsed(hold_expires_at: Any) -> bool:
    """Whether a TTL hold's deadline has passed (unparseable → lapsed)."""
    if not hold_expires_at:
        return False  # no TTL recorded — the hold doesn't expire
    text = str(hold_expires_at).strip().replace("Z", "+00:00")
    try:
        expires = datetime.fromisoformat(text)
    except ValueError:
        return True
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= datetime.now(timezone.utc)


def _parse_start_utc(start_utc: str | None) -> datetime:
    if not start_utc:
        return datetime.now(timezone.utc)
    text = str(start_utc).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = datetime.strptime(str(start_utc).strip(), "%Y-%m-%d %H:%M")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lease_window_strings(
    *, start_utc: str | None, duration_seconds: int,
) -> tuple[str, str]:
    start = _parse_start_utc(start_utc)
    end = start + timedelta(seconds=int(duration_seconds))
    return start.isoformat(), end.strftime("%Y-%m-%d %H:%M")


async def _commit_capacity_hold(
    *,
    capacity: Any,
    held_reservation: dict[str, Any] | None,
    escrow_uid: str,
    duration_seconds: int,
    stage_event: StageEventFn,
    start_utc: str | None = None,
) -> dict[str, Any] | None:
    """Secure an acceptance-time hold for this deal, or None to reserve fresh.

    Committing before provisioning turns the soft hold into a lease
    immediately, so it cannot lapse mid-provision; the lease window set
    here starts at settlement and is refreshed to provision-complete +
    duration by the normal post-provision commit.
    """
    if not held_reservation or not held_reservation.get("capacity_reservation_id"):
        return None
    if _hold_lapsed(held_reservation.get("hold_expires_at")):
        logger.info(
            "[CAPACITY] Hold %s lapsed before settlement — reserving fresh",
            held_reservation.get("capacity_reservation_id"),
        )
        return None
    lease_start_utc, lease_end_utc = _lease_window_strings(
        start_utc=start_utc,
        duration_seconds=duration_seconds,
    )
    try:
        await capacity.commit(
            resource_id=held_reservation.get("resource_id"),
            capacity_reservation_id=str(held_reservation["capacity_reservation_id"]),
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            idempotency_ref=escrow_uid,
        )
    except Exception as exc:
        logger.warning(
            "[CAPACITY] Could not commit hold %s (lapsed at the ledger?): "
            "%s — reserving fresh",
            held_reservation.get("capacity_reservation_id"), exc,
        )
        return None
    stage_event(
        "provision", "capacity_hold_committed",
        escrow_uid=escrow_uid,
        capacity_reservation_id=held_reservation.get("capacity_reservation_id"),
        resource_id=held_reservation.get("resource_id"),
        site=held_reservation.get("site"),
    )
    return dict(held_reservation)


async def _commit_fresh_reservation(
    *,
    capacity: Any,
    reserved: dict[str, Any],
    escrow_uid: str,
    duration_seconds: int,
    stage_event: StageEventFn,
    start_utc: str | None = None,
) -> None:
    """Promote a settlement-time fallback reservation before provisioning."""
    capacity_reservation_id = reserved.get("capacity_reservation_id")
    resource_id = reserved.get("resource_id")
    if not capacity_reservation_id:
        raise RuntimeError("Reserved capacity is missing reservation identity")
    lease_start_utc, lease_end_utc = _lease_window_strings(
        start_utc=start_utc,
        duration_seconds=duration_seconds,
    )
    await capacity.commit(
        resource_id=resource_id,
        capacity_reservation_id=str(capacity_reservation_id),
        lease_start_utc=lease_start_utc,
        lease_end_utc=lease_end_utc,
        idempotency_ref=escrow_uid,
    )
    stage_event(
        "provision", "capacity_reservation_committed",
        escrow_uid=escrow_uid,
        capacity_reservation_id=capacity_reservation_id,
        resource_id=resource_id,
        site=reserved.get("site"),
    )


# Site-authority capacity client (core_storefront.capacity.CapacityClient
# shape); duck-typed so this concept module needs no core import.
CapacityClientLike = Any
ProvisionVmFn = Callable[..., Awaitable[Any]]
ScheduleShutdownFn = Callable[..., Awaitable[Any]]
RegisterLeaseFn = Callable[..., Awaitable[Any]]
ApplyFailurePolicyFn = Callable[..., Awaitable[None]]



async def _build_vm_fulfillment_context(
    *, escrow_uid: str, vm_target: str, ssh_public_key: str,
    order: str | dict[str, Any] | None, duration_seconds: int,
    start_utc: str | None, listing_id: str | None,
    seller_order_id: str | None, chain_configs: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any]]:
    """Build the immutable VM request and its restart-recovery envelope."""
    plan = build_vm_fulfillment_plan(
        order=order, duration_seconds=duration_seconds, chain_configs=chain_configs,
    )
    connectivity = None
    try:
        from market_storefront.services.fulfillment_service import (
            _connectivity_settings_from_storefront_config,
        )
        connectivity = _connectivity_settings_from_storefront_config()
    except Exception:
        logger.exception(
            "[PROVISIONING] Failed to resolve connectivity context for escrow %s",
            escrow_uid,
        )
    request_payload: dict[str, Any] = {
        "vm_target": vm_target, "ssh_pubkey": ssh_public_key,
    }
    if connectivity:
        request_payload["connectivity"] = connectivity
    context = {
        "kind": "vm.storefront.fulfillment-context",
        "schema_version": 1,
        "payload": {
            "escrow_uid": escrow_uid,
            "listing_id": listing_id or plan.order_id,
            "seller_order_id": seller_order_id,
            "duration_seconds": int(duration_seconds),
            "start_utc": start_utc,
            "required_attributes": plan.required_attributes,
            "fulfillment_request": {
                "kind": "vm.fulfillment.request",
                "schema_version": 1,
                "payload": request_payload,
            },
        },
    }
    return plan, context


async def _reserve_capacity_for_obligation(
    *, capacity: Any, held_reservation: dict[str, Any] | None,
    escrow_uid: str, listing_id: str | None, order_id: str | None,
    required_attributes: dict[str, Any], duration_seconds: int,
    start_utc: str | None, stage_event: StageEventFn,
) -> dict[str, Any]:
    """Commit an accepted hold or create and commit an idempotent fallback."""
    reserved = await _commit_capacity_hold(
        capacity=capacity, held_reservation=held_reservation,
        escrow_uid=escrow_uid, duration_seconds=duration_seconds,
        start_utc=start_utc, stage_event=stage_event,
    )
    if reserved is None:
        reserved = await capacity.reserve(
            claim=required_attributes or None,
            deal_ref={"listing_id": listing_id or order_id, "escrow_uid": escrow_uid},
            lease_start_utc=start_utc,
            lease_duration_seconds=duration_seconds,
        )
        if reserved:
            await _commit_fresh_reservation(
                capacity=capacity, reserved=reserved, escrow_uid=escrow_uid,
                duration_seconds=duration_seconds, start_utc=start_utc,
                stage_event=stage_event,
            )
    if not reserved:
        raise RuntimeError("No available compute VM matched required attributes")
    return reserved


async def fulfill_vm_obligation(
    *,
    client: Any | None,
    escrow_uid: str,
    ssh_public_key: str,
    order: str | dict[str, Any] | None = None,
    duration_seconds: int = 3600,
    start_utc: str | None = None,
    listing_id: str | None = None,
    seller_order_id: str | None = None,
    chain_configs: dict[str, Any] | None = None,
    base_url: str | None = None,
    get_sqlite_client: SQLiteClientFactory,
    capacity: CapacityClientLike,
    stage_event: StageEventFn,
    provision_vm: ProvisionVmFn,
    schedule_shutdown: ScheduleShutdownFn,
    register_lease: RegisterLeaseFn,
    apply_failure_policy: ApplyFailurePolicyFn | None = None,
    held_reservation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Provision VM capacity and submit settlement fulfillment.

    ``held_reservation`` is the TTL soft hold the negotiation's
    acceptance placed (two-phase reserve). It is committed into a lease
    *before* provisioning starts — that removes the
    hold-expires-during-provisioning race entirely, and the post-provision
    commit below simply refreshes the lease window. A hold that already
    lapsed falls back to the plain atomic reserve.
    """
    fulfillment_uid = None
    connection_details: str | None = None
    reserved_capacity_reservation_id: str | None = None
    reserved_resource_id: str | None = None
    reserved_vm_host: str | None = None
    order_id: str | None = None
    vm_target = f"tenant-{uuid.uuid4().hex[:4]}"

    logger.info("[ALKAHEST] Order for fulfillment: %s", order)

    try:
        plan, recovery_context = await _build_vm_fulfillment_context(
            escrow_uid=escrow_uid, vm_target=vm_target,
            ssh_public_key=ssh_public_key, order=order,
            duration_seconds=duration_seconds, start_utc=start_utc,
            listing_id=listing_id, seller_order_id=seller_order_id,
            chain_configs=chain_configs,
        )
        order_id = plan.order_id
        required_attributes = plan.required_attributes
        await persist_escrow_fields_with_retry(
            get_sqlite_client, escrow_uid=escrow_uid,
            fulfillment_context=json.dumps(recovery_context, sort_keys=True),
            fulfillment_phase="context_persisted",
        )

        reserved = await _reserve_capacity_for_obligation(
            capacity=capacity, held_reservation=held_reservation,
            escrow_uid=escrow_uid, listing_id=listing_id, order_id=order_id,
            required_attributes=required_attributes,
            duration_seconds=duration_seconds, start_utc=start_utc,
            stage_event=stage_event,
        )
        reserved_capacity_reservation_id = (
            str(reserved.get("capacity_reservation_id")) if reserved.get("capacity_reservation_id") else None
        )
        # Not coerced with str(...): resource_id is an opaque placement
        # detail the capacity boundary does not guarantee at this point
        # (schedule_resource(), called by provision_vm below, is what
        # actually selects/confirms the settlement resource) -- str(None)
        # would silently become the three-character string "None", which
        # is worse than an absent value if anything ever persisted it.
        # Kept only as best-effort stage_event telemetry.
        reserved_resource_id = reserved.get("resource_id")
        # vm_host is unconditionally stripped from the reservation
        # response (kit/site's opaque-reservation boundary -- see
        # openspec/specs/site-capacity/spec.md); reserved.get("vm_host")
        # is therefore always None. Kept as a variable, not deleted,
        # because provision_vm/register_lease/schedule_shutdown already
        # treat it as an accepted-but-unused compatibility parameter
        # (documented on _do_provision and _register_vm_lease_with_settings)
        # -- removing it from every call site is a larger signature change
        # than stripping it from the API response requires.
        reserved_vm_host = reserved.get("vm_host")
        await persist_escrow_fields_with_retry(
            get_sqlite_client,
            escrow_uid=escrow_uid,
            capacity_reservation_id=reserved_capacity_reservation_id,
            fulfillment_phase="capacity_reserved",
        )
        stage_event(
            "provision", "resource_reserved",
            listing_id=order_id,
            escrow_uid=escrow_uid,
            pool_id=reserved.get("pool_id"),
            member_id=reserved.get("member_id"),
            resource_id=reserved_resource_id,
            required_attributes=required_attributes,
            capacity_reservation_id=reserved_capacity_reservation_id,
            allocated_gpu_count=reserved.get("allocated_gpu_count"),
        )
        # Stale derived listings are closed by the storefront's
        # capacity-delta subscriber (reacting to the reserve above), not
        # inline here — another storefront's reservation must trigger
        # the same reconciliation, so it can't live in this deal flow.

        start_dt = _parse_start_utc(start_utc)
        delay_seconds = (start_dt - datetime.now(timezone.utc)).total_seconds()
        if delay_seconds > 0:
            stage_event(
                "provision", "scheduled",
                listing_id=order_id,
                escrow_uid=escrow_uid,
                resource_id=reserved_resource_id,
                capacity_reservation_id=reserved_capacity_reservation_id,
                lease_start_utc=start_dt.isoformat(),
                delay_seconds=delay_seconds,
            )
            await asyncio.sleep(delay_seconds)

        async def _record_fulfillment_id(fulfillment_id: str) -> None:
            """Persist the durable fulfillment identity as soon as it's known.

            Named for what it now carries: ``provision_vm``'s
            ``on_job_submitted`` hook is invoked with a durable
            ``fulfillment_id`` (from ``begin_fulfillment``), not an
            ephemeral executor job id -- distinct from ``fulfillment_uid``
            (the on-chain settlement-claim identity), which may already be
            set on the same row. ``capacity_reservation_id`` is persisted
            alongside it here since both are durable and known by this
            point. This is identity persistence only -- nothing yet reads
            these values back to resume an in-progress fulfillment after a
            storefront restart; that capability does not exist yet.
            """
            await persist_escrow_fields_with_retry(
                get_sqlite_client,
                escrow_uid=escrow_uid,
                fulfillment_id=fulfillment_id,
                capacity_reservation_id=reserved_capacity_reservation_id,
            )
            stage_event(
                "provision", "job_submitted",
                listing_id=order_id,
                escrow_uid=escrow_uid,
                resource_id=reserved_resource_id,
                fulfillment_id=fulfillment_id,
            )

        provision_result = await provision_vm(
            ssh_public_key,
            vm_host=reserved_vm_host,
            vm_target=vm_target,
            capacity_reservation_id=reserved_capacity_reservation_id,
            escrow_uid=escrow_uid,
            on_job_submitted=_record_fulfillment_id,
        )
        authentication: dict[str, Any] | None = None
        if isinstance(provision_result, dict):
            authentication = provision_result.pop("authentication", None)
            connection_details = json.dumps(provision_result)
        else:
            connection_details = provision_result
    except Exception as error:
        if apply_failure_policy is not None:
            try:
                await apply_failure_policy(
                    capacity_reservation_id=reserved_capacity_reservation_id,
                    escrow_uid=escrow_uid,
                    listing_id=listing_id or order_id,
                    resource_id=reserved_resource_id,
                    reason="provisioning_failed",
                    message=str(error),
                    source="settlement_provisioning",
                )
            except Exception as policy_err:
                logger.warning(
                    "[FULFILLMENT_POLICY] Failed to apply provisioning failure "
                    "policy for escrow %s: %s",
                    escrow_uid,
                    policy_err,
                )
        logger.error(
            "[ALKAHEST] Provisioning failed, skipping obligation fulfillment: %s",
            error,
        )
        stage_event(
            "provision", "failed",
            escrow_uid=escrow_uid,
            resource_id=reserved_resource_id,
            error=str(error),
        )
        return {
            "status": "error",
            "message": f"Provisioning failed: {error}",
            "escrow_uid": escrow_uid,
            "connection_details": None,
            "ssh_public_key": ssh_public_key,
        }

    lease_start_utc, lease_end_utc = _lease_window_strings(
        start_utc=start_utc,
        duration_seconds=duration_seconds,
    )

    if reserved_capacity_reservation_id:
        # capacity_reservation_id is the durable identity commit() actually
        # needs; resource_id is accepted only for a resource-id-only lookup
        # path with no current caller (see CapacityLedgerService.commit's
        # docstring) and is never guaranteed present -- the opaque
        # capacity-reservation boundary negotiates on pooled capacity, not a
        # specific physical resource, so a real reservation response
        # legitimately omits it. Gating this refresh on resource_id would
        # skip the lease-window refresh for every ordinary pool-scoped
        # reservation, which is the common case, not an edge case.
        try:
            await capacity.commit(
                resource_id=reserved_resource_id,
                capacity_reservation_id=reserved_capacity_reservation_id,
                lease_start_utc=lease_start_utc,
                lease_end_utc=lease_end_utc,
                idempotency_ref=escrow_uid,
            )
        except Exception as lease_err:
            logger.warning(
                "[LOCAL DB] Failed to mark reservation %s as leased after provisioning: %s",
                reserved_capacity_reservation_id,
                lease_err,
            )

    cred_order_id = seller_order_id or order_id
    if authentication and cred_order_id:
        try:
            cred_client = get_sqlite_client()
            root_data = authentication.get("root", {}) or {}
            tenant_data = authentication.get("tenant", {}) or {}
            if root_data:
                await cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="root",
                    granted_to="self",
                    password=root_data.get("password"),
                    ssh_commands=(
                        json.dumps(root_data.get("ssh_commands"))
                        if root_data.get("ssh_commands") else None
                    ),
                    ssh_key_path_host=root_data.get("ssh_key_path_host"),
                )
            if tenant_data:
                await cred_client.store_credential(
                    listing_id=cred_order_id,
                    role="tenant",
                    granted_to="self",
                    password=tenant_data.get("password"),
                    ssh_commands=(
                        json.dumps(tenant_data.get("ssh_commands"))
                        if tenant_data.get("ssh_commands") else None
                    ),
                    key_type=tenant_data.get("key_type"),
                )
        except Exception as cred_err:
            logger.warning(
                "[LOCAL DB] Failed to store credentials for order %s: %s",
                cred_order_id,
                cred_err,
            )

    if reserved_capacity_reservation_id and vm_target and escrow_uid:
        # register_lease's downstream LeaseRegistration call does not read
        # resource_id/vm_host at all (executor_ref self-heals from the
        # commit-time-written reservation.vm_host instead -- see
        # openspec/specs/physical-provisioning/spec.md's lease-registration
        # requirement). Requiring them here would make lease registration,
        # and therefore the watchdog's ability to auto-release this VM,
        # depend on the negotiation having pinned a specific physical
        # resource -- which is the exception, not the ordinary pool-scoped
        # capacity-reservation case this path exists to serve.
        try:
            await register_lease(
                resource_id=reserved_resource_id,
                capacity_reservation_id=reserved_capacity_reservation_id,
                escrow_uid=escrow_uid,
                vm_host=reserved_vm_host,
                vm_target=vm_target,
                lease_start_utc=lease_start_utc,
                lease_end_utc=lease_end_utc,
            )
            logger.info(
                "[LEASE] Registered lease with provisioning service "
                "(reservation=%s escrow=%s expires=%s)",
                reserved_capacity_reservation_id, escrow_uid, lease_end_utc,
            )
        except Exception as lease_err:
            logger.warning(
                "[LEASE] Failed to register lease with provisioning service "
                "(reservation=%s escrow=%s): %s - watchdog will not auto-release "
                "this resource",
                reserved_capacity_reservation_id,
                escrow_uid,
                lease_err,
            )

    async def _schedule_shutdown_best_effort() -> None:
        try:
            await schedule_shutdown(
                lease_end_utc,
                vm_host=reserved_vm_host,
                vm_target=vm_target,
            )
        except Exception as shutdown_err:
            logger.warning(
                "[LEASE] Failed to schedule VM expiry with provisioning service "
                "(resource=%s escrow=%s vm=%s): %s",
                reserved_resource_id,
                escrow_uid,
                vm_target,
                shutdown_err,
            )

    asyncio.create_task(_schedule_shutdown_best_effort())

    try:
        fulfillment_uid = await submit_compute_fulfillment(
            client=client,
            escrow_uid=escrow_uid,
            connection_details=connection_details,
        )
    except Exception as error:
        logger.error(
            "[ALKAHEST] EVENT=settlement_failed_after_provisioning "
            "escrow_uid=%s listing_id=%s resource_id=%s capacity_reservation_id=%s "
            "error=%s",
            escrow_uid,
            order_id,
            reserved_resource_id,
            reserved_capacity_reservation_id,
            error,
        )
        stage_event(
            "settlement", "failed_after_provisioning",
            listing_id=order_id,
            escrow_uid=escrow_uid,
            resource_id=reserved_resource_id,
            capacity_reservation_id=reserved_capacity_reservation_id,
            error=str(error),
        )
        return {
            "status": "error",
            "message": f"On-chain fulfillment failed after provisioning: {error}",
            "escrow_uid": escrow_uid,
            "connection_details": None,
            "ssh_public_key": ssh_public_key,
        }

    if order_id:
        try:
            sqlite_client = get_sqlite_client()
            await sqlite_client.update_listing(
                listing_id=order_id,
                fulfillment_resource=connection_details,
            )
        except Exception as exc:
            logger.warning(
                "[LOCAL DB] Failed to update fulfillment for order %s: %s",
                order_id,
                exc,
            )
        if fulfillment_uid:
            try:
                await get_sqlite_client().update_escrow(
                    escrow_uid=escrow_uid,
                    fulfillment_uid=fulfillment_uid,
                )
            except Exception as exc:
                logger.warning(
                    "[LOCAL DB] Failed to record fulfillment_uid on escrow %s: %s",
                    escrow_uid,
                    exc,
                )

    tenant_auth = (authentication or {}).get("tenant", {}) or {}
    stage_event(
        "provision", "fulfilled",
        listing_id=order_id,
        escrow_uid=escrow_uid,
        fulfillment_uid=fulfillment_uid,
        resource_id=reserved_resource_id,
        capacity_reservation_id=reserved_capacity_reservation_id,
        lease_end_utc=lease_end_utc,
        seller_order_id=seller_order_id,
        order_id=order_id,
    )
    return {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "escrow_uid": escrow_uid,
        "fulfillment_uid": fulfillment_uid,
        "connection_details": connection_details,
        "ssh_public_key": ssh_public_key,
        "fulfilling_party_url": base_url,
        "tenant_credentials": {
            "password": tenant_auth.get("password"),
            "key_type": tenant_auth.get("key_type"),
        },
    }
