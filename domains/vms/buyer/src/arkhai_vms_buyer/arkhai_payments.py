"""VM buyer approval and seller settlement transport for Arkhai payments."""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass, replace

from core_buyer import BuyResult
from core_buyer.orchestration import make_publisher_trust_resolver, wait_for_settlement
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval
from market_arkhai_payments.models import AccountId
from market_config.config_loader import load_user_config
from market_core.schemas import Agreement
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, Pending

from .evidence import evidence_store
from .lifecycle import buyer_lifecycle, run_sync


@dataclass
class AgreedTerms:
    """VM settlement summary presented before the buyer commits an effect."""

    seller_url: str
    seller_wallet_address: str
    negotiation_id: str
    listing_id: str
    agreed_amount: int
    duration_seconds: int


def payer_selection(selected):
    """Add the VM buyer's account to a selected payments option."""
    section = load_user_config().get("vms", {})
    payer = AccountId.model_validate(section.get("payer_account")).root
    return replace(
        selected,
        selection=selected.selection.model_copy(
            update={
                "settlement": {**selected.selection.settlement, "payer_account": payer},
            }
        ),
    )


def payment_buyer(policy) -> PaymentApproval:
    section = load_user_config().get("vms", {})
    return PaymentApproval(
        ArkhaiPaymentsConfig.model_validate(
            policy.config.mechanism_config("arkhai_payments")
        ),
        AccountId.model_validate(section.get("payer_account")).root,
    )


def settle_payment(
    *,
    buyer,
    agreement_bytes,
    settlement_data,
    seller_url,
    principal,
    signer,
    resolve_seller_principals,
    negotiation_id,
    timeout,
    interval,
    on_event,
):
    raw = (
        base64.b64decode(agreement_bytes, validate=True)
        if isinstance(agreement_bytes, str)
        else agreement_bytes
    )
    agreement = Agreement.model_validate_json(raw)
    if (
        agreement.negotiation_id != negotiation_id
        or agreement.buyer != principal.model_dump(mode="json")
    ):
        raise ValueError("accepted payment Agreement has another owner")
    transaction = buyer.approve(
        raw,
        settlement_data,
        timeout=timeout,
        interval=interval,
    )
    evidence_store().remember_commitment(negotiation_id, transaction)
    on_event(
        "payment_approved",
        {"transaction_id": transaction, "negotiation_id": negotiation_id},
    )
    deadline = time.monotonic() + timeout

    async def commit():
        async with buyer_lifecycle(
            agreement_bytes=raw, settlement_data=settlement_data, seller_url=seller_url,
            signer=signer, publishers=resolve_seller_principals(), approval=buyer,
            timeout=timeout,
        ) as lifecycle:
            message = CommitMessage(
                negotiation_id=negotiation_id, commitment_ref=transaction,
                operation_key="commit:" + transaction,
            )
            while True:
                outcome = await lifecycle.commit(message)
                if isinstance(outcome, Accepted):
                    return
                if not isinstance(outcome, Pending):
                    raise RuntimeError("seller commit: " + outcome.model_dump_json())
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("seller is still waiting for the payment receipt")
                await asyncio.sleep(min(interval, remaining))

    run_sync(commit)
    submitted = {"status": "committed", "negotiation_id": negotiation_id, "settlement_ref": transaction}
    on_event("settlement_submitted", {"escrow_uid": negotiation_id, "body": submitted})
    return wait_for_settlement(
        seller_url=seller_url,
        escrow_uid=negotiation_id,
        principal=principal,
        signer=signer,
        resolve_seller_principals=resolve_seller_principals,
        total_timeout=max(0, deadline - time.monotonic()),
        poll_interval=interval,
        on_poll=lambda attempt, body: on_event(
            "settlement_poll", {"attempt": attempt, "body": body}
        ),
    )


def make_payment_settle_hook(
    *, config, policy, timeout, interval, confirm_settlement=None
):
    def settle(negotiation, on_event):
        match, outcome = negotiation.match, negotiation.outcome
        seller_url = (
            match.get("storefront_url")
            or match.get("seller_url")
            or match.get("seller")
        )
        if confirm_settlement is not None:
            terms = AgreedTerms(
                seller_url,
                "",
                outcome.negotiation_id,
                match["listing_id"],
                outcome.agreed_amount,
                outcome.agreement.duration_seconds,
            )
            if not confirm_settlement(terms, match):
                return BuyResult(status="exited", reason="user_declined")
        final = settle_payment(
            buyer=payment_buyer(policy),
            agreement_bytes=outcome.agreement_bytes,
            settlement_data=outcome.settlement_data or {},
            seller_url=seller_url,
            principal=config.principal,
            signer=config.signer,
            resolve_seller_principals=make_publisher_trust_resolver(
                config=config, listing=match
            ),
            negotiation_id=outcome.negotiation_id,
            timeout=timeout,
            interval=interval,
            on_event=on_event,
        )
        return BuyResult(
            status=final.get("status", "failed"),
            seller_url=seller_url,
            negotiation_id=outcome.negotiation_id,
            agreed_amount=outcome.agreed_amount,
            escrow_uid=outcome.negotiation_id,
            fulfillment_uid=final.get("fulfillment_uid"),
            connection_details=final.get("connection_details"),
            tenant_credentials=final.get("tenant_credentials"),
            reason=final.get("reason"),
            rounds=outcome.rounds,
            attempts=negotiation.attempts,
        )

    return settle


__all__ = ["payment_buyer", "settle_payment"]
