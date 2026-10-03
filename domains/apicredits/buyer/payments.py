"""Buyer-side approval and seller-settlement trigger for API-credit payments."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Mapping
from typing import Any

from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.orchestration import (
    make_publisher_trust_resolver,
    submit_settlement_request,
    wait_for_settlement,
)
from core_buyer.orchestrator import BuyConfig, BuyResult, NegotiationResult
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    MandatePolicy,
    PaymentsOptionParams,
    check,
    payments_client_for_owner,
    transaction_id,
    verify_receipt,
)
from market_config.config_loader import load_user_config
from market_core.schemas import Agreement, SettlementOption, SettlementSelection
from market_settlement_runtime import SettlementConfig

from domains.apicredits.settlement import (
    validate_payer_account,
)


def configured_payer_account() -> str:
    """Resolve the buyer account independently of payment-service policy."""
    settings = load_user_config().get("apicredits", {})
    if not isinstance(settings, Mapping):
        raise ValueError("[apicredits] must be a table")
    return validate_payer_account(settings.get("payer_account"))


class _PaymentApprovalDeclined(RuntimeError):
    """The buyer declined the validated payment mandate."""


def payment_selection_for_listing(
    policy: Any,
    listing: Mapping[str, Any],
    *,
    expiration_unix: int,
    payer_account: str | None,
    prefer_payment: bool = False,
) -> SettlementSelection | None:
    """Return a selected payment option carrying the buyer's Arkhai account."""
    config = policy.config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY)
    if config is None or not getattr(config, "enabled", False):
        return None
    if prefer_payment:
        candidate = next(
            (
                option
                for registration, option in policy.compatible_options(
                    listing.get("settlement_options") or ()
                )
                if registration.mechanism_id == ARKHAI_PAYMENTS_MECHANISM
            ),
            None,
        )
        if candidate is None:
            return None
        mechanism = candidate.mechanism
        option_id = candidate.option_id
    else:
        selected = policy.select(listing, expiration_unix=expiration_unix)
        if (
            selected is None
            or selected.selection.mechanism != ARKHAI_PAYMENTS_MECHANISM
        ):
            return None
        mechanism = selected.selection.mechanism
        option_id = selected.selection.option_id
    return SettlementSelection(
        mechanism=mechanism,
        option_id=option_id,
        expiration_unix=expiration_unix,
        params={"payer_account": validate_payer_account(payer_account)},
    )


def _mandate_policy(
    agreement: Mapping[str, Any], config: ArkhaiPaymentsConfig, payer_account: str
) -> MandatePolicy:
    selected = agreement.get("settlement")
    if (
        not isinstance(selected, Mapping)
        or selected.get("mechanism") != ARKHAI_PAYMENTS_MECHANISM
    ):
        raise ValueError("accepted Agreement does not select arkhai.payments.v1")
    account_id = validate_payer_account(payer_account)
    settlement_params = agreement.get("settlement_params")
    payer_account = (
        settlement_params.get("payer_account")
        if isinstance(settlement_params, Mapping)
        else None
    )
    if payer_account != account_id:
        raise ValueError("accepted Agreement does not name this buyer's Arkhai account")
    if config.fee_bps is None or config.dispute_authority is None:
        raise ValueError("buyer Arkhai payments policy is incomplete")
    return MandatePolicy(
        buyer_account=account_id,
        option=PaymentsOptionParams.model_validate(selected.get("params")),
        accepted_at=agreement["accepted_at"],
        start_utc=agreement["start_utc"],
        duration_seconds=agreement["duration_seconds"],
        amount=agreement["amount"],
        asset=agreement["asset"],
        fee_bps=config.fee_bps,
        dispute_authority=config.dispute_authority,
    )


