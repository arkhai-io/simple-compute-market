"""On-chain registration command — in-process port of the legacy
scripts/register_onchain.py.

All inputs come from the typed CONFIG (TOML). The .env writeback paths
that lived in the old script are gone — there is no .env in the new
deployment shape.
"""

from __future__ import annotations

import traceback
from urllib.parse import urlparse

from market_storefront.utils.config import CHAINS, settings, AGENT_ID, AGENT_NAME
from market_storefront.utils.zerotier import (
    BaseUrlResolutionError,
    await_base_url_resolution,
    get_zerotier_node_id,
    join_zerotier_network,
)
from service.config_loader import ChainConfig
from service.clients.erc8004.blockchain import build_erc8004_canonical_id
from service.clients.erc8004.registration import (
    RegisterOnchainConfig,
    build_agent_card_url,
    build_registration_file_url,
    register_onchain_from_config,
)


async def _resolve_base_url(port: int, base_url_raw: str | None, zerotier_network: str | None) -> str | None:
    """Resolve the externally-reachable base URL the on-chain
    registration should publish. Returns None on a hard failure."""
    if zerotier_network:
        if base_url_raw and "{ZEROTIER_IP}" in base_url_raw:
            template = base_url_raw
        else:
            template_port = port
            if base_url_raw:
                parsed = urlparse(base_url_raw)
                if parsed.port is not None:
                    template_port = parsed.port
            template = f"http://{{ZEROTIER_IP}}:{template_port}/"

        print("ZeroTier network detected. Ensuring network is joined...")
        if not join_zerotier_network(zerotier_network):
            print(f"❌ Failed to join ZeroTier network {zerotier_network}.")
            return None

        node_id = get_zerotier_node_id()
        if node_id:
            print(f"ZeroTier node ID: {node_id}")
            print("Share this node ID with the Market Controller for authorization.")
        else:
            print("⚠️  Unable to determine ZeroTier node ID (zerotier-cli info failed).")

        print("Waiting for ZeroTier IP assignment...")
        try:
            return await await_base_url_resolution(
                template, zerotier_network, wait_timeout=120.0,
            )
        except BaseUrlResolutionError as exc:
            print(f"❌ Failed to resolve base URL with ZeroTier IP: {exc}")
            return None

    if base_url_raw:
        if "{ZEROTIER_IP}" in base_url_raw:
            print(
                "⚠️  base_url contains {ZEROTIER_IP} but seller.zerotier_network is unset; "
                "proceeding without ZeroTier resolution."
            )
        return base_url_raw
    return f"http://localhost:{port}"


