"""VM buyer approval and seller settlement transport for Arkhai payments."""

from __future__ import annotations

import base64
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from core_buyer import DEFAULT_HTTP_TIMEOUT, BuyResult, signed_storefront_json
from core_buyer.orchestration import make_publisher_trust_resolver, wait_for_settlement
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval
from market_arkhai_payments.models import AccountId
from market_config.config_loader import load_user_config
from market_core.schemas import Agreement
from market_identity import Identity, Signer, TrustedIdentitySet

from .buy_orchestrator import AgreedTerms
from .run_log import read_run


@dataclass(frozen=True, slots=True)
class VmSettlementTransport:
    """Submit a negotiation-scoped settlement request to its trusted storefront."""

    seller_url: str
    principal: Identity
    signer: Signer
    resolve_seller_principals: Callable[[], TrustedIdentitySet]
    timeout: float = DEFAULT_HTTP_TIMEOUT

    def settle(self, negotiation_id: str) -> dict[str, Any]:
        body = {
            "negotiation_id": negotiation_id,
            "buyer_principal": self.principal.model_dump(mode="json"),
        }
        return signed_storefront_json(
            self.seller_url.rstrip("/") + f"/api/v1/settle/{negotiation_id}",
            body,
            signer=self.signer,
            principal=self.principal,
            method="POST",
            operation="settle_escrow",
            resource=negotiation_id,
            timeout=self.timeout,
            resolve_response_principals=self.resolve_seller_principals,
        )


def payer_selection(selected):
    """Add the VM buyer's account only after selecting the payments mechanism."""
    if selected.selection.mechanism != "arkhai.payments.v1":
        return selected
    section = load_user_config().get("vms", {})
    payer = AccountId.model_validate(section.get("payer_account")).root
    return replace(
        selected,
        selection=selected.selection.model_copy(
            update={
                "params": {**selected.selection.params, "payer_account": payer},
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


def accepted_payment_from_run(run_id, *, signer, negotiation_id):
    """Read the exact accepted artifact from a validated profile-bound run."""
    found = None
    for event in read_run(run_id, signer=signer):
        reply = event.get("their_reply") or event
        encoded = reply.get("agreement_bytes")
        data = reply.get("settlement_data")
        if not isinstance(encoded, str) or not isinstance(data, dict):
            continue
        raw = base64.b64decode(encoded, validate=True)
        agreement = Agreement.model_validate_json(raw)
        if agreement.negotiation_id != negotiation_id:
            continue
        candidate = (raw, data)
        if found is not None and found != candidate:
            raise ValueError("run contains conflicting accepted payment artifacts")
        found = candidate
    if found is None:
        raise ValueError("run has no accepted Agreement and payment mandate")
    return found


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
    on_event(
        "payment_approved",
        {"transaction_id": transaction, "negotiation_id": negotiation_id},
    )
    transport = VmSettlementTransport(
        seller_url, principal, signer, resolve_seller_principals
    )
    deadline = time.monotonic() + timeout
    while True:
        submitted = transport.settle(negotiation_id)
        if submitted.get("status") != "pending":
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("seller is still waiting for the payment receipt")
        time.sleep(interval)
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


__all__ = ["VmSettlementTransport", "payment_buyer", "settle_payment"]
