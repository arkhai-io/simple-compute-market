"""Address-config resolution for the Alkahest SDK.

Three sources of truth, in priority order:

1. JSON override at ``config_path`` — for ``anvil`` (always required) or any
   chain where the operator has deployed their own contracts. Loaded into a
   ``SimpleNamespace`` tree that the SDK accepts via FromPyObject duck-typing.

2. ``DefaultExtensionConfig.for_chain(name)`` — pulled from the alkahest-py
   SDK (>= 0.3.0), which exposes the upstream Rust constants
   (``BASE_SEPOLIA_ADDRESSES``, ``ETHEREUM_SEPOLIA_ADDRESSES``,
   ``ETHEREUM_ADDRESSES``, ``FILECOIN_CALIBRATION_ADDRESSES``,
   ``GENLAYER_BRADBURY_ADDRESSES``). Single source of truth for any
   SDK-supported chain — keeps us in lockstep with whatever Alkahest ships.

3. SDK default — the ``AlkahestClient`` constructor accepts ``None`` and
   uses Base Sepolia internally. ``resolve_alkahest_address_config`` returns
   ``None`` for that case so the client takes the path it was designed for.

The named-network constants used to live here (~270 lines of hand-copied
addresses); the SDK now exposes them via ``DefaultExtensionConfig.for_chain``
so we delete the duplicate.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

NETWORK_ANVIL = "anvil"
NETWORK_BASE_SEPOLIA = "base_sepolia"
NETWORK_ETHEREUM_SEPOLIA = "ethereum_sepolia"
NETWORK_ETHEREUM_MAINNET = "ethereum_mainnet"
NETWORK_FILECOIN_CALIBRATION = "filecoin_calibration"
NETWORK_GENLAYER_BRADBURY = "genlayer_bradbury"
SUPPORTED_NETWORKS = {
    NETWORK_ANVIL,
    NETWORK_BASE_SEPOLIA,
    NETWORK_ETHEREUM_SEPOLIA,
    NETWORK_ETHEREUM_MAINNET,
    NETWORK_FILECOIN_CALIBRATION,
    NETWORK_GENLAYER_BRADBURY,
}


def get_alkahest_network(value: str | None) -> str:
    network = (value or NETWORK_BASE_SEPOLIA).strip().lower()
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(
            f"Unsupported chain network '{network}'. "
            f"Supported values: {sorted(SUPPORTED_NETWORKS)}"
        )
    return network


@lru_cache(maxsize=8)
def _load_override_config_cached(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("alkahest address config path must point to a JSON object")
    return data


def _load_override_config(
    config_path: str | None,
) -> dict[str, Any] | None:
    if config_path and config_path.strip():
        normalized_path = str(Path(config_path).expanduser().resolve())
        return copy.deepcopy(_load_override_config_cached(normalized_path))
    return None


def _dict_to_namespace(value: Any) -> Any:
    if isinstance(value, dict):
        return SimpleNamespace(**{k: _dict_to_namespace(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_dict_to_namespace(item) for item in value]
    return value


def prewarm_alkahest_address_config_cache(config_path: str | None) -> None:
    """Eagerly load/validate the configured address override JSON (if any)."""
    _load_override_config(config_path)


def _sdk_addresses_for_chain(chain_name: str) -> Any:
    """Look up `DefaultExtensionConfig.for_chain(name)` from alkahest-py.

    Imported lazily so this module can be loaded for the override-only path
    (anvil) without alkahest-py installed.
    """
    from alkahest_py import DefaultExtensionConfig

    return DefaultExtensionConfig.for_chain(chain_name)


def resolve_alkahest_address_config(
    network: str,
    *,
    config_path: str | None = None,
) -> Any | None:
    """Return an address config the AlkahestClient constructor accepts.

    Returns:
      - the override `SimpleNamespace` tree if `config_path` is set
      - `None` for `base_sepolia` (so the SDK uses its built-in default)
      - a `DefaultExtensionConfig` from the SDK for any other supported chain
      - raises for `anvil` without a `config_path`
    """
    selected = get_alkahest_network(network)
    override = _load_override_config(config_path)
    if override is not None:
        return _dict_to_namespace(override)

    if selected == NETWORK_BASE_SEPOLIA:
        return None
    if selected == NETWORK_ANVIL:
        raise ValueError(
            "chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with deployed local addresses."
        )
    return _sdk_addresses_for_chain(selected)


def _arbiter_address(
    chain_name: str,
    *,
    config_path: str | None,
    arbiter_field: str,
) -> str:
    """Resolve a named arbiter address for the chain (override JSON wins)."""
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        return str(override["arbiters_addresses"][arbiter_field])
    if selected == NETWORK_ANVIL:
        raise ValueError(
            "chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with deployed local addresses."
        )
    cfg = _sdk_addresses_for_chain(selected)
    return str(getattr(cfg.arbiters_addresses, arbiter_field))


def get_trusted_oracle_arbiter(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    return _arbiter_address(
        chain_name, config_path=config_path, arbiter_field="trusted_oracle_arbiter"
    )


def get_recipient_arbiter(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve the RecipientArbiter address for the selected network.

    Used when the escrow demand is "the fulfillment attestation's recipient
    must equal X" — the simplest non-oracle gating scheme available. For
    compute deals, X is the seller's wallet, because
    ``StringObligation.doObligation`` sets the fulfillment attestation's
    recipient to ``msg.sender`` (the seller).
    """
    return _arbiter_address(
        chain_name, config_path=config_path, arbiter_field="recipient_arbiter"
    )


