"""VM-owned Alkahest escrow materialization and submission adapters."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from market_alkahest.schemas import EscrowProposal, EscrowTerms

logger = logging.getLogger(__name__)

BuildEscrowTermsFn = Callable[[Any, str | None, int, int], list[EscrowTerms]]
CreateEscrowFn = Callable[[list[Any]], list[str]]


def encode_escrow_proposal(proposal: Any) -> dict[str, Any]:
    """Encode the VM Alkahest proposal without changing its HTTP shape."""
    decoded = EscrowProposal.model_validate(
        proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
    )
    return {
        "chain_name": decoded.chain_name,
        "escrow_address": decoded.escrow_address,
        "fields": dict(decoded.fields or {}),
        "literal_fields": dict(decoded.literal_fields or decoded.fields or {}),
        "rates": [
            rate.model_dump() if hasattr(rate, "model_dump") else dict(rate)
            for rate in (decoded.rates or [])
        ],
        "demand": (
            decoded.demand.model_dump()
            if hasattr(decoded.demand, "model_dump")
            else dict(decoded.demand)
            if decoded.demand is not None
            else None
        ),
        "expiration_unix": decoded.expiration_unix,
    }


def make_alkahest_settlement_payload_fn(
    *,
    buyer_evm_address: str,
    ssh_public_key: str,
) -> Callable[[str, Any], dict[str, Any]]:
    """Build the VM-owned EVM settlement request encoder."""

    def _build(negotiation_id: str, proposal: Any) -> dict[str, Any]:
        decoded = EscrowProposal.model_validate(
            proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
        )
        return {
            "negotiation_id": negotiation_id,
            "ssh_public_key": ssh_public_key,
            "buyer_evm_address": buyer_evm_address,
            "chain_name": decoded.chain_name,
        }

    return _build


def looks_like_propagation_lag(exc: RuntimeError) -> bool:
    """Classify transient EVM read failures after escrow creation."""
    message = str(exc)
    if "HTTP 400" not in message:
        return False
    return any(
        hint in message
        for hint in ("buffer overrun", "ABI decoding", "Failed to read escrow")
    )


def make_buyer_payment_escrow_terms_fn(
    *,
    chain_name: str,
    addr_config_path: Optional[str],
) -> BuildEscrowTermsFn:
    """Build a closure that materializes a negotiated proposal to terms."""

    def _build(
        proposal: Any,
        seller_wallet_address: str,
        agreed_amount: int,
        duration_seconds: int,
    ) -> list[EscrowTerms]:
        from market_alkahest.alkahest import materialize_escrow_terms_from_proposal

        return materialize_escrow_terms_from_proposal(
            proposal=proposal,
            seller_wallet_address=seller_wallet_address,
            agreed_amount=int(agreed_amount),
            duration_seconds=duration_seconds,
            addr_config_path=addr_config_path,
        )

    return _build


def make_create_escrow_fn(
    *,
    private_key: str,
    rpc_url: str,
    chain_name: str,
    addr_config_path: Optional[str],
) -> CreateEscrowFn:
    """Build the Alkahest submission hook used by VM buyer composition."""

    def _create(escrows: list[Any]) -> list[str]:
        from alkahest_py import AlkahestClient
        from market_alkahest.alkahest import (
            get_alkahest_network,
            get_escrow_kind_codec_by_address,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
        )

        decoded = [EscrowTerms.model_validate(escrow) for escrow in escrows]
        buyer_escrows = [escrow for escrow in decoded if escrow.maker == "buyer"]
        if not buyer_escrows:
            return []

        prewarm_alkahest_address_config_cache(addr_config_path)
        alkahest_network = get_alkahest_network(chain_name)
        address_config = resolve_alkahest_address_config(
            alkahest_network,
            config_path=addr_config_path,
        )
        client = AlkahestClient(
            private_key=private_key,
            rpc_url=rpc_url,
            address_config=address_config,
        )

        async def _do_one(escrow: EscrowTerms) -> str:
            escrow_chain = escrow.chain_name or chain_name
            codec = get_escrow_kind_codec_by_address(
                escrow.escrow_contract,
                escrow_chain,
                config_path=addr_config_path,
            )
            logger.info(
                "[CLI_ESCROW] Creating escrow kind=%s contract=%s amount=%s exp=%s",
                codec.kind,
                escrow.escrow_contract,
                escrow.obligation_data.get("amount"),
                escrow.expiration_unix,
            )
            return await codec.create_obligation(
                client,
                escrow.obligation_data,
                escrow.expiration_unix,
            )

        async def _do_all() -> list[str]:
            return [await _do_one(escrow) for escrow in buyer_escrows]

        return _run_sync(_do_all())

    return _create


def accepted_proposal_recipient(proposal: Any) -> str | None:
    """Decode the Alkahest recipient for core's generic settlement hook."""
    from market_alkahest.schemas import accepted_recipient_address

    return accepted_recipient_address(proposal)


def _run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)
