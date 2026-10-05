"""Seller-owned settlement execution and recovery gates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    Mandate,
    SignedReceipt,
    transaction_id,
)
from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_core import SettlementEvidence
from market_core.schemas import (
    Agreement,
    EscrowProposal,
    SettlementPlan,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import Identity

from .models import BareMetalSettlePendingResponse
from .settlement_evidence import EvidencePayload

ALKAHEST_MECHANISM = "alkahest.v1"


class SettlementRequestError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


async def verify_payment(
    service: Any,
    *,
    negotiation_id: str,
    thread: Mapping[str, Any],
    buyer_principal: Identity,
    escrow_uid: str,
    request: Any,
) -> Any:
    if escrow_uid != negotiation_id or request.buyer_evm_address is not None:
        raise SettlementRequestError(
            "Arkhai settlement is addressed by negotiation ID only", status_code=400
        )
    await service.physical_terms(thread, negotiation_id)
    stage = service.arkhai_payments_stage
    agreement_bytes = thread.get("agreement_bytes")
    record = await service.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    if stage is None or record is None:
        raise SettlementRequestError("Arkhai settlement is not configured")
    if not isinstance(agreement_bytes, (bytes, bytearray)):
        raise SettlementRequestError("accepted Agreement bytes are unavailable")
    agreement_sha256 = hashlib.sha256(bytes(agreement_bytes)).hexdigest()
    if record.get("agreement_sha256") != agreement_sha256:
        raise SettlementRequestError(
            "stored payment mandate is bound to another Agreement"
        )
    try:
        agreement = json.loads(agreement_bytes)
        accepted = Agreement.model_validate(agreement)
        if (
            agreement.get("negotiation_id") != negotiation_id
            or agreement.get("listing_id") != thread.get("our_listing_id")
            or agreement.get("buyer") != buyer_principal.model_dump(mode="json")
            or agreement.get("seller")
            != Identity.model_validate(thread["seller_principal"]).model_dump(
                mode="json"
            )
            or accepted.amount != thread.get("agreed_price")
            or agreement.get("duration_seconds")
            != thread.get("agreed_duration_seconds")
        ):
            raise ValueError("stored Agreement does not match the accepted negotiation")
        derived = stage.mandate_for_agreement(agreement)
        if thread.get("settlement_data") != derived:
            raise ValueError(
                "stored payment mandate differs from the accepted Agreement"
            )
        mandate = Mandate.model_validate(derived)
        settlement_ref = transaction_id(mandate)
    except Exception as exc:
        raise SettlementRequestError(
            "payment mandate does not prove the accepted Agreement", status_code=400
        ) from exc

    if record.get("status") == "settlement_verified":
        try:
            receipt = SignedReceipt.model_validate(
                record["evidence"]["source"].get("receipt")
            )
        except (TypeError, ValueError) as exc:
            raise SettlementRequestError(
                "stored payment receipt is invalid", status_code=400
            ) from exc
        if record.get("settlement_ref") != settlement_ref or not stage.receipt_matches(
            receipt, agreement=agreement, mandate=mandate
        ):
            raise SettlementRequestError(
                "stored payment receipt is invalid", status_code=400
            )
        return service._response(
            escrow_uid=settlement_ref,
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
        )

    try:
        signed_receipt = await stage.verify_receipt(
            transaction=settlement_ref, agreement=agreement
        )
    except Exception as exc:
        raise SettlementRequestError(
            "payments receipt service is temporarily unavailable", status_code=503
        ) from exc
    if signed_receipt is None:
        return BareMetalSettlePendingResponse(
            negotiation_id=negotiation_id,
            escrow_uid=settlement_ref,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
        )
    try:
        await service.persist_verified(
            negotiation_id=negotiation_id,
            settlement_ref=settlement_ref,
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
            agreement_sha256=agreement_sha256,
            source={
                "receipt": signed_receipt.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                )
            },
            thread=thread,
        )
    except Exception as exc:
        raise SettlementRequestError(
            "payment settlement evidence conflicts with accepted state"
        ) from exc
    return service._response(
        escrow_uid=settlement_ref,
        negotiation_id=negotiation_id,
        buyer_principal=buyer_principal,
        seller_principal=Identity.model_validate(thread["seller_principal"]),
    )


async def verify_alkahest(
    service: Any,
    *,
    negotiation_id: str,
    thread: Mapping[str, Any],
    buyer_principal: Identity,
    escrow_uid: str,
    request: Any,
) -> Any:
    existing = await service.db.load_escrow(escrow_uid=escrow_uid)
    terms, listing = await service.physical_terms(thread, request.negotiation_id)
    agreed_amount = thread["agreed_price"]
    if request.buyer_evm_address is None:
        raise SettlementRequestError("Alkahest settlement requires buyer_evm_address")
    proposal = EscrowProposal.model_validate(thread.get("buyer_escrow_proposal"))
    primary = await service.db.load_primary_escrow_for_negotiation(
        negotiation_id=request.negotiation_id,
    )
    if primary is not None and primary.get("escrow_uid") != escrow_uid:
        raise SettlementRequestError("negotiation already has a primary escrow")
    if existing is not None and (
        existing.get("negotiation_id") != request.negotiation_id
        or existing.get("status") != "settlement_verified"
        or existing.get("chain_name") != proposal.chain_name
        or str(existing.get("escrow_address", "")).lower()
        != proposal.escrow_address.lower()
    ):
        raise SettlementRequestError("escrow identity already belongs to another state")

    try:
        artifacts = service.build_plan(
            proposal=proposal,
            agreed_amount=int(agreed_amount),
            duration_seconds=terms.duration_seconds,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
            seller_wallet_address=service.seller_wallet or "",
            chain_config_paths=service.chain_config_paths,
        )
        plan = SettlementPlan.model_validate(artifacts.get("settlement_plan"))
    except SettlementRequestError:
        raise
    except Exception as exc:
        raise SettlementRequestError(
            "settlement verification failed",
            status_code=400,
        ) from exc
    obligations = tuple(
        obligation.model_dump(mode="json") for obligation in plan.obligations
    )
    if not obligations:
        raise SettlementRequestError(
            "accepted settlement plan has no obligations",
            status_code=400,
        )

    records = None
    if existing is not None:
        try:
            records = await service.settlement_runtime.register_plan(
                agreement_ref=request.negotiation_id,
                obligations=list(obligations),
            )
        except Exception as exc:
            raise SettlementRequestError(
                "settlement plan conflicts with accepted terms"
            ) from exc
        adopted = [
            record
            for record in records
            if record.mechanism_ref == escrow_uid
            and record.materialization_state == "materialized"
        ]
        if len(adopted) == 1:
            await service.persist_verified(
                negotiation_id=request.negotiation_id,
                settlement_ref=escrow_uid,
                mechanism=ALKAHEST_MECHANISM,
                thread=thread,
                source={"obligation_ref": adopted[0].obligation_ref},
            )
            return service._response(
                escrow_uid=escrow_uid,
                negotiation_id=request.negotiation_id,
                buyer_principal=buyer_principal,
                seller_principal=Identity.model_validate(
                    thread["seller_principal"],
                ),
                obligation_ref=adopted[0].obligation_ref,
            )
        if any(record.mechanism_ref == escrow_uid for record in records):
            raise SettlementRequestError("verified settlement adoption is incomplete")

    client = service.chain_clients.get(proposal.chain_name)
    if client is None:
        raise SettlementRequestError(
            f"settlement chain {proposal.chain_name!r} is unavailable",
            status_code=503,
        )
    try:
        matched_index = await service.verify_escrow(
            escrow_uid=escrow_uid,
            seller_wallet=service.seller_wallet or "",
            agreed_price=int(agreed_amount),
            agreed_duration_seconds=terms.duration_seconds,
            listing=listing,
            alkahest_client=client,
            chain_name=proposal.chain_name,
            alkahest_address_config_path=service.chain_config_paths.get(
                proposal.chain_name,
            ),
            escrow_proposal=proposal,
        )
    except SettlementRequestError:
        raise
    except Exception as exc:
        raise SettlementRequestError(
            "settlement verification failed",
            status_code=400,
        ) from exc
    if (
        isinstance(matched_index, bool)
        or not isinstance(matched_index, int)
        or matched_index < 0
        or matched_index >= len(obligations)
    ):
        raise SettlementRequestError(
            "settlement verification returned no exact obligation",
            status_code=400,
        )

    if records is None:
        try:
            records = await service.settlement_runtime.register_plan(
                agreement_ref=request.negotiation_id,
                obligations=list(obligations),
            )
        except Exception as exc:
            raise SettlementRequestError(
                "settlement plan conflicts with accepted terms"
            ) from exc

    try:
        outcome = await service.settlement_runtime.adopt(
            records[matched_index].obligation_ref,
            local_principal=Identity.model_validate(thread["seller_principal"]),
            mechanism_ref=escrow_uid,
            receipt=None,
            condition_anchor=None,
            mechanism_state=None,
            worker_id="bare-metal-verified",
        )
    except Exception as exc:
        raise SettlementRequestError(
            "conflicting verified settlement adoption"
        ) from exc
    if outcome.status != "succeeded":
        raise SettlementRequestError("verified settlement adoption is incomplete")
    if existing is None:
        inserted = await service.db.insert_escrow(
            escrow_uid=escrow_uid,
            negotiation_id=request.negotiation_id,
            chain_name=proposal.chain_name,
            escrow_address=proposal.escrow_address,
            is_primary=True,
            status="settlement_verified",
        )
        if not inserted:
            raced = await service.db.load_escrow(escrow_uid=escrow_uid)
            if not raced or (
                raced.get("negotiation_id") != request.negotiation_id
                or raced.get("chain_name") != proposal.chain_name
                or str(raced.get("escrow_address", "")).lower()
                != proposal.escrow_address.lower()
                or raced.get("status") != "settlement_verified"
            ):
                raise SettlementRequestError("conflicting escrow settlement")
    await service.persist_verified(
        negotiation_id=request.negotiation_id,
        settlement_ref=escrow_uid,
        mechanism=ALKAHEST_MECHANISM,
        thread=thread,
        source={"obligation_ref": records[matched_index].obligation_ref},
    )
    return service._response(
        escrow_uid=escrow_uid,
        negotiation_id=request.negotiation_id,
        buyer_principal=buyer_principal,
        seller_principal=Identity.model_validate(thread["seller_principal"]),
        obligation_ref=records[matched_index].obligation_ref,
    )


async def verify_contact(service: Any, **kwargs: Any) -> Any:
    raise SettlementRequestError(
        "contact exchange settles through the authenticated introductions surface",
        status_code=400,
    )


async def revalidate_payment(
    service: Any, thread: Mapping[str, Any], record: Mapping[str, Any]
) -> None:
    stage = service.arkhai_payments_stage
    if stage is None:
        raise SettlementRequestError("Arkhai settlement is not configured")
    try:
        agreement = json.loads(thread["agreement_bytes"])
        mandate = Mandate.model_validate(stage.mandate_for_agreement(agreement))
        receipt = SignedReceipt.model_validate(record["evidence"]["source"]["receipt"])
        if (
            thread.get("settlement_data")
            != mandate.model_dump(mode="json", by_alias=True, exclude_none=True)
            or transaction_id(mandate) != record["settlement_ref"]
            or not stage.receipt_matches(receipt, agreement=agreement, mandate=mandate)
        ):
            raise ValueError("stored payment receipt differs from accepted state")
    except Exception as exc:
        raise SettlementRequestError(
            "stored payment receipt is invalid", status_code=400
        ) from exc


async def revalidate_alkahest(
    service: Any, thread: Mapping[str, Any], record: Mapping[str, Any]
) -> None:
    aggregate = await service.settlement_runtime.get_status(record["negotiation_id"])
    adopted = [
        obligation
        for obligation in aggregate.obligations
        if obligation.mechanism_ref == record["settlement_ref"]
        and obligation.materialization_state == "materialized"
        and obligation.obligation_ref
        == record["evidence"]["source"].get("obligation_ref")
    ]
    if len(adopted) != 1 or adopted[0].fulfillment_ref is not None:
        raise SettlementRequestError("verified settlement lifecycle is inconsistent")


async def revalidate_contact(
    service: Any, thread: Mapping[str, Any], record: Mapping[str, Any]
) -> None:
    reveal = await service.db.load_contact_introduction(
        obligation_ref=record["settlement_ref"]
    )
    if reveal is None or reveal.agreement_ref != record["negotiation_id"]:
        raise SettlementRequestError("introduction has not been revealed")


def alkahest_resources(
    seller_wallet: str | None, build_chains: Callable[[], Any]
) -> Any:
    if not seller_wallet:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_EVM_ADDRESS is required when Alkahest is enabled"
        )
    return build_chains()


@dataclass(frozen=True, slots=True)
class SellerStage:
    registration_factory: Callable[[], Any]
    verify: Callable[..., Any]
    revalidate: Callable[..., Any]
    physical: bool
    runtime_resources: Callable[..., Any] | None = None

    def accepted_data(
        self, agreement: Mapping[str, Any], payment_stage: Any
    ) -> Mapping[str, Any] | None:
        return None


@dataclass(frozen=True, slots=True)
class PaymentStage(SellerStage):
    def accepted_data(
        self, agreement: Mapping[str, Any], payment_stage: Any
    ) -> Mapping[str, Any]:
        if payment_stage is None:
            raise ValueError("Arkhai settlement is not configured")
        return payment_stage.mandate_for_agreement(agreement)


@dataclass(frozen=True, slots=True)
class ContactStage(SellerStage):
    @staticmethod
    async def record_reveal(db: Any, agreement: Any) -> None:
        thread = await db.load_negotiation_thread_row(
            negotiation_id=agreement.agreement_ref
        )
        if thread is None or not thread.get("agreement_bytes"):
            raise ValueError("accepted introduction Agreement is unavailable")
        await db.save_bare_metal_settlement_evidence(
            SettlementEvidence(
                negotiation_id=agreement.agreement_ref,
                mechanism=CONTACT_MECHANISM,
                settlement_ref=agreement.obligation_ref,
                status="settlement_verified",
                evidence=EvidencePayload(
                    agreement_sha256=hashlib.sha256(
                        thread["agreement_bytes"]
                    ).hexdigest(),
                    source={"obligation_ref": agreement.obligation_ref},
                ).model_dump(mode="json"),
            )
        )


def legacy_alkahest_option(
    proposal: EscrowProposal, plan: Mapping[str, Any]
) -> SettlementOption:
    """Project the explicit Alkahest acceptance into the Agreement's selection."""
    obligations = plan.get("obligations") or []
    asset = obligations[0].get("asset") if obligations else None
    asset = asset or "native"
    params = proposal.model_dump(mode="json", exclude_none=True)
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=ALKAHEST_MECHANISM, asset=asset, rates=[], params=params
        ),
        mechanism=ALKAHEST_MECHANISM,
        asset=asset,
        rates=[],
        params=params,
    )
