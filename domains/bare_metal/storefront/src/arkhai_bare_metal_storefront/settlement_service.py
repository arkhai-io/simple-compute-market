"""Commercial settlement verification without fulfillment claims."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_core.schemas import EscrowProposal, SettlementPlan
from market_settlement_runtime import SettlementRuntime
from market_identity import Identity

from .models import (
    BareMetalSettleRequest,
    BareMetalSettleResponse,
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
    seller_wallet: str
    chain_clients: Mapping[str, Any]
    chain_config_paths: Mapping[str, str | None]
    build_plan: PlanBuilder
    verify_escrow: VerifyEscrow
    settlement_runtime: SettlementRuntime

    @staticmethod
    def _response(
        *,
        escrow_uid: str,
        negotiation_id: str,
        buyer_principal: Identity,
        seller_principal: Identity,
    ) -> BareMetalSettleResponse:
        return BareMetalSettleResponse(
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            buyer_principal=buyer_principal,
            seller_principal=seller_principal,
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
        if thread.get("buyer_principal") != buyer_principal:
            raise SettlementRequestError("negotiation buyer mismatch", status_code=403)
        return thread

    async def verify(
        self,
        *,
        escrow_uid: str,
        request: BareMetalSettleRequest,
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse:
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
                seller_wallet_address=self.seller_wallet,
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
                seller_wallet=self.seller_wallet,
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
                local_role="seller",
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
        )

    async def status(
        self,
        *,
        escrow_uid: str,
        buyer_principal: Identity,
    ) -> BareMetalSettleStatusResponse:
        escrow = await self.db.load_escrow(escrow_uid=escrow_uid)
        if escrow is None:
            raise SettlementRequestError("escrow not found", status_code=404)
        await self._owned_thread(
            negotiation_id=str(escrow["negotiation_id"]),
            buyer_principal=buyer_principal,
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
                (await self._owned_thread(
                    negotiation_id=str(escrow["negotiation_id"]),
                    buyer_principal=buyer_principal,
                ))["seller_principal"],
            ),
            status=str(escrow["status"]),
        )
