"""Domain-owned buyer stages; core only selects their Agreement identity."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_alkahest import create_alkahest_registration
from market_arkhai_payments import create_arkhai_payments_registration
from .common import buyer_chains, resolve_buyer_wallet

from market_alkahest.plans import escrow_terms_from_settlement_plan
from market_alkahest.schemas import accepted_recipient_address, accepted_token_address

from .payments import payment_selection_for_listing, settle_api_credit_negotiation


class PaymentBuyerStage:
    registration = staticmethod(create_arkhai_payments_registration)

    def resources(self) -> dict[str, Any]:
        return {}

    def validate_acceptance(self, outcome: Any) -> None:
        if not outcome.agreement or not outcome.agreement_bytes:
            raise ValueError("payment acceptance requires the exact Agreement")
        data = outcome.settlement_data
        if not isinstance(data, Mapping) or not data.get("mandate"):
            raise ValueError("payment acceptance requires its accepted mandate")

    def enrich(self, deal: Any) -> None:
        pass

    def select(self, policy: Any, listing: Any, *, alkahest: Any = None, **kwargs: Any) -> Any:
        return payment_selection_for_listing(policy, listing, prefer_payment=True, **kwargs)

    def settle(self, negotiation: Any, on_event: Any, *, payment: Mapping[str, Any], **_unused: Any) -> Any:
        self.validate_acceptance(negotiation.outcome)
        return settle_api_credit_negotiation(
            negotiation=negotiation, on_event=on_event, **payment
        )

    def resume(self, *, payment: Any, **_unused: Any) -> Any:
        return payment()


class AlkahestBuyerStage:
    registration = staticmethod(create_alkahest_registration)

    def resources(self) -> dict[str, Any]:
        chains = buyer_chains()
        address, _private_key = resolve_buyer_wallet()
        resources = {"chains": chains, "wallet": {"address": address}}
        if len(chains) == 1:
            resources["default_chain"] = next(iter(chains))
        return resources

    def select(self, policy: Any, listing: Any, *, alkahest: Any, **_unused: Any) -> Any:
        return alkahest() if alkahest is not None else None

    def validate_acceptance(self, outcome: Any) -> None:
        if outcome.accepted_escrow_proposal is None:
            raise ValueError("Alkahest acceptance requires the accepted escrow proposal")
        if not outcome.settlement_plan:
            raise ValueError("Alkahest acceptance requires the accepted settlement plan")

    def enrich(self, deal: Any) -> None:
        if deal.accepted_escrow_proposal is not None:
            recipient = accepted_recipient_address(deal.accepted_escrow_proposal)
            if recipient:
                deal.seller_wallet_address = recipient
            token = accepted_token_address(deal.accepted_escrow_proposal)
            if token:
                deal.token_contract = token
        if deal.settlement_plan is not None and not deal.accepted_escrow_terms:
            deal.accepted_escrow_terms = [
                terms.model_dump()
                for terms in escrow_terms_from_settlement_plan(deal.settlement_plan)
            ]

    def settle(self, negotiation: Any, on_event: Any, *, alkahest: Any, **_unused: Any) -> Any:
        self.validate_acceptance(negotiation.outcome)
        if alkahest is None:
            raise ValueError("Alkahest settlement resources are unavailable")
        return alkahest(negotiation, on_event)

    def resume(self, *, alkahest: Any, **_unused: Any) -> Any:
        return alkahest()
