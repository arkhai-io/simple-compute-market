"""VM buyer approval and seller settlement transport for Arkhai payments."""

from __future__ import annotations

import base64
from collections.abc import Callable
from dataclasses import dataclass, replace

from core_buyer import BuyResult
from core_buyer.orchestration import make_publisher_trust_resolver, wait_for_settlement
from market_arkhai_payments import ArkhaiPaymentsConfig, PaymentApproval
from market_arkhai_payments.models import AccountId
from market_config.config_loader import load_user_config
from market_core.schemas import AgreedPrice, Agreement
from market_deal_lifecycle_buyer import WaitClock
from market_deal_lifecycle_contracts.models import Accepted, CommitMessage, Pending
from market_settlement_runtime.buyer_terms import BuyerTermsPolicy

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
    quote: AgreedPrice | None = None


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
    """The run's approval, honouring the terms its settlement policy waived.

    The policy's option preference is the run's terms policy; a policy without
    one approves only what a default buyer accepts.
    """
    section = load_user_config().get("vms", {})
    preference = getattr(policy, "option_preference", None)
    return PaymentApproval(
        ArkhaiPaymentsConfig.model_validate(
            policy.config.mechanism_config("arkhai_payments")
        ),
        AccountId.model_validate(section.get("payer_account")).root,
        terms_policy=preference if isinstance(preference, BuyerTermsPolicy) else None,
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
    clock: WaitClock = WaitClock(),
):
    """Approve the mandate, commit it to the seller, and wait for its delivery.

    The commit's retries and the settlement wait run on ``clock``, the
    command's wait clock, and ``timeout`` bounds both together on its
    ``monotonic``, so the clock that paces the watchdog paces them too.
    """
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
    deadline = clock.monotonic() + timeout

    async def commit():
        # ``timeout`` bounds the whole wait; each request keeps the lifecycle
        # client's own timeout, so a wait nearly spent still sends its commit.
        async with buyer_lifecycle(
            agreement_bytes=raw, settlement_data=settlement_data, seller_url=seller_url,
            signer=signer, publishers=resolve_seller_principals(), approval=buyer,
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
                remaining = deadline - clock.monotonic()
                if remaining <= 0:
                    raise TimeoutError("seller is still waiting for the payment receipt")
                await clock.sleep(min(interval, remaining))

    run_sync(commit)
    submitted = {"status": "committed", "negotiation_id": negotiation_id, "settlement_ref": transaction}
    on_event("settlement_submitted", {"escrow_uid": negotiation_id, "body": submitted})
    return wait_for_settlement(
        seller_url=seller_url,
        escrow_uid=negotiation_id,
        principal=principal,
        signer=signer,
        resolve_seller_principals=resolve_seller_principals,
        total_timeout=max(0, deadline - clock.monotonic()),
        poll_interval=interval,
        on_poll=lambda attempt, body: on_event(
            "settlement_poll", {"attempt": attempt, "body": body}
        ),
        sleep=sync_sleep(clock),
        monotonic=clock.monotonic,
    )


def sync_sleep(clock: WaitClock) -> Callable[[float], None]:
    """``clock``'s asynchronous sleep, for a synchronous wait to pause on."""

    def sleep(seconds: float) -> None:
        async def pause() -> None:
            await clock.sleep(seconds)

        run_sync(pause)

    return sleep


def make_payment_settle_hook(
    *, config, policy, timeout, interval, confirm_settlement=None,
    clock: WaitClock = WaitClock(),
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
                policy.registry.agreed_price(outcome.agreement),
            )
            if not confirm_settlement(terms, match):
                return BuyResult(status="exited", reason="user_declined")
        try:
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
                clock=clock,
            )
        except TimeoutError as exc:
            # A wait that runs out, the approval's poll, the commit's or the
            # settle status's, ends the run ``timeout``, as the Alkahest hook's
            # does; a payment approved by then is resumed from the run's log.
            return BuyResult(
                status="timeout",
                seller_url=seller_url,
                negotiation_id=outcome.negotiation_id,
                agreed_amount=outcome.agreed_amount,
                escrow_uid=outcome.negotiation_id,
                reason=str(exc),
                rounds=outcome.rounds,
                attempts=negotiation.attempts,
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


__all__ = ["payment_buyer", "settle_payment", "sync_sleep"]
