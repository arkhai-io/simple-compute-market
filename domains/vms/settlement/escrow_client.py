"""VM buyer-side on-chain escrow creation via Alkahest."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from market_alkahest.schemas import EscrowTerms

logger = logging.getLogger(__name__)


BuildEscrowTermsFn = Callable[
    [Any, str | None, int, int],
    list[EscrowTerms],
]


CreateEscrowFn = Callable[[list[EscrowTerms]], list[str]]


def make_buyer_payment_escrow_terms_fn(
    *,
    chain_name: str,
    addr_config_path: Optional[str],
) -> BuildEscrowTermsFn:
    """Build a closure that materializes negotiated proposal to terms."""

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
    """Build the ``list[EscrowTerms] -> list[escrow_uid]`` submit hook."""

    def _create(escrows: list[EscrowTerms]) -> list[str]:
        from alkahest_py import AlkahestClient
        from market_alkahest.alkahest import (
            get_alkahest_network,
            get_escrow_kind_codec_by_address,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
        )

        buyer_escrows = [escrow for escrow in escrows if escrow.maker == "buyer"]
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


def _run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return loop.run_until_complete(coro)
