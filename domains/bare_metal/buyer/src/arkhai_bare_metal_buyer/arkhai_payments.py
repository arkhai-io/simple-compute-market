"""Bare-metal buyer approval and seller settlement transport for Arkhai payments."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from core_buyer import DEFAULT_HTTP_TIMEOUT, signed_storefront_json
from market_arkhai_payments import (
    ArkhaiPaymentsConfig,
    Mandate,
    MandatePolicy,
    PaymentsOptionParams,
    check,
    payments_client_for_owner,
    transaction_id,
    verify_receipt,
)
from market_arkhai_payments.models import AccountId
from market_identity import Identity, Signer, TrustedIdentitySet


@dataclass(frozen=True, slots=True)
class BareMetalArkhaiPaymentsBuyer:
    """Validate and approve the seller mandate using the buyer's account authority."""

    config: ArkhaiPaymentsConfig
    payer_account: str

    def validate_acceptance(
        self,
        *,
        agreement: Any,
        settlement_data: Mapping[str, Any],
    ) -> tuple[Mandate, dict[str, Any]]:
        agreement_wire = (
            agreement.model_dump(mode="json", exclude_none=True)
            if hasattr(agreement, "model_dump")
            else dict(agreement)
            if isinstance(agreement, Mapping)
            else None
        )
        if agreement_wire is None:
            raise ValueError("accepted Agreement is unavailable")
        selected = agreement_wire.get("settlement")
        if (
            not isinstance(selected, Mapping)
            or selected.get("mechanism") != "arkhai.payments.v1"
        ):
            raise ValueError("accepted Agreement does not select Arkhai payments")
        option = PaymentsOptionParams.model_validate(selected.get("params"))
        settlement_params = agreement_wire.get("settlement_params")
        payer = (
            settlement_params.get("payer_account")
            if isinstance(settlement_params, Mapping)
            else None
        )
        payer_account = AccountId.model_validate(self.payer_account).root
        if payer != payer_account:
            raise ValueError("accepted Agreement names a different payer account")

        if self.config.fee_bps is None or self.config.dispute_authority is None:
            raise ValueError("buyer payment policy is incomplete")
        policy = MandatePolicy(
            buyer_account=payer_account,
            option=option,
            accepted_at=agreement_wire["accepted_at"],
            start_utc=agreement_wire["start_utc"],
            duration_seconds=agreement_wire["duration_seconds"],
            amount=agreement_wire["amount"],
            asset=agreement_wire["asset"],
            fee_bps=self.config.fee_bps,
            dispute_authority=self.config.dispute_authority,
        )
        raw_mandate = Mandate.model_validate(settlement_data)
        mandate = check(raw_mandate, agreement_wire, policy)
        return mandate, agreement_wire

    def approve(
        self,
        *,
        agreement: Any,
        settlement_data: Mapping[str, Any],
        timeout: float = 300.0,
        interval: float = 1.0,
    ) -> str:
        mandate, agreement_wire = self.validate_acceptance(
            agreement=agreement, settlement_data=settlement_data
        )
        transaction = transaction_id(mandate)
        service_identity = self.config.service_identity
        if service_identity is None:
            raise ValueError("payments service identity is not configured")

        with payments_client_for_owner(self.config, payer_account) as client:
            approved = client.approve(mandate, agreement=agreement_wire)
            if not verify_receipt(
                approved,
                service_identity,
                mandate=mandate,
                agreement_json=agreement_wire,
            ):
                raise ValueError(
                    "payments approval receipt does not match the accepted Agreement"
                )
            snapshot = client.poll(
                transaction,
                timeout=timeout,
                interval=interval,
            )
        if snapshot.snapshot.transaction.root != transaction or not verify_receipt(
            snapshot.snapshot.receipt,
            service_identity,
            mandate=mandate,
            agreement_json=agreement_wire,
        ):
            raise ValueError(
                "payments transaction snapshot does not match the accepted Agreement"
            )
        return transaction


@dataclass(frozen=True, slots=True)
class BareMetalSettlementTransport:
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


__all__ = ["BareMetalArkhaiPaymentsBuyer", "BareMetalSettlementTransport"]
