"""Receipt-gated VM provisioning and negotiation-scoped retry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    fulfill_domain,
)
from market_arkhai_payments import Mandate, SignedReceipt, transaction_id
from market_identity import Identity

from market_storefront.arkhai_payments import VmArkhaiPaymentsStage
from market_storefront.services.fulfillment_resume_runtime import (
    resume_incomplete_fulfillments_once,
)
from market_storefront.utils import config

logger = logging.getLogger(__name__)


class VmPaymentsCoordinator:
    def __init__(self, *, domain: Any, db: Any, stage: VmArkhaiPaymentsStage) -> None:
        self.domain = domain
        self.db = db
        self.stage = stage
        self.tasks: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = {}

    async def stop(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def start(
        self, negotiation_id: str, thread: dict[str, Any]
    ) -> dict[str, Any]:
        async with self.locks.setdefault(negotiation_id, asyncio.Lock()):
            raw = thread.get("agreement_bytes")
            if not isinstance(raw, bytes):
                raise ValueError("accepted Agreement bytes are unavailable")
            agreement = json.loads(raw)
            buyer = Identity.model_validate(thread["buyer_principal"])
            seller = Identity.model_validate(thread["seller_principal"])
            provision = normalize_vm_provision_terms(agreement.get("provision_terms"))
            if (
                agreement["negotiation_id"] != negotiation_id
                or agreement["listing_id"] != thread["our_listing_id"]
                or agreement["buyer"] != buyer.model_dump(mode="json")
                or agreement["seller"] != seller.model_dump(mode="json")
                or str(agreement["amount"]) != str(thread["agreed_price"])
                or agreement["duration_seconds"] != thread["agreed_duration_seconds"]
                or not provision.ssh_public_key.strip()
            ):
                raise ValueError("accepted Agreement does not match negotiation")
            record = await self.db.load_vm_payment_record(negotiation_id=negotiation_id)
            mandate_wire = self.stage.mandate_for_agreement(agreement)
            digest = hashlib.sha256(raw).hexdigest()
            data = thread.get("settlement_data")
            if not isinstance(data, dict) or data.get("mandate") != mandate_wire:
                raise ValueError("stored mandate does not match accepted Agreement")
            mandate = Mandate.model_validate(mandate_wire)
            transaction = transaction_id(mandate)
            if record is not None and record["receipt"] is not None:
                receipt = SignedReceipt.model_validate(record["receipt"])
                if (
                    record["agreement_sha256"] != digest
                    or record["transaction_id"] != transaction
                    or not self.stage.receipt_matches(
                        receipt, agreement=agreement, mandate=mandate
                    )
                ):
                    raise ValueError("stored receipt does not match accepted mandate")
            else:
                receipt = await self.stage.verify_receipt(
                    transaction=transaction, agreement=agreement
                )
                if receipt is None:
                    return {
                        "escrow_uid": negotiation_id,
                        "negotiation_id": negotiation_id,
                        "status": "pending",
                        "retryable": True,
                    }
                await self.db.verify_vm_payment_record(
                    negotiation_id=negotiation_id,
                    agreement_sha256=digest,
                    transaction_id=transaction,
                    receipt=receipt.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    ),
                )
            binding = await self.db.load_thread_binding(negotiation_id=negotiation_id)
            if self.db.domain_registry.resolve(binding.binding) is not self.domain:
                raise ValueError("accepted domain binding disagrees with provisioning")
            existing = await self.db.load_escrow(escrow_uid=negotiation_id)
            if existing and existing["negotiation_id"] != negotiation_id:
                raise ValueError("settlement coordinate belongs to another negotiation")
            if existing and existing["status"] in ("ready", "failed", "refunded"):
                return existing
            await self.db.insert_escrow(
                escrow_uid=negotiation_id,
                negotiation_id=negotiation_id,
                chain_name=None,
                escrow_address=None,
                is_primary=True,
                status="provisioning",
            )
            task = self.tasks.get(negotiation_id)
            if task is None or task.done():
                self.tasks[negotiation_id] = asyncio.create_task(
                    self._provision(negotiation_id, agreement, binding, provision)
                )
            return await self.db.load_escrow(escrow_uid=negotiation_id)

    async def _provision(
        self, negotiation_id: str, agreement: dict, binding: Any, provision: Any
    ) -> None:
        owner = f"payments:{negotiation_id}"
        start = datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00"))
        until = max(start, datetime.now(timezone.utc)) + timedelta(
            seconds=float(config.settings.provisioning.timeout) + 60
        )
        claimed = await self.db.claim_escrow_convergence(
            escrow_uid=negotiation_id, owner=owner, lease_until=until.isoformat()
        )
        if not claimed:
            return
        try:
            row = await self.db.load_escrow(escrow_uid=negotiation_id)
            if row.get("fulfillment_context"):
                # Resume the durable request instead of allocating a second VM.
                await self.db.release_escrow_convergence(
                    escrow_uid=negotiation_id, owner=owner
                )
                await resume_incomplete_fulfillments_once(sqlite_client=self.db)
                return
            listing = await self.db.load_listing(listing_id=agreement["listing_id"])
            if listing is None:
                raise ValueError("accepted listing is unavailable")
            result = await fulfill_domain(
                self.domain,
                StorefrontFulfillmentContext(
                    thread_binding=binding,
                    escrow_uid=negotiation_id,
                    buyer_principal=Identity.model_validate(agreement["buyer"]),
                    ports=StorefrontFulfillmentPorts(
                        repository=self.db,
                        capacity_client=None,
                        fulfillment_client=None,
                    ),
                    domain_input={
                        "ssh_public_key": provision.ssh_public_key,
                        "order": dict(listing),
                        "duration_seconds": agreement["duration_seconds"],
                        "start_utc": agreement["start_utc"],
                        "listing_id": agreement["listing_id"],
                        "settlement_mechanism": "arkhai.payments.v1",
                    },
                ),
            )
            private = dict(result.domain_result or {})
            await self.db.update_escrow(
                escrow_uid=negotiation_id,
                status="ready" if result.state == "fulfilled" else "failed",
                fulfillment_uid=result.fulfillment_id,
                connection_details=private.get("connection_details"),
                tenant_credentials=json.dumps(private["tenant_credentials"])
                if private.get("tenant_credentials") is not None
                else None,
                reason=result.failure_reason,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "VM payment provisioning interrupted for %s", negotiation_id
            )
        finally:
            await self.db.release_escrow_convergence(
                escrow_uid=negotiation_id, owner=owner
            )
