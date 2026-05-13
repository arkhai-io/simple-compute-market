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
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol, runtime_checkable

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


# ---------------------------------------------------------------------------
# Arbiter codecs
# ---------------------------------------------------------------------------
#
# An ArbiterCodec encapsulates everything arbiter-kind-specific:
#   - which on-chain contract address holds the arbiter
#   - how the buyer should encode the demand bytes for it
#
# ``build_payment_obligation_data`` delegates both to the codec, so adding
# a new arbiter (e.g. TrustedOracleArbiter) only requires writing a codec
# + registering it — neither the buyer's escrow construction nor the
# seller's verification needs to know about the new kind.
#
# The seller's verifier doesn't consult codecs at all: it dict-compares
# the chain-read obligation_data against the buyer-built one. Both sides
# call the same builder with the same inputs, so the demand bytes match
# bytewise. Codec-aware verification (e.g. "decode demand and report the
# *recipient address* that didn't match") is a UX nicety we can add later;
# the structural check is already covered.


@dataclass(frozen=True)
class AgreementContext:
    """Negotiated values an arbiter codec might read to encode its demand.

    Captures the cross-codec contract: every codec receives the same
    bag of agreed-to fields and uses what it needs. Adding a field for
    a new codec doesn't break existing ones.

    Today only ``seller_wallet`` is read (by RecipientArbiterCodec).
    Future codecs that bind more of the agreement into the demand
    (TrustedOracle, AttestationProperty, etc.) read the other fields.
    """

    seller_wallet: str
    agreed_price: int
    duration_seconds: int


@runtime_checkable
class ArbiterCodec(Protocol):
    """Per-arbiter-kind logic for resolving the on-chain address and
    encoding the demand bytes that go into the escrow obligation_data.

    Codecs are stateless module-level singletons in
    ``_ARBITER_CODECS``; the buyer's builder looks one up by ``kind``
    (today: ``"recipient"``) and delegates the arbiter parts of
    obligation_data construction to it. Both sides — buyer at escrow
    creation, seller via the shared ``build_payment_obligation_data``
    helper — go through the same codec, so demand bytes match
    bytewise across the wire and dict-compare verification passes.
    """

    kind: str

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str: ...

    def encode_demand(self, agreement: AgreementContext) -> bytes: ...


class RecipientArbiterCodec:
    """The escrow releases on any fulfillment attestation whose
    ``recipient`` equals the encoded seller address.

    Demand bytes: ``abi.encode(["address"], [seller_wallet])``.

    Trust-based: the seller can fulfill with any attestation as long
    as its recipient is their wallet. The on-chain release condition
    binds zero of the negotiated provision details — the seller's
    commitment to actually deliver the agreed compute is honor-system.
    Future codecs that bind more of the agreement (TrustedOracle,
    AttestationProperty) tighten this.
    """

    kind = "recipient"

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str:
        return get_recipient_arbiter(chain_name, config_path=config_path)

    def encode_demand(self, agreement: AgreementContext) -> bytes:
        return encode_recipient_demand(agreement.seller_wallet)


_ARBITER_CODECS: dict[str, ArbiterCodec] = {
    "recipient": RecipientArbiterCodec(),
}


def register_arbiter_codec(codec: ArbiterCodec) -> None:
    """Add or replace a codec under its ``kind``.

    Idempotent: calling twice with the same kind overwrites — useful
    for test setups that need to swap in a mock codec.
    """
    _ARBITER_CODECS[codec.kind] = codec


def get_arbiter_codec(kind: str) -> ArbiterCodec:
    """Lookup by kind; raises ValueError for unknown kinds with the
    list of registered ones in the message."""
    codec = _ARBITER_CODECS.get(kind)
    if codec is None:
        raise ValueError(
            f"Unknown arbiter_kind={kind!r}; "
            f"registered: {sorted(_ARBITER_CODECS)}"
        )
    return codec


