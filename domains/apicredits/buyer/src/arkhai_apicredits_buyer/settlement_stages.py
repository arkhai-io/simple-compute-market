"""Domain-owned buyer stages; core only selects their Agreement identity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from core_buyer.negotiation_client import display_to_base_units
from market_alkahest import create_alkahest_registration
from market_arkhai_payments import create_arkhai_payments_registration
from .common import (
    buyer_chains,
    chain_by_name,
    resolve_buyer_wallet,
    select_chain_for_listing,
)
from .escrow_selection import select_escrow_entry

from market_alkahest.plans import escrow_terms_from_settlement_plan
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_alkahest.token import TokenResolutionError, resolve_token
from market_alkahest.schemas import accepted_recipient_address, accepted_token_address

from .payments import (
    configured_payer_account,
    payment_selection_for_listing,
    settle_api_credit_negotiation,
)


class PaymentBuyerStage:
    registration = staticmethod(create_arkhai_payments_registration)

    def resources(self) -> dict[str, Any]:
        return {}

    def prepare_selection(self, selected: Any, **_unused: Any) -> Any:
        return replace(selected, selection=selected.selection.model_copy(update={
            "params": {"payer_account": configured_payer_account()},
        }))

    def accepted_entry(self, selected: Any) -> None:
        return None

    def negotiation_prices(
        self, selected: Any, *, initial_price: Any, max_price: Any, **_unused: Any,
    ) -> tuple[Any, Any]:
        return initial_price, max_price

    def proposal(self, listing: Any, selected: Any) -> Any:
        return selected.selection

    def prepare_chain(self, chain: Any, selected: Any) -> Any:
        # Scalar policies recognize their opening shape from rates; the opaque
        # selection carrier alone contains no price-field declaration.
        rates = [rate.model_dump(mode="json") for rate in selected.option.rates]

        def opening_shape(history: Any, context: Any) -> Any:
            if not history:
                context.our_escrow_proposal = {
                    **context.our_escrow_proposal, "rates": rates,
                }
            return None, context

        return [opening_shape, *chain]

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

    def prepare_selection(
        self, selected: Any, *, listing: Any, settlement_policy: Any, policy: Any,
        chain_name: str | None, token_contract: str | None, assume_yes: bool,
        evm_address: str | None, evm_private_key: str | None, console: Any,
    ) -> Any:
        address, _key = resolve_buyer_wallet(
            override_addr=evm_address, override_pk=evm_private_key,
        )
        if not address:
            raise ValueError(
                "Missing EVM address required to select and inspect the Alkahest "
                "escrow. Pass --evm-address or configure wallet.address."
            )
        options = [
            option for _registration, option in settlement_policy.compatible_options(
                listing.get("settlement_options") or (),
            ) if option.mechanism == selected.selection.mechanism
        ]
        constrained = dict(listing)
        constrained["accepted_escrows"] = [self.accepted_entry(
            replace(selected, option=option),
        ) for option in options]
        chain = select_chain_for_listing(constrained, override=chain_name, yes=assume_yes)
        entry = select_escrow_entry(
            constrained, chain_name=chain.name, token_contract_filter=token_contract,
            assume_yes=assume_yes, rpc_url=chain.rpc_url, buyer_address=address,
            console=console, compatible=policy.compatible,
            preference=policy.prefer_settlement,
        )
        if entry is None:
            message = (
                f"Listing {listing.get('listing_id')!r} has no accepted_escrows entry "
                f"on chain {chain.name!r}"
            )
            if token_contract:
                message += f" with token {token_contract}"
            raise ValueError(message + ".")
        option = next(option for option in options if option.params["accepted_escrow"] == entry)
        return replace(selected, option=option, selection=selected.selection.model_copy(
            update={"option_id": option.option_id},
        ))

    def accepted_entry(self, selected: Any) -> dict[str, Any]:
        entry = selected.option.params.get("accepted_escrow")
        if not isinstance(entry, Mapping):
            raise ValueError("selected Alkahest option has no accepted escrow payload")
        return dict(entry)

    def negotiation_prices(
        self, selected: Any, *, initial_price: Any, max_price: Any,
        initial_explicit: bool, max_explicit: bool, token_decimals: Any,
    ) -> tuple[Any, Any]:
        if initial_explicit or max_explicit:
            decimals = int(token_decimals) if token_decimals is not None else None
            if decimals is None:
                entry = self.accepted_entry(selected)
                token = accepted_token_address(entry)
                chain = chain_by_name(entry["chain_name"])
                if token and token.startswith("0x"):
                    try:
                        decimals = resolve_token(
                            token, rpc_url=chain.rpc_url, chain_id=chain.chain_id,
                        ).decimals
                    except (TokenResolutionError, RuntimeError):
                        decimals = None
            if decimals is None:
                raise ValueError(
                    "Could not resolve token decimals to scale prices. "
                    "Pass --token-decimals or ensure the listing's accepted "
                    "chain is configured in [chains.<name>]."
                )
            if initial_explicit and initial_price is not None:
                initial_price = display_to_base_units(
                    initial_price, decimals, field="--initial-price"
                )
            if max_explicit and max_price is not None:
                max_price = display_to_base_units(max_price, decimals, field="--max-price")
        return initial_price, max_price

    def prepare_chain(self, chain: Any, selected: Any) -> Any:
        return chain

    def proposal(self, listing: Any, selected: Any) -> Any:
        return escrow_proposal_from_accepted_entry(
            listing=listing, entry=self.accepted_entry(selected),
            expiration_unix=selected.selection.expiration_unix,
        )

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
