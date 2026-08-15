"""Hosted funding gate, selected-site fulfillment, evidence, and cleanup."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from arkhai_bare_metal import (
    HOSTED_MECHANISM,
    BareMetalAcceptedHostedBinding,
    BareMetalAccessResult,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyResult,
    BareMetalMaterialization,
    bare_metal_digest,
    build_bare_metal_lease_ready_evidence,
)
from compute_provisioning import FulfillmentRequestBody, FulfillmentScheduleRequest
from market_core.schemas import SettlementObligation
from market_fulfillment import VersionedEnvelope
from market_identity import Identity
from market_settlement_runtime import (
    HostedAcceptedAgreement,
    SettlementObligationRecord,
    SettlementRuntime,
    derive_obligation_ref,
)

from .hosted_binding import build_accepted_hosted_obligation
from .models import BareMetalHostedLifecycle
from .sqlite_client import SQLiteClient

EvidencePublisher = Callable[[BareMetalLeaseReadyEvidence], Awaitable[str]]

_NO_EFFECT_CAPACITY_STATES = frozenset(
    {"provisioning_failed", "released", "force_released"}
)
_NO_EFFECT_FULFILLMENT_STATES = frozenset({"failed", "torn_down", "abandoned"})
_FULFILLMENT_MAY_EXIST_STATES = frozenset(
    {"scheduled", "fulfillment_pending", "access_ready", "evidence_published"}
)


class BareMetalHostedLifecycleError(RuntimeError):
    """A safe lifecycle conflict that must not trigger alternate placement."""


@dataclass(frozen=True, slots=True)
class BareMetalHostedLifecycleCallbacks:
    """Domain callbacks consumed by the shared hosted settlement route/worker."""

    db: SQLiteClient
    runtime: SettlementRuntime
    local_principal: Identity
    capacity_client: Any
    fulfillment_client: Any
    publish_evidence: EvidencePublisher

    async def prepare(
        self,
        agreement_ref: str,
        obligation_ref: str,
        record: SettlementObligationRecord | None,
    ) -> HostedAcceptedAgreement:
        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref
        )
        if lifecycle is None:
            raise ValueError("accepted bare-metal hosted binding is unavailable")
        binding = lifecycle.accepted_binding
        if (
            binding.agreement_ref != agreement_ref
            or binding.negotiation_id != agreement_ref
            or binding.obligation_ref != obligation_ref
        ):
            raise ValueError(
                "hosted request conflicts with accepted bare-metal identity"
            )
        _, terms = await self._validate_accepted_authority(binding)
        obligation = self._obligation(
            binding,
            duration_seconds=terms.duration_seconds,
        )
        derived_ref = derive_obligation_ref(
            binding.agreement_ref,
            0,
            obligation.model_dump(mode="json"),
        )
        if derived_ref != binding.obligation_ref:
            raise ValueError("accepted bare-metal obligation digest is inconsistent")
        if record is not None:
            if (
                record.agreement_ref != binding.agreement_ref
                or record.obligation_ref != binding.obligation_ref
                or record.obligation != obligation.model_dump(mode="json")
                or record.payer_principal
                != Identity.model_validate(
                    binding.buyer_principal.model_dump(mode="json")
                )
                or record.claimant_principal
                != Identity.model_validate(
                    binding.claimant_principal.model_dump(mode="json")
                )
            ):
                raise ValueError("durable hosted obligation changed accepted authority")
        return HostedAcceptedAgreement(
            agreement_ref=binding.agreement_ref,
            obligation_ref=binding.obligation_ref,
            buyer_principal=Identity.model_validate(
                binding.buyer_principal.model_dump(mode="json")
            ),
            obligation=obligation,
            mechanism_params={
                "funding_profile": binding.option.funding_profile,
            },
        )

    async def reserve(
        self,
        agreement: HostedAcceptedAgreement,
        funding_authorization_ref: str,
    ) -> SettlementObligationRecord:
        if not funding_authorization_ref.strip():
            raise ValueError("funding authorization reference must be non-empty")
        records = await self.runtime.register_plan(
            agreement_ref=agreement.agreement_ref,
            obligations=[agreement.obligation.model_dump(mode="json")],
        )
        record = records[0]
        if record.obligation_ref != agreement.obligation_ref:
            raise ValueError("registered hosted obligation changed accepted identity")
        return await self.runtime.bind_mechanism_params(
            agreement.obligation_ref,
            {
                **agreement.mechanism_params,
                "funding_authorization_ref": funding_authorization_ref,
            },
            local_principal=agreement.buyer_principal,
        )

    async def fulfill(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
    ) -> SettlementObligationRecord:
        if record.obligation.get("mechanism") != HOSTED_MECHANISM:
            raise BareMetalHostedLifecycleError(
                "bare-metal hosted callback refuses another settlement mechanism"
            )
        if record.mechanism_status != "ready":
            return record
        reserved = await self.runtime.reserve_fulfillment(
            record.obligation_ref,
            local_principal=self.local_principal,
            worker_id=worker_id,
        )
        if reserved.status in {"busy", "succeeded"}:
            return await self._settlement_record(record.obligation_ref)
        try:
            lifecycle = await self._ensure_access_ready(record)
            if lifecycle.public_result is None:
                raise BareMetalHostedLifecycleError(
                    "selected-site fulfillment is not access-ready"
                )
            if not record.condition_anchor:
                raise BareMetalHostedLifecycleError(
                    "hosted authority returned no immutable condition anchor"
                )
            evidence = build_bare_metal_lease_ready_evidence(
                binding=lifecycle.accepted_binding,
                condition_anchor=record.condition_anchor,
                result=lifecycle.public_result,
            )
            evidence_ref = lifecycle.portable_evidence_ref
            if evidence_ref is None:
                evidence_ref = await self.publish_evidence(evidence)
                if not isinstance(evidence_ref, str) or not evidence_ref.strip():
                    raise BareMetalHostedLifecycleError(
                        "portable evidence publisher returned no signed reference"
                    )
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                physical_state="evidence_published",
                portable_evidence=evidence,
                portable_evidence_ref=evidence_ref,
            )
            return await self.runtime.complete_fulfillment(
                record.obligation_ref,
                evidence_ref,
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
        except Exception as exc:
            await self.runtime.retry_fulfillment(
                record.obligation_ref,
                exc,
                local_principal=self.local_principal,
                worker_id=worker_id,
            )
            raise

    async def project(
        self,
        record: SettlementObligationRecord,
        transient_action: Any | None,
        transient_receipt: Mapping[str, Any] | None,
    ) -> Mapping[str, Any]:
        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref
        )
        if lifecycle is None:
            raise BareMetalHostedLifecycleError(
                "accepted bare-metal hosted lifecycle is unavailable"
            )
        action = (
            transient_action.model_dump(mode="json")
            if hasattr(transient_action, "model_dump")
            else transient_action
        )
        return {
            "agreement_ref": record.agreement_ref,
            "obligation_ref": record.obligation_ref,
            "settlement_ref": record.mechanism_ref,
            "funding_profile": lifecycle.accepted_binding.option.funding_profile,
            "status": self._public_status(record, lifecycle),
            "physical_state": lifecycle.physical_state,
            "financial_state": lifecycle.financial_state,
            "recovery_state": lifecycle.recovery_state,
            "teardown_state": lifecycle.teardown_state,
            "fulfillment_identity": lifecycle.fulfillment_identity,
            "public_result": (
                lifecycle.public_result.model_dump(mode="json")
                if lifecycle.public_result is not None
                else None
            ),
            "portable_evidence_ref": lifecycle.portable_evidence_ref,
            "action": action,
            "receipt": dict(transient_receipt) if transient_receipt else None,
        }

    async def assert_reclaim_safe(
        self,
        record: SettlementObligationRecord,
    ) -> None:
        """Prove from the selected site that no physical effect remains."""

        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref
        )
        if lifecycle is None:
            raise ValueError("accepted bare-metal hosted lifecycle is unavailable")
        binding = lifecycle.accepted_binding
        if (
            binding.obligation_ref != record.obligation_ref
            or binding.agreement_ref != record.agreement_ref
        ):
            raise ValueError(
                "reclaim request conflicts with accepted physical identity"
            )
        if lifecycle.portable_evidence_ref is not None:
            raise ValueError("access-ready evidence excludes financial reclaim")
        site = self.capacity_client.site(binding.option.facts.site_id)
        deal_ref = {
            "negotiation_id": binding.negotiation_id,
            "hosted_obligation_ref": binding.obligation_ref,
        }
        reservation_id = lifecycle.capacity_reservation_id
        if reservation_id is None:
            reservations = await site.list_reservations()
            matching = [row for row in reservations if row.get("deal_ref") == deal_ref]
            if matching:
                raise ValueError("selected site has an unrecorded physical reservation")
            if (
                lifecycle.settlement_resource_id is not None
                or lifecycle.fulfillment_id is not None
                or lifecycle.physical_state
                not in {"accepted", "funded", "physical_failed"}
            ):
                raise ValueError(
                    "local physical lifecycle is inconsistent with site authority"
                )
            return

        reservation = await site.get_reservation(reservation_id)
        if reservation is None:
            raise ValueError("selected-site reservation is missing")
        if (
            str(reservation.get("capacity_reservation_id") or "") != reservation_id
            or reservation.get("deal_ref") != deal_ref
            or (
                binding.option.facts.resource_selection == "specific"
                and reservation.get("resource_id")
                != binding.option.facts.physical_resource_id
            )
        ):
            raise ValueError("selected-site reservation identity is inconsistent")
        reservation_state = reservation.get("state")
        if reservation_state not in _NO_EFFECT_CAPACITY_STATES:
            raise ValueError(
                "selected-site reservation may still have a physical effect"
            )

        fulfillment_id = lifecycle.fulfillment_id
        if fulfillment_id is None:
            if (
                lifecycle.settlement_resource_id is not None
                or lifecycle.physical_state in _FULFILLMENT_MAY_EXIST_STATES
            ):
                raise ValueError(
                    "fulfillment aggregate identity is missing after scheduling"
                )
            return
        remote = await self.fulfillment_client.get_fulfillment_status(
            fulfillment_id,
            capacity_reservation_id=reservation_id,
        )
        if (
            remote.fulfillment_id != fulfillment_id
            or remote.capacity_reservation_id != reservation_id
        ):
            raise ValueError("fulfillment aggregate identity is inconsistent")
        if remote.state not in _NO_EFFECT_FULFILLMENT_STATES:
            raise ValueError("fulfillment aggregate may still have a physical effect")

    async def cleanup(self, agreement_ref: str, reason: str) -> None:
        lifecycle = await self.db.load_bare_metal_hosted_lifecycle_for_agreement(
            agreement_ref=agreement_ref
        )
        if lifecycle is None:
            raise BareMetalHostedLifecycleError(
                "accepted bare-metal hosted lifecycle is unavailable"
            )
        if lifecycle.financial_state in {"collection_unknown", "collected"}:
            raise BareMetalHostedLifecycleError(
                "collection cannot be excluded; physical cleanup is frozen"
            )
        if lifecycle.portable_evidence_ref is not None:
            raise BareMetalHostedLifecycleError(
                "successful lease-ready evidence excludes financial reclaim"
            )
        reclaimed = reason == "hosted settlement reclaimed"
        obligation_ref = lifecycle.accepted_binding.obligation_ref
        await self.db.advance_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref,
            financial_state=("reclaimed" if reclaimed else "collection_blocked"),
            recovery_state=("reclaimed" if reclaimed else "funding_returned"),
            failure_reason=reason,
        )
        await self._teardown(obligation_ref)

    async def teardown_lease(self, obligation_ref: str) -> None:
        """Converge physical lease teardown without changing financial state."""

        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref
        )
        if lifecycle is None:
            raise BareMetalHostedLifecycleError(
                "accepted bare-metal hosted lifecycle is unavailable"
            )
        if lifecycle.financial_state not in {
            "collected",
            "collection_blocked",
            "reclaimed",
        }:
            raise BareMetalHostedLifecycleError("lease teardown is not yet authorized")
        await self._teardown(obligation_ref)

    async def reconcile_terminal(
        self,
        record: SettlementObligationRecord,
        outcome: str,
        reason: str | None,
    ) -> None:
        """Converge collection, return/loss, and manual-review outcomes."""

        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref
        )
        if lifecycle is None or record.obligation.get("mechanism") != HOSTED_MECHANISM:
            return
        if record.collection_state == "succeeded" or outcome == "collected":
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                financial_state="collected",
                recovery_state=(
                    "loss_manual"
                    if record.mechanism_status == "manual_required"
                    else None
                ),
                failure_reason=reason,
            )
            return
        if record.collection_state == "in_progress":
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                financial_state="collection_unknown",
                recovery_state="manual_review",
                failure_reason=reason,
            )
            return
        if record.mechanism_status == "manual_required":
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                financial_state="manual_review",
                recovery_state="manual_review",
                failure_reason=reason,
            )
            return
        if record.mechanism_status in {"failed", "expired", "reclaimed"}:
            await self.cleanup(record.agreement_ref, reason or outcome)

    @staticmethod
    def _obligation(
        binding: BareMetalAcceptedHostedBinding,
        *,
        duration_seconds: int,
    ) -> SettlementObligation:
        return build_accepted_hosted_obligation(
            option=binding.option,
            duration_seconds=duration_seconds,
            expiration_unix=int(binding.authorization_expires_at.timestamp()),
            buyer_principal=Identity.model_validate(
                binding.buyer_principal.model_dump(mode="json")
            ),
            seller_principal=Identity.model_validate(
                binding.seller_principal.model_dump(mode="json")
            ),
        )

    async def _validate_accepted_authority(
        self,
        binding: BareMetalAcceptedHostedBinding,
    ) -> tuple[dict[str, Any], Any]:
        context = await self.db.load_bare_metal_fulfillment_context(
            negotiation_id=binding.negotiation_id
        )
        if context is None or context.get("terminal_state") != "success":
            raise ValueError("bare-metal negotiation is not accepted")
        buyer = Identity(
            scheme=context["buyer_scheme"],
            identifier=context["buyer_identifier"],
        )
        seller = Identity(
            scheme=context["seller_scheme"],
            identifier=context["seller_identifier"],
        )
        facts = binding.option.facts
        if (
            buyer
            != Identity.model_validate(binding.buyer_principal.model_dump(mode="json"))
            or seller
            != Identity.model_validate(binding.seller_principal.model_dump(mode="json"))
            or seller
            != Identity.model_validate(
                binding.claimant_principal.model_dump(mode="json")
            )
            or context["site_id"] != facts.site_id
        ):
            raise ValueError("accepted bare-metal authority binding changed")
        if facts.resource_selection == "specific" and (
            context.get("physical_resource_id") != facts.physical_resource_id
            or context.get("physical_host_id") != facts.physical_host_id
        ):
            raise ValueError("accepted Physical Resource binding changed")
        if facts.pool_id is not None and context.get("pool_id") != facts.pool_id:
            raise ValueError("accepted bare-metal pool binding changed")
        terms = await self.db.load_bare_metal_terms(
            negotiation_id=binding.negotiation_id
        )
        if terms is None:
            raise ValueError("accepted bare-metal terms are unavailable")
        if (
            terms.access_method != facts.access_method
            or bare_metal_digest({"ssh_public_key": terms.ssh_public_key})
            != binding.access_public_digest
        ):
            raise ValueError("accepted bare-metal access binding changed")
        return context, terms

    async def _ensure_access_ready(
        self,
        record: SettlementObligationRecord,
    ) -> BareMetalHostedLifecycle:
        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref
        )
        if lifecycle is None:
            raise BareMetalHostedLifecycleError(
                "accepted bare-metal hosted lifecycle is unavailable"
            )
        binding = lifecycle.accepted_binding
        context, terms = await self._validate_accepted_authority(binding)
        if (
            record.agreement_ref != binding.agreement_ref
            or record.payer_principal
            != Identity.model_validate(binding.buyer_principal.model_dump(mode="json"))
            or record.claimant_principal
            != Identity.model_validate(
                binding.claimant_principal.model_dump(mode="json")
            )
        ):
            raise BareMetalHostedLifecycleError(
                "funded obligation conflicts with accepted bare-metal authority"
            )
        lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref,
            physical_state="funded",
        )
        facts = binding.option.facts
        reservation_id = lifecycle.capacity_reservation_id
        deal_ref = {
            "negotiation_id": binding.negotiation_id,
            "hosted_obligation_ref": binding.obligation_ref,
        }
        claim = {
            "dimensions": {"units": 1},
            "offering_mode": facts.executor_kind,
        }
        if facts.resource_selection == "specific":
            claim["resource_id"] = facts.physical_resource_id
        elif facts.pool_id is not None:
            claim["pool_id"] = facts.pool_id
        if reservation_id is None:
            reservations = await self.capacity_client.site(
                facts.site_id
            ).list_reservations()
            matching = [row for row in reservations if row.get("deal_ref") == deal_ref]
            if len(matching) > 1:
                raise BareMetalHostedLifecycleError(
                    "multiple selected-site reservations match one obligation"
                )
            if matching:
                reservation_id = str(matching[0].get("capacity_reservation_id") or "")
                if not reservation_id:
                    raise BareMetalHostedLifecycleError(
                        "recovered selected-site reservation has no identity"
                    )
                lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                    obligation_ref=record.obligation_ref,
                    physical_state="capacity_reserved",
                    capacity_reservation_id=reservation_id,
                )
        if reservation_id is None:
            reserved = await self.capacity_client.reserve(
                site=facts.site_id,
                claim=claim,
                deal_ref=deal_ref,
                lease_duration_seconds=terms.duration_seconds,
            )
            if reserved is None or reserved.get("site") != facts.site_id:
                raise BareMetalHostedLifecycleError(
                    "accepted selected site refused bare-metal capacity"
                )
            reservation_id = str(reserved.get("capacity_reservation_id") or "")
            if not reservation_id:
                raise BareMetalHostedLifecycleError(
                    "selected-site reservation returned no identity"
                )
            lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                physical_state="capacity_reserved",
                capacity_reservation_id=reservation_id,
            )
        self.capacity_client.reservation_sites[reservation_id] = facts.site_id
        lease_start = datetime.now(timezone.utc)
        lease_end = lease_start + timedelta(seconds=terms.duration_seconds)
        if lifecycle.physical_state in {"funded", "capacity_reserved"}:
            await self.capacity_client.commit(
                capacity_reservation_id=reservation_id,
                resource_id=(
                    facts.physical_resource_id
                    if facts.resource_selection == "specific"
                    else None
                ),
                lease_start_utc=lease_start.isoformat(),
                lease_end_utc=lease_end.isoformat(),
                idempotency_ref=lifecycle.fulfillment_identity,
                site_id=facts.site_id,
            )
            lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                physical_state="capacity_committed",
            )
        settlement_resource_id = lifecycle.settlement_resource_id
        scheduled = None
        if settlement_resource_id is None:
            scheduled = await self.fulfillment_client.schedule_resource(
                FulfillmentScheduleRequest(
                    capacity_reservation_id=reservation_id,
                    market="bare_metal",
                    requirements={"offering_mode": facts.executor_kind},
                    resource_id=(
                        facts.physical_resource_id
                        if facts.resource_selection == "specific"
                        else None
                    ),
                )
            )
            if (
                scheduled.resource_kind != "compute.bare-metal"
                or scheduled.provider != "bare_metal.ansible"
                or scheduled.pool_id != facts.pool_id
            ):
                raise BareMetalHostedLifecycleError(
                    "selected resource resolved to an unexpected executor"
                )
            if facts.resource_selection == "specific" and (
                scheduled.attributes.get("physical_host_id") != facts.physical_host_id
                or scheduled.attributes.get("machine_id") != context.get("machine_id")
            ):
                raise BareMetalHostedLifecycleError(
                    "scheduler changed accepted Physical Resource"
                )
            settlement_resource_id = scheduled.settlement_resource_id
            lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                physical_state="scheduled",
                settlement_resource_id=settlement_resource_id,
            )
        fulfillment_id = lifecycle.fulfillment_id
        if fulfillment_id is None:
            machine_id = (
                str(scheduled.attributes.get("machine_id"))
                if scheduled is not None
                else str(context["machine_id"])
            )
            physical_host_id = (
                str(scheduled.attributes.get("physical_host_id"))
                if scheduled is not None
                else str(context["physical_host_id"])
            )
            if facts.resource_selection == "specific" and (
                machine_id != context["machine_id"]
                or physical_host_id != facts.physical_host_id
            ):
                raise BareMetalHostedLifecycleError(
                    "scheduled executor conflicts with accepted resource"
                )
            materialization = BareMetalMaterialization(
                settlement_obligation_ref=binding.obligation_ref,
                machine_id=machine_id,
                physical_host_id=physical_host_id,
                lease_start_utc=lease_start,
                lease_end_utc=lease_end,
                access_method=terms.access_method,
                ssh_public_key=terms.ssh_public_key,
                access_ref=terms.access_ref,
                listing_ref=binding.listing_id,
                settlement_ref={
                    "fulfillment_identity": lifecycle.fulfillment_identity,
                },
            )
            await self.db.save_bare_metal_materialization(
                negotiation_id=binding.negotiation_id,
                materialization=materialization,
            )
            accepted = await self.fulfillment_client.begin_fulfillment(
                FulfillmentRequestBody(
                    capacity_reservation_id=reservation_id,
                    market="bare_metal",
                    fulfillment_request=VersionedEnvelope(
                        kind="bare_metal.v1",
                        schema_version=1,
                        payload=materialization.model_dump(
                            mode="json", exclude_none=True
                        ),
                    ),
                )
            )
            fulfillment_id = accepted.fulfillment_id
            lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=record.obligation_ref,
                physical_state="fulfillment_pending",
                fulfillment_id=fulfillment_id,
            )
        remote = await self.fulfillment_client.get_fulfillment_status(
            fulfillment_id,
            capacity_reservation_id=reservation_id,
        )
        if remote.state != "active":
            if remote.state in {"failed", "teardown_failed"}:
                await self.db.advance_bare_metal_hosted_lifecycle(
                    obligation_ref=record.obligation_ref,
                    physical_state="physical_failed",
                    failure_reason=remote.failure_reason or remote.failure_message,
                )
                raise BareMetalHostedLifecycleError(
                    "bare-metal fulfillment failed before access readiness"
                )
            return lifecycle
        result_envelope = await self.fulfillment_client.get_fulfillment_result(
            fulfillment_id,
            capacity_reservation_id=reservation_id,
        )
        payload = result_envelope.payload
        if (
            result_envelope.kind != "fulfillment.result.v1"
            or result_envelope.schema_version != 1
            or not isinstance(payload, dict)
            or payload.get("state") != "active"
        ):
            raise BareMetalHostedLifecycleError(
                "provisioning returned unsupported fulfillment result"
            )
        domain = VersionedEnvelope.model_validate(payload.get("domain_result"))
        if (
            domain.kind != "bare_metal.fulfillment.result.v1"
            or domain.schema_version != 1
        ):
            raise BareMetalHostedLifecycleError(
                "provisioning returned unsupported bare-metal result"
            )
        access = BareMetalAccessResult.model_validate(domain.payload)
        if (
            access.action != "node_grant_access"
            or access.status != "success"
            or access.access_grant_ref is None
            or access.lease_expires_at is None
            or access.timestamp is None
        ):
            raise BareMetalHostedLifecycleError(
                "executor success lacks authoritative access-ready state"
            )
        ready_at = datetime.fromisoformat(access.timestamp)
        if ready_at.tzinfo is None:
            raise BareMetalHostedLifecycleError(
                "access-ready timestamp is not timezone-aware"
            )
        public_result = BareMetalLeaseReadyResult(
            site_id=facts.site_id,
            executor_kind=facts.executor_kind,
            resource_selection=facts.resource_selection,
            physical_resource_id=facts.physical_resource_id,
            capacity_reservation_ref=reservation_id,
            settlement_resource_ref=settlement_resource_id,
            fulfillment_ref=fulfillment_id,
            access_grant_ref=access.access_grant_ref,
            access_method=facts.access_method,
            access_ready=True,
            access_ready_at=ready_at,
            expires_at=access.lease_expires_at,
        )
        return await self.db.advance_bare_metal_hosted_lifecycle(
            obligation_ref=record.obligation_ref,
            physical_state="access_ready",
            public_result=public_result,
        )

    async def _teardown(self, obligation_ref: str) -> None:
        lifecycle = await self.db.load_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref
        )
        if lifecycle is None:
            raise BareMetalHostedLifecycleError("hosted lifecycle is unavailable")
        reservation_id = lifecycle.capacity_reservation_id
        if reservation_id is None:
            return
        if lifecycle.fulfillment_id is None:
            await self.capacity_client.site(
                lifecycle.accepted_binding.option.facts.site_id
            ).release(
                capacity_reservation_id=reservation_id,
                deal_ref={
                    "negotiation_id": lifecycle.accepted_binding.negotiation_id,
                    "hosted_obligation_ref": obligation_ref,
                },
            )
            self.capacity_client.reservation_sites.pop(reservation_id, None)
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=obligation_ref,
                teardown_state="released",
            )
            return
        if lifecycle.teardown_state in {"not_started", "failed"}:
            accepted = await self.fulfillment_client.begin_fulfillment_teardown(
                lifecycle.fulfillment_id,
                capacity_reservation_id=reservation_id,
            )
            lifecycle = await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=obligation_ref,
                teardown_state=(
                    "failed" if accepted.state == "teardown_failed" else "pending"
                ),
            )
        remote = await self.fulfillment_client.get_fulfillment_status(
            lifecycle.fulfillment_id,
            capacity_reservation_id=reservation_id,
        )
        if remote.state == "teardown_failed":
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=obligation_ref,
                teardown_state="failed",
                failure_reason=remote.failure_reason or remote.failure_message,
            )
            raise BareMetalHostedLifecycleError(
                "bare-metal teardown remains quarantined"
            )
        if remote.state != "torn_down":
            await self.db.advance_bare_metal_hosted_lifecycle(
                obligation_ref=obligation_ref,
                teardown_state="tearing_down",
            )
            raise BareMetalHostedLifecycleError("bare-metal teardown is pending")
        await self.db.advance_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref,
            teardown_state="torn_down",
        )
        await self.capacity_client.site(
            lifecycle.accepted_binding.option.facts.site_id
        ).release(
            capacity_reservation_id=reservation_id,
            deal_ref={
                "negotiation_id": lifecycle.accepted_binding.negotiation_id,
                "hosted_obligation_ref": obligation_ref,
            },
        )
        self.capacity_client.reservation_sites.pop(reservation_id, None)
        await self.db.advance_bare_metal_hosted_lifecycle(
            obligation_ref=obligation_ref,
            teardown_state="released",
        )

    async def _settlement_record(
        self,
        obligation_ref: str,
    ) -> SettlementObligationRecord:
        row = await self.db.load_settlement_obligation(obligation_ref)
        if row is None:
            raise BareMetalHostedLifecycleError("settlement obligation is unavailable")
        return SettlementObligationRecord.model_validate(row)

    @staticmethod
    def _public_status(
        record: SettlementObligationRecord,
        lifecycle: BareMetalHostedLifecycle,
    ) -> str:
        if lifecycle.recovery_state in {"loss_manual", "manual_review"}:
            return "manual_required"
        if lifecycle.financial_state == "collected":
            return "collected"
        if lifecycle.financial_state == "reclaimed":
            return "reclaimed"
        if lifecycle.portable_evidence_ref is not None:
            return "ready"
        if record.mechanism_status == "ready":
            return "funded"
        return record.mechanism_status or "pending"


__all__ = [
    "BareMetalHostedLifecycleCallbacks",
    "BareMetalHostedLifecycleError",
    "EvidencePublisher",
]
