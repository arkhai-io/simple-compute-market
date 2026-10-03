"""Commercial settlement verification without fulfillment claims."""

from __future__ import annotations

import json
import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_core.schemas import EscrowProposal, SettlementPlan
from market_identity import Identity
from market_settlement_runtime import SettlementRuntime

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_arkhai_payments import Mandate, SignedReceipt, transaction_id

from .arkhai_payments import BareMetalArkhaiPaymentsStage
from .models import (
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettlePendingResponse,
    BareMetalSettleStatusResponse,
)
from .sqlite_client import SQLiteClient


class SettlementRequestError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


VerifyEscrow = Callable[..., Awaitable[int]]
PlanBuilder = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class BareMetalSettlementService:
    db: SQLiteClient
    seller_wallet: str | None
    chain_clients: Mapping[str, Any]
    chain_config_paths: Mapping[str, str | None]
    build_plan: PlanBuilder
    verify_escrow: VerifyEscrow
    settlement_runtime: SettlementRuntime
    arkhai_payments_stage: BareMetalArkhaiPaymentsStage | None = None

    @staticmethod
    def _response(
        *,
        escrow_uid: str,
        negotiation_id: str,
        buyer_principal: Identity,
        seller_principal: Identity,
        obligation_ref: str | None = None,
    ) -> BareMetalSettleResponse:
        return BareMetalSettleResponse(
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
            obligation_ref=obligation_ref,
        )

    async def _owned_thread(
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
    ) -> dict[str, Any]:
        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id,
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        if Identity.model_validate(thread.get("buyer_principal")) != buyer_principal:
            raise SettlementRequestError("negotiation buyer mismatch", status_code=403)
        return thread

    async def _verify_arkhai_payment(
        self,
        *,
        negotiation_id: str,
        thread: Mapping[str, Any],
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse | BareMetalSettlePendingResponse:
        stage = self.arkhai_payments_stage
        agreement_bytes = thread.get("agreement_bytes")
        record = await self.db.load_bare_metal_settlement_record(
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
            if (
                agreement.get("negotiation_id") != negotiation_id
                or agreement.get("listing_id") != thread.get("our_listing_id")
                or agreement.get("buyer") != buyer_principal.model_dump(mode="json")
                or agreement.get("seller")
                != Identity.model_validate(thread["seller_principal"]).model_dump(
                    mode="json"
                )
                or agreement.get("amount") != thread.get("agreed_price")
                or agreement.get("duration_seconds")
                != thread.get("agreed_duration_seconds")
            ):
                raise ValueError(
                    "stored Agreement does not match the accepted negotiation"
                )
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
                receipt = SignedReceipt.model_validate(record.get("receipt"))
            except (TypeError, ValueError) as exc:
                raise SettlementRequestError(
                    "stored payment receipt is invalid", status_code=400
                ) from exc
            if record.get(
                "settlement_ref"
            ) != settlement_ref or not stage.receipt_matches(
                receipt, agreement=agreement, mandate=mandate
            ):
                raise SettlementRequestError(
                    "stored payment receipt is invalid", status_code=400
                )
            return self._response(
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
            await self.db.mark_bare_metal_settlement_verified(
                negotiation_id=negotiation_id,
                settlement_ref=settlement_ref,
                mechanism=ARKHAI_PAYMENTS_MECHANISM,
                agreement_sha256=agreement_sha256,
                receipt=signed_receipt.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
            )
        except Exception as exc:
            raise SettlementRequestError(
                "payment settlement evidence conflicts with accepted state"
            ) from exc
        return self._response(
            escrow_uid=settlement_ref,
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
        )

    async def verify(
        self,
        *,
        escrow_uid: str,
        request: BareMetalSettleRequest,
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse | BareMetalSettlePendingResponse:
        existing = await self.db.load_escrow(escrow_uid=escrow_uid)
        thread = await self._owned_thread(
            negotiation_id=request.negotiation_id,
            buyer_principal=buyer_principal,
        )
        if thread.get("terminal_state") != "success":
            raise SettlementRequestError("negotiation is not accepted")
        agreed_amount = thread.get("agreed_price")
        duration = thread.get("agreed_duration_seconds")
        if agreed_amount is None or not isinstance(duration, int) or duration < 1:
            raise SettlementRequestError("negotiation has no committed agreement")
        terms = await self.db.load_bare_metal_terms(
            negotiation_id=request.negotiation_id,
        )
        if terms is None or terms.duration_seconds != duration:
            raise SettlementRequestError(
                "bare-metal agreement terms are missing or inconsistent"
            )
        listing = await self.db.load_listing(listing_id=thread["our_listing_id"])
        if listing is None:
            raise SettlementRequestError(
                "negotiated listing not found", status_code=404
            )
        offer = await self.db.load_bare_metal_listing_payload(
            listing_id=thread["our_listing_id"],
        )
        assert offer is not None
        if (
            offer.machine_id != terms.machine_id
            or offer.physical_host_id != terms.physical_host_id
            or terms.listing_ref != thread["our_listing_id"]
        ):
            raise SettlementRequestError(
                "bare-metal agreement no longer matches its listing"
            )
        agreement_bytes = thread.get("agreement_bytes")
        if isinstance(agreement_bytes, (bytes, bytearray)):
            try:
                agreement = json.loads(agreement_bytes)
            except (TypeError, ValueError) as exc:
                raise SettlementRequestError(
                    "accepted Agreement bytes are invalid"
                ) from exc
            selected = agreement.get("settlement")
            if (
                isinstance(selected, Mapping)
                and selected.get("mechanism") == ARKHAI_PAYMENTS_MECHANISM
            ):
                if (
                    escrow_uid != request.negotiation_id
                    or request.buyer_evm_address is not None
                ):
                    raise SettlementRequestError(
                        "Arkhai settlement is addressed by negotiation ID only",
                        status_code=400,
                    )
                return await self._verify_arkhai_payment(
                    negotiation_id=request.negotiation_id,
                    thread=thread,
                    buyer_principal=buyer_principal,
                )
        if request.buyer_evm_address is None:
            raise SettlementRequestError(
                "Alkahest settlement requires buyer_evm_address"
            )
        proposal = EscrowProposal.model_validate(thread.get("buyer_escrow_proposal"))
        primary = await self.db.load_primary_escrow_for_negotiation(
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
            raise SettlementRequestError(
                "escrow identity already belongs to another state"
            )

        try:
            artifacts = self.build_plan(
                proposal=proposal,
                agreed_amount=int(agreed_amount),
                duration_seconds=terms.duration_seconds,
                buyer_principal=buyer_principal,
                seller_principal=Identity.model_validate(thread["seller_principal"]),
                seller_wallet_address=self.seller_wallet or "",
                chain_config_paths=self.chain_config_paths,
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
                records = await self.settlement_runtime.register_plan(
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
                return self._response(
                    escrow_uid=escrow_uid,
                    negotiation_id=request.negotiation_id,
                    buyer_principal=buyer_principal,
                    seller_principal=Identity.model_validate(
                        thread["seller_principal"],
                    ),
                    obligation_ref=adopted[0].obligation_ref,
                )
            if any(record.mechanism_ref == escrow_uid for record in records):
                raise SettlementRequestError(
                    "verified settlement adoption is incomplete"
                )

        client = self.chain_clients.get(proposal.chain_name)
        if client is None:
            raise SettlementRequestError(
                f"settlement chain {proposal.chain_name!r} is unavailable",
                status_code=503,
            )
        try:
            matched_index = await self.verify_escrow(
                escrow_uid=escrow_uid,
                seller_wallet=self.seller_wallet or "",
                agreed_price=int(agreed_amount),
                agreed_duration_seconds=terms.duration_seconds,
                listing=listing,
                alkahest_client=client,
                chain_name=proposal.chain_name,
                alkahest_address_config_path=self.chain_config_paths.get(
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
                records = await self.settlement_runtime.register_plan(
                    agreement_ref=request.negotiation_id,
                    obligations=list(obligations),
                )
            except Exception as exc:
                raise SettlementRequestError(
                    "settlement plan conflicts with accepted terms"
                ) from exc

        try:
            outcome = await self.settlement_runtime.adopt(
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
            inserted = await self.db.insert_escrow(
                escrow_uid=escrow_uid,
                negotiation_id=request.negotiation_id,
                chain_name=proposal.chain_name,
                escrow_address=proposal.escrow_address,
                is_primary=True,
                status="settlement_verified",
            )
            if not inserted:
                raced = await self.db.load_escrow(escrow_uid=escrow_uid)
                if not raced or (
                    raced.get("negotiation_id") != request.negotiation_id
                    or raced.get("chain_name") != proposal.chain_name
                    or str(raced.get("escrow_address", "")).lower()
                    != proposal.escrow_address.lower()
                    or raced.get("status") != "settlement_verified"
                ):
                    raise SettlementRequestError("conflicting escrow settlement")
        return self._response(
            escrow_uid=escrow_uid,
            negotiation_id=request.negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
            obligation_ref=records[matched_index].obligation_ref,
        )

    async def status(
        self,
        *,
        escrow_uid: str,
        buyer_principal: Identity,
    ) -> BareMetalSettleStatusResponse:
        record = await self.db.load_bare_metal_settlement_record_by_ref(
            settlement_ref=escrow_uid
        )
        if record is not None:
            thread = await self._owned_thread(
                negotiation_id=str(record["negotiation_id"]),
                buyer_principal=buyer_principal,
            )
            if record.get("status") != "settlement_verified":
                raise SettlementRequestError("payment receipt has not been verified")
            return BareMetalSettleStatusResponse(
                escrow_uid=escrow_uid,
                negotiation_id=str(record["negotiation_id"]),
                buyer_principal=buyer_principal,
                seller_principal=Identity.model_validate(thread["seller_principal"]),
                status="settlement_verified",
            )
        escrow = await self.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise SettlementRequestError("escrow not found", status_code=404)
        await self._owned_thread(
            negotiation_id=str(escrow["negotiation_id"]),
            buyer_principal=buyer_principal,
        )
        if escrow.get("chain_name") == ARKHAI_PAYMENTS_MECHANISM:
            if escrow.get("status") != "settlement_verified":
                raise SettlementRequestError("payment receipt has not been verified")
            thread = await self._owned_thread(
                negotiation_id=str(escrow["negotiation_id"]),
                buyer_principal=buyer_principal,
            )
            return BareMetalSettleStatusResponse(
                escrow_uid=escrow_uid,
                negotiation_id=str(escrow["negotiation_id"]),
                buyer_principal=buyer_principal,
                seller_principal=Identity.model_validate(thread["seller_principal"]),
                status="settlement_verified",
            )
        try:
            aggregate = await self.settlement_runtime.get_status(
                str(escrow["negotiation_id"])
            )
        except Exception as exc:
            raise SettlementRequestError(
                "verified settlement lifecycle is unavailable"
            ) from exc
        adopted = [
            obligation
            for obligation in aggregate.obligations
            if obligation.mechanism_ref == escrow_uid
            and obligation.materialization_state == "materialized"
        ]
        if len(adopted) != 1 or adopted[0].fulfillment_ref is not None:
            raise SettlementRequestError(
                "verified settlement lifecycle is inconsistent"
            )
        return BareMetalSettleStatusResponse(
            escrow_uid=escrow_uid,
            negotiation_id=str(escrow["negotiation_id"]),
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(
                (
                    await self._owned_thread(
                        negotiation_id=str(escrow["negotiation_id"]),
                        buyer_principal=buyer_principal,
                    )
                )["seller_principal"],
            ),
            status=str(escrow["status"]),
            obligation_ref=adopted[0].obligation_ref,
        )
