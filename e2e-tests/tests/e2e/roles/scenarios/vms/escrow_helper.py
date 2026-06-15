"""Create real on-chain ERC20EscrowObligation attestations for e2e tests.

Stage 07 of the full-deal scenario needs an EAS attestation that the
storefront's pre-settlement verifier (commit 03e47bf) can resolve. A
placeholder uid would be rejected by alkahest's ``get_obligation``
call. So we drive alkahest-py against the local Anvil from the
buyer's wallet, the same way
``core_buyer.escrow_client.make_create_escrow_fn`` does in
production — but inlined here because e2e-tests doesn't
depend on the buyer wheel.

Token distribution is baked into the chain state (account #1 holds
MockERC20 — see dev-env/generate_state.py). Escrow creation is runtime: in production
the buyer signs and sends this transaction themselves, so the test
does the same — with the buyer's private key, against the just-
finalized negotiation terms.
"""
from __future__ import annotations

import asyncio
import logging
import time
from importlib import resources

from alkahest_py import AlkahestClient
from market_alkahest.alkahest import (
    encode_recipient_demand,
    get_alkahest_network,
    get_recipient_arbiter,
    prewarm_alkahest_address_config_cache,
    resolve_alkahest_address_config,
)

log = logging.getLogger(__name__)

_HTTP_TO_WS = {"http": "ws", "https": "wss"}


def _ensure_ws_rpc_url(rpc_url: str) -> str:
    """Coerce an HTTP RPC URL to its WebSocket equivalent and validate it.

    ``AlkahestClient`` is backed by the Rust SDK, whose provider factory uses
    Alloy ``WsConnect``. Passing an ``http://`` or ``https://`` URL reaches the
    Rust URL parser and fails with the opaque message "URL scheme not
    supported". Callers often source their URL from the same config used by
    web3.py smoke tests, so we correct standard HTTP(S) Anvil/provider URLs
    here and log the correction.

    Raises ``ValueError`` on an empty or unsupported URL so the error surfaces
    as a clear test failure before entering the Rust extension.
    """
    if not rpc_url or not rpc_url.strip():
        raise ValueError(
            "rpc_url is empty — cannot create on-chain escrow. "
            "Set buyer.chain_rpc_url to a ws:// RPC endpoint in "
            "config/config-<profile>.yml."
        )

    normalized = rpc_url.strip()
    for http_scheme, ws_scheme in _HTTP_TO_WS.items():
        prefix = f"{http_scheme}://"
        if normalized.startswith(prefix):
            corrected = f"{ws_scheme}://{normalized[len(prefix):]}"
            log.warning(
                "AlkahestClient requires a WebSocket RPC URL; "
                "coercing %r → %r. "
                "Set buyer.chain_rpc_url to a ws:// URL to silence this warning.",
                normalized,
                corrected,
            )
            return corrected

    if not normalized.startswith("ws://") and not normalized.startswith("wss://"):
        raise ValueError(
            f"rpc_url {normalized!r} uses an unsupported scheme for AlkahestClient. "
            "Only ws:// and wss:// are supported by the current alkahest-py client. "
            "Set buyer.chain_rpc_url in config/config-<profile>.yml."
        )
    return normalized


def _alkahest_addresses_path() -> str:
    """Locate the bundled alkahest_anvil_addresses.json shipped with
    market-storefront. It's the same file the seller container uses,
    and it's installed into the e2e-tests venv as a
    transitive resource via the ``market-storefront`` dependency."""
    ref = resources.files("market_storefront.data").joinpath(
        "alkahest_anvil_addresses.json"
    )
    return str(ref)


def create_buyer_escrow(
    *,
    buyer_private_key: str,
    seller_wallet_address: str,
    agreed_amount: int,
    duration_seconds: int,
    token_contract_address: str,
    rpc_url: str = "ws://localhost:8545",
    chain_name: str = "anvil",
    expiration_seconds: int = 3600,
) -> str:
    """Create an ERC20EscrowObligation under RecipientArbiter for the
    seller, returning the EAS attestation uid (0x-prefixed 32 bytes).

    ``agreed_amount`` is the absolute payment in base units of
    ``token_contract_address`` — already multiplied out from any
    per-hour rate during negotiation. The middleware chain owns price
    math; this helper just escrows the agreed total.

    ``rpc_url`` must use the ``ws://`` or ``wss://`` scheme for alkahest-py.
    ``http://`` / ``https://`` URLs are coerced automatically with a warning;
    use ``buyer.chain_rpc_url`` in the integration-test config to supply
    the correct scheme directly.
    """
    rpc_url = _ensure_ws_rpc_url(rpc_url)

    addr_config_path = _alkahest_addresses_path()
    prewarm_alkahest_address_config_cache(addr_config_path)
    network = get_alkahest_network(chain_name)
    address_config = resolve_alkahest_address_config(
        network, config_path=addr_config_path
    )
    arbiter_address = get_recipient_arbiter(
        chain_name, config_path=addr_config_path
    )
    demand_bytes = encode_recipient_demand(seller_wallet_address)

    price_data = {"address": token_contract_address, "value": int(agreed_amount)}
    arbiter_data = {"arbiter": arbiter_address, "demand": demand_bytes}
    expiration = int(time.time()) + int(expiration_seconds)

    client = AlkahestClient(
        private_key=buyer_private_key,
        rpc_url=rpc_url,
        address_config=address_config,
    )

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

    return asyncio.run(_do_it())
