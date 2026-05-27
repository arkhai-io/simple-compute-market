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
            _AGENT_IDS,
            agent_card_data,
        )
        from market_storefront.utils.agent_card import build_erc8004_registration_file
        from market_storefront.utils.config import CHAINS

        registrations: list[tuple[int, int, str]] = []
        for name, chain in CHAINS.items():
            agent_id = _AGENT_IDS.get(name)
            if agent_id is None or not chain.identity_registry_address:
                continue
            registrations.append((agent_id, chain.chain_id, chain.identity_registry_address))

        return build_erc8004_registration_file(
            agent_card_data=agent_card_data,
            registrations=registrations,
            supported_trust=[],
        )

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