def known_arbiter_kinds() -> list[str]:
    """Snapshot of currently-registered arbiter kinds (for diagnostics)."""
    return sorted(_ARBITER_CODECS)


def build_payment_obligation_data(
    *,
    seller_wallet: str,
    agreed_price: int,
    duration_seconds: int,
    token_contract_address: str,
    chain_name: str,
    addr_config_path: str | None = None,
    arbiter_kind: str = "recipient",
) -> dict[str, Any]:
    """Canonical obligation_data for an ERC20 + arbiter-kind payment escrow.

    Both the buyer (at escrow creation) and the seller (at verification)
    call this helper with the negotiated inputs and the chain config, so
    they produce identical expected obligation_data. Any divergence
    between sides means a misconfiguration somewhere — wrong token,
    wrong chain config, wrong amount formula, wrong arbiter kind — and
    the seller's verifier flags it before any provisioning side-effect.

    Returns the literal ``ERC20EscrowObligation.ObligationData`` struct:

        {arbiter: <kind-specific address for chain_name>,
         demand:  "0x" + <kind-specific demand bytes>,
         token:   token_contract_address,
         amount:  agreed_price * duration_seconds / 3600}

    The arbiter address and demand bytes are produced by the registered
    ``ArbiterCodec`` matching ``arbiter_kind``. The amount formula is
    today's hard-coded policy (per-hour rate × duration / 3600); step 6
    moves it into a per-escrow-kind helper as the escrow contract
    dispatch becomes polymorphic.
    """
    codec = get_arbiter_codec(arbiter_kind)
    agreement = AgreementContext(
        seller_wallet=seller_wallet,
        agreed_price=agreed_price,
        duration_seconds=duration_seconds,
    )
    arbiter_address = codec.resolve_address(chain_name, config_path=addr_config_path)
    demand_bytes = codec.encode_demand(agreement)
    amount_raw = int(agreed_price) * int(max(duration_seconds, 1)) // 3600
    return {
        "arbiter": arbiter_address,
        "demand": "0x" + demand_bytes.hex(),
        "token": token_contract_address,
        "amount": amount_raw,
    }


# ---------------------------------------------------------------------------
# Escrow-kind codecs
# ---------------------------------------------------------------------------
#
# An EscrowKindCodec encapsulates everything escrow-contract-specific:
#   - which on-chain contract address holds the escrow obligation
#   - how to call ``doObligation`` for it via the alkahest SDK
#   - how to read the obligation back via ``get_obligation``
#
# The buyer's create_escrow hook looks up the codec by
# ``EscrowTerms.escrow_contract`` address — the address is the natural
# identity, so the same EscrowTerms artifact dispatches the right SDK
# path without any side-channel "what kind is this" metadata.
#
# Today only ``Erc20NonTierableEscrowCodec`` is registered. Adding
# native / ERC721 / token-bundle / attestation escrows later means
# writing a codec + registering it — neither the buyer's submit hook
# nor the seller's verifier needs to learn about new kinds.


def _normalize_demand_bytes(value: Any) -> bytes:
    """Coerce a demand value (hex string or bytes) to raw bytes.

    Buyer's EscrowTerms stores demand as a "0x"-prefixed hex string for
    JSON-friendly transport; chain submission needs raw bytes. Tolerate
    bare hex (no 0x) and existing bytes so callers don't have to
    normalize themselves.
    """
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value)
    if isinstance(value, str):
        s = value
        if s.startswith("0x"):
            s = s[2:]
        return bytes.fromhex(s)
    raise TypeError(
        f"demand must be bytes or hex-string, got {type(value).__name__}: {value!r}"
    )


@runtime_checkable
class EscrowKindCodec(Protocol):
    """Per-escrow-contract SDK adapter.

    Maps an abstract ``EscrowTerms`` (flat ``obligation_data`` dict +
    expiration) to the alkahest SDK's create-obligation / read-obligation
    calls for one specific obligation contract. Stateless module-level
    singletons in ``_ESCROW_KIND_CODECS``; lookup is by ``kind`` or by
    on-chain contract address (the codec's ``resolve_address`` output).
    """

    kind: str

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str: ...

    async def create_obligation(
        self,
        client: Any,
        obligation_data: dict[str, Any],
        expiration_unix: int,
    ) -> str: ...

    async def get_obligation(self, client: Any, uid: str) -> Any: ...


