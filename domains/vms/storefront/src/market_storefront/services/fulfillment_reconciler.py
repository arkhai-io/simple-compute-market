"""Restart-safe VM storefront orchestration over durable fulfillment APIs."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from compute_provisioning import (
    FulfillmentBeginRequest,
    FulfillmentResultView,
    FulfillmentScheduleRequest,
)
from core_storefront.capacity_remote import RemoteCapacityClient
from domains.vms.settlement import submit_compute_fulfillment

from market_storefront.services.provisioning_sites import (
    compute_client_for_site,
    require_provisioning_site,
)

logger = logging.getLogger(__name__)

_FAILED_STATES = {"failed", "abandoned", "teardown_failed", "torn_down"}


def _lease_window(thread: dict[str, Any], listing: dict[str, Any]) -> tuple[str, str]:
    duration = int(
        thread.get("agreed_duration_seconds")
        or thread.get("requested_duration_seconds")
        or listing.get("max_duration_seconds")
        or 3600
    )
    raw_start = thread.get("requested_start_utc")
    if raw_start:
        start = datetime.fromisoformat(str(raw_start).replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    else:
        start = datetime.now(timezone.utc)
    return start.isoformat(), (start + timedelta(seconds=duration)).isoformat()


class StorefrontFulfillmentReconciler:
    def __init__(self, *, sqlite_client: Any, worker_id: str | None = None) -> None:
        self._db = sqlite_client
        self._worker_id = worker_id or f"storefront-{uuid.uuid4()}"

    async def _fail(self, workflow: dict[str, Any], reason: str) -> None:
        await self._db.update_fulfillment_workflow(
            escrow_uid=workflow["escrow_uid"],
            phase="failed",
            last_reconcile_error=reason,
            failure_message=reason,
            claimed_by=None,
            claim_expires_unix=None,
        )
        await self._db.update_escrow(
            escrow_uid=workflow["escrow_uid"], status="failed", reason=reason
        )

    async def _advance(
        self, workflow: dict[str, Any], *, phase: str, **updates: Any
    ) -> None:
        await self._db.update_fulfillment_workflow(
            escrow_uid=workflow["escrow_uid"],
            phase=phase,
            next_reconcile_unix=None,
            last_reconcile_error=None,
            claimed_by=None,
            claim_expires_unix=None,
            **updates,
        )

    async def _settlement_context(
        self, escrow_uid: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        escrow = await self._db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise RuntimeError(f"escrow {escrow_uid!r} is missing")
        thread = await self._db.load_negotiation_thread_row(
            negotiation_id=escrow["negotiation_id"]
        )
        if thread is None:
            raise RuntimeError("fulfillment negotiation is missing")
        listing_id = thread.get("our_listing_id")
        listing = await self._db.load_listing(listing_id=listing_id)
        if listing is None:
            raise RuntimeError("fulfillment listing is missing")
        return escrow, thread, listing

    async def reconcile_one(self, workflow: dict[str, Any]) -> None:
        escrow_uid = str(workflow["escrow_uid"])
        site_id = str(workflow["site_id"])
        phase = str(workflow["phase"])
        binding = require_provisioning_site(site_id)

        if phase == "reserved":
            request = FulfillmentScheduleRequest.model_validate(
                workflow["schedule_request"]
            )
            async with compute_client_for_site(site_id) as client:
                selected = await client.schedule_resource(request)
            await self._advance(
                workflow,
                phase="scheduled",
                settlement_resource=selected.model_dump(mode="json"),
            )
            return

        if phase == "scheduled":
            selected = dict(workflow["settlement_resource"] or {})
            if not selected.get("settlement_resource_id"):
                raise RuntimeError("scheduled workflow has no selected resource")
            _, thread, listing = await self._settlement_context(escrow_uid)
            lease_start, lease_end = _lease_window(thread, listing)
            capacity = RemoteCapacityClient(binding.base_url, binding.admin_key)
            await capacity.commit(
                resource_id=str(selected["settlement_resource_id"]),
                capacity_reservation_id=str(workflow["capacity_reservation_id"]),
                lease_start_utc=lease_start,
                lease_end_utc=lease_end,
                idempotency_ref=escrow_uid,
            )
            await self._advance(workflow, phase="committed")
            return

        if phase == "committed":
            request = FulfillmentBeginRequest.model_validate(workflow["begin_request"])
            async with compute_client_for_site(site_id) as client:
                accepted = await client.begin_fulfillment(request)
            await self._advance(
                workflow,
                phase="accepted",
                fulfillment_id=accepted.fulfillment_id,
                remote_state=accepted.state,
            )
            return

        if phase == "accepted":
            fulfillment_id = str(workflow["fulfillment_id"])
            async with compute_client_for_site(site_id) as client:
                status = await client.get_fulfillment_status(fulfillment_id)
            if status.state in _FAILED_STATES:
                await self._fail(
                    workflow,
                    status.failure_message or status.failure_reason or status.state,
                )
                return
            if status.state != "active":
                await self._advance(
                    workflow, phase="accepted", remote_state=status.state
                )
                return
            async with compute_client_for_site(site_id) as client:
                result = await client.get_fulfillment_result(fulfillment_id)
            await self._apply_result(workflow, result)
            return

        if phase == "result_applied":
            await self._submit_settlement(workflow)
            return

        raise RuntimeError(f"unsupported storefront fulfillment phase {phase!r}")

    async def _apply_result(
        self, workflow: dict[str, Any], result: FulfillmentResultView
    ) -> None:
        generation = int(result.credential_generation)
        if result.credentials and generation <= int(workflow["credential_generation"]):
            raise RuntimeError("fulfillment credential generation did not advance")
        credential_payloads = [item.payload for item in result.credentials]
        connection = {
            "provisioned_resources": [
                item.model_dump(mode="json") for item in result.provisioned_resources
            ],
            "access": credential_payloads,
        }
        await self._db.apply_fulfillment_result(
            escrow_uid=workflow["escrow_uid"],
            connection_details=json.dumps(connection),
            tenant_credentials=(
                json.dumps(credential_payloads) if credential_payloads else None
            ),
            remote_state=result.state,
            provisioned_resources=[
                item.model_dump(mode="json") for item in result.provisioned_resources
            ],
            failure_reason=result.failure_reason,
            failure_message=result.failure_message,
            credential_generation=generation,
        )

    async def _submit_settlement(self, workflow: dict[str, Any]) -> None:
        from market_core.schemas import EscrowProposal

        from market_storefront import container
        from market_storefront.services.claims_runtime import (
            derive_claim_obligation,
            submit_claim,
        )
        from market_storefront.utils.config import CHAINS

        escrow, thread, listing = await self._settlement_context(
            str(workflow["escrow_uid"])
        )
        chain_name = str(escrow.get("chain_name") or "")
        fulfillment_uid = escrow.get("fulfillment_uid")
        if not fulfillment_uid:
            client = container.get_alkahest_client(chain_name)
            fulfillment_uid = await submit_compute_fulfillment(
                client=client,
                escrow_uid=str(workflow["escrow_uid"]),
                connection_details=escrow.get("connection_details"),
            )
            await self._db.update_escrow(
                escrow_uid=workflow["escrow_uid"],
                fulfillment_uid=fulfillment_uid,
            )
        proposal_raw = thread.get("buyer_escrow_proposal")
        proposal = (
            EscrowProposal.model_validate(proposal_raw)
            if isinstance(proposal_raw, dict)
            else None
        )
        duration = int(
            thread.get("agreed_duration_seconds")
            or thread.get("requested_duration_seconds")
            or listing.get("max_duration_seconds")
            or 3600
        )
        obligation = derive_claim_obligation(
            proposal=proposal,
            agreed_amount=int(thread["agreed_price"]),
            duration_seconds=duration,
            chain_config_paths={
                name: cfg.alkahest_address_config_path for name, cfg in CHAINS.items()
            },
        )
        await submit_claim(
            sqlite_client=self._db,
            escrow_uid=str(workflow["escrow_uid"]),
            fulfillment_uid=str(fulfillment_uid),
            negotiation_id=str(escrow["negotiation_id"]),
            listing_id=str(thread.get("our_listing_id") or ""),
            obligation=obligation,
            chain_name=chain_name,
            escrow_address=escrow.get("escrow_address"),
        )
        await self._db.update_escrow(escrow_uid=workflow["escrow_uid"], status="ready")
        await self._advance(workflow, phase="ready")

    async def run_once(self, *, limit: int = 25) -> int:
        now = time.time()
        workflows = await self._db.claim_due_fulfillment_workflows(
            worker_id=self._worker_id,
            now_unix=now,
            lease_seconds=30,
            limit=limit,
        )
        for workflow in workflows:
            try:
                await self.reconcile_one(workflow)
            except Exception as exc:
                logger.exception(
                    "VM fulfillment reconciliation failed for %s",
                    workflow["escrow_uid"],
                )
                attempts = int(workflow["reconcile_attempts"])
                delay = min(60.0, float(2 ** min(attempts, 6)))
                await self._db.update_fulfillment_workflow(
                    escrow_uid=workflow["escrow_uid"],
                    next_reconcile_unix=time.time() + delay,
                    last_reconcile_error=str(exc),
                    claimed_by=None,
                    claim_expires_unix=None,
                )
        return len(workflows)


async def fulfillment_reconciler_loop() -> None:
    from market_storefront.utils.config import settings
    from market_storefront.utils.sqlite_client import get_sqlite_client

    interval = float(getattr(settings, "fulfillment_sweep_interval", 2) or 2)
    reconciler = StorefrontFulfillmentReconciler(sqlite_client=get_sqlite_client())
    while True:
        await reconciler.run_once()
        await asyncio.sleep(interval)
