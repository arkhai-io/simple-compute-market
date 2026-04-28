"""Buyer-side on-chain escrow creation via alkahest-py.

Mirrors market_storefront/utils/action_executor.buy_compute_with_erc20 but
runs in the CLI process. This is the `create_escrow` hook for
buy_orchestrator.run_buy — it takes AgreedTerms, does the approve +
escrow.create on-chain, and returns the escrow_uid.

Everything needed is resolved from:
- buyer's wallet (private_key + address)
- RPC URL
- alkahest address config (arbiter addresses per chain)
- token metadata (contract address, decimals)

No agent involvement. No event pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional


logger = logging.getLogger(__name__)


def make_create_escrow_fn(
    *,
    private_key: str,
    rpc_url: str,
    chain_name: str,
    addr_config_path: Optional[str],
    token_contract_address: str,
    token_decimals: int,
    expiration_seconds: int = 3600,
) -> Callable[[Any], str]:
    """Build a synchronous `create_escrow(terms) -> escrow_uid` hook.

    Deferred imports of alkahest-py + service clients so importing this
    module alone (e.g. from tests that mock it) does not require a live
    chain config. The returned callable, however, expects to be called
    in a runtime where alkahest-py can initialize an AlkahestClient.
    """
    def _create(terms: Any) -> str:
        # Late imports — avoid paying the alkahest-py binary load cost
        # when this module is imported but the hook is never invoked.
        from alkahest_py import AlkahestClient
        from service.clients.alkahest import (
            encode_recipient_demand,
            get_recipient_arbiter,
            prewarm_alkahest_address_config_cache,
            resolve_alkahest_address_config,
            get_alkahest_network,
        )

        # Resolve alkahest address config for the target chain.
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

        # Under RecipientArbiter, the demand is literally the seller's address.
        demand_bytes = encode_recipient_demand(terms.seller_wallet_address)
        arbiter_address = get_recipient_arbiter(
            chain_name, config_path=addr_config_path,
        )

        # Total payment = agreed_price × duration. agreed_price is already
        # in raw token units (see negotiation_threads.agreed_price).
        amount_raw = int(terms.agreed_price) * int(max(terms.duration_hours, 1))
        price_data = {"address": token_contract_address, "value": amount_raw}
        arbiter_data = {"arbiter": arbiter_address, "demand": demand_bytes}
        expiration = int(time.time()) + int(expiration_seconds)

        logger.info(
            "[CLI_ESCROW] Creating escrow for negotiation=%s seller=%s "
            "amount=%s exp=%s",
            terms.negotiation_id, terms.seller_wallet_address,
            amount_raw, expiration,
        )

        # alkahest-py exposes async APIs; run them synchronously for the hook.
        async def _do_it() -> str:
            await client.erc20.util.approve(price_data, "escrow")
            receipt = await client.erc20.escrow.non_tierable.create(
                price_data, arbiter_data, expiration,
            )
            uid = (receipt or {}).get("log", {}).get("uid")
            if not uid:
                raise RuntimeError(
                    f"escrow.create did not return a uid: {receipt!r}"
                )
            return uid

        return _run_sync(_do_it())

    return _create


def _run_sync(coro):
    """Run an async coroutine from sync code, handling both with- and
    without-a-running-event-loop cases."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # If we're already inside a loop (e.g. a Jupyter notebook), schedule
    # and wait. This path is rare from the CLI but cheap to support.
    return loop.run_until_complete(coro)
