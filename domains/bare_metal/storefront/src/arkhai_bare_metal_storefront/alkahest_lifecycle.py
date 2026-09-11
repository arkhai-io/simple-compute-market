"""Bare-metal delivery evidence callbacks for shared Alkahest servicing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from arkhai_bare_metal import (
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bare_metal_digest,
    build_bare_metal_alkahest_lease_ready_evidence,
)
from market_identity import Identity
from market_settlement_runtime import SettlementObligationRecord, SettlementRuntime

ALKAHEST_MECHANISM = "alkahest.v1"


class BareMetalAlkahestLifecycleError(RuntimeError):
    """Raised when accepted, physical, and on-chain identities do not converge."""


async def project_alkahest_terminal_state(
    record: SettlementObligationRecord,
    repository: Any,
    *,
    evidence_terminal: str | None = None,
    fallback: str | None = None,
) -> str:
    """Project financial terminal state from the canonical shared operation."""
    if record.collection_state == "succeeded":
        return "collected"
    operation = await repository.load_settlement_operation(
        record.obligation_ref, "collect"
    )
    if (
        operation
        and operation.get("uncertain_acknowledgement")
        and operation.get("state") != "succeeded"
    ) or record.collection_state == "in_progress":
        return "collection_unknown"
    if evidence_terminal == "collection_unknown":
        return "collection_unknown"
    if (
        record.collection_state == "manual_required"
        or evidence_terminal == "manual_required"
    ):
        return "manual_required"
    if record.mechanism_status in {
        "expired",
        "reclaimed",
        "failed",
        "manual_required",
    }:
        return str(record.mechanism_status)
    return fallback or str(record.mechanism_status or "collection_unknown")


@dataclass(frozen=True)
class BareMetalAlkahestLifecycleCallbacks:
    db: Any
    runtime: SettlementRuntime
    settlement_repository: Any
    local_principal: Identity
    fulfillment_service: Any
    publishers: Mapping[str, Any]

    async def reconcile_publication_absent(
        self,
        record: SettlementObligationRecord,
    ) -> None:
        """Resume an intent after an authority has proven no attestation exists."""
        binding = await self.db.load_bare_metal_alkahest_evidence(
            obligation_ref=record.obligation_ref
        )
        operation = await self.settlement_repository.load_settlement_operation(
            record.obligation_ref, "fulfill"
        )
        if (
            binding is None
            or binding.get("fulfillment_uid") is not None
            or not binding.get("evidence_digest")
            or operation is None
            or operation.get("state") != "pending"
            or not operation.get("uncertain_acknowledgement")
            or operation.get("lease_owner") is not None
        ):
            raise BareMetalAlkahestLifecycleError(
                "publication absence recovery has no fenced ambiguous intent"
            )
        await self.db.reconcile_bare_metal_alkahest_publication_absent(
            obligation_ref=record.obligation_ref,
            evidence_digest=str(binding["evidence_digest"]),
        )
        await self.runtime.resolve_fulfillment_not_published(
            record.obligation_ref,
            local_principal=self.local_principal,
        )

    async def fulfill(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
    ) -> SettlementObligationRecord:
        if record.obligation.get("mechanism") != ALKAHEST_MECHANISM:
            raise BareMetalAlkahestLifecycleError(
                "bare-metal Alkahest callback refuses another mechanism"
            )
        binding = await self.db.load_bare_metal_alkahest_evidence(
            obligation_ref=record.obligation_ref
        )
        if binding is None:
            # Historical proposal-based settlements predate automatic evidence
            # collection and retain their previous operator-driven behavior.
            return record
        publisher = self._publisher(record)
        await self._validate_binding(record, binding, publisher)
        reserved = await self.runtime.reserve_fulfillment(
            record.obligation_ref,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )
        if reserved.status in {"busy", "succeeded"}:
            return record

        try:
            await self.fulfillment_service.begin(
                negotiation_id=record.agreement_ref,
                escrow_uid=str(binding["escrow_uid"]),
                buyer_principal=record.payer_principal,
            )
            delivery = await self.fulfillment_service.lease_ready_evidence_inputs(
                negotiation_id=record.agreement_ref,
                buyer_principal=record.payer_principal,
            )
            physical = delivery["lifecycle"]
            if physical.get("state") != "active":
                await self.runtime.defer_fulfillment(
                    record.obligation_ref,
                    local_principal=self.local_principal,
                    worker_id=worker_id,
                )
                return record
            evidence = self._evidence(record, binding, delivery)
            persisted = await self.db.record_bare_metal_alkahest_evidence_intent(
                obligation_ref=record.obligation_ref,
                evidence=evidence,
            )
            uid = await self._publish_or_recover(
                record=record,
                worker_id=worker_id,
                binding=persisted,
                evidence=evidence.canonical_json(),
                publisher=publisher,
            )
            try:
                await publisher.confirm_fulfillment(
                    fulfillment_uid=uid,
                    condition_anchor=str(binding["escrow_uid"]),
                    evidence=evidence.canonical_json(),
                )
            except Exception as exc:
                await self.db.advance_bare_metal_alkahest_evidence(
                    obligation_ref=record.obligation_ref,
                    publication_state="readback_unknown",
                    fulfillment_uid=uid,
                    failure_reason=(
                        "fulfillment attestation readback failed: "
                        f"{type(exc).__name__}"
                    ),
                )
                raise
            await self.db.advance_bare_metal_alkahest_evidence(
                obligation_ref=record.obligation_ref,
                publication_state="confirmed",
                fulfillment_uid=uid,
            )
            return await self.runtime.complete_fulfillment(
                record.obligation_ref,
                uid,
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
        except Exception as exc:
            latest = await self.db.load_bare_metal_alkahest_evidence(
                obligation_ref=record.obligation_ref
            )
            publication_uncertain = bool(
                latest
                and latest.get("publication_state")
                in {
                    "submitting",
                    "submission_unknown",
                    "uid_recorded",
                    "readback_unknown",
                    "confirmed",
                }
            )
            await self.runtime.retry_fulfillment(
                record.obligation_ref,
                exc,
                local_principal=self.local_principal,
                worker_id=worker_id,
                uncertain=publication_uncertain,
            )
            raise

    async def _publish_or_recover(
        self,
        *,
        record: SettlementObligationRecord,
        worker_id: str,
        binding: dict[str, Any],
        evidence: str,
        publisher: Any,
    ) -> str:
        state = str(binding["publication_state"])
        recorded_uid = binding.get("fulfillment_uid")
        if recorded_uid is not None:
            return str(recorded_uid)
        if state in {"submitting", "submission_unknown"}:
            raise BareMetalAlkahestLifecycleError(
                "fulfillment publication is ambiguous and requires "
                "manual reconciliation"
            )
        if state != "intent_recorded":
            raise BareMetalAlkahestLifecycleError(
                f"unsupported fulfillment publication state {state!r}"
            )
        await self.runtime.fence_fulfillment_publication(
            record.obligation_ref,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )
        claimed = await self.db.claim_bare_metal_alkahest_evidence_submission(
            obligation_ref=record.obligation_ref,
            evidence_digest=str(binding["evidence_digest"]),
            worker_id=worker_id,
        )
        if claimed is None:
            raise BareMetalAlkahestLifecycleError(
                "fulfillment publication intent is already claimed"
            )
        try:
            uid = await publisher.submit_fulfillment(
                condition_anchor=str(binding["escrow_uid"]),
                evidence=evidence,
            )
        except Exception:
            await self.db.advance_bare_metal_alkahest_evidence(
                obligation_ref=record.obligation_ref,
                publication_state="submission_unknown",
                failure_reason="fulfillment publication acknowledgement is unknown",
                publication_owner=worker_id,
            )
            raise
        try:
            await self.db.advance_bare_metal_alkahest_evidence(
                obligation_ref=record.obligation_ref,
                publication_state="uid_recorded",
                fulfillment_uid=uid,
                publication_owner=worker_id,
            )
        except Exception:
            # The pre-submit marker prevents a later worker from resending even
            # when the returned UID could not be made durable.
            raise
        return uid

    async def _validate_binding(
        self,
        record: SettlementObligationRecord,
        binding: dict[str, Any],
        publisher: Any,
    ) -> None:
        if (
            binding.get("obligation_ref") != record.obligation_ref
            or binding.get("agreement_ref") != record.agreement_ref
            or binding.get("escrow_uid") != record.mechanism_ref
            or str(binding.get("seller_recipient", "")).lower()
            != publisher.publisher_address.lower()
        ):
            raise BareMetalAlkahestLifecycleError(
                "accepted Alkahest evidence identity does not match settlement"
            )

        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=record.agreement_ref
        )
        if (
            thread is None
            or bare_metal_digest(thread.get("settlement_plan"))
            != binding.get("accepted_plan_digest")
        ):
            raise BareMetalAlkahestLifecycleError(
                "accepted plan changed before fulfillment evidence"
            )
        if (
            Identity.model_validate(thread.get("buyer_principal"))
            != record.payer_principal
            or Identity.model_validate(thread.get("seller_principal"))
            != record.claimant_principal
        ):
            raise BareMetalAlkahestLifecycleError(
                "accepted parties changed before fulfillment evidence"
            )

    def _publisher(self, record: SettlementObligationRecord) -> Any:
        params = record.obligation.get("params")
        chain = params.get("chain_name") if isinstance(params, dict) else None
        if not isinstance(chain, str) or chain not in self.publishers:
            raise BareMetalAlkahestLifecycleError(
                "accepted Alkahest chain has no evidence publisher"
            )
        return self.publishers[chain]

    def _evidence(
        self,
        record: SettlementObligationRecord,
        binding: dict[str, Any],
        delivery: dict[str, Any],
    ) -> Any:
        physical = delivery["lifecycle"]
        materialization = delivery.get("materialization")
        result = delivery.get("result")
        receipt = delivery.get("receipt")
        if materialization is None or result is None or receipt is None:
            raise BareMetalAlkahestLifecycleError(
                "authoritative physical evidence is incomplete"
            )
        if (
            result.action != "node_grant_access"
            or result.status != "success"
            or result.machine_id != materialization.machine_id
            or result.physical_host_id != materialization.physical_host_id
            or result.escrow_uid != binding["escrow_uid"]
            or receipt.status != "ready"
            or receipt.escrow_uid != binding["escrow_uid"]
            or receipt.machine_id != materialization.machine_id
            or receipt.physical_host_id != materialization.physical_host_id
            or result.lease_expires_at != materialization.lease_end_utc
            or receipt.lease_start_utc != materialization.lease_start_utc
            or receipt.lease_end_utc != materialization.lease_end_utc
            or not result.ssh_user
            or not result.host
            or result.port is None
        ):
            raise BareMetalAlkahestLifecycleError(
                "authoritative physical result conflicts with accepted delivery"
            )
        required_refs = {
            "site_id": physical.get("site_id"),
            "physical_resource_id": physical.get("physical_resource_id"),
            "capacity_reservation_ref": physical.get("capacity_reservation_id"),
            "settlement_resource_ref": physical.get("settlement_resource_id"),
            "fulfillment_ref": physical.get("fulfillment_id"),
            "access_grant_ref": result.access_grant_ref,
        }
        if any(
            not isinstance(value, str) or not value
            for value in required_refs.values()
        ):
            raise BareMetalAlkahestLifecycleError(
                "authoritative physical result omits a durable identity"
            )
        if result.timestamp is None or result.lease_expires_at is None:
            raise BareMetalAlkahestLifecycleError(
                "authoritative physical result omits lease timing"
            )
        try:
            access_ready_at = datetime.fromisoformat(result.timestamp)
        except ValueError as exc:
            raise BareMetalAlkahestLifecycleError(
                "authoritative physical result has invalid timing"
            ) from exc
        public_result = BareMetalLeaseReadyResult(
            **required_refs,
            resource_selection="specific",
            access_ready_at=access_ready_at,
            expires_at=result.lease_expires_at,
        )
        return build_bare_metal_alkahest_lease_ready_evidence(
            agreement_ref=record.agreement_ref,
            obligation_ref=record.obligation_ref,
            obligation_hash=record.obligation_hash,
            accepted_plan_digest=str(binding["accepted_plan_digest"]),
            escrow_uid=str(binding["escrow_uid"]),
            buyer_principal=CanonicalPrincipal.model_validate(
                record.payer_principal.model_dump(mode="json")
            ),
            seller_principal=CanonicalPrincipal.model_validate(
                record.claimant_principal.model_dump(mode="json")
            ),
            seller_recipient=str(binding["seller_recipient"]),
            result=public_result,
        )

    async def reconcile_terminal(
        self,
        record: SettlementObligationRecord,
        outcome: str,
        reason: str | None,
    ) -> None:
        binding = await self.db.load_bare_metal_alkahest_evidence(
            obligation_ref=record.obligation_ref
        )
        if binding is None or record.obligation.get("mechanism") != ALKAHEST_MECHANISM:
            return
        terminal = await project_alkahest_terminal_state(
            record,
            self.settlement_repository,
            evidence_terminal=str(binding.get("terminal_state") or ""),
            fallback=outcome,
        )
        await self.db.advance_bare_metal_alkahest_evidence(
            obligation_ref=record.obligation_ref,
            terminal_state=terminal,
            failure_reason=reason,
        )


__all__ = [
    "BareMetalAlkahestLifecycleCallbacks",
    "BareMetalAlkahestLifecycleError",
    "project_alkahest_terminal_state",
]
