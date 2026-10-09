"""VM seller entries: accepted artifacts, request guards and settlement effects."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from arkhai_vms_listings import extract_compute_from_order
from arkhai_vms_settlement import (
    encode_compute_lease,
    token_resource_from_accepted_escrow,
)
from arkhai_vms_settlement.fulfillment import reconcile_or_submit_compute_fulfillment
from arkhai_vms_settlement.proposals import escrow_proposal_from_accepted_entry
from core_storefront import build_domain_settlement_artifacts
from core_storefront.models.settle_models import AgreementSettleResponse
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from market_arkhai_payments import (
    MandatePolicyError,
    PaymentSettlementData,
    SignedReceipt,
    duration_seconds,
)
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_core import SettlementEvidence, SettlementStageTable
from market_core.schemas import (
    EscrowProposal,
)
from market_identity import Identity

from market_storefront.failure_actions import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
    refund_escrow_listing,
)
from market_storefront.payment_repository import VmSettlementEvidenceConflict
from market_storefront.models.settle_models import (
    VmPaymentsSettleRequest,
    VmSettleRequest,
)
from market_storefront.services.capacity_client import build_capacity_runtime
from market_storefront.services.vm_fulfillment_planner import (
    VERIFIED_EVIDENCE_STATUSES,
)
from market_storefront.services.vm_job_spec_service import (
    compute_capacity_claim_from_order,
)
from market_storefront.utils import config
from market_storefront.utils.escrow_verification import (
    EscrowVerificationError,
    verify_escrow_for_settlement,
)

logger = logging.getLogger(__name__)


class PaymentSettlementError(RuntimeError):
    """A settlement or refund refusal carrying the HTTP status the route returns."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class PaymentSettleResult:
    """A settle or refund outcome: its status code and neutral payload fields."""

    status_code: int
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VmAlkahestSellerStage:
    build_plan: Callable[..., Any]
    mechanism: str = "alkahest.v1"

    def readiness_inputs(self, clauses: Any) -> dict[str, Any]:
        chains = tuple(
            dict.fromkeys(
                str(clause.mechanism_input["chain"])
                for clause in clauses
                if isinstance(clause.mechanism_input.get("chain"), str)
            )
        )
        return (
            {"accepted_escrows": [{"chain_name": chain} for chain in chains]}
            if chains
            else {}
        )

    def publication_chains(self, clauses: Any) -> set[str]:
        return {
            str(clause.mechanism_input["chain"])
            for clause in clauses
            if isinstance(clause.mechanism_input.get("chain"), str)
        }

    def accepted_artifacts(
        self, *, domain: Any, context: Any, listing: Mapping[str, Any],
        selection: Any, option: Mapping[str, Any], build_selection: Callable,
    ) -> dict[str, Any]:
        entry = option.get("params", {}).get("accepted_escrow")
        if not isinstance(entry, Mapping):
            raise ValueError("selected Alkahest option has no accepted escrow")
        proposal = escrow_proposal_from_accepted_entry(
            listing=dict(listing), entry=dict(entry),
            expiration_unix=selection.expiration_unix,
        )
        artifacts = build_domain_settlement_artifacts(
            domain, replace(context, proposal=proposal), build_plan=self.build_plan,
        )
        return {
            **dict(artifacts.supplemental),
            "settlement_plan": dict(artifacts.settlement_plan),
        }

    def verified_evidence(
        self, *, raw: bytes, order: dict, source: dict, chain_configs: dict
    ) -> SettlementEvidence:
        agreement = json.loads(raw)
        selected = agreement["settlement"]
        if selected["mechanism"] != self.mechanism:
            raise ValueError("Agreement does not select Alkahest")
        accepted = selected["params"]["accepted_escrow"]
        token = token_resource_from_accepted_escrow(
            accepted, chain_configs=chain_configs
        )
        if token is None:
            raise ValueError("Alkahest VM lease requires an accepted token resource")
        encoded = encode_compute_lease(
            compute_resource=extract_compute_from_order(order),
            token_resource=token,
            duration_seconds=agreement["duration_seconds"],
        )
        return vm_evidence(
            raw=raw,
            mechanism=self.mechanism,
            reference=source["escrow_uid"],
            source=source,
            facts=delivery_facts(
                agreement,
                order,
                lease_bytes=encoded,
                condition_anchor=source["escrow_uid"],
                funding_expires=source.get("expiration_unix"),
            ),
        )

    async def recover_evidence(
        self,
        *,
        evidence: SettlementEvidence,
        thread: dict,
        composition: Any,
        db: Any,
        client: Any = None,
    ) -> None:
        validate_accepted_evidence(evidence, thread)
        source = evidence.evidence["source"]
        chain_name = source["chain_name"]
        if client is None:
            client = composition.evidence_clients.get(chain_name)
        proposal = EscrowProposal.model_validate(self.accepted_proposal(thread))
        if (
            source["escrow_uid"] != evidence.settlement_ref
            or proposal.chain_name != chain_name
            or proposal.escrow_address != source["escrow_address"]
        ):
            raise ValueError("Alkahest source differs from accepted settlement")
        facts = evidence.evidence["delivery"]["payload"]
        index = await verify_escrow_for_settlement(
            escrow_uid=evidence.settlement_ref,
            seller_wallet=config.get_evm_wallet_address(),
            agreed_price=int(thread["agreed_price"]),
            agreed_duration_seconds=facts["duration_seconds"],
            listing=facts["order"],
            alkahest_client=client,
            chain_name=chain_name,
            alkahest_address_config_path=config.CHAINS[
                chain_name
            ].alkahest_address_config_path,
            escrow_proposal=proposal,
        )
        if index != source["obligation_index"]:
            raise ValueError("Alkahest recovered obligation changed")

    async def continue_delivery(
        self,
        *,
        evidence: SettlementEvidence,
        db: Any,
        delivery: dict,
        connection_json: str,
        client: Any = None,
        submit: Any = None,
        bind: Any = None,
        composition: Any = None,
    ) -> str:
        source = evidence.evidence["source"]
        if client is None and composition is not None:
            client = composition.evidence_clients.get(source["chain_name"])
        fulfillment_uid = delivery.get("fulfillment_uid")
        if not fulfillment_uid:
            ambiguous = (
                delivery.get("fulfillment_phase") == "onchain_submission_started"
            )
            # This write must succeed before the external effect. Otherwise a
            # restart could blindly submit again after an unrecorded success.
            if not ambiguous:
                await db.update_vm_delivery(
                    negotiation_id=evidence.negotiation_id,
                    fulfillment_phase="onchain_submission_started",
                )
            fulfillment_uid = await (submit or reconcile_or_submit_compute_fulfillment)(
                client=client,
                escrow_uid=evidence.settlement_ref,
                connection_details=connection_json,
                allow_submit=not ambiguous,
            )
            await db.update_vm_delivery(
                negotiation_id=evidence.negotiation_id,
                fulfillment_uid=str(fulfillment_uid),
                fulfillment_phase="onchain_fulfilled",
            )
        if not fulfillment_uid or not source.get("obligation_ref"):
            raise ValueError("Alkahest delivery has no immutable claim binding")
        if bind is not None:
            await bind(
                obligation_ref=source["obligation_ref"],
                fulfillment_ref=str(fulfillment_uid),
            )
        elif composition is not None:
            await composition.runtime.bind_fulfillment(
                source["obligation_ref"],
                str(fulfillment_uid),
                local_principal=composition.local_principal,
            )
            await composition.worker.wake(source["obligation_ref"])
        await db.update_escrow(
            escrow_uid=evidence.settlement_ref,
            status="ready",
            fulfillment_uid=str(fulfillment_uid),
            connection_details=connection_json,
        )
        return str(fulfillment_uid)

    async def delivery_failed(
        self, *, evidence: SettlementEvidence, db: Any, **fields: Any
    ) -> None:
        await apply_fulfillment_failure_policy(
            db,
            FulfillmentFailureContext(**fields, escrow_uid=evidence.settlement_ref),
            capacity=build_capacity_runtime(lambda: db),
        )

    async def refund_failed_delivery(
        self, *, db: Any, ctx: Any, listing_id: str | None, thread: dict, **_: Any
    ) -> dict[str, Any]:
        """The ``refund`` failure action: the escrow's token refund to the buyer."""
        return await refund_escrow_listing(db, ctx, listing_id, thread)

    def accepted_data(
        self, agreement: Any, payments_stage: Any, *, artifacts: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {"accepted_escrow_proposal": artifacts["accepted_escrow_proposal"]}

    def accepted_proposal(self, thread: Mapping[str, Any]) -> dict[str, Any]:
        raw = thread.get("agreement_bytes")
        if not isinstance(raw, bytes):
            raise ValueError("accepted Agreement bytes are unavailable")
        agreement = json.loads(raw)
        selected = agreement.get("settlement")
        if not isinstance(selected, Mapping) or selected.get("mechanism") != self.mechanism:
            raise ValueError("accepted Agreement does not select Alkahest")
        data = thread.get("settlement_data") or {}
        proposal = data.get("accepted_escrow_proposal") or thread.get("buyer_escrow_proposal")
        if not isinstance(proposal, dict) or "chain_name" not in proposal:
            raise ValueError("accepted negotiation has no persisted accepted escrow proposal")
        return proposal

    async def start(
        self,
        *,
        reference: str,
        body: Any,
        thread: dict,
        auth: Any,
        composition: Any,
        db: Any,
        configured_chains: Any,
    ) -> Any:
        escrow_uid = reference
        _container = configured_chains
        if not isinstance(body, VmSettleRequest):
            raise HTTPException(
                status_code=400, detail="Alkahest settlement requires EVM inputs"
            )
        if auth.exact_retry:
            if auth.recorded_outcome is None:
                raise HTTPException(status_code=409, detail="request retry is pending")
            status_code, payload = auth.recorded_outcome
            return JSONResponse(content=payload, status_code=status_code)

        persisted_negotiation_id = str(
            thread.get("negotiation_id") or body.negotiation_id
        )
        existing = await db.load_escrow(escrow_uid=escrow_uid)
        if (
            existing is not None
            and existing.get("negotiation_id") != persisted_negotiation_id
        ):
            raise HTTPException(
                status_code=403,
                detail="escrow does not match persisted negotiation binding",
            )
        try:
            persisted_buyer = Identity.model_validate(thread.get("buyer_principal"))
            provision = normalize_vm_provision_terms(thread.get("provision_terms"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="accepted negotiation terms are invalid",
            ) from exc
        if not provision.ssh_public_key.strip():
            raise HTTPException(
                status_code=409,
                detail="accepted provision terms have no SSH public key",
            )

        try:
            proposal = self.accepted_proposal(thread)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        selection = proposal.get("settlement_selection")
        mechanism = self.mechanism
        if isinstance(selection, Mapping) and selection.get("mechanism") != mechanism:
            raise HTTPException(
                status_code=400,
                detail="this route accepts only alkahest.v1",
            )
        accepted_chain = proposal.get("chain_name")
        if not isinstance(accepted_chain, str) or not accepted_chain:
            raise HTTPException(
                status_code=409,
                detail="accepted settlement terms have no chain",
            )

        if composition is None:
            raise HTTPException(
                status_code=503, detail="settlement runtime is unavailable"
            )
        mechanism_client = composition.mechanism_clients.get(mechanism)
        if mechanism_client is None:
            raise HTTPException(
                status_code=400,
                detail=f"settlement mechanism {mechanism!r} is not configured",
            )
        if accepted_chain not in _container.configured_chain_names():
            raise HTTPException(
                status_code=400,
                detail=(
                    f"chain {accepted_chain!r} not configured on this storefront — "
                    f"available chains: {sorted(_container.configured_chain_names())}"
                ),
            )
        try:
            result = await composition.coordinator.start(
                escrow_uid=escrow_uid,
                negotiation_id=persisted_negotiation_id,
                mechanism_client=mechanism_client,
                chain_name=accepted_chain,
                request=None,
            )
        except EscrowVerificationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except VmSettlementEvidenceConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("[SETTLE] settlement start failed: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return result, persisted_buyer


@dataclass(frozen=True)
class VmPaymentsSellerStage:
    mechanism: str = "arkhai.payments.v1"

    def readiness_inputs(self, clauses: Any) -> dict[str, Any]:
        return {}

    def publication_chains(self, clauses: Any) -> set[str]:
        return set()

    def accepted_artifacts(self, *, build_selection: Callable, **_: Any) -> dict[str, Any]:
        return build_selection()

    def accepted_data(
        self, agreement: Any, payments_stage: Any, *, artifacts: Mapping[str, Any],
    ) -> dict[str, Any]:
        if payments_stage is None:
            raise ValueError("payments_settlement_unavailable")
        return payments_stage.settlement_data(
            agreement.model_dump(mode="json", exclude_none=True)
        ).to_wire()

    def verified_evidence(
        self,
        *,
        raw: bytes,
        order: dict,
        receipt: Any,
        data: PaymentSettlementData,
    ) -> SettlementEvidence:
        agreement = json.loads(raw)
        wire = receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
        holds = [
            part.model_dump(mode="json", by_alias=True)["hold"]
            for part in receipt.receipt.parts
        ]
        facts = delivery_facts(agreement, order, funding_expires=data.mandate.expires)
        facts["payload"]["payment_hold"] = holds
        facts["payload"]["hold_until_utc"] = [
            (
                datetime.fromtimestamp(receipt.receipt.approvedAt, timezone.utc)
                + timedelta(seconds=duration_seconds(hold["for"]))
            ).isoformat()
            if "for" in hold
            else None
            for hold in holds
        ]
        facts["payload"]["receipt_identity"] = {
            "transaction_id": data.transaction_id,
            "approved_at": receipt.receipt.approvedAt,
            "deal": receipt.receipt.deal.root.root,
        }
        return vm_evidence(
            raw=raw,
            mechanism=self.mechanism,
            reference=data.transaction_id,
            source={"receipt": wire, "mandate": data.to_wire()["mandate"]},
            facts=facts,
        )

    async def recover_evidence(
        self,
        *,
        evidence: SettlementEvidence,
        thread: dict,
        composition: Any,
        db: Any,
        client: Any = None,
    ) -> None:
        self.revalidate(
            evidence=evidence, thread=thread, verifier=composition.arkhai_payments_stage
        )

    async def continue_delivery(
        self,
        *,
        evidence: SettlementEvidence,
        db: Any,
        delivery: dict,
        connection_json: str,
        **_: Any,
    ) -> str:
        identity = delivery.get("fulfillment_id")
        if not identity:
            raise ValueError("physical fulfillment has no durable identity")
        return str(identity)

    async def delivery_failed(
        self, *, evidence: SettlementEvidence, db: Any, **fields: Any
    ) -> None:
        await apply_fulfillment_failure_policy(
            db,
            FulfillmentFailureContext(**fields),
            capacity=build_capacity_runtime(lambda: db),
        )

    def revalidate(
        self, *, evidence: SettlementEvidence, thread: Mapping[str, Any], verifier: Any
    ) -> None:
        """Re-prove stored evidence against the exact Agreement before any effect.

        The stored settlement data must be the one the Agreement binds, under the
        policy recorded in its mandate, and the stored receipt must still verify
        under the current receipt identity pin.
        """
        validate_accepted_evidence(evidence, thread)
        raw = thread.get("agreement_bytes")
        if not isinstance(raw, bytes) or verifier is None:
            raise ValueError("accepted payment Agreement or verifier is unavailable")
        try:
            agreement, data = verifier.accepted(raw, thread.get("settlement_data"))
        except MandatePolicyError as exc:
            raise ValueError("accepted payment settlement data is invalid") from exc
        source = evidence.evidence.get("source") or {}
        if (
            evidence.settlement_ref != data.transaction_id
            or source.get("mandate") != data.to_wire()["mandate"]
            or not verifier.receipt_matches(
                SignedReceipt.model_validate(source.get("receipt")), agreement, data
            )
        ):
            raise ValueError("payment evidence does not match accepted Agreement")

    async def start(
        self,
        *,
        reference: str,
        body: Any,
        thread: dict,
        auth: Any,
        composition: Any,
        db: Any,
        configured_chains: Any,
    ) -> Any:
        if (
            not isinstance(body, VmPaymentsSettleRequest)
            or reference != body.negotiation_id
        ):
            raise HTTPException(
                status_code=400, detail="Arkhai settlement uses negotiation ID only"
            )
        coordinator = composition.payments_coordinator
        if coordinator is None:
            raise HTTPException(
                status_code=503, detail="Arkhai settlement is unavailable"
            )
        if auth.exact_retry and auth.recorded_outcome is None:
            raise HTTPException(status_code=409, detail="request retry is pending")
        result = await self._call(coordinator.start(body.negotiation_id, thread))
        # The settlement composition imports these entries to build its table,
        # so its job projection is loaded here rather than at module scope.
        from market_storefront.settlement_composition import serialize_settlement_job

        payload = (
            serialize_settlement_job(result.payload)
            if "created_at" in result.payload
            else dict(result.payload)
        )
        # Job serialization emits a fixed shape; the neutral settlement fields
        # come from the coordinator's result.
        payload.update(
            {
                key: result.payload[key]
                for key in (
                    "negotiation_id", "escrow_uid", "settlement_ref", "status", "retryable"
                )
                if key in result.payload
            }
        )
        payload["buyer_principal"] = Identity.model_validate(
            thread["buyer_principal"]
        ).model_dump(mode="json")
        payload["seller_principal"] = composition.local_principal.model_dump(mode="json")
        # The neutral fields are a cross-domain contract; refuse to emit a
        # payload that would not parse as one.
        AgreementSettleResponse.model_validate(payload)
        return JSONResponse(content=payload, status_code=result.status_code)

    async def refund(
        self, *, negotiation_id: str, thread: dict, composition: Any
    ) -> tuple[int, dict[str, Any]]:
        """Reverse the deal's held payment at the seller operator's request."""
        coordinator = composition.payments_coordinator
        if coordinator is None:
            raise HTTPException(
                status_code=503, detail="Arkhai settlement is unavailable"
            )
        result = await self._call(coordinator.refund(negotiation_id, thread))
        return result.status_code, dict(result.payload)

    async def refund_failed_delivery(
        self, *, thread: dict, composition: Any, **_: Any
    ) -> dict[str, Any]:
        """The ``refund`` failure action: reverse the payment if nothing was delivered."""
        coordinator = getattr(composition, "payments_coordinator", None)
        if coordinator is None:
            return {"action": "refund", "status": "skipped", "reason": "payments_unavailable"}
        return await coordinator.refund_before_delivery(str(thread["negotiation_id"]))

    @staticmethod
    async def _call(pending: Any) -> Any:
        try:
            return await pending
        except PaymentSettlementError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def validate_accepted_evidence(
    evidence: SettlementEvidence, thread: Mapping[str, Any]
) -> None:
    raw = thread.get("agreement_bytes")
    if not isinstance(raw, bytes):
        raise ValueError("accepted Agreement bytes are unavailable")
    agreement = json.loads(raw)
    if (
        evidence.status not in VERIFIED_EVIDENCE_STATUSES
        or evidence.negotiation_id != agreement["negotiation_id"]
        or evidence.mechanism != agreement["settlement"]["mechanism"]
        or evidence.evidence.get("agreement_sha256") != hashlib.sha256(raw).hexdigest()
    ):
        raise ValueError("settlement evidence differs from accepted Agreement")
    facts = evidence.evidence["delivery"]["payload"]
    for key in ("listing_id", "provision_terms", "duration_seconds", "start_utc"):
        if facts[key] != agreement[key]:
            raise ValueError("delivery facts differ from accepted Agreement")


def delivery_facts(
    agreement: Mapping[str, Any],
    order: Mapping[str, Any],
    *,
    lease_bytes: bytes = b"",
    condition_anchor: str | None = None,
    funding_expires: int | None = None,
) -> dict[str, Any]:
    start = datetime.fromisoformat(agreement["start_utc"].replace("Z", "+00:00"))
    end = start + timedelta(seconds=agreement["duration_seconds"])
    return {
        "kind": "vm.delivery-facts",
        "schema_version": 1,
        "payload": {
            "listing_id": agreement["listing_id"],
            "order": dict(order),
            "required_attributes": compute_capacity_claim_from_order(dict(order)),
            "provision_terms": agreement["provision_terms"],
            "duration_seconds": agreement["duration_seconds"],
            "start_utc": agreement["start_utc"],
            "lease_end_utc": end.astimezone(timezone.utc).isoformat(),
            "funding_expiration_unix": funding_expires,
            "lease_bytes_hex": lease_bytes.hex(),
            "condition_anchor": condition_anchor,
        },
    }


def vm_evidence(
    *,
    raw: bytes,
    mechanism: str,
    reference: str | None,
    source: dict,
    facts: dict,
    status: str = "verified",
) -> SettlementEvidence:
    agreement = json.loads(raw)
    return SettlementEvidence(
        negotiation_id=agreement["negotiation_id"],
        mechanism=mechanism,
        settlement_ref=reference,
        status=status,
        evidence={
            "schema": "vm.settlement-evidence.v1",
            "agreement_sha256": hashlib.sha256(raw).hexdigest(),
            "source": source,
            "delivery": facts,
        },
    )


@dataclass(frozen=True)
class VmContactSellerStage:
    """A contact exchange completes by the authenticated introduction reveal.

    Its accepted plan comes from the registration, and the reveal is served by
    the contact-exchange kit, so this entry publishes no chains and has no
    settle, delivery or refund operation.
    """

    mechanism: str = CONTACT_MECHANISM

    def readiness_inputs(self, clauses: Any) -> dict[str, Any]:
        return {}

    def publication_chains(self, clauses: Any) -> set[str]:
        return set()

    def accepted_artifacts(self, *, build_selection: Callable, **_: Any) -> dict[str, Any]:
        return build_selection()

    def accepted_data(
        self, agreement: Any, payments_stage: Any, *, artifacts: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {}

    async def start(self, **_: Any) -> Any:
        raise HTTPException(
            status_code=409,
            detail="a contact exchange completes by introduction, not settlement",
        )


def vm_seller_stages(build_plan: Callable[..., Any]) -> SettlementStageTable[Any]:
    return SettlementStageTable(
        {
            "alkahest.v1": VmAlkahestSellerStage(build_plan),
            "arkhai.payments.v1": VmPaymentsSellerStage(),
            CONTACT_MECHANISM: VmContactSellerStage(),
        }
    )


def resolve_proposal_stage(
    stages: SettlementStageTable[Any], proposal: Any, *, agreement: Any = None,
) -> Any:
    """Require an explicit selection, or the exact accepted Agreement on recovery."""
    selection = (
        proposal.get("settlement_selection") if isinstance(proposal, Mapping) else None
    )
    accepted = agreement.get("settlement") if isinstance(agreement, Mapping) else None
    mechanism = (
        selection.get("mechanism") if isinstance(selection, Mapping)
        else accepted.get("mechanism") if isinstance(accepted, Mapping) else None
    )
    if not isinstance(mechanism, str) or not mechanism:
        raise ValueError("settlement_mechanism_required")
    if isinstance(accepted, Mapping) and accepted.get("mechanism") != mechanism:
        raise ValueError("settlement_selection_differs_from_agreement")
    try:
        return stages[mechanism]
    except KeyError as exc:
        raise ValueError("settlement_mechanism_unsupported") from exc