def settle_api_credit_payment(
    *,
    seller_url: str,
    listing: Mapping[str, Any],
    negotiation_id: str,
    buyer: ResolvedBuyerIdentity,
    buy_config: BuyConfig,
    settlement_config: SettlementConfig,
    payer_account: str,
    agreement: Mapping[str, Any],
    agreement_bytes: str,
    settlement_selection: Mapping[str, Any] | SettlementSelection | None,
    settlement_data: Mapping[str, Any] | None,
    poll_interval: float,
    total_timeout: float,
    on_event: Callable[[str, dict[str, Any]], None],
    confirm_payment: Callable[[Any, str], bool] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Approve the seller mandate, then ask the seller to provision from its own poll."""
    if settlement_selection is None:
        raise ValueError("buyer settlement selection is missing for payment approval")
    selected = None
    if settlement_selection is not None:
        selected = SettlementSelection.model_validate(settlement_selection)
        if selected.mechanism != ARKHAI_PAYMENTS_MECHANISM:
            raise ValueError("accepted settlement selection is not an Arkhai payment")
    if not agreement_bytes:
        raise ValueError("accepted Agreement bytes are required for payment settlement")
    try:
        raw_agreement = base64.b64decode(agreement_bytes, validate=True)
        agreement_json = json.loads(raw_agreement)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("accepted Agreement bytes are malformed") from exc
    if not isinstance(agreement_json, dict):
        raise ValueError("accepted Agreement bytes must contain a JSON object")
    parsed_agreement = Agreement.model_validate(agreement_json)
    if parsed_agreement.model_dump(mode="json", exclude_none=True) != dict(agreement):
        raise ValueError("accepted Agreement differs from its preserved bytes")
    if selected is None:
        raise ValueError("buyer settlement selection is missing for payment approval")
    if parsed_agreement.listing_id != str(listing.get("listing_id") or ""):
        raise ValueError("accepted Agreement belongs to a different listing")
    raw_options = listing.get("settlement_options")
    if isinstance(raw_options, (list, tuple)):
        advertised_value = next(
            (
                option
                for option in raw_options
                if isinstance(option, Mapping)
                and option.get("option_id") == selected.option_id
            ),
            None,
        )
    else:
        advertised_value = (
            parsed_agreement.settlement.model_dump(mode="json", exclude_none=True)
            if parsed_agreement.settlement is not None
            else None
        )
    if advertised_value is None:
        raise ValueError(
            "selected payment option is unavailable in the trusted listing or accepted Agreement"
        )
    advertised = SettlementOption.model_validate(advertised_value)
    if (
        parsed_agreement.settlement != advertised
        or selected.mechanism != advertised.mechanism
    ):
        raise ValueError("accepted Agreement differs from the selected listing option")
    if selected is not None and dict(selected.params or {}) != dict(
        parsed_agreement.settlement_params or {}
    ):
        raise ValueError(
            "accepted Agreement settlement params differ from the buyer selection"
        )

    config = settlement_config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY)
    if config is None or not getattr(config, "enabled", False):
        raise ValueError("buyer Arkhai payments is not enabled")
    policy = _mandate_policy(agreement_json, config, payer_account)
    if not isinstance(settlement_data, Mapping):
        raise ValueError("seller did not return payment settlement artifacts")
    mandate_value = settlement_data.get("mandate")
    if not isinstance(mandate_value, Mapping):
        raise ValueError("seller did not return a mandate")
    mandate = check(dict(mandate_value), agreement_json, policy)
    expected_transaction = transaction_id(mandate)
    if settlement_data.get("transaction_id") != expected_transaction:
        raise ValueError(
            "seller returned a transaction ID that does not match its mandate"
        )
    if confirm_payment is not None and not confirm_payment(
        mandate, expected_transaction
    ):
        raise _PaymentApprovalDeclined("buyer declined payment approval")

    client = payments_client_for_owner(config, policy.buyer_account)
    try:
        signed_receipt = client.approve(
            mandate,
            agreement=agreement_json if policy.option.deposit_agreement else None,
        )
        if not verify_receipt(
            signed_receipt,
            config.service_identity,
            mandate=mandate,
            agreement_json=agreement_json,
        ):
            raise ValueError(
                "payments approval receipt does not match the accepted Agreement"
            )
        snapshot = client.poll(
            expected_transaction,
            timeout=total_timeout,
            interval=poll_interval,
        )
        if not verify_receipt(
            snapshot.snapshot.receipt,
            config.service_identity,
            mandate=mandate,
            agreement_json=agreement_json,
        ):
            raise ValueError(
                "payments snapshot receipt does not match the accepted Agreement"
            )
        client.ensure_agreement_attached(
            expected_transaction,
            agreement_json,
            policy.option,
        )
    finally:
        client.close()

    on_event(
        "payment_approved",
        {
            "settlement_ref": expected_transaction,
            "transaction_id": expected_transaction,
        },
    )
    resolve_seller_principals = make_publisher_trust_resolver(
        config=buy_config,
        listing=dict(listing),
        on_update=on_event,
    )
    response = submit_settlement_request(
        seller_url=seller_url,
        escrow_uid=negotiation_id,
        payload={
            "negotiation_id": negotiation_id,
            "buyer_principal": buyer.principal.model_dump(mode="json"),
        },
        principal=buyer.principal,
        signer=buyer.signer,
        resolve_seller_principals=resolve_seller_principals,
    )
    on_event(
        "settlement_submitted",
        {"settlement_ref": expected_transaction, "body": response},
    )
    final = wait_for_settlement(
        seller_url=seller_url,
        escrow_uid=negotiation_id,
        principal=buyer.principal,
        signer=buyer.signer,
        poll_interval=poll_interval,
        total_timeout=total_timeout,
        on_poll=lambda attempt, body: on_event(
            "settlement_poll",
            {
                "attempt": attempt,
                "settlement_ref": expected_transaction,
                "body": body,
            },
        ),
        resolve_seller_principals=resolve_seller_principals,
    )
    return expected_transaction, final


def settle_api_credit_negotiation(
    *,
    negotiation: NegotiationResult,
    buyer: ResolvedBuyerIdentity,
    buy_config: BuyConfig,
    settlement_config: SettlementConfig,
    payer_account: str,
    poll_interval: float,
    total_timeout: float,
    on_event: Callable[[str, dict[str, Any]], None],
    confirm_payment: Callable[[Any, str], bool] | None = None,
) -> BuyResult:
    """Settle an agreed payment-backed API-credit negotiation."""
    outcome = negotiation.outcome
    match = negotiation.match or {}
    if outcome is None or outcome.agreement is None or outcome.negotiation_id is None:
        return BuyResult(
            status="exited",
            reason="accepted payment Agreement is missing",
            attempts=negotiation.attempts,
        )
    try:
        txid, final = settle_api_credit_payment(
            seller_url=str(
                match.get("storefront_url")
                or match.get("seller")
                or match.get("seller_url")
                or ""
            ),
            listing=match,
            negotiation_id=outcome.negotiation_id,
            buyer=buyer,
            buy_config=buy_config,
            settlement_config=settlement_config,
            payer_account=payer_account,
            agreement=outcome.agreement.model_dump(mode="json", exclude_none=True),
            agreement_bytes=outcome.agreement_bytes or "",
            settlement_selection=outcome.settlement_selection,
            settlement_data=outcome.settlement_data,
            poll_interval=poll_interval,
            total_timeout=total_timeout,
            on_event=on_event,
            confirm_payment=confirm_payment,
        )
    except _PaymentApprovalDeclined as exc:
        on_event("payment_approval_declined", {"error": str(exc)})
        return BuyResult(
            status="exited",
            negotiation_id=outcome.negotiation_id,
            seller_url=match.get("storefront_url")
            or match.get("seller")
            or match.get("seller_url"),
            agreed_amount=outcome.agreed_amount,
            reason=str(exc),
            rounds=outcome.rounds,
            attempts=negotiation.attempts,
        )
    except Exception as exc:
        on_event("settlement_failed", {"error": str(exc)})
        return BuyResult(
            status="failed",
            negotiation_id=outcome.negotiation_id,
            seller_url=match.get("storefront_url")
            or match.get("seller")
            or match.get("seller_url"),
            agreed_amount=outcome.agreed_amount,
            reason=str(exc),
            rounds=outcome.rounds,
            attempts=negotiation.attempts,
        )
    return BuyResult(
        status=str(final.get("status") or "unknown"),
        negotiation_id=outcome.negotiation_id,
        seller_url=match.get("storefront_url")
        or match.get("seller")
        or match.get("seller_url"),
        agreed_amount=outcome.agreed_amount,
        settlement_ref=txid,
        fulfillment_uid=final.get("fulfillment_uid"),
        connection_details=final.get("connection_details"),
        tenant_credentials=final.get("tenant_credentials"),
        reason=final.get("reason"),
        rounds=outcome.rounds,
        attempts=negotiation.attempts,
    )


__all__ = [
    "configured_payer_account",
    "payment_selection_for_listing",
    "settle_api_credit_negotiation",
    "settle_api_credit_payment",
]
