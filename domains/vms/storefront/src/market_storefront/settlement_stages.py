"""VM seller entries: accepted artifacts, request guards and settlement effects."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from arkhai_vms import normalize_vm_provision_terms
from domains.vms.listings import extract_compute_from_order
from domains.vms.settlement import (
    encode_compute_lease,
    token_resource_from_accepted_escrow,
)
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from market_arkhai_payments import (
    Mandate,
    SignedReceipt,
    duration_seconds,
    transaction_id,
)
from market_core import SettlementEvidence, SettlementStageTable
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Identity

from market_storefront.services.vm_job_spec_service import compute_capacity_claim_from_order
from market_storefront.models.settle_models import (
    VmPaymentsSettleRequest,
    VmSettleRequest,
)
from market_storefront.utils.escrow_verification import EscrowVerificationError

logger = logging.getLogger(__name__)


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

    def proposal_option(
        self, proposal: Mapping[str, Any], listing: Mapping[str, Any]
    ) -> dict[str, Any]:
        entries = listing.get("accepted_escrows") or []
        if isinstance(entries, str):
            entries = json.loads(entries)
        entry = next(
            (
                dict(item)
                for item in entries
                if item.get("chain_name") == proposal.get("chain_name")
                and item.get("escrow_address") == proposal.get("escrow_address")
            ),
            None,
        )
        if entry is None:
            raise ValueError("accepted escrow is not advertised by listing")
        literals = entry.get("literal_fields") or {}
        asset = str(
            literals.get("token")
            or literals.get("asset")
            or entry.get("asset")
            or "native"
        )
        rates = [RateValue.model_validate(rate) for rate in entry.get("rates") or []]
        params = {"accepted_escrow": entry}
        return SettlementOption(
            option_id=derive_settlement_option_id(
                mechanism=self.mechanism, asset=asset, rates=rates, params=params
            ),
            mechanism=self.mechanism,
            asset=asset,
            rates=rates,
            params=params,
        ).model_dump(mode="json")

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

    def accepted_data(self, agreement: Any, payments_stage: Any) -> dict[str, Any]:
        return {}

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
        accepted_ssh_public_key = provision.ssh_public_key
        if not accepted_ssh_public_key.strip():
            raise HTTPException(
                status_code=409,
                detail="accepted provision terms have no SSH public key",
            )
        if body.ssh_public_key != accepted_ssh_public_key:
            raise HTTPException(
                status_code=403,
                detail="SSH public key does not match accepted provision terms",
            )

        proposal = thread.get("buyer_escrow_proposal")
        if not isinstance(proposal, dict):
            raise HTTPException(
                status_code=409,
                detail="accepted negotiation has no settlement selection",
            )
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
        if body.chain_name != accepted_chain:
            raise HTTPException(
                status_code=403,
                detail="settlement chain does not match accepted terms",
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

    def accepted_data(self, agreement: Any, payments_stage: Any) -> dict[str, Any]:
        if payments_stage is None:
            raise ValueError("payments_settlement_unavailable")
        return {
            "mandate": payments_stage.mandate_for_agreement(
                agreement.model_dump(mode="json", exclude_none=True)
            )
        }

    def verified_evidence(
        self, *, raw: bytes, order: dict, receipt: Any, mandate: Any
    ) -> SettlementEvidence:
        agreement = json.loads(raw)
        wire = receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
        holds = [
            part.model_dump(mode="json", by_alias=True)["hold"]
            for part in receipt.receipt.parts
        ]
        facts = delivery_facts(agreement, order, funding_expires=mandate.expires)
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
            "transaction_id": transaction_id(mandate),
            "approved_at": receipt.receipt.approvedAt,
            "deal": receipt.receipt.deal.root.root,
        }
        return vm_evidence(
            raw=raw,
            mechanism=self.mechanism,
            reference=transaction_id(mandate),
            source={
                "receipt": wire,
                "mandate": mandate.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            },
            facts=facts,
        )

    def revalidate(
        self, *, evidence: SettlementEvidence, thread: Mapping[str, Any], verifier: Any
    ) -> None:
        raw = thread.get("agreement_bytes")
        if not isinstance(raw, bytes) or verifier is None:
            raise ValueError("accepted payment Agreement or verifier is unavailable")
        agreement = json.loads(raw)
        source = evidence.evidence.get("source") or {}
        mandate_wire = (thread.get("settlement_data") or {}).get("mandate")
        mandate = Mandate.model_validate(mandate_wire)
        if (
            evidence.status != "verified"
            or evidence.evidence.get("agreement_sha256")
            != hashlib.sha256(raw).hexdigest()
            or evidence.settlement_ref != transaction_id(mandate)
            or source.get("mandate") != mandate_wire
            or mandate_wire != verifier.mandate_for_agreement(agreement)
            or not verifier.receipt_matches(
                SignedReceipt.model_validate(source.get("receipt")),
                agreement=agreement,
                mandate=mandate,
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
        try:
            result = await coordinator.start(body.negotiation_id, thread)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=503, detail="payments service is unavailable"
            ) from exc
        return result, Identity.model_validate(thread["buyer_principal"])


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


def vm_seller_stages(build_plan: Callable[..., Any]) -> SettlementStageTable[Any]:
    return SettlementStageTable(
        {
            "alkahest.v1": VmAlkahestSellerStage(build_plan),
            "arkhai.payments.v1": VmPaymentsSellerStage(),
        }
    )


def resolve_proposal_stage(stages: SettlementStageTable[Any], proposal: Any) -> Any:
    """Decode the legacy Alkahest carrier only at the settlement boundary."""
    selection = (
        proposal.get("settlement_selection") if isinstance(proposal, Mapping) else None
    )
    mechanism = (
        selection.get("mechanism") if isinstance(selection, Mapping) else "alkahest.v1"
    )
    try:
        return stages[mechanism]
    except KeyError as exc:
        raise ValueError("settlement_mechanism_unsupported") from exc
