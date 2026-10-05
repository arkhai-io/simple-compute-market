"""Receipt-gated VM provisioning and negotiation-scoped retry."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from core_storefront.domain_lifecycle import (
    StorefrontFulfillmentContext,
    StorefrontFulfillmentPorts,
    fulfill_domain,
)
from market_arkhai_payments import Mandate, transaction_id
from market_identity import Identity

from market_storefront.arkhai_payments import VmArkhaiPaymentsStage
from market_storefront.services.fulfillment_resume_runtime import (
    resume_incomplete_fulfillments_once,
)
from market_storefront.settlement_stages import vm_evidence
from market_storefront.utils import config

logger = logging.getLogger(__name__)


class VmPaymentsCoordinator:
    def __init__(self, *, domain: Any, db: Any, stage: VmArkhaiPaymentsStage) -> None:
        self.domain = domain
        self.db = db
        self.stage = stage
        self.tasks: dict[str, asyncio.Task] = {}
        self.locks: dict[str, asyncio.Lock] = {}
        self.owner = f"payments:{uuid.uuid4()}"

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
            record = await self.db.load_vm_settlement_evidence(
                negotiation_id=negotiation_id
            )
            entry = self.domain.settlement.seller_stages[
                agreement["settlement"]["mechanism"]
            ]
            mandate_wire = self.stage.mandate_for_agreement(agreement)
            data = thread.get("settlement_data")
            if not isinstance(data, dict) or data.get("mandate") != mandate_wire:
                raise ValueError("stored mandate does not match accepted Agreement")
            mandate = Mandate.model_validate(mandate_wire)
            transaction = transaction_id(mandate)
            if record is not None and record.status == "verified":
                entry.revalidate(evidence=record, thread=thread, verifier=self.stage)
            else:
                await self.db.save_vm_settlement_evidence(
                    vm_evidence(
                        raw=raw,
                        mechanism=entry.mechanism,
                        reference=transaction,
                        status="pending",
                        source={"mandate": mandate_wire},
                        facts={},
                    )
                )
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
                listing = await self.db.load_listing(listing_id=agreement["listing_id"])
                if not isinstance(listing, dict):
                    raise ValueError("accepted listing is unavailable")
                record = entry.verified_evidence(
                    raw=raw, order=listing, receipt=receipt, mandate=mandate
                )
                await self.db.save_vm_settlement_evidence(record)
            binding = await self.db.load_thread_binding(negotiation_id=negotiation_id)
            if self.db.domain_registry.resolve(binding.binding) is not self.domain:
                raise ValueError("accepted domain binding disagrees with provisioning")
            existing = await self.db.load_vm_delivery(negotiation_id=negotiation_id)
            if existing and existing["status"] in ("ready", "failed", "refunded"):
                return {**existing, "escrow_uid": negotiation_id}
            await self.db.insert_vm_delivery(negotiation_id=negotiation_id)
            task = self.tasks.get(negotiation_id)
            if task is None or task.done():
                self.tasks[negotiation_id] = asyncio.create_task(
                    self._provision(
                        negotiation_id, agreement, binding, provision, record
                    )
                )
            return {
                **await self.db.load_vm_delivery(negotiation_id=negotiation_id),
                "escrow_uid": negotiation_id,
            }

    async def _provision(
        self,
        negotiation_id: str,
        agreement: dict,
        binding: Any,
        provision: Any,
        evidence: Any,
    ) -> None:
        owner = self.owner
        delivery = self.db
        entry = self.domain.settlement.seller_stages[
            agreement["settlement"]["mechanism"]
        ]
        start = datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00"))
        until = max(start, datetime.now(timezone.utc)) + timedelta(
            seconds=float(config.settings.provisioning.timeout) + 60
        )
        claimed = await delivery.claim_vm_delivery(
            negotiation_id=negotiation_id, owner=owner, lease_until=until.isoformat()
        )
        if not claimed:
            return
        try:
            row = await delivery.load_vm_delivery(negotiation_id=negotiation_id)
            if row.get("fulfillment_context"):
                # Resume the durable request instead of allocating a second VM.
                await delivery.release_vm_delivery(
                    negotiation_id=negotiation_id, owner=owner
                )
                await resume_incomplete_fulfillments_once(sqlite_client=self.db)
                return
            listing = evidence.evidence["delivery"]["payload"]["order"]
            if listing is None:
                raise ValueError("accepted listing is unavailable")
            result = await fulfill_domain(
                self.domain,
                StorefrontFulfillmentContext(
                    thread_binding=binding,
                    settlement_evidence=evidence,
                    buyer_principal=Identity.model_validate(agreement["buyer"]),
                    ports=StorefrontFulfillmentPorts(
                        repository=delivery,
                        capacity_client=None,
                        fulfillment_client=None,
                    ),
                    domain_input={
                        "failure_policy": partial(
                            entry.delivery_failed, evidence=evidence, db=delivery
                        )
                    },
                ),
            )
            private = dict(result.domain_result or {})
            fulfillment_uid = None
            if result.state == "fulfilled":
                row = await delivery.load_vm_delivery(negotiation_id=negotiation_id)
                fulfillment_uid = await entry.continue_delivery(
                    evidence=evidence,
                    db=delivery,
                    delivery=row,
                    connection_json=private.get("connection_details"),
                )
            await delivery.update_vm_delivery(
                negotiation_id=negotiation_id,
                status="ready" if result.state == "fulfilled" else "failed",
                fulfillment_uid=fulfillment_uid,
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
            await delivery.release_vm_delivery(
                negotiation_id=negotiation_id, owner=owner
            )
