"""Restart-safe convergence for accepted VM storefront deliveries.

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
from functools import partial
from typing import Any

from compute_provisioning_contracts import (
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
)
from market_core import SettlementEvidence, VersionedEnvelope
from market_fulfillment import (
    FULFILLMENT_RESULT_KIND,
    FULFILLMENT_RESULT_SCHEMA_VERSION,
    FulfillmentResultPayload,
)

from market_storefront import container as _container
from market_storefront.lifecycle import FULFILLMENT_RESUME, gate, idle
from market_storefront.services.capacity_client import (
    build_capacity_client,
    build_fulfillment_client,
)
from market_storefront.services.fulfillment_service import (
    _fulfillment_result_to_connection,
)
from market_storefront.services.vm_fulfillment_planner import (
    VERIFIED_EVIDENCE_STATUSES,
    build_vm_fulfillment_plan,
)
from market_storefront.services.vm_fulfillment_service import (
    _lease_window_strings,
    persist_delivery_fields_with_retry,
)
from market_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

_TERMINAL_DELIVERY_STATUSES = {"ready", "failed", "refunded"}


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


async def _commit_recovered_reservation(
    *,
    negotiation_id: str,
    reservation_id: str,
    context: dict[str, Any],
    capacity_client: Any,
    site_id: str,
) -> None:
    """Commit the deal's reservation before its fulfillment begins.

    A recovered deal's reservation may never have been committed: a fresh
    recovery reserve is not, and the settlement path can stop between
    reserving and committing. A lease with no negotiated start begins at
    commit, so the deal's window starts here; a reservation already committed
    keeps the window its first commit recorded, since a repeat commit leaves it
    unchanged. The commit also names the deal. A failed commit raises, so the
    pass stops before provisioning and the next one retries.
    """
    if capacity_client is None:
        return
    lease_start_utc, lease_end_utc = _lease_window_strings(
        start_utc=context.get("start_utc"),
        duration_seconds=int(context.get("duration_seconds") or 3600),
    )
    await capacity_client.commit(
        capacity_reservation_id=reservation_id,
        lease_start_utc=lease_start_utc,
        lease_end_utc=lease_end_utc,
        idempotency_ref=negotiation_id,
        deal_ref={"negotiation_id": negotiation_id},
        site_id=site_id,
    )


async def _store_fulfillment_credentials(
    *,
    sqlite_client: SQLiteClient,
    negotiation_id: str,
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
                # A delivery carries each credential's allowlisted fields only:
                # no key path on a provisioner host, and no commands.
                key_type=data.get("key_type"),
            )
        except Exception:
            logger.exception(
                "[FULFILLMENT_RESUME] Credential storage failed for negotiation %s role %s",
                negotiation_id,
                role,
            )


async def _update_fulfilled_listing(
    *,
    sqlite_client: SQLiteClient,
    negotiation_id: str,
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
            "[FULFILLMENT_RESUME] Listing update failed for negotiation %s",
            negotiation_id,
        )


async def _mark_delivery_complete(
    *,
    sqlite_client: SQLiteClient,
    negotiation_id: str,
    fulfillment_uid: str | None,
    connection_json: str,
    authentication: dict[str, Any] | None,
) -> None:
    tenant = (authentication or {}).get("tenant") or {}
    await persist_delivery_fields_with_retry(
        lambda: sqlite_client,
        negotiation_id=negotiation_id,
        status="ready",
        fulfillment_uid=fulfillment_uid,
        connection_details=connection_json,
        tenant_credentials=json.dumps(
            {"password": tenant.get("password"), "key_type": tenant.get("key_type")},
            sort_keys=True,
        ),
        fulfillment_phase="complete",
    )


async def converge_post_physical_delivery(
    *,
    delivery: dict[str, Any],
    context: dict[str, Any],
    sqlite_client: SQLiteClient,
    capacity_client: Any,
    connection_details: dict[str, Any],
    authentication: dict[str, Any] | None,
    continuation: Callable[..., Awaitable[str]] | None = None,
) -> bool:
    """Converge the durable storefront effects after physical success.

    The lease needs nothing here: its window was recorded at commit, before
    the fulfillment began, and provisioning recorded its target when the
    fulfillment became active.
    """
    negotiation_id = str(delivery["negotiation_id"])
    listing_id = context.get("listing_id")
    await _store_fulfillment_credentials(
        sqlite_client=sqlite_client,
        negotiation_id=negotiation_id,
        credential_listing_id=context.get("seller_order_id") or listing_id,
        authentication=authentication,
    )
    connection_json = json.dumps(connection_details, sort_keys=True)
    if continuation is None:
        return True
    fulfillment_uid = await continuation(
        delivery=delivery, connection_json=connection_json
    )
    await _update_fulfilled_listing(
        sqlite_client=sqlite_client,
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        connection_json=connection_json,
    )
    await _mark_delivery_complete(
        sqlite_client=sqlite_client,
        negotiation_id=negotiation_id,
        fulfillment_uid=fulfillment_uid,
        connection_json=connection_json,
        authentication=authentication,
    )
    return True


async def _ensure_recovery_capacity(
    *,
    negotiation_id: str,
    context: dict[str, Any],
    sqlite_client: SQLiteClient,
    capacity_client: Any | None,
    reservation_id: Any,
    settlement_resource_id: Any,
    thread_binding: Any,
) -> tuple[str | None, str | None]:
    if reservation_id:
        return str(reservation_id), (
            str(settlement_resource_id) if settlement_resource_id else None
        )
    if capacity_client is None:
        logger.warning(
            "[FULFILLMENT_RESUME] Negotiation %s requires capacity reconciliation",
            negotiation_id,
        )
        return None, None
    listing_id = thread_binding.listing_id
    site_id = thread_binding.site_id
    if context.get("listing_id") not in (None, listing_id):
        raise RuntimeError("recovery context listing disagrees with accepted binding")
    claim = dict(context.get("required_attributes") or {})
    claimed_mode = claim.get("offering_mode")
    if claimed_mode not in (None, thread_binding.binding.offering_mode):
        raise RuntimeError("recovery context offering mode disagrees with binding")
    claim["offering_mode"] = thread_binding.binding.offering_mode
    try:
        reserved = await capacity_client.reserve(
            claim=claim,
            deal_ref={"listing_id": listing_id, "negotiation_id": negotiation_id},
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
            "[FULFILLMENT_RESUME] reserve at pinned site %r failed for negotiation %s: %s",
            site_id,
            negotiation_id,
            exc,
        )
        reserved = None
    if not reserved or not reserved.get("capacity_reservation_id"):
        raise RuntimeError(
            f"No capacity available while recovering negotiation {negotiation_id}"
        )
    reservation = str(reserved["capacity_reservation_id"])
    resource = str(reserved["resource_id"]) if reserved.get("resource_id") else None
    await persist_delivery_fields_with_retry(
        lambda: sqlite_client,
        negotiation_id=negotiation_id,
        capacity_reservation_id=reservation,
        settlement_resource_id=resource,
        fulfillment_phase="capacity_reserved",
    )
    return reservation, None


async def _ensure_recovery_fulfillment_started(
    *,
    negotiation_id: str,
    request_envelope: dict[str, Any],
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    reservation_id: str,
    settlement_resource_id: str | None,
    fulfillment_id: Any,
    site_id: str,
) -> tuple[str, str | None]:
    resource_id = settlement_resource_id
    if fulfillment_id:
        return str(fulfillment_id), resource_id
    if not resource_id:
        scheduled = await fulfillment_client.schedule_resource(
            FulfillmentScheduleRequest(
                capacity_reservation_id=reservation_id, market="vms"
            ),
            site_id=site_id,
        )
        resource_id = str(scheduled.settlement_resource_id)
        await persist_delivery_fields_with_retry(
            lambda: sqlite_client,
            negotiation_id=negotiation_id,
            capacity_reservation_id=reservation_id,
            settlement_resource_id=resource_id,
            fulfillment_phase="resource_scheduled",
        )
    accepted = await fulfillment_client.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=reservation_id,
            market="vms",
            fulfillment_request=VersionedEnvelope.model_validate(request_envelope),
        ),
        site_id=site_id,
    )
    fid = str(accepted.fulfillment_id)
    await persist_delivery_fields_with_retry(
        lambda: sqlite_client,
        negotiation_id=negotiation_id,
        capacity_reservation_id=reservation_id,
        settlement_resource_id=resource_id,
        fulfillment_id=fid,
        fulfillment_phase="fulfillment_accepted",
    )
    return fid, resource_id


async def _load_active_physical_result(
    *,
    negotiation_id: str,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    fulfillment_id: str,
    reservation_id: str,
    site_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None] | None:
    status = await fulfillment_client.get_fulfillment_status(
        fulfillment_id,
        capacity_reservation_id=reservation_id,
        site_id=site_id,
    )
    if status.state == "failed":
        await persist_delivery_fields_with_retry(
            lambda: sqlite_client,
            negotiation_id=negotiation_id,
            status="failed",
            reason=status.failure_message or "physical fulfillment failed",
            fulfillment_phase="physical_failed",
        )
        return ({"__failed__": True, "failure_message": status.failure_message}, None)
    if status.state != "active":
        return None
    result_envelope = await fulfillment_client.get_fulfillment_result(
        fulfillment_id,
        capacity_reservation_id=reservation_id,
        site_id=site_id,
    )
    if (
        result_envelope.kind != FULFILLMENT_RESULT_KIND
        or result_envelope.schema_version != FULFILLMENT_RESULT_SCHEMA_VERSION
    ):
        raise RuntimeError(
            "physical fulfillment returned an unsupported result envelope"
        )
    try:
        result_payload = FulfillmentResultPayload.model_validate(
            result_envelope.payload
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "physical fulfillment returned a malformed result payload"
        ) from exc
    if (
        result_payload.fulfillment_id != fulfillment_id
        or result_payload.capacity_reservation_id != reservation_id
        or result_payload.state != "active"
    ):
        raise RuntimeError(
            "physical fulfillment result disagrees with active lifecycle"
        )
    connection = _fulfillment_result_to_connection(result_envelope)
    authentication = connection.pop("authentication", None)
    checkpoint = await sqlite_client.load_vm_delivery(negotiation_id=negotiation_id)
    phase = checkpoint.get("fulfillment_phase")
    await persist_delivery_fields_with_retry(
        lambda: sqlite_client,
        negotiation_id=negotiation_id,
        connection_details=json.dumps(connection, sort_keys=True),
        tenant_credentials=(
            json.dumps((authentication or {}).get("tenant") or {}, sort_keys=True)
            if authentication
            else None
        ),
        fulfillment_phase=(
            phase
            if phase in ("onchain_submission_started", "onchain_fulfilled")
            else "physical_result_recorded"
        ),
    )
    return connection, authentication


async def converge_delivery_once(
    delivery: dict[str, Any],
    *,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any,
    capacity_client: Any | None = None,
    evidence: SettlementEvidence,
    continuation: Callable[..., Awaitable[str]] | None = None,
    failure_policy: Callable[..., Awaitable[Any]] | None = None,
) -> bool:
    """Advance one delivery by at most one externally observable phase."""
    if delivery.get("status") in _TERMINAL_DELIVERY_STATUSES:
        return False
    context = _validated_context(delivery.get("fulfillment_context"))
    if context is None:
        logger.error(
            "[FULFILLMENT_RESUME] Negotiation %s has no supported recovery context",
            delivery.get("negotiation_id"),
        )
        return False
    plan = build_vm_fulfillment_plan(evidence=evidence)
    if (
        evidence.negotiation_id != delivery["negotiation_id"]
        or context.get("settlement_ref") != evidence.settlement_ref
        or context.get("agreement_sha256") != evidence.evidence["agreement_sha256"]
        or context.get("listing_id") != plan.order_id
        or context.get("required_attributes") != plan.required_attributes
        or context.get("duration_seconds") != plan.duration_seconds
        or context.get("start_utc") != plan.start_utc
    ):
        raise ValueError("delivery context differs from verified evidence")
    raw_context = json.loads(delivery["fulfillment_context"])
    negotiation_id = delivery.get("negotiation_id")
    if not negotiation_id:
        raise RuntimeError(
            f"negotiation {delivery.get('negotiation_id')!r} has no negotiation"
        )
    thread_binding = await sqlite_client.validate_fulfillment_context_binding(
        negotiation_id=str(negotiation_id),
        context=raw_context,
        registry=sqlite_client.domain_registry,
    )
    site_id = thread_binding.site_id
    negotiation_id = str(delivery["negotiation_id"])
    request_envelope = context.get("fulfillment_request")
    if not delivery.get("fulfillment_id") and not isinstance(request_envelope, dict):
        logger.error(
            "[FULFILLMENT_RESUME] Negotiation %s recovery context has no fulfillment request",
            negotiation_id,
        )
        return False
    if (
        isinstance(request_envelope, dict)
        and (request_envelope.get("payload") or {}).get("ssh_pubkey")
        != plan.provision_terms.ssh_public_key
    ):
        raise ValueError("delivery SSH key differs from verified evidence")
    reservation_id, resource_id = await _ensure_recovery_capacity(
        negotiation_id=negotiation_id,
        context=context,
        sqlite_client=sqlite_client,
        capacity_client=capacity_client,
        reservation_id=delivery.get("capacity_reservation_id"),
        settlement_resource_id=delivery.get("settlement_resource_id"),
        thread_binding=thread_binding,
    )
    if not reservation_id:
        return False
    if not delivery.get("fulfillment_id"):
        await _commit_recovered_reservation(
            negotiation_id=negotiation_id,
            reservation_id=reservation_id,
            context=context,
            capacity_client=capacity_client,
            site_id=site_id,
        )
    fulfillment_id, resource_id = await _ensure_recovery_fulfillment_started(
        negotiation_id=negotiation_id,
        request_envelope=request_envelope or {},
        sqlite_client=sqlite_client,
        fulfillment_client=fulfillment_client,
        reservation_id=reservation_id,
        settlement_resource_id=resource_id,
        fulfillment_id=delivery.get("fulfillment_id"),
        site_id=site_id,
    )
    sqlite_client.domain_registry.resolve(thread_binding.binding)
    physical = await _load_active_physical_result(
        negotiation_id=negotiation_id,
        sqlite_client=sqlite_client,
        fulfillment_client=fulfillment_client,
        fulfillment_id=fulfillment_id,
        reservation_id=reservation_id,
        site_id=site_id,
    )
    if physical is None:
        return False
    connection_details, authentication = physical
    if connection_details.pop("__failed__", False):
        if failure_policy is not None:
            await failure_policy(
                negotiation_id=negotiation_id,
                listing_id=plan.order_id,
                capacity_reservation_id=reservation_id,
                resource_id=resource_id,
                reason="provisioning_failed",
                message=connection_details.get("failure_message"),
                source="fulfillment_resume",
            )
        return True
    current = dict(delivery)
    current.update(
        {
            "capacity_reservation_id": reservation_id,
            "settlement_resource_id": resource_id,
            "fulfillment_id": fulfillment_id,
        }
    )
    return await converge_post_physical_delivery(
        delivery=current,
        context=context,
        sqlite_client=sqlite_client,
        capacity_client=capacity_client,
        connection_details=connection_details,
        authentication=authentication,
        continuation=continuation,
    )


async def resume_incomplete_fulfillments_once(
    *,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any | None = None,
    capacity_client: Any | None = None,
    limit: int = 50,
    owner: str | None = None,
    lease_seconds: int = 60,
    composition: Any | None = None,
) -> int:
    """Reconstruct selected continuations, revalidate sources, and resume delivery."""
    db = sqlite_client
    composition = composition or _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    capacity = capacity_client or build_capacity_client(lambda: db)
    remote = fulfillment_client or build_fulfillment_client(capacity)
    worker = owner or f"fulfillment-resume:{uuid.uuid4()}"
    progressed = 0
    for delivery in await db.list_incomplete_vm_deliveries(limit=limit):
        negotiation_id = delivery["negotiation_id"]
        claimed = await db.claim_vm_delivery(
            negotiation_id=negotiation_id,
            owner=worker,
            lease_until=(
                datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
            ).isoformat(),
        )
        if not claimed:
            continue
        try:
            evidence = await db.load_vm_settlement_evidence(
                negotiation_id=negotiation_id
            )
            thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            # A delivery that started before a refund still completes; its
            # evidence keeps the verified facts while the status records the refund.
            if (
                evidence is None
                or evidence.status not in VERIFIED_EVIDENCE_STATUSES
                or thread is None
            ):
                continue
            agreement = json.loads(thread["agreement_bytes"])
            stage = composition.seller_stages[agreement["settlement"]["mechanism"]]
            await stage.recover_evidence(
                evidence=evidence, thread=thread, composition=composition, db=db
            )
            continuation = partial(
                stage.continue_delivery,
                evidence=evidence,
                db=db,
                composition=composition,
            )
            if await converge_delivery_once(
                delivery,
                evidence=evidence,
                continuation=continuation,
                failure_policy=partial(stage.delivery_failed, evidence=evidence, db=db),
                sqlite_client=db,
                fulfillment_client=remote,
                capacity_client=capacity,
            ):
                progressed += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[FULFILLMENT_RESUME] Failed to converge negotiation %s", negotiation_id
            )
        finally:
            await db.release_vm_delivery(negotiation_id=negotiation_id, owner=worker)
    return progressed


#: Cadence for re-reading a held gate; idle work only.
_PAUSED_POLL_SECONDS = 0.05


async def _reconcile_payment_deals() -> None:
    """Advance accepted payment deals a buyer has not settled (none without payments)."""
    composition = _container.resolved_settlement_composition
    coordinator = getattr(composition, "payments_coordinator", None)
    if coordinator is not None:
        await coordinator.reconcile_once()


async def fulfillment_resume_loop(sqlite_client: SQLiteClient) -> None:
    """Periodically sweep unfinished accepted VM deliveries."""
    from market_storefront.utils.config import settings

    interval = float(getattr(settings, "fulfillment_resume_sweep_interval", 30))
    db = sqlite_client
    while True:
        try:
            # Checked before the sweep, not during: a paused storefront must not
            # be part-way through re-driving a delivery when a scenario reads
            # its state.
            if gate(FULFILLMENT_RESUME):
                await asyncio.sleep(_PAUSED_POLL_SECONDS)
                continue
            await resume_incomplete_fulfillments_once(sqlite_client=db)
            await _reconcile_payment_deals()
        except asyncio.CancelledError:
            logger.info("[FULFILLMENT_RESUME] cancelled, shutting down")
            break
        except Exception:
            # A cycle that raises must not end the loop. The per-delivery handler
            # inside the sweep contains its own failures; this catches the ones
            # outside it -- listing the incomplete deliveries, or building a client
            # -- which would otherwise stop the resume worker for the life of
            # the process with no further sweep and no recovery.
            logger.exception("[FULFILLMENT_RESUME] sweep failed; continuing")
        # Through the controller, so a pause requested during the interval
        # reaches the gate at once rather than after it.
        await idle(interval)
