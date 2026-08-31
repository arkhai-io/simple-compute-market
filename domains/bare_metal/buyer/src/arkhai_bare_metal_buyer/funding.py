"""Exact hosted funding authorization for accepted bare-metal obligations."""

from __future__ import annotations

import asyncio
import os
import time
import webbrowser
from collections.abc import Mapping
from typing import Any

import typer
from core_buyer import BuyerActionHandler, resolve_buyer_action_policy
from core_buyer.profile_service import BuyerProfileService
from market_config.config_loader import load_user_config
from market_hosted_settlement import (
    AuthorizationReservationJournal,
    AutomationPolicyRefused,
    FundingAuthorizationReceipt,
    FundingSelection,
    HostedFundingAuthorizer,
    StripeSettlementConfig,
    authorization_journal_path,
    derive_accepted_funding_authorization,
    payer_command_context_from_config,
)
from market_identity import Identity, Signer


def stripe_config_from_user_config() -> StripeSettlementConfig:
    """Resolve the strict buyer Stripe section without importing another domain."""

    document = load_user_config()
    settlement = document.get("Settlement", {})
    if not isinstance(settlement, Mapping):
        raise ValueError("[Settlement] must be a table")
    raw = settlement.get("stripe")
    if not isinstance(raw, Mapping):
        raise ValueError("bare-metal hosted funding requires [Settlement.stripe]")
    config = StripeSettlementConfig.model_validate(dict(raw))
    if not config.enabled or config.authority_id is None or config.environment is None:
        raise ValueError(
            "bare-metal hosted funding requires exact enabled Stripe authority config"
        )
    return config


def _dispatch_action(action: Any, requested: str | None) -> Any:
    policy = resolve_buyer_action_policy(
        requested,
        interactive=os.isatty(0) and os.isatty(1),
    )
    return BuyerActionHandler(
        policy,
        open_url=webbrowser.open,
        print_url=typer.echo,
    ).handle(action.model_dump(mode="json", exclude_none=True))


async def prepare_funding_authorization_async(
    *,
    buyer_profile_id: str,
    principal: Identity,
    signer: Signer,
    obligation_ref: str,
    obligation: Mapping[str, Any],
    selection: FundingSelection,
    automatic: bool,
    action: str | None,
) -> FundingAuthorizationReceipt:
    """Authorize one immutable accepted obligation immediately before start."""

    config = stripe_config_from_user_config()
    profiles = BuyerProfileService()
    binding = profiles.authority_payer_binding(
        buyer_profile_id,
        authority_id=config.authority_id,
        environment=config.environment,
        principal=principal,
    )
    accepted = derive_accepted_funding_authorization(
        obligation_ref=obligation_ref,
        obligation=obligation,
    )
    context = payer_command_context_from_config(
        config,
        profiles=profiles,
        dispatch_action=lambda payer_action, _binding: _dispatch_action(
            payer_action,
            action,
        ),
    )
    client = context.client_factory(signer)
    try:
        authorizer = HostedFundingAuthorizer(
            config=config,
            client=client,
            signer=signer,
        )
        if automatic:
            journal = AuthorizationReservationJournal(
                authorization_journal_path(config.authorization_journal_path)
            )
            try:
                return await authorizer.authorize_automatically(
                    accepted,
                    binding=binding,
                    selection=selection,
                    policy=config.off_session_policy,
                    journal=journal,
                    now_unix=int(time.time()),
                )
            except AutomationPolicyRefused as exc:
                raise ValueError(
                    f"off-session funding refused: {exc.decision.reason}"
                ) from None
        return await authorizer.authorize(
            accepted,
            binding=binding,
            selection=selection,
        )
    finally:
        await client.aclose()


def prepare_funding_authorization(**kwargs: Any) -> FundingAuthorizationReceipt:
    return asyncio.run(prepare_funding_authorization_async(**kwargs))


__all__ = [
    "prepare_funding_authorization",
    "prepare_funding_authorization_async",
    "stripe_config_from_user_config",
]