def get_erc20_escrow_obligation_nontierable(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve the address of ``ERC20EscrowObligation`` (non-tierable variant).

    This is where buyer-side ERC20 payment escrows live on-chain. It's the
    contract the buyer calls ``doObligation`` on at escrow creation, and the
    one the seller reads back via ``get_obligation`` at settlement-time
    verification. Populates ``EscrowTerms.escrow_contract`` so settlement
    code can dispatch the right SDK read shape without consulting a codec
    registry — the address is the natural identity.
    """
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        return str(override["erc20_addresses"]["escrow_obligation_nontierable"])
    if selected == NETWORK_ANVIL:
        raise ValueError(
            "chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with deployed local addresses."
        )
    cfg = _sdk_addresses_for_chain(selected)
    return str(cfg.erc20_addresses.escrow_obligation_nontierable)


def encode_recipient_demand(recipient_address: str) -> bytes:
    """ABI-encode RecipientArbiter.DemandData{address recipient}.

    alkahest_py exposes TrustedOracleArbiterDemandData but no analogous
    encoder for RecipientArbiter, so we encode the tuple directly. The
    solidity struct is a single-field struct, which abi.encodes as a
    padded 32-byte address (same as abi.encode(address)).
    """
    from eth_abi import encode as _abi_encode
    from eth_abi.exceptions import EncodingError

    if (
        not isinstance(recipient_address, str)
        or not recipient_address.startswith("0x")
        or len(recipient_address) != 42
    ):
        raise ValueError(
            f"recipient_address must be a 0x-prefixed 20-byte hex string, got {recipient_address!r}"
        )
    try:
        return _abi_encode(["address"], [recipient_address])
    except EncodingError as exc:
        raise ValueError(
            f"recipient_address {recipient_address!r} is not valid hex: {exc}"
        ) from exc


def build_payment_obligation_data(
    *,
    seller_wallet: str,
    agreed_price: int,
    duration_seconds: int,
    token_contract_address: str,
    chain_name: str,
    addr_config_path: str | None = None,
) -> dict[str, Any]:
    """Canonical obligation_data for an ERC20 + RecipientArbiter payment escrow.

    Both the buyer (at escrow creation) and the seller (at verification)
    call this helper with the negotiated inputs and the chain config, so
    they're guaranteed to produce identical expected obligation_data. Any
    divergence between sides means a misconfiguration somewhere — wrong
    token contract, wrong chain config, wrong amount formula — and the
    seller's verifier flags it before any provisioning side-effect.

    Returns the literal ``ERC20EscrowObligation.ObligationData`` struct:

        {arbiter: <RecipientArbiter address for chain_name>,
         demand:  "0x" + abi.encode(["address"], [seller_wallet]),
         token:   token_contract_address,
         amount:  agreed_price * duration_seconds / 3600}

    Step 5 (arbiter codec extraction) replaces the inlined demand encoding
    with a codec lookup keyed by arbiter address; the function's external
    contract stays the same.
    """
    arbiter_address = get_recipient_arbiter(chain_name, config_path=addr_config_path)
    demand_bytes = encode_recipient_demand(seller_wallet)
    amount_raw = int(agreed_price) * int(max(duration_seconds, 1)) // 3600
    return {
        "arbiter": arbiter_address,
        "demand": "0x" + demand_bytes.hex(),
        "token": token_contract_address,
        "amount": amount_raw,
    }
