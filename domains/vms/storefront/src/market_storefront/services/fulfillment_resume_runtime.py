"""Restart-safe convergence for accepted VM storefront escrows.

The foreground settlement task normally drives fulfillment to completion. This
runtime recovers unfinished physical fulfillment after process interruption.
It deliberately treats local checkpoint persistence as best effort after deal
acceptance: delivery continues when external state is available, while failed
writes are logged for operator reconciliation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from compute_provisioning import FulfillmentRequestBody, FulfillmentScheduleRequest
from market_fulfillment import VersionedEnvelope

from market_storefront.services.capacity_client import (
    build_capacity_client,
    build_fulfillment_client,
)
from market_storefront.services.fulfillment_service import (
    _fulfillment_result_to_legacy_shape,
)
from market_storefront.services.vm_fulfillment_service import (
    _lease_window_strings,
    persist_escrow_fields_with_retry,
)
from market_storefront.utils.sqlite_client import SQLiteClient, get_sqlite_client

logger = logging.getLogger(__name__)

_TERMINAL_ESCROW_STATUSES = {"ready", "failed", "refunded"}


def _validated_context(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if envelope.get("kind") != "vm.storefront.fulfillment-context":
        return None
    if envelope.get("schema_version") != 1:
        return None
    payload = envelope.get("payload")
    return payload if isinstance(payload, dict) else None


async def _refresh_capacity_lease(
    *,
    escrow_uid: str,
    reservation_id: str,
    resource_id: str,
    lease_start_utc: str,
    lease_end_utc: str,
    capacity_client: Any,
) -> None:
    if capacity_client is None or not reservation_id or not resource_id:
        return
    try:
        await capacity_client.commit(
            resource_id=resource_id,
            capacity_reservation_id=reservation_id,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            idempotency_ref=escrow_uid,
        )
    except Exception:
        logger.exception(
            "[FULFILLMENT_RESUME] Lease refresh failed for escrow %s", escrow_uid
        )


async def _store_fulfillment_credentials(
    *,
    sqlite_client: SQLiteClient,
    escrow_uid: str,
    credential_listing_id: str | None,
    authentication: dict[str, Any] | None,
) -> None:
    if not authentication or not credential_listing_id:
        return
    for role in ("root", "tenant"):
        data = authentication.get(role) or {}
        if not data:
            continue
        try:
            await sqlite_client.store_credential(
                listing_id=str(credential_listing_id),
                role=role,
                granted_to="self",
                password=data.get("password"),
                ssh_commands=(
                    json.dumps(data.get("ssh_commands"))
                    if data.get("ssh_commands")
                    else None
                ),
                ssh_key_path_host=(
                    data.get("ssh_key_path_host") if role == "root" else None
                ),
                key_type=(data.get("key_type") if role == "tenant" else None),
            )
        except Exception:
            logger.exception(
                "[FULFILLMENT_RESUME] Credential storage failed for escrow %s role %s",
                escrow_uid,
                role,
            )


async def _register_recovered_vm_lease(
    *,
    register_lease: Callable[..., Awaitable[Any]] | None,
    escrow_uid: str,
    reservation_id: str,
    resource_id: str,
    vm_host: Any,
    vm_target: Any,
    lease_start_utc: str,
    lease_end_utc: str,
) -> None:
    if not (
        register_lease and reservation_id and resource_id and vm_host and vm_target
    ):
        return
    try:
        await register_lease(
            resource_id=resource_id,
            capacity_reservation_id=reservation_id,
            escrow_uid=escrow_uid,
            vm_host=str(vm_host),
            vm_target=str(vm_target),
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
        )
    except Exception:
        logger.exception(
            "[FULFILLMENT_RESUME] Provisioning lease registration failed for escrow %s",
            escrow_uid,
        )


async def _ensure_onchain_fulfillment(
    *,
    escrow: dict[str, Any],
    sqlite_client: SQLiteClient,
    submit_fulfillment: Callable[..., Awaitable[str]] | None,
    alkahest_client: Any | None,
    connection_json: str,
) -> str | None:
    fulfillment_uid = escrow.get("fulfillment_uid")
    if fulfillment_uid or submit_fulfillment is None:
        return str(fulfillment_uid) if fulfillment_uid else None
    escrow_uid = str(escrow["escrow_uid"])
    ambiguous = escrow.get("fulfillment_phase") == "onchain_submission_started"
    if not ambiguous:
        await persist_escrow_fields_with_retry(
            lambda: sqlite_client,
            escrow_uid=escrow_uid,
            fulfillment_phase="onchain_submission_started",
        )
    try:
        fulfillment_uid = await submit_fulfillment(
            client=alkahest_client,
            escrow_uid=escrow_uid,
            connection_details=connection_json,
            allow_submit=not ambiguous,
        )
    except TypeError:
        if ambiguous:
            raise
        fulfillment_uid = await submit_fulfillment(
            client=alkahest_client,
            escrow_uid=escrow_uid,
            connection_details=connection_json,
        )
    await persist_escrow_fields_with_retry(
        lambda: sqlite_client,
        escrow_uid=escrow_uid,
        fulfillment_uid=str(fulfillment_uid),
        fulfillment_phase="onchain_fulfilled",
    )
    return str(fulfillment_uid)


async def _update_fulfilled_listing(
    *,
    sqlite_client: SQLiteClient,
    escrow_uid: str,
    listing_id: Any,
    connection_json: str,
) -> None:
    if not listing_id:
        return
    try:
        await sqlite_client.update_listing(
            listing_id=str(listing_id), fulfillment_resource=connection_json
        )
    except Exception:
        logger.exception(
            "[FULFILLMENT_RESUME] Listing update failed for escrow %s", escrow_uid
        )


async def _mark_escrow_delivery_complete(
    *,
    sqlite_client: SQLiteClient,
    escrow_uid: str,
    fulfillment_uid: str | None,
    connection_json: str,
    authentication: dict[str, Any] | None,
) -> None:
    tenant = (authentication or {}).get("tenant") or {}
    await persist_escrow_fields_with_retry(
        lambda: sqlite_client,
        escrow_uid=escrow_uid,
        status="ready",
        fulfillment_uid=fulfillment_uid,
        connection_details=connection_json,
        tenant_credentials=json.dumps(
            {"password": tenant.get("password"), "key_type": tenant.get("key_type")},
            sort_keys=True,
        ),
        fulfillment_phase="complete",
    )


async def _bind_recovered_settlement_fulfillment(
    *,
    bind_fulfillment_fn: Callable[..., Awaitable[Any]] | None,
    escrow: dict[str, Any],
    fulfillment_uid: str | None,
) -> None:
    if bind_fulfillment_fn is None:
        return
    obligation_ref = escrow.get("obligation_ref")
    if not obligation_ref:
        raise RuntimeError(
            f"escrow {escrow.get('escrow_uid')} has no persisted settlement obligation"
        )
    if not fulfillment_uid:
        raise RuntimeError(
            f"escrow {escrow.get('escrow_uid')} has no immutable fulfillment UID"
        )
    await bind_fulfillment_fn(
        obligation_ref=str(obligation_ref),
        fulfillment_ref=str(fulfillment_uid),
    )


async def converge_post_physical_delivery(
    *,
    escrow: dict[str, Any],
    context: dict[str, Any],
    sqlite_client: SQLiteClient,
    capacity_client: Any,
    connection_details: dict[str, Any],
    authentication: dict[str, Any] | None,
    register_lease: Callable[..., Awaitable[Any]] | None = None,
    submit_fulfillment: Callable[..., Awaitable[str]] | None = None,
    bind_fulfillment_fn: Callable[..., Awaitable[Any]] | None = None,
    alkahest_client: Any | None = None,
) -> bool:
    """Converge the durable storefront effects after physical success."""
    escrow_uid = str(escrow["escrow_uid"])
    reservation_id = str(escrow.get("capacity_reservation_id") or "")
    resource_id = str(escrow.get("settlement_resource_id") or "")
    listing_id = context.get("listing_id")
    request = (context.get("fulfillment_request") or {}).get("payload") or {}
    lease_start_utc, lease_end_utc = _lease_window_strings(
        start_utc=context.get("start_utc"),
        duration_seconds=int(context.get("duration_seconds") or 3600),
    )
    await _refresh_capacity_lease(
        escrow_uid=escrow_uid,
        reservation_id=reservation_id,
        resource_id=resource_id,
        lease_start_utc=lease_start_utc,
        lease_end_utc=lease_end_utc,
        capacity_client=capacity_client,
    )
    await _store_fulfillment_credentials(
        sqlite_client=sqlite_client,
        escrow_uid=escrow_uid,
        credential_listing_id=context.get("seller_order_id") or listing_id,
        authentication=authentication,
    )
    await _register_recovered_vm_lease(
        register_lease=register_lease,
        escrow_uid=escrow_uid,
        reservation_id=reservation_id,
        resource_id=resource_id,
        vm_host=connection_details.get("host"),
        vm_target=request.get("vm_target"),
        lease_start_utc=lease_start_utc,
        lease_end_utc=lease_end_utc,
    )
    connection_json = json.dumps(connection_details, sort_keys=True)
    if (
        register_lease is None
        and submit_fulfillment is None
        and bind_fulfillment_fn is None
    ):
        return True
    fulfillment_uid = await _ensure_onchain_fulfillment(
        escrow=escrow,
        sqlite_client=sqlite_client,
        submit_fulfillment=submit_fulfillment,
        alkahest_client=alkahest_client,
        connection_json=connection_json,
    )
    await _bind_recovered_settlement_fulfillment(
        bind_fulfillment_fn=bind_fulfillment_fn,
        escrow=escrow,
        fulfillment_uid=fulfillment_uid,
    )
    await _update_fulfilled_listing(
        sqlite_client=sqlite_client,
        escrow_uid=escrow_uid,
        listing_id=listing_id,
        connection_json=connection_json,
    )
    await _mark_escrow_delivery_complete(
        sqlite_client=sqlite_client,
        escrow_uid=escrow_uid,
        fulfillment_uid=fulfillment_uid,
        connection_json=connection_json,
        authentication=authentication,
    )
    return True


async def _ensure_recovery_capacity(
    *,
    escrow_uid: str,
    context: dict[str, Any],
    sqlite_client: SQLiteClient,
    capacity_client: Any | None,
    reservation_id: Any,
    settlement_resource_id: Any,
) -> tuple[str | None, str | None]:
    if reservation_id:
        return str(reservation_id), (
            str(settlement_resource_id) if settlement_resource_id else None
        )
    if capacity_client is None:
        logger.warning(
            "[FULFILLMENT_RESUME] Escrow %s requires capacity reconciliation",
            escrow_uid,
        )
        return None, None
    from domains.vms.listings.reconciler import site_id_for_listing

    listing_id = context.get("listing_id")
    site_id = (
        site_id_for_listing(sqlite_client.db_path, listing_id) if listing_id else None
    )
    try:
        reserved = await capacity_client.reserve(
            claim=context.get("required_attributes") or None,
            deal_ref={"listing_id": listing_id, "escrow_uid": escrow_uid},
            lease_start_utc=context.get("start_utc"),
            lease_duration_seconds=int(context.get("duration_seconds") or 3600),
            site=site_id,
        )
    except Exception as exc:
        if site_id is None:
            raise
        # A mapped listing's site errored (not just refused) -- no
        # fallback exists to try, so this surfaces the same way a
        # refusal already does below rather than as a new, unhandled
        # exception shape during resume.
        logger.warning(
            "[FULFILLMENT_RESUME] reserve at pinned site %r failed for escrow %s: %s",
            site_id,
            escrow_uid,
            exc,
        )
        reserved = None
    if not reserved or not reserved.get("capacity_reservation_id"):
        raise RuntimeError(
            f"No capacity available while recovering escrow {escrow_uid}"
        )
    reservation = str(reserved["capacity_reservation_id"])
    resource = str(reserved["resource_id"]) if reserved.get("resource_id") else None
    await persist_escrow_fields_with_retry(
        lambda: sqlite_client,
        escrow_uid=escrow_uid,
        capacity_reservation_id=reservation,
        settlement_resource_id=resource,
        fulfillment_phase="capacity_reserved",
    )
    return reservation, None


async def _ensure_recovery_fulfillment_started(
    *,
    escrow_uid: str,
    request_envelope: dict[str, Any],
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    reservation_id: str,
    settlement_resource_id: str | None,
    fulfillment_id: Any,
) -> tuple[str, str | None]:
    resource_id = settlement_resource_id
    if fulfillment_id:
        return str(fulfillment_id), resource_id
    if not resource_id:
        scheduled = await fulfillment_client.schedule_resource(
            FulfillmentScheduleRequest(
                capacity_reservation_id=reservation_id, market="vms"
            )
        )
        resource_id = str(scheduled.settlement_resource_id)
        await persist_escrow_fields_with_retry(
            lambda: sqlite_client,
            escrow_uid=escrow_uid,
            capacity_reservation_id=reservation_id,
            settlement_resource_id=resource_id,
            fulfillment_phase="resource_scheduled",
        )
    accepted = await fulfillment_client.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=reservation_id,
            market="vms",
            fulfillment_request=VersionedEnvelope.model_validate(request_envelope),
        )
    )
    fid = str(accepted.fulfillment_id)
    await persist_escrow_fields_with_retry(
        lambda: sqlite_client,
        escrow_uid=escrow_uid,
        capacity_reservation_id=reservation_id,
        settlement_resource_id=resource_id,
        fulfillment_id=fid,
        fulfillment_phase="fulfillment_accepted",
    )
    return fid, resource_id


async def _load_active_physical_result(
    *,
    escrow_uid: str,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    fulfillment_id: str,
    reservation_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    status = await fulfillment_client.get_fulfillment_status(
        fulfillment_id, capacity_reservation_id=reservation_id
    )
    if status.state == "failed":
        await persist_escrow_fields_with_retry(
            lambda: sqlite_client,
            escrow_uid=escrow_uid,
            status="failed",
            reason=status.failure_message or "physical fulfillment failed",
            fulfillment_phase="physical_failed",
        )
        return ({"__failed__": True}, None)
    if status.state != "active":
        return None
    result_envelope = await fulfillment_client.get_fulfillment_result(
        fulfillment_id, capacity_reservation_id=reservation_id
    )
    legacy = _fulfillment_result_to_legacy_shape(result_envelope)
    authentication = legacy.pop("authentication", None)
    await persist_escrow_fields_with_retry(
        lambda: sqlite_client,
        escrow_uid=escrow_uid,
        connection_details=json.dumps(legacy, sort_keys=True),
        tenant_credentials=(
            json.dumps((authentication or {}).get("tenant") or {}, sort_keys=True)
            if authentication
            else None
        ),
        fulfillment_phase="physical_result_recorded",
    )
    return legacy, authentication


async def converge_escrow_once(
    escrow: dict[str, Any],
    *,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    capacity_client: Any | None = None,
    register_lease: Callable[..., Awaitable[Any]] | None = None,
    submit_fulfillment: Callable[..., Awaitable[str]] | None = None,
    bind_fulfillment_fn: Callable[..., Awaitable[Any]] | None = None,
    alkahest_client: Any | None = None,
) -> bool:
    """Advance one escrow by at most one externally observable phase."""
    if escrow.get("status") in _TERMINAL_ESCROW_STATUSES:
        return False
    context = _validated_context(escrow.get("fulfillment_context"))
    if context is None:
        logger.error(
            "[FULFILLMENT_RESUME] Escrow %s has no supported recovery context",
            escrow.get("escrow_uid"),
        )
        return False
    escrow_uid = str(escrow["escrow_uid"])
    request_envelope = context.get("fulfillment_request")
    if not escrow.get("fulfillment_id") and not isinstance(request_envelope, dict):
        logger.error(
            "[FULFILLMENT_RESUME] Escrow %s recovery context has no fulfillment request",
            escrow_uid,
        )
        return False
    reservation_id, resource_id = await _ensure_recovery_capacity(
        escrow_uid=escrow_uid,
        context=context,
        sqlite_client=sqlite_client,
        capacity_client=capacity_client,
        reservation_id=escrow.get("capacity_reservation_id"),
        settlement_resource_id=escrow.get("settlement_resource_id"),
    )
    if not reservation_id:
        return False
    fulfillment_id, resource_id = await _ensure_recovery_fulfillment_started(
        escrow_uid=escrow_uid,
        request_envelope=request_envelope or {},
        sqlite_client=sqlite_client,
        fulfillment_client=fulfillment_client,
        reservation_id=reservation_id,
        settlement_resource_id=resource_id,
        fulfillment_id=escrow.get("fulfillment_id"),
    )
    physical = await _load_active_physical_result(
        escrow_uid=escrow_uid,
        sqlite_client=sqlite_client,
        fulfillment_client=fulfillment_client,
        fulfillment_id=fulfillment_id,
        reservation_id=reservation_id,
    )
    if physical is None:
        return False
    connection_details, authentication = physical
    if connection_details.pop("__failed__", False):
        return True
    current = dict(escrow)
    current.update(
        {
            "capacity_reservation_id": reservation_id,
            "settlement_resource_id": resource_id,
            "fulfillment_id": fulfillment_id,
        }
    )
    return await converge_post_physical_delivery(
        escrow=current,
        context=context,
        sqlite_client=sqlite_client,
        capacity_client=capacity_client,
        connection_details=connection_details,
        authentication=authentication,
        register_lease=register_lease,
        submit_fulfillment=submit_fulfillment,
        bind_fulfillment_fn=bind_fulfillment_fn,
        alkahest_client=alkahest_client,
    )


async def resume_incomplete_fulfillments_once(
    *,
    sqlite_client: SQLiteClient | None = None,
    fulfillment_client: Any | None = None,
    capacity_client: Any | None = None,
    limit: int = 50,
    owner: str | None = None,
    lease_seconds: int = 60,
    register_lease: Callable[..., Awaitable[Any]] | None = None,
    submit_fulfillment: Callable[..., Awaitable[str]] | None = None,
    bind_fulfillment_fn: Callable[..., Awaitable[Any]] | None = None,
    alkahest_client: Any | None = None,
) -> int:
    """Run one bounded recovery sweep and return the number progressed."""
    db = sqlite_client or get_sqlite_client()
    capacity = capacity_client or build_capacity_client(lambda: db)
    remote = fulfillment_client or build_fulfillment_client(capacity)
    worker = owner or f"fulfillment-resume:{uuid.uuid4()}"
    if register_lease is None or submit_fulfillment is None:
        from domains.vms.settlement.fulfillment import (
            reconcile_or_submit_compute_fulfillment,
        )

        from market_storefront.services.fulfillment_service import (
            _register_vm_lease_with_settings,
        )

        register_lease = register_lease or _register_vm_lease_with_settings
        submit_fulfillment = (
            submit_fulfillment or reconcile_or_submit_compute_fulfillment
        )
    if bind_fulfillment_fn is None:
        from market_storefront import container

        composition = container.resolved_settlement_composition
        if composition is None:
            raise RuntimeError("settlement composition was not initialized")

        async def bind_fulfillment_fn(
            *, obligation_ref: str, fulfillment_ref: str
        ) -> None:
            await composition.runtime.bind_fulfillment(
                obligation_ref,
                fulfillment_ref,
                local_role="seller",
            )
            await composition.worker.wake(obligation_ref)

    progressed = 0
    for escrow in await db.list_incomplete_primary_escrows(limit=limit):
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        ).isoformat()
        claimed = await db.claim_escrow_convergence(
            escrow_uid=str(escrow["escrow_uid"]), owner=worker, lease_until=lease_until
        )
        if not claimed:
            continue
        try:
            escrow_chain_client = alkahest_client
            if escrow_chain_client is None and escrow.get("chain_name"):
                try:
                    from market_storefront import container

                    escrow_chain_client = container.get_alkahest_client(
                        str(escrow["chain_name"])
                    )
                except Exception:
                    logger.exception(
                        "[FULFILLMENT_RESUME] Could not build chain client for escrow %s",
                        escrow.get("escrow_uid"),
                    )
                    continue
            if await converge_escrow_once(
                escrow,
                sqlite_client=db,
                fulfillment_client=remote,
                capacity_client=capacity,
                register_lease=register_lease,
                submit_fulfillment=submit_fulfillment,
                bind_fulfillment_fn=bind_fulfillment_fn,
                alkahest_client=escrow_chain_client,
            ):
                progressed += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[FULFILLMENT_RESUME] Failed to converge escrow %s",
                escrow.get("escrow_uid"),
            )
        finally:
            await db.release_escrow_convergence(
                escrow_uid=str(escrow["escrow_uid"]), owner=worker
            )
    return progressed


async def fulfillment_resume_loop() -> None:
    """Periodically sweep unfinished accepted VM escrows."""
    from market_storefront.utils.config import settings

    interval = float(getattr(settings, "fulfillment_resume_sweep_interval", 30))
    db = SQLiteClient(get_sqlite_client().db_path)
    while True:
        await resume_incomplete_fulfillments_once(sqlite_client=db)
        await asyncio.sleep(interval)
