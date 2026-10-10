"""Agreement-based seller dispatch, whose verified evidence starts fulfillment."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_arkhai_payments import (
    PaymentSellerStage,
    ReconciliationPass,
    reconcile_accepted_payments,
)
from market_core import SettlementEvidence, SettlementStageTable
from market_core.schemas import Agreement
from market_identity import Identity
from market_settlement_runtime import SettlementRuntime

from .fulfillment_service import BareMetalFulfillmentError
from .models import (
    BareMetalSettleRequest,
    BareMetalSettleResponse,
    BareMetalSettleStatusResponse,
)
from .settlement_evidence import DeliveryInput, EvidencePayload
from .settlement_stages import PaymentSettleResult, SettlementRequestError
from .settlement_composition import SELLER_STAGES
from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

VerifyEscrow = Callable[..., Awaitable[int]]
BeginFulfillment = Callable[..., Awaitable[dict[str, Any]]]

# Evidence statuses a seller refund may move verified evidence through. The
# verified facts stay unchanged; only delivery that had already started may
# still be read under them.
_REFUND_STATUSES = frozenset({"refunding", "refunded"})

__all__ = [
    "BareMetalSettlementService",
    "PaymentSettleResult",
    "SettlementRequestError",
]


@dataclass(frozen=True)
class BareMetalSettlementService:
    db: SQLiteClient
    seller_wallet: str | None
    chain_clients: Mapping[str, Any]
    chain_config_paths: Mapping[str, str | None]
    verify_escrow: VerifyEscrow
    settlement_runtime: SettlementRuntime
    arkhai_payments_stage: PaymentSellerStage | None = None
    stages: SettlementStageTable[Any] = SELLER_STAGES
    begin_fulfillment: BeginFulfillment | None = None
    # Steps an adopted obligation once, so fulfillment starts without waiting
    # for the worker's next pass; the worker remains its only retry path.
    service_obligation: Callable[[str], Awaitable[None]] | None = None

    async def _step(self, obligation_ref: str) -> None:
        if self.service_obligation is None:
            return
        try:
            await self.service_obligation(obligation_ref)
        except Exception:
            # The adoption stands; the worker's schedule retries the step.
            logger.exception(
                "stepping a verified bare-metal settlement failed",
                extra={"obligation_ref": obligation_ref},
            )

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
            offer.host_id != terms.host_id
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
        self,
        *,
        negotiation_id: str,
        buyer_principal: Identity,
        include_refunds: bool = False,
        delivery_started: bool = False,
    ) -> SettlementEvidence:
        """Verified evidence for an accepted deal, after its entry's recovery gate.

        ``include_refunds`` also admits evidence a seller refund has since moved
        to ``refunding`` or ``refunded``; only reads of delivery that had already
        started may ask for it, since a refund never undoes a started delivery.
        ``delivery_started`` asks the entry's recovery gate to confirm only the
        evidence's identity: a started delivery is observed and ended under the
        evidence it began with, while the mechanism's own progress (collection,
        reclaim) moves on.
        """
        thread = await self._owned_thread(
            negotiation_id=negotiation_id, buyer_principal=buyer_principal
        )
        stage = self.accepted_stage(thread, negotiation_id)
        record = await self.db.load_bare_metal_settlement_record(
            negotiation_id=negotiation_id
        )
        admitted = {"settlement_verified"} | (
            _REFUND_STATUSES if include_refunds else set()
        )
        if (
            record is None
            or record["status"] not in admitted
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
            await stage.revalidate(
                self, thread, record, delivery_started=delivery_started
            )
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

    async def start_delivery(
        self, *, negotiation_id: str, buyer_principal: Identity
    ) -> dict[str, Any]:
        """Start fulfillment for a deal whose settlement stage verifies and delivers.

        Fulfillment re-reads the verified evidence and orders its start against
        refund intent, so a deal refunded first is never delivered.
        """
        if self.begin_fulfillment is None:
            raise SettlementRequestError(
                "bare-metal fulfillment authorities are unavailable", status_code=503
            )
        try:
            return await self.begin_fulfillment(
                negotiation_id=negotiation_id, buyer_principal=buyer_principal
            )
        except BareMetalFulfillmentError as exc:
            raise SettlementRequestError(exc.detail, status_code=exc.status_code) from exc

    async def verify(
        self,
        *,
        escrow_uid: str,
        request: BareMetalSettleRequest,
        buyer_principal: Identity,
    ) -> BareMetalSettleResponse | PaymentSettleResult:
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

    async def reconcile_payments_once(self, *, limit: int = 100) -> ReconciliationPass:
        """Advance accepted deals their buyers have not settled, without the buyer.

        Each seller entry that converges without its buyer selects its own
        candidates: deals with no verified evidence, refunds left ``refunding``,
        and verified deals whose delivery never started. The entry's settle path,
        the one a buyer's call takes, advances each.
        """
        reconciling = {
            mechanism: stage
            for mechanism, stage in self.stages.items()
            if stage.reconcile is not None
        }
        candidates: list[tuple[str, Any]] = []
        for mechanism, stage in reconciling.items():
            for negotiation_id in await self.db.list_unsettled_payment_negotiations(
                mechanism=mechanism, limit=limit
            ):
                candidates.append((negotiation_id, stage))
        by_negotiation = dict(candidates[:limit])

        async def settle(negotiation_id: str) -> None:
            thread = await self.db.load_negotiation_thread_row(
                negotiation_id=negotiation_id
            )
            if thread is None:
                raise SettlementRequestError("negotiation not found", status_code=404)
            await by_negotiation[negotiation_id].reconcile(
                self,
                negotiation_id=negotiation_id,
                thread=thread,
                buyer_principal=Identity.model_validate(thread["buyer_principal"]),
            )

        return await reconcile_accepted_payments(
            list(by_negotiation), settle, logger=logger
        )

    async def refund(self, *, negotiation_id: str) -> PaymentSettleResult:
        """Refund an accepted deal through its Agreement's seller entry.

        An entry without a seller refund reverses through its own mechanism
        path, so the request is refused rather than reinterpreted.
        """
        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        if thread is None or thread.get("terminal_state") != "success":
            raise SettlementRequestError(
                "accepted negotiation not found", status_code=404
            )
        stage = self.accepted_stage(thread, negotiation_id)
        if stage.refund is None:
            raise SettlementRequestError(
                "this settlement mechanism refunds through its own path"
            )
        return await stage.refund(self, negotiation_id=negotiation_id, thread=thread)

    async def status(
        self, *, escrow_uid: str, buyer_principal: Identity
    ) -> BareMetalSettleStatusResponse:
        record = await self.db.load_bare_metal_settlement_record_by_ref(
            settlement_ref=escrow_uid
        ) or await self.db.load_bare_metal_settlement_record(negotiation_id=escrow_uid)
        if record is None:
            raise SettlementRequestError(
                "settlement evidence not found", status_code=404
            )
        evidence = await self.verified_evidence(
            negotiation_id=record["negotiation_id"],
            buyer_principal=buyer_principal,
            include_refunds=True,
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
            fulfillment_available=(
                evidence.evidence["delivery"] is not None
                and evidence.status == "settlement_verified"
            ),
        )
