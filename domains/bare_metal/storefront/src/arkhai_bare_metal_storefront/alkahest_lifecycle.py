"""Deliver an Alkahest-settled bare-metal deal from the servicing worker.

Settle verify adopts the escrow's obligation; this step, the worker's ready
hook for Alkahest, then starts or resumes the fulfillment, waits for the lease
to become active, and binds a fulfillment the worker can check and collect: an
on-chain string obligation whose data is the digest of the deal's lease-ready
evidence. The body stays with the storefront, since it names the deal's parties
and a chain is public and permanent.

A string obligation has no identity the chain deduplicates, so the step records
what it is about to submit before submitting, and the attestation's UID before
completing with it. An attempt that finds a submission without a UID cannot
tell whether the chain holds an attestation, and parks the obligation for an
operator rather than submitting again. See
openspec/specs/settlement-servicing/spec.md, "A fulfillment submission with an
unknown outcome is never repeated", and openspec/specs/storefront-publication/
spec.md, "Complete bare-metal seller lifecycle".
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from arkhai_bare_metal import (
    BareMetalAcceptedAlkahestBinding,
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bare_metal_digest,
    build_bare_metal_lease_ready_evidence,
)
from market_alkahest import AlkahestFulfillmentPublisher
from market_identity import Identity
from market_settlement_runtime import (
    FULFILLMENT_REFERENCE_KEY,
    FULFILLMENT_SUBMISSION_KEY,
    SettlementManualRequired,
    SettlementObligationRecord,
    SettlementRuntime,
)

if TYPE_CHECKING:
    # Injected collaborators: importing them at run time would close a cycle
    # through the domain runtime, which composes the seller entries that name
    # this lifecycle.
    from .fulfillment_service import BareMetalFulfillmentService
    from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

ALKAHEST_MECHANISM = "alkahest.v1"
OUTCOME_UNKNOWN = "alkahest_submission_outcome_unknown"
REJECTED = "alkahest_submission_rejected"
# Refusals of a deal's evidence submission after which a chain that keeps
# refusing it is left to an operator rather than retried again.
REJECTION_BOUND = 3

# Settlement outcomes that end a deal without paying for it.
_UNCOLLECTED_ENDS = frozenset({"expired", "reclaimed", "failed"})
# Physical states in which the fulfillment will not become active on its own.
_FAILED_STATES = frozenset({"failed", "teardown_failed", "torn_down", "released"})


class BareMetalAlkahestFulfillmentError(RuntimeError):
    """The Alkahest step could not advance, and the worker should retry."""


def _canonical(principal: Identity) -> CanonicalPrincipal:
    return CanonicalPrincipal(
        scheme=principal.scheme.value, identifier=principal.identifier
    )


@dataclass(frozen=True)
class BareMetalAlkahestLifecycle:
    """The Alkahest ready step over one storefront's durable state."""

    db: SQLiteClient
    runtime: SettlementRuntime
    local_principal: Identity
    fulfillment_service: Callable[[], BareMetalFulfillmentService]
    chain_clients: Mapping[str, Any]

    async def ready(
        self, record: SettlementObligationRecord, worker_id: str
    ) -> SettlementObligationRecord:
        if record.obligation.get("mechanism") != ALKAHEST_MECHANISM:
            raise BareMetalAlkahestFulfillmentError(
                "the Alkahest step refuses another settlement mechanism"
            )
        if record.mechanism_status != "ready":
            return record
        reserved = await self.runtime.reserve_fulfillment(
            record.obligation_ref,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )
        if reserved.status != "pending":
            return record
        receipt = reserved.receipt or {}
        reference = receipt.get(FULFILLMENT_REFERENCE_KEY)
        if reference:
            # Published before the process stopped: complete with what the
            # chain already holds, and never publish again.
            return await self.runtime.complete_fulfillment(
                record.obligation_ref,
                str(reference),
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
        if FULFILLMENT_SUBMISSION_KEY in receipt:
            await self._park(
                record,
                worker_id,
                "an evidence submission's outcome is unknown",
                OUTCOME_UNKNOWN,
            )
            return record
        try:
            evidence = await self._lease_ready_evidence(record)
            if evidence is None:
                await self.runtime.defer_fulfillment(
                    record.obligation_ref,
                    local_principal=self.local_principal,
                    worker_id=worker_id,
                )
                return record
            publisher = self._publisher(record)
            await self.runtime.record_fulfillment_submission(
                record.obligation_ref,
                {"evidence_digest": evidence.evidence_digest},
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
        except Exception as exc:
            await self._retry(record, worker_id, exc)
            raise
        publication = await publisher.publish(
            condition_anchor=self._escrow_uid(record),
            data=evidence.evidence_digest,
        )
        if publication.outcome == "published":
            assert publication.reference is not None
            await self.runtime.record_fulfillment_publication(
                record.obligation_ref,
                publication.reference,
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
            return await self.runtime.complete_fulfillment(
                record.obligation_ref,
                publication.reference,
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
        if publication.outcome == "outcome_unknown":
            await self._park(
                record,
                worker_id,
                f"an evidence submission's outcome is unknown ({publication.reason})",
                OUTCOME_UNKNOWN,
            )
            return record
        # Not submitted, or rejected: no attestation exists, so the submission
        # is withdrawn and a later attempt may submit again.
        await self.runtime.clear_fulfillment_submission(
            record.obligation_ref,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )
        if publication.outcome == "rejected" and (
            await self.db.record_bare_metal_evidence_rejection(
                negotiation_id=record.agreement_ref
            )
            >= REJECTION_BOUND
        ):
            await self._park(
                record,
                worker_id,
                f"the chain rejected the evidence submission ({publication.reason})",
                REJECTED,
            )
            return record
        error = BareMetalAlkahestFulfillmentError(
            f"evidence submission {publication.outcome} ({publication.reason})"
        )
        await self._retry(record, worker_id, error)
        raise error

    async def terminal(
        self, record: SettlementObligationRecord, state: str, reason: str | None
    ) -> None:
        """End the lease of a deal whose settlement ended without collection.

        Only a settlement that has ended (expired, reclaimed, or failed) ends
        the service; a collected one was paid for, and an obligation waiting
        for an operator has not ended. A deal whose fulfillment never reserved
        capacity has no lease to end. Terminating a lease the site is already
        ending returns it as it is, so a repeated call changes nothing.
        """

        if state not in _UNCOLLECTED_ENDS:
            return
        lifecycle = await self.db.load_bare_metal_fulfillment_lifecycle(
            negotiation_id=record.agreement_ref
        )
        if lifecycle is None or not lifecycle.get("capacity_reservation_id"):
            return
        if lifecycle.get("state") == "released":
            return
        await self.fulfillment_service().end_lease(
            negotiation_id=record.agreement_ref,
            capacity_reservation_id=str(lifecycle["capacity_reservation_id"]),
            reason=f"settlement_{state}" + (f": {reason}" if reason else ""),
        )

    async def _lease_ready_evidence(self, record: SettlementObligationRecord):
        """Start or resume delivery; return the evidence once the lease is active."""

        negotiation_id = record.agreement_ref
        escrow_uid = self._escrow_uid(record)
        service = self.fulfillment_service()
        await service.begin(
            negotiation_id=negotiation_id,
            settlement_ref=escrow_uid,
            buyer_principal=record.payer_principal,
        )
        lifecycle = await service.status(
            negotiation_id=negotiation_id,
            buyer_principal=record.payer_principal,
        )
        state = str(lifecycle.get("state") or "")
        if state in _FAILED_STATES:
            raise BareMetalAlkahestFulfillmentError(
                f"bare-metal fulfillment is {state}"
                + (
                    f": {lifecycle['failure_reason']}"
                    if lifecycle.get("failure_reason")
                    else ""
                )
            )
        if state != "active":
            return None
        if lifecycle.get("lease_ready_evidence_json"):
            # Recorded on an earlier attempt, whose digest may be on chain.
            stored = await self.db.load_bare_metal_lease_ready_evidence(
                evidence_digest=str(lifecycle["lease_ready_evidence_digest"])
            )
            if stored is None:
                raise BareMetalAlkahestFulfillmentError(
                    "recorded lease-ready evidence is unreadable"
                )
            return stored
        evidence = await self._build_evidence(record, lifecycle, escrow_uid)
        return await self.db.save_bare_metal_lease_ready_evidence(
            negotiation_id=negotiation_id, evidence=evidence
        )

    async def _build_evidence(
        self,
        record: SettlementObligationRecord,
        lifecycle: Mapping[str, Any],
        escrow_uid: str,
    ):
        negotiation_id = record.agreement_ref
        context = await self.db.load_bare_metal_fulfillment_context(
            negotiation_id=negotiation_id
        )
        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        materialization = await self.db.load_bare_metal_materialization(
            negotiation_id=negotiation_id
        )
        result = await self.db.load_bare_metal_result(negotiation_id=negotiation_id)
        if context is None or thread is None:
            raise BareMetalAlkahestFulfillmentError(
                "the accepted bare-metal agreement is unavailable"
            )
        plan = thread.get("settlement_plan")
        if not plan:
            raise BareMetalAlkahestFulfillmentError(
                "the accepted bare-metal agreement has no committed settlement plan"
            )
        if materialization is None or result is None:
            raise BareMetalAlkahestFulfillmentError(
                "an active bare-metal fulfillment has no recorded result"
            )
        seller = Identity(
            scheme=context["seller_scheme"], identifier=context["seller_identifier"]
        )
        binding = BareMetalAcceptedAlkahestBinding(
            agreement_ref=negotiation_id,
            negotiation_id=negotiation_id,
            listing_id=str(context["listing_id"]),
            obligation_ref=record.obligation_ref,
            escrow_uid=escrow_uid,
            accepted_plan_digest=bare_metal_digest(plan),
            buyer_principal=_canonical(record.payer_principal),
            seller_principal=_canonical(seller),
            claimant_principal=_canonical(record.claimant_principal),
            site_id=str(context["site_id"]),
            resource_selection="specific",
            physical_resource_id=str(context["physical_resource_id"]),
            pool_id=context.get("pool_id"),
        )
        return build_bare_metal_lease_ready_evidence(
            binding=binding,
            condition_anchor=escrow_uid,
            result=BareMetalLeaseReadyResult(
                site_id=binding.site_id,
                resource_selection="specific",
                physical_resource_id=binding.physical_resource_id,
                capacity_reservation_ref=str(lifecycle["capacity_reservation_id"]),
                settlement_resource_ref=str(lifecycle["settlement_resource_id"]),
                fulfillment_ref=str(lifecycle["fulfillment_id"]),
                access_ready_at=result.ready_at,
                expires_at=materialization.lease_end_utc,
            ),
        )

    def _publisher(self, record: SettlementObligationRecord) -> AlkahestFulfillmentPublisher:
        params = record.obligation.get("params") or {}
        chain_name = str(params.get("chain_name") or "")
        client = self.chain_clients.get(chain_name)
        if client is None:
            raise BareMetalAlkahestFulfillmentError(
                f"no Alkahest chain client is configured for {chain_name!r}"
            )
        return AlkahestFulfillmentPublisher(client)

    @staticmethod
    def _escrow_uid(record: SettlementObligationRecord) -> str:
        if not record.mechanism_ref:
            raise BareMetalAlkahestFulfillmentError(
                "an adopted Alkahest obligation has no escrow"
            )
        return record.mechanism_ref

    async def _park(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
        message: str,
        code: str,
    ) -> None:
        logger.error(
            "bare-metal Alkahest fulfillment waits for an operator: %s",
            message,
            extra={"obligation_ref": record.obligation_ref, "reason": code},
        )
        await self.runtime.park_fulfillment(
            record.obligation_ref,
            SettlementManualRequired(message, code=code),
            local_principal=self.local_principal,
            worker_id=worker_id,
        )

    async def _retry(
        self, record: SettlementObligationRecord, worker_id: str, error: Exception
    ) -> None:
        await self.runtime.retry_fulfillment(
            record.obligation_ref,
            error,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )


__all__ = [
    "BareMetalAlkahestFulfillmentError",
    "BareMetalAlkahestLifecycle",
    "OUTCOME_UNKNOWN",
    "REJECTED",
    "REJECTION_BOUND",
]


def alkahest_servicing(runtime: Any) -> BareMetalAlkahestLifecycle | None:
    """The Alkahest entry's obligation servicing over one storefront runtime.

    A configured Alkahest section, enabled or not, owns the obligations accepted
    under it, so its servicing exists whenever the section does.
    """

    composition = runtime.settlement_composition
    if composition is None or not composition.configures(ALKAHEST_MECHANISM):
        return None
    return BareMetalAlkahestLifecycle(
        db=runtime.db,
        runtime=runtime.settlement_runtime,
        local_principal=runtime.seller_principal,
        fulfillment_service=runtime.fulfillment_service,
        chain_clients=composition.resources.get("clients") or {},
    )