async def perform_registration_for_chain(chain: ChainConfig) -> int:
    """Register the agent on a specific chain and return the numeric agent ID.

    Per-chain entry point. The storefront has N identities (one per
    configured chain); this is the unit of work for one of them. Reads
    wallet credentials + base-URL config from ``settings`` and the chain-
    specific RPC + identity-registry from ``chain``.

    Raises ``RuntimeError`` on unrecoverable failure. Returns the numeric
    agent ID (always positive on success).
    """
    base_url_raw = settings.base_url
    zerotier_network = settings.zerotier_network
    port = settings.port
    identity_registry_address = chain.identity_registry_address
    agent_wallet_address = settings.wallet.address
    chain_rpc_url = chain.rpc_url
    onchain_agent_id = chain.onchain_agent_id

    resolved_base_url = await _resolve_base_url(port, base_url_raw, zerotier_network)
    if resolved_base_url is None:
        raise RuntimeError("Could not resolve externally-reachable base URL for registration.")

    agent_card_url = build_agent_card_url(resolved_base_url)
    registration_file_url = build_registration_file_url(resolved_base_url)

    print("=" * 70)
    print(f"🔗 On-Chain Registration — chain={chain.name}")
    print("=" * 70)
    print(f"Agent Card URL: {agent_card_url}")
    print(f"Registration File URL (tokenURI): {registration_file_url}")
    print(f"Identity Registry: {identity_registry_address}")
    print(f"Chain RPC: {chain_rpc_url}")
    print(f"Chain ID: {chain.chain_id}")
    print(f"Wallet Address: {agent_wallet_address}")
    if onchain_agent_id:
        print(f"Existing Agent ID: {onchain_agent_id}")
    print("=" * 70)
    print()

    agent_priv_key = settings.wallet.private_key
    agent_name = AGENT_NAME or AGENT_ID or "root_agent"
    missing = [
        k for k, v in {
            "wallet.private_key": agent_priv_key,
            f"chains.{chain.name}.rpc_url": chain_rpc_url,
            f"chains.{chain.name}.identity_registry_address": identity_registry_address,
            "wallet.address": agent_wallet_address,
        }.items()
        if not v
    ]
    if missing:
        raise RuntimeError(f"Missing required config keys: {', '.join(missing)}")

    print("Registering agent on-chain...")
    try:
        result = await register_onchain_from_config(RegisterOnchainConfig(
            private_key=agent_priv_key,
            chain_rpc_url=chain_rpc_url,
            identity_registry_address=identity_registry_address,
            wallet_address=agent_wallet_address,
            base_url=resolved_base_url,
            agent_name=agent_name,
            explicit_agent_id=str(onchain_agent_id) if onchain_agent_id else None,
        ))
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    except Exception as exc:
        traceback.print_exc()
        raise RuntimeError(f"Registration failed: {exc}") from exc

    if not result:
        raise RuntimeError("Registration failed — no result returned.")

    tx_hash, numeric_agent_id, updates_dict = result
    canonical_id = build_erc8004_canonical_id(
        chain_id=chain.chain_id,
        identity_registry=identity_registry_address,
        agent_id=numeric_agent_id,
    )

    print()
    print("=" * 70)
    if updates_dict is None:
        print("✅ New Registration Successful!")
        status_msg = "New agent registered on-chain"
    elif updates_dict.get("no_changes", False):
        print("✓ No Changes Detected")
        status_msg = "Agent already up to date"
    else:
        print("✅ Registration Updated!")
        status_msg = "Existing agent updated"
        changes: list[str] = []
        if updates_dict.get("token_uri_updated"):
            changes.append("Token URI")
        if updates_dict.get("metadata_updated"):
            changes.extend(updates_dict["metadata_updated"])
        if changes:
            print(f"  Changes: {', '.join(changes)}")
    print("=" * 70)
    print(f"Status: {status_msg}")
    print(f"Numeric Agent ID: {numeric_agent_id}")
    print(f"Canonical Agent ID: {canonical_id}")
    if tx_hash:
        print(f"Transaction Hash: {tx_hash}")
    else:
        print("Transaction: None (no changes made)")
    print("=" * 70)
    print()

    if onchain_agent_id is None:
        print("💡 Pin this in your storefront.toml to skip registration on next start:")
        print(f"   [chains.{chain.name}]\n   onchain_agent_id = {numeric_agent_id}")

    return numeric_agent_id


async def run_register(chain_name: str | None = None) -> int:
    """CLI entry point for ``market-storefront register``.

    Registers on every configured chain (or only the named one when
    ``chain_name`` is given). Returns 0 if every targeted registration
    succeeded, else 1. Per-chain failures do not abort the rest of the
    sweep — operator gets a summary line per chain.
    """
    if chain_name is not None:
        target = CHAINS.get(chain_name)
        if target is None:
            print(f"❌ chain {chain_name!r} not configured. Available: {sorted(CHAINS)}")
            return 1
        chains_to_register = {chain_name: target}
    else:
        chains_to_register = dict(CHAINS)

    if not chains_to_register:
        print("❌ No [chains.<name>] tables configured. Add at least one to storefront.toml.")
        return 1

    rc = 0
    for name, chain in chains_to_register.items():
        try:
            await perform_registration_for_chain(chain)
        except RuntimeError as exc:
            print(f"❌ chain={name}: {exc}")
            rc = 1
    return rc