class Erc20NonTierableEscrowCodec:
    """``ERC20EscrowObligation`` (non-tierable variant).

    Solidity ObligationData layout:
        (address arbiter, bytes demand, address token, uint256 amount)

    SDK call shape splits the four fields into:
      - ``price_data = {"address": token, "value": amount}``
      - ``arbiter_data = {"arbiter": arbiter, "demand": <bytes>}``
      - ``expiration`` as a separate uint64
    """

    kind = "erc20_non_tierable"

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str:
        return get_erc20_escrow_obligation_nontierable(
            chain_name, config_path=config_path,
        )

    async def create_obligation(
        self,
        client: Any,
        obligation_data: dict[str, Any],
        expiration_unix: int,
    ) -> str:
        price_data = {
            "address": obligation_data["token"],
            "value": int(obligation_data["amount"]),
        }
        arbiter_data = {
            "arbiter": obligation_data["arbiter"],
            "demand": _normalize_demand_bytes(obligation_data["demand"]),
        }
        await client.erc20.util.approve(price_data, "escrow")
        receipt = await client.erc20.escrow.non_tierable.create(
            price_data, arbiter_data, expiration_unix,
        )
        uid = (receipt or {}).get("log", {}).get("uid")
        if not uid:
            raise RuntimeError(
                f"escrow.create did not return a uid: {receipt!r}"
            )
        return uid

    async def get_obligation(self, client: Any, uid: str) -> Any:
        return await client.erc20.escrow.non_tierable.get_obligation(uid)


_ESCROW_KIND_CODECS: dict[str, EscrowKindCodec] = {
    "erc20_non_tierable": Erc20NonTierableEscrowCodec(),
}


def register_escrow_kind_codec(codec: EscrowKindCodec) -> None:
    """Add or replace a codec under its ``kind``. Idempotent on kind."""
    _ESCROW_KIND_CODECS[codec.kind] = codec


def get_escrow_kind_codec(kind: str) -> EscrowKindCodec:
    """Lookup by kind; raises ValueError on unknown kinds."""
    codec = _ESCROW_KIND_CODECS.get(kind)
    if codec is None:
        raise ValueError(
            f"Unknown escrow_kind={kind!r}; "
            f"registered: {sorted(_ESCROW_KIND_CODECS)}"
        )
    return codec


def get_escrow_kind_codec_by_address(
    address: str,
    chain_name: str,
    *,
    config_path: str | None = None,
) -> EscrowKindCodec:
    """Find the codec whose resolved address matches ``address`` on
    ``chain_name``.

    Iterates registered codecs (O(n); n is small). Used by the buyer's
    submit hook to pick the SDK path from ``EscrowTerms.escrow_contract``
    without carrying a separate escrow_kind tag. Raises ValueError when
    no codec matches — usually means the buyer's EscrowTerms was built
    against a different chain config than what's now configured.
    """
    target = address.lower()
    for codec in _ESCROW_KIND_CODECS.values():
        try:
            resolved = codec.resolve_address(chain_name, config_path=config_path)
        except Exception:
            # A codec that can't resolve on this chain (e.g. anvil without
            # an override JSON) is simply not a candidate; skip it.
            continue
        if resolved.lower() == target:
            return codec
    raise ValueError(
        f"No escrow-kind codec found for address={address!r} on chain={chain_name!r}; "
        f"registered: {sorted(_ESCROW_KIND_CODECS)}"
    )


def known_escrow_kinds() -> list[str]:
    """Snapshot of currently-registered escrow kinds (for diagnostics)."""
    return sorted(_ESCROW_KIND_CODECS)
