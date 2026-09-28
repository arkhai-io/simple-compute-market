"""VM composition seam for accepted hosted funding authorization."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

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

from core_buyer.action_policy import BuyerActionMetadata, BuyerActionRequired
from core_buyer.profile_service import BuyerProfileService


async def prepare_hosted_funding_authorization_async(
    *,
    buyer_profile_id: str,
    principal: Identity,
    signer: Signer,
    stripe_config: StripeSettlementConfig,
    obligation_ref: str,
    obligation: Mapping[str, Any],
    selection: FundingSelection,
    automatic: bool,
    profiles: BuyerProfileService | None = None,
    client: Any | None = None,
    now_unix: int | None = None,
) -> FundingAuthorizationReceipt:
    """Authorize one already accepted VM obligation immediately before start."""
    service = profiles or BuyerProfileService()
    resolved = StripeSettlementConfig.model_validate(stripe_config)
    if resolved.authority_id is None or resolved.environment is None:
        raise ValueError("hosted funding authorization requires exact authority config")
    binding = service.authority_payer_binding(
        buyer_profile_id,
        authority_id=resolved.authority_id,
        environment=resolved.environment,
        principal=principal,
    )
    accepted = derive_accepted_funding_authorization(
        obligation_ref=obligation_ref,
        obligation=obligation,
    )
    owns_client = client is None
    if owns_client:
        context = payer_command_context_from_config(
            resolved,
            profiles=service,
            dispatch_action=lambda _action, _binding: None,
        )
        client = context.client_factory(signer)
    try:
        authorizer = HostedFundingAuthorizer(
            config=resolved,
            client=client,
            signer=signer,
        )
        if automatic:
            journal = AuthorizationReservationJournal(
                authorization_journal_path(resolved.authorization_journal_path)
            )
            try:
                return await authorizer.authorize_automatically(
                    accepted,
                    binding=binding,
                    selection=selection,
                    policy=resolved.off_session_policy,
                    journal=journal,
                    now_unix=int(time.time()) if now_unix is None else now_unix,
                )
            except AutomationPolicyRefused as exc:
                raise BuyerActionRequired(
                    BuyerActionMetadata(
                        kind=f"off_session_policy:{exc.decision.reason}",
                        expires_at_unix=accepted.expires_at_unix,
                    )
                ) from None
        return await authorizer.authorize(
            accepted,
            binding=binding,
            selection=selection,
        )
    finally:
        if owns_client:
            await client.aclose()


def prepare_hosted_funding_authorization(**kwargs: Any) -> FundingAuthorizationReceipt:
    """Synchronous VM buyer-command wrapper for the exact async client call."""
    return asyncio.run(prepare_hosted_funding_authorization_async(**kwargs))


__all__ = [
    "prepare_hosted_funding_authorization",
    "prepare_hosted_funding_authorization_async",
]
