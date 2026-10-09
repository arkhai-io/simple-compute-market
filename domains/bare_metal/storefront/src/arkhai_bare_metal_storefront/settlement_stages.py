"""Seller-owned settlement execution and recovery gates."""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core_storefront.models.settle_models import (
    AgreementSettleResponse,
    RefundSettlementResponse,
)
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    MandatePolicyError,
    NothingToReverse,
    NotPaid,
    PaymentsBlocked,
    PaymentSellerStage,
    PaymentSettlementData,
    PaymentsUnavailable,
    ReceiptBlocked,
    ReceiptInvalid,
    ReceiptPending,
    ReceiptUnavailable,
    RefundBlocked,
    Refunded,
    SignedReceipt,
)
from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_contact_exchange import SQLiteIntroductionStore
from market_core import SettlementEvidence
from market_core.schemas import (
    Agreement,
    EscrowProposal,
    SettlementPlan,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import Identity

from .settlement_evidence import EvidencePayload

ALKAHEST_MECHANISM = "alkahest.v1"

logger = logging.getLogger(__name__)


class SettlementRequestError(ValueError):
    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class PaymentSettleResult:
    """A payment settle or refund outcome: its status code and neutral payload."""

    status_code: int
    payload: dict[str, Any]


def _accepted_payment(
    service: Any,
    *,
    negotiation_id: str,
    thread: Mapping[str, Any],
    record: Mapping[str, Any] | None,
    buyer_principal: Identity,
) -> tuple[PaymentSellerStage, dict[str, Any], PaymentSettlementData]:
    """The servicing stage plus the stored Agreement and settlement data it derives."""

    stage = service.arkhai_payments_stage
    if stage is None or record is None:
        raise SettlementRequestError("Arkhai settlement is not configured")
    agreement_bytes = thread.get("agreement_bytes")
    if not isinstance(agreement_bytes, (bytes, bytearray)):
        raise SettlementRequestError("accepted Agreement bytes are unavailable")
    if record.get("agreement_sha256") != hashlib.sha256(bytes(agreement_bytes)).hexdigest():
        raise SettlementRequestError("stored payment mandate is bound to another Agreement")
    try:
        agreement, data = stage.accepted(bytes(agreement_bytes), thread.get("settlement_data"))
        accepted = Agreement.model_validate(agreement)
        seller = Identity.model_validate(thread["seller_principal"])
    except (MandatePolicyError, KeyError, TypeError, ValueError) as exc:
        raise SettlementRequestError("accepted payment state is invalid") from exc
    if (
        agreement.get("negotiation_id") != negotiation_id
        or agreement.get("listing_id") != thread.get("our_listing_id")
        or agreement.get("buyer") != buyer_principal.model_dump(mode="json")
        or agreement.get("seller") != seller.model_dump(mode="json")
        or accepted.amount != thread.get("agreed_price")
        or agreement.get("duration_seconds") != thread.get("agreed_duration_seconds")
    ):
        raise SettlementRequestError("stored Agreement does not match the accepted negotiation")
    return stage, agreement, data


def _payment_payload(
    *,
    negotiation_id: str,
    data: PaymentSettlementData,
    status: str,
    buyer_principal: Identity,
    seller_principal: Identity,
    retryable: bool = False,
    lifecycle: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = dict(lifecycle or {})
    payload.update(
        negotiation_id=negotiation_id,
        escrow_uid=negotiation_id,
        settlement_ref=data.transaction_id,
        status=status,
        retryable=retryable,
        buyer_principal=buyer_principal.model_dump(mode="json"),
        seller_principal=seller_principal.model_dump(mode="json"),
    )
    return payload


async def verify_payment(
    service: Any,
    *,
    negotiation_id: str,
    thread: Mapping[str, Any],
    buyer_principal: Identity,
    escrow_uid: str,
    request: Any,
) -> PaymentSettleResult:
    if escrow_uid != negotiation_id or request.buyer_evm_address is not None:
        raise SettlementRequestError(
            "Arkhai settlement is addressed by negotiation ID only", status_code=400
        )
    return await settle_payment(
        service,
        negotiation_id=negotiation_id,
        thread=thread,
        buyer_principal=buyer_principal,
    )


async def settle_payment(
    service: Any,
    *,
    negotiation_id: str,
    thread: Mapping[str, Any],
    buyer_principal: Identity,
) -> PaymentSettleResult:
    """Verify, record and deposit an accepted payment, then start its delivery.

    Idempotent, so the buyer's retries and the seller's reconciliation pass
    take the same path: a recorded receipt is re-checked rather than fetched,
    and a refund left ``refunding`` is completed instead of delivering.
    """

    await service.physical_terms(thread, negotiation_id)
    record = await service.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    stage, agreement, data = _accepted_payment(
        service,
        negotiation_id=negotiation_id,
        thread=thread,
        record=record,
        buyer_principal=buyer_principal,
    )
    assert record is not None
    seller = Identity.model_validate(thread["seller_principal"])

    def result(status_code: int, status: str, **extra: Any) -> PaymentSettleResult:
        return PaymentSettleResult(
            status_code,
            _payment_payload(
                negotiation_id=negotiation_id,
                data=data,
                status=status,
                buyer_principal=buyer_principal,
                seller_principal=seller,
                **extra,
            ),
        )

    if record.get("status") in ("refunding", "refunded"):
        if record.get("status") == "refunding":
            await _complete_refund(service, negotiation_id, stage, agreement, data)
        return result(200, "refunded")
    if record.get("status") == "settlement_verified":
        try:
            receipt = SignedReceipt.model_validate(
                record["evidence"]["source"].get("receipt")
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SettlementRequestError("stored payment receipt is invalid") from exc
        if record.get("settlement_ref") != data.transaction_id or not stage.receipt_matches(
            receipt, agreement, data
        ):
            logger.error("stored payment receipt for %s no longer verifies", negotiation_id)
            raise SettlementRequestError("stored payment receipt does not prove this Agreement")
    else:
        outcome = await stage.check_receipt(agreement, data)
        if isinstance(outcome, ReceiptPending):
            return result(202, "pending", retryable=True)
        if isinstance(outcome, ReceiptUnavailable):
            raise SettlementRequestError("payments service is unavailable", status_code=503)
        if isinstance(outcome, ReceiptBlocked):
            logger.error(
                "payment settlement for %s needs operator action: %s",
                negotiation_id,
                outcome.reason,
            )
            raise SettlementRequestError(
                "payments integration needs operator action", status_code=500
            )
        if isinstance(outcome, ReceiptInvalid):
            logger.error(
                "payment receipt for %s does not verify: %s", negotiation_id, outcome.reason
            )
            raise SettlementRequestError("payments receipt does not prove this Agreement")
        try:
            await service.persist_verified(
                negotiation_id=negotiation_id,
                settlement_ref=data.transaction_id,
                mechanism=ARKHAI_PAYMENTS_MECHANISM,
                agreement_sha256=record["agreement_sha256"],
                source={
                    "receipt": outcome.receipt.model_dump(
                        mode="json", by_alias=True, exclude_none=True
                    )
                },
                thread=thread,
            )
        except SettlementRequestError:
            raise
        except (RuntimeError, ValueError) as exc:
            raise SettlementRequestError(
                "payment settlement evidence conflicts with accepted state"
            ) from exc
    try:
        await stage.deposit_if_advertised(agreement, data)
    except PaymentsUnavailable as exc:
        raise SettlementRequestError(
            "payments Agreement deposit is unavailable", status_code=503
        ) from exc
    except PaymentsBlocked as exc:
        logger.error("payment deposit for %s needs operator action: %s", negotiation_id, exc)
        raise SettlementRequestError(
            "payments integration needs operator action", status_code=500
        ) from exc
    lifecycle = await service.start_delivery(
        negotiation_id=negotiation_id, buyer_principal=buyer_principal
    )
    settled = result(
        200, str(lifecycle.get("state") or "fulfillment_started"), lifecycle=lifecycle
    )
    # The neutral fields are a cross-domain contract; refuse to emit a payload
    # that would not parse as one.
    AgreementSettleResponse.model_validate(settled.payload)
    return settled


async def refund_payment(
    service: Any, *, negotiation_id: str, thread: Mapping[str, Any]
) -> PaymentSettleResult:
    """Reverse an accepted payment deal's held funds at the seller operator's request."""

    record = await service.db.load_bare_metal_settlement_record(
        negotiation_id=negotiation_id
    )
    stage, agreement, data = _accepted_payment(
        service,
        negotiation_id=negotiation_id,
        thread=thread,
        record=record,
        buyer_principal=Identity.model_validate(thread["buyer_principal"]),
    )
    payload = {
        "negotiation_id": negotiation_id,
        "settlement_ref": data.transaction_id,
        "status": "refunded",
    }
    assert record is not None
    if record.get("status") not in ("refunding", "refunded"):
        # Refuse before recording intent when there is no payment to reverse,
        # so an unpaid deal is never left blocked by an abandoned refund.
        current = await stage.check_receipt(agreement, data)
        if isinstance(current, (ReceiptPending, ReceiptInvalid)):
            raise SettlementRequestError("no verified payment exists to refund")
        if isinstance(current, ReceiptUnavailable):
            raise SettlementRequestError("payments service is unavailable", status_code=503)
        if isinstance(current, ReceiptBlocked):
            logger.error(
                "refund for %s needs operator action: %s", negotiation_id, current.reason
            )
            raise SettlementRequestError(
                "payments integration needs operator action", status_code=500
            )
    await _complete_refund(service, negotiation_id, stage, agreement, data)
    RefundSettlementResponse.model_validate(payload)
    return PaymentSettleResult(200, payload)


async def _complete_refund(
    service: Any,
    negotiation_id: str,
    stage: PaymentSellerStage,
    agreement: Mapping[str, Any],
    data: PaymentSettlementData,
) -> None:
    """Record intent, reverse, then record the refund; safe to repeat after a crash."""

    intent = await service.db.record_bare_metal_refund_intent(negotiation_id=negotiation_id)
    if intent["status"] == "refunded":
        return
    outcome = await stage.reverse(agreement, data)
    if isinstance(outcome, (NotPaid, NothingToReverse)):
        await service.db.abandon_bare_metal_refund_intent(
            negotiation_id=negotiation_id, prior_status=intent["status"]
        )
        raise SettlementRequestError(
            "no verified payment exists to refund"
            if isinstance(outcome, NotPaid)
            else "nothing left to reverse"
        )
    if isinstance(outcome, RefundBlocked):
        logger.error("refund for %s needs operator action: %s", negotiation_id, outcome.reason)
        raise SettlementRequestError(
            "payments integration needs operator action", status_code=500
        )
    if not isinstance(outcome, Refunded):
        raise SettlementRequestError("payments service is unavailable", status_code=503)
    await service.db.mark_bare_metal_settlement_refunded(
        negotiation_id=negotiation_id, settlement_ref=data.transaction_id
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
    if not service.seller_wallet:
        raise SettlementRequestError(
            "Alkahest settlement is not configured", status_code=503
        )
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

    # The plan the buyer funded is the one committed at acceptance; one
    # rebuilt from today's configuration could name another wallet or chain.
    committed = thread.get("settlement_plan")
    if not committed:
        raise SettlementRequestError(
            "the accepted agreement has no committed settlement plan"
        )
    try:
        plan = SettlementPlan.model_validate(committed)
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
            await service._step(adopted[0].obligation_ref)
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
    await service._step(records[matched_index].obligation_ref)
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
    service: Any,
    thread: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    delivery_started: bool = False,
) -> None:
    stage = service.arkhai_payments_stage
    if stage is None:
        raise SettlementRequestError("Arkhai settlement is not configured")
    try:
        agreement, data = stage.accepted(
            bytes(thread["agreement_bytes"]), thread.get("settlement_data")
        )
        receipt = SignedReceipt.model_validate(record["evidence"]["source"]["receipt"])
        if data.transaction_id != record["settlement_ref"] or not stage.receipt_matches(
            receipt, agreement, data
        ):
            raise ValueError("stored payment receipt differs from accepted state")
    except (MandatePolicyError, KeyError, TypeError, ValueError) as exc:
        raise SettlementRequestError(
            "stored payment receipt is invalid", status_code=400
        ) from exc


async def revalidate_alkahest(
    service: Any,
    thread: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    delivery_started: bool = False,
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
    if len(adopted) != 1:
        raise SettlementRequestError("verified settlement lifecycle is inconsistent")
    obligation = adopted[0]
    if delivery_started:
        # Once delivery started, the servicing worker carries the obligation on
        # through fulfillment and collection; neither retracts that delivery.
        return
    if (
        obligation.reclaim_state != "pending"
        or obligation.mechanism_status != "ready"
        or obligation.collection_state != "pending"
    ):
        raise SettlementRequestError("verified settlement is no longer active")

    # The journal records adoption, not current chain authority. Recheck the
    # accepted escrow before any physical recovery can consume this evidence.
    if not service.seller_wallet:
        raise SettlementRequestError(
            "Alkahest settlement is not configured", status_code=503
        )
    proposal = EscrowProposal.model_validate(thread.get("buyer_escrow_proposal"))
    client = service.chain_clients.get(proposal.chain_name)
    if client is None:
        raise SettlementRequestError(
            f"settlement chain {proposal.chain_name!r} is unavailable",
            status_code=503,
        )
    terms, listing = await service.physical_terms(thread, record["negotiation_id"])
    try:
        matched_index = await service.verify_escrow(
            escrow_uid=record["settlement_ref"],
            seller_wallet=service.seller_wallet,
            agreed_price=int(thread["agreed_price"]),
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
            "stored escrow source is invalid", status_code=400
        ) from exc
    if (
        isinstance(matched_index, bool)
        or not isinstance(matched_index, int)
        or matched_index != obligation.obligation_index
    ):
        raise SettlementRequestError("stored escrow source matches another obligation")


async def revalidate_contact(
    service: Any,
    thread: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    delivery_started: bool = False,
) -> None:
    reveal = await SQLiteIntroductionStore(service.db.db_path).load(
        record["settlement_ref"]
    )
    if reveal is None or reveal.agreement_ref != record["negotiation_id"]:
        raise SettlementRequestError("introduction has not been revealed")


@dataclass(frozen=True, slots=True)
class SellerStage:
    """One mechanism's seller entry: its verification, recovery gate and hooks.

    ``physical`` declares whether the deal provisions the listed machine
    through site capacity, so admission and evidence follow the entry rather
    than a separate declaration. ``refund`` is the seller-initiated reversal
    of an accepted deal and ``reconcile`` advances an accepted deal without
    its buyer; an entry without them refunds or converges through its own
    mechanism path.
    """

    registration_factory: Callable[[], Any]
    verify: Callable[..., Any]
    revalidate: Callable[..., Any]
    physical: bool
    refund: Callable[..., Any] | None = None
    reconcile: Callable[..., Any] | None = None

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
        return payment_stage.settlement_data(agreement).to_wire()


@dataclass(frozen=True, slots=True)
class ContactStage(SellerStage):
    @staticmethod
    async def record_reveal(db: Any, *, negotiation_id: str, obligation_ref: str) -> None:
        thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if thread is None or not thread.get("agreement_bytes"):
            raise ValueError("accepted introduction Agreement is unavailable")
        await db.save_bare_metal_settlement_evidence(
            SettlementEvidence(
                negotiation_id=negotiation_id,
                mechanism=CONTACT_MECHANISM,
                settlement_ref=obligation_ref,
                status="settlement_verified",
                evidence=EvidencePayload(
                    agreement_sha256=hashlib.sha256(
                        thread["agreement_bytes"]
                    ).hexdigest(),
                    source={"obligation_ref": obligation_ref},
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
