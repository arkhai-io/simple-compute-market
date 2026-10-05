"""Agreement-based seller dispatch and durable evidence handoff."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_core import SettlementEvidence, SettlementStageTable
from market_core.schemas import Agreement
from market_identity import Identity
from market_settlement_runtime import SettlementRuntime

from .arkhai_payments import BareMetalArkhaiPaymentsStage
from .models import (
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettlePendingResponse,
    BareMetalSettleStatusResponse,
)
from .settlement_evidence import DeliveryInput, EvidencePayload
from .settlement_stages import SettlementRequestError
from .settlement_composition import SELLER_STAGES
from .sqlite_client import SQLiteClient

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
    stages: SettlementStageTable[Any] = SELLER_STAGES

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
        self, *, negotiation_id: str, buyer_principal: Identity
    ) -> dict[str, Any]:
        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if thread is None:
            raise SettlementRequestError("negotiation not found", status_code=404)
        if Identity.model_validate(thread.get("buyer_principal")) != buyer_principal:
            raise SettlementRequestError("negotiation buyer mismatch", status_code=403)
        return thread

    def accepted_stage(self, thread: Mapping[str, Any], negotiation_id: str) -> Any:
        if thread.get("terminal_state") != "success":
            raise SettlementRequestError("negotiation is not accepted")
        try:
            agreement = Agreement.model_validate_json(thread["agreement_bytes"])
            if (
                agreement.negotiation_id != negotiation_id
                or agreement.listing_id != thread["our_listing_id"]
                or Identity.model_validate(agreement.buyer)
                != Identity.model_validate(thread["buyer_principal"])
                or Identity.model_validate(agreement.seller)
                != Identity.model_validate(thread["seller_principal"])
                or agreement.amount != thread["agreed_price"]
                or agreement.duration_seconds != thread["agreed_duration_seconds"]
            ):
                raise ValueError("Agreement differs from accepted negotiation")
            if agreement.settlement is None:
                raise ValueError("Agreement has no selected settlement")
            return self.stages[agreement.settlement.mechanism]
        except (KeyError, TypeError, ValueError) as exc:
            raise SettlementRequestError(
                "accepted Agreement has no supported settlement stage"
            ) from exc

    async def physical_terms(
        self, thread: Mapping[str, Any], negotiation_id: str
    ) -> tuple[Any, Any]:
        duration = thread.get("agreed_duration_seconds")
        terms = await self.db.load_bare_metal_terms(negotiation_id=negotiation_id)
        if terms is None or terms.duration_seconds != duration:
            raise SettlementRequestError(
                "bare-metal agreement terms are missing or inconsistent"
            )
        listing = await self.db.load_listing(listing_id=thread["our_listing_id"])
        offer = await self.db.load_bare_metal_listing_payload(
            listing_id=thread["our_listing_id"]
        )
        if listing is None or offer is None:
            raise SettlementRequestError(
                "negotiated listing not found", status_code=404
            )
        if (
            offer.machine_id != terms.machine_id
            or offer.physical_host_id != terms.physical_host_id
            or terms.listing_ref != thread["our_listing_id"]
        ):
            raise SettlementRequestError(
                "bare-metal agreement no longer matches its listing"
            )
        agreement = Agreement.model_validate_json(thread["agreement_bytes"])
        message = self.db._market_domain.codecs.message(agreement.provision_terms)
        if (
            message.duration_seconds != terms.duration_seconds
            or message.access_method != terms.access_method
            or message.ssh_public_key != terms.ssh_public_key
            or message.access_ref != terms.access_ref
        ):
            raise SettlementRequestError(
                "accepted physical terms differ from the Agreement"
            )
        return terms, listing

    async def persist_verified(
        self,
        *,
        negotiation_id: str,
        settlement_ref: str,
        mechanism: str,
        thread: Mapping[str, Any],
        source: Mapping[str, Any],
        agreement_sha256: str | None = None,
    ) -> SettlementEvidence:
        stage = self.accepted_stage(thread, negotiation_id)
        digest = hashlib.sha256(thread["agreement_bytes"]).hexdigest()
        if agreement_sha256 is not None and digest != agreement_sha256:
            raise SettlementRequestError(
                "settlement evidence is bound to another Agreement"
            )
        delivery = None
        if stage.physical:
            terms, _ = await self.physical_terms(thread, negotiation_id)
            context = await self.db.load_bare_metal_fulfillment_context(
                negotiation_id=negotiation_id
            )
            if context is None:
                raise SettlementRequestError("accepted resource binding is missing")
            delivery = DeliveryInput(
                site_id=context["site_id"],
                physical_resource_id=context["physical_resource_id"],
                pool_id=context.get("pool_id"),
                terms=terms,
            )
        evidence = SettlementEvidence(
            negotiation_id=negotiation_id,
            mechanism=mechanism,
            settlement_ref=settlement_ref,
            status="settlement_verified",
            evidence=EvidencePayload(
                agreement_sha256=digest, source=dict(source), delivery=delivery
            ).model_dump(mode="json"),
        )
        await self.db.save_bare_metal_settlement_evidence(evidence)
        return evidence

    async def verified_evidence(
        self, *, negotiation_id: str, buyer_principal: Identity
    ) -> SettlementEvidence:
        thread = await self._owned_thread(
            negotiation_id=negotiation_id, buyer_principal=buyer_principal
        )
        stage = self.accepted_stage(thread, negotiation_id)
        record = await self.db.load_bare_metal_settlement_record(
            negotiation_id=negotiation_id
        )
        if (
            record is None
            or record["status"] != "settlement_verified"
            or not record["settlement_ref"]
        ):
            raise SettlementRequestError(
                "bare-metal settlement is not authoritatively verified"
            )
        agreement = Agreement.model_validate_json(thread["agreement_bytes"])
        if (
            record["mechanism"] != agreement.settlement.mechanism
            or record["agreement_sha256"]
            != hashlib.sha256(thread["agreement_bytes"]).hexdigest()
        ):
            raise SettlementRequestError(
                "settlement evidence conflicts with accepted state"
            )
        try:
            await stage.revalidate(self, thread, record)
        except SettlementRequestError:
            raise
        except Exception as exc:
            raise SettlementRequestError(
                "verified settlement lifecycle is unavailable"
            ) from exc
        return SettlementEvidence(
            negotiation_id=record["negotiation_id"],
            mechanism=record["mechanism"],
            settlement_ref=record["settlement_ref"],
            status=record["status"],
            evidence=record["evidence"],
        )

    async def verify(
        self,
        *,
        escrow_uid: str,
        request: BareMetalSettleRequest,
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse | BareMetalSettlePendingResponse:
        thread = await self._owned_thread(
            negotiation_id=request.negotiation_id, buyer_principal=buyer_principal
        )
        stage = self.accepted_stage(thread, request.negotiation_id)
        record = await self.db.load_bare_metal_settlement_record(
            negotiation_id=request.negotiation_id
        )
        if (
            record is None
            or record["agreement_sha256"]
            != hashlib.sha256(thread["agreement_bytes"]).hexdigest()
        ):
            raise SettlementRequestError(
                "settlement evidence conflicts with accepted state"
            )
        return await stage.verify(
            self,
            negotiation_id=request.negotiation_id,
            thread=thread,
            buyer_principal=buyer_principal,
            escrow_uid=escrow_uid,
            request=request,
        )

    async def status(
        self, *, escrow_uid: str, buyer_principal: Identity
    ) -> BareMetalSettleStatusResponse:
        record = await self.db.load_bare_metal_settlement_record_by_ref(
            settlement_ref=escrow_uid
        )
        if record is None:
            raise SettlementRequestError(
                "settlement evidence not found", status_code=404
            )
        evidence = await self.verified_evidence(
            negotiation_id=record["negotiation_id"], buyer_principal=buyer_principal
        )
        thread = await self._owned_thread(
            negotiation_id=evidence.negotiation_id, buyer_principal=buyer_principal
        )
        return BareMetalSettleStatusResponse(
            escrow_uid=escrow_uid,
            negotiation_id=evidence.negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=Identity.model_validate(thread["seller_principal"]),
            status=evidence.status,
            obligation_ref=evidence.evidence["source"].get("obligation_ref"),
            fulfillment_available=evidence.evidence["delivery"] is not None,
        )
