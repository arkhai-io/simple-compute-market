"""Bare-metal domain callbacks for the contact-exchange introduction reveal."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_contact_exchange import (
    AuthorizedIntroductionRequest,
    DeliverIntroduction,
    IntroductionAgreement,
    IntroductionRecord,
    IntroductionRouteCallbacks,
    IntroductionRouteService,
)
from market_core.schemas import SettlementObligation, SettlementPlan
from market_identity import Identity
from market_settlement_runtime import (
    SettlementObligationRecord,
    derive_obligation_ref,
)

from .sqlite_client import SQLiteClient


async def _accepted_introduction(
    db: SQLiteClient,
    negotiation_id: str,
    obligation_ref: str,
) -> tuple[IntroductionAgreement, SettlementObligation]:
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    if thread is None or thread.get("terminal_state") != "success":
        raise ValueError("introduction deal is not accepted")
    plan = SettlementPlan.model_validate(thread.get("settlement_plan"))
    if len(plan.obligations) != 1:
        raise ValueError("introduction agreement must contain one obligation")
    obligation = plan.obligations[0]
    if obligation.mechanism != CONTACT_MECHANISM:
        raise ValueError("accepted deal is not an introduction")
    expected_ref = derive_obligation_ref(
        negotiation_id,
        0,
        obligation.model_dump(mode="json"),
    )
    if expected_ref != obligation_ref:
        raise ValueError("requested obligation does not match the accepted plan")
    package = plan.service_terms.get(CONTACT_MECHANISM)
    return (
        IntroductionAgreement(
            agreement_ref=negotiation_id,
            obligation_ref=obligation_ref,
            buyer_principal=Identity.model_validate(obligation.payer_principal),
            seller_principal=Identity.model_validate(obligation.claimant_principal),
            introduction_package=dict(package) if isinstance(package, Mapping) else {},
        ),
        obligation,
    )


def build_bare_metal_introduction_service(
    *,
    db: SQLiteClient,
    repository: Any,
    settlement_runtime: Any,
    seller_contact: Mapping[str, str],
    authorize_request: Callable[
        [Any, str, str, tuple[Identity, ...], Mapping[str, Any] | None],
        Awaitable[AuthorizedIntroductionRequest],
    ],
    deliver: DeliverIntroduction | None = None,
) -> IntroductionRouteService:
    """Install bare-metal accepted-state interpretation into the reveal service."""

    def _worker(operation: str) -> str:
        return f"{operation}:{uuid.uuid4().hex}"

    async def prepare(
        negotiation_id: str | None,
        obligation_ref: str,
    ) -> IntroductionAgreement:
        if negotiation_id is None:
            row = await repository.load_settlement_obligation(obligation_ref)
            if row is None:
                raise ValueError("introduction not found")
            negotiation_id = SettlementObligationRecord.model_validate(
                row
            ).agreement_ref
        agreement, _ = await _accepted_introduction(
            db,
            negotiation_id,
            obligation_ref,
        )
        return agreement

    async def persist(
        agreement: IntroductionAgreement,
        buyer_contact: Mapping[str, str],
        seller_payload: Mapping[str, str],
    ) -> IntroductionRecord:
        return await db.save_contact_introduction(
            IntroductionRecord(
                obligation_ref=agreement.obligation_ref,
                agreement_ref=agreement.agreement_ref,
                buyer_contact=dict(buyer_contact),
                seller_contact=dict(seller_payload),
                introduction_package=dict(agreement.introduction_package),
            )
        )

    async def load(obligation_ref: str) -> IntroductionRecord | None:
        return await db.load_contact_introduction(obligation_ref=obligation_ref)

    async def complete(agreement: IntroductionAgreement) -> None:
        """Drive the one non-financial obligation to collected; every step is
        idempotent, so a retried start converges instead of failing."""

        _, obligation = await _accepted_introduction(
            db,
            agreement.agreement_ref,
            agreement.obligation_ref,
        )
        await settlement_runtime.register_plan(
            agreement_ref=agreement.agreement_ref,
            obligations=[obligation.model_dump(mode="json")],
        )
        await settlement_runtime.materialize(
            obligation_ref=agreement.obligation_ref,
            local_principal=agreement.buyer_principal,
            worker_id=_worker("introduction-materialize"),
        )
        await settlement_runtime.bind_fulfillment(
            agreement.obligation_ref,
            f"introduction:{agreement.obligation_ref}",
            local_principal=agreement.seller_principal,
        )
        await settlement_runtime.check(
            obligation_ref=agreement.obligation_ref,
            local_principal=agreement.seller_principal,
            worker_id=_worker("introduction-check"),
        )
        await settlement_runtime.collect(
            obligation_ref=agreement.obligation_ref,
            local_principal=agreement.seller_principal,
            worker_id=_worker("introduction-collect"),
        )

    return IntroductionRouteService(
        callbacks=IntroductionRouteCallbacks(
            prepare=prepare,
            authorize=authorize_request,
            persist=persist,
            load=load,
            complete=complete,
        ),
        seller_contact=seller_contact,
        deliver=deliver,
    )


async def load_revealed_introduction(
    db: SQLiteClient,
    obligation_ref: str,
) -> tuple[IntroductionRecord, IntroductionAgreement]:
    """Load one already-revealed introduction and the deal it belongs to.

    The path an operator's re-delivery takes: it reads the durable reveal
    rather than reconstructing one, so a re-send can never invent contact data
    that was never exchanged.
    """

    record = await db.load_contact_introduction(obligation_ref=obligation_ref)
    if record is None:
        raise ValueError("introduction has not been revealed")
    agreement, _ = await _accepted_introduction(
        db,
        record.agreement_ref,
        obligation_ref,
    )
    return record, agreement


__all__ = [
    "build_bare_metal_introduction_service",
    "load_revealed_introduction",
]
