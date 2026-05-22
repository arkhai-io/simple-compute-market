"""Identity controller — ERC-8004 well-known endpoints.

Extracted from agent.py. Serves agent identity metadata at the
standard well-known paths defined by the ERC-8004 spec.

Endpoints
---------
GET /.well-known/erc-8004-registration.json   — ERC-8004 registration file
GET /.well-known/agent-card.json              — A2A AgentCard
GET /.well-known/agent-wallet.json            — on-chain wallet address
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi_utils.cbv import cbv

router = APIRouter(tags=["identity"])


@cbv(router)
class IdentityController:
    @router.get(
        "/.well-known/erc-8004-registration.json",
        summary="ERC-8004 agent registration file",
    )
    async def erc8004_registration(self) -> dict[str, Any]:
        from market_storefront.agent import (
            _AGENT_ID,
            agent_card_data,
        )
        from market_storefront.utils.agent_card import build_erc8004_registration_file
        from market_storefront.utils.config import settings

        registration_file = build_erc8004_registration_file(
            agent_card_data=agent_card_data,
            agent_id=_AGENT_ID,
            chain_id=settings.chain.chain_id,
            identity_registry=settings.registry.identity_registry_address,
            supported_trust=[],
        )
        return registration_file

    @router.get(
        "/.well-known/agent-card.json",
        summary="A2A AgentCard",
    )
    async def agent_card(self) -> dict[str, Any]:
        from market_storefront.agent import agent_card_data
        return agent_card_data

    @router.get(
        "/.well-known/agent-wallet.json",
        summary="Agent on-chain wallet address",
    )
    async def agent_wallet(self) -> dict[str, Any]:
        from market_storefront.utils.config import settings

        return {"agent_wallet_address": settings.wallet.address or ""}
