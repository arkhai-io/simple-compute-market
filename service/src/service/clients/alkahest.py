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


def _escrow_obligation_address(
    chain_name: str,
    *,
    config_path: str | None,
    category: str,
    field: str,
) -> str:
    """Resolve an escrow-obligation address from an Alkahest address category."""
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        return str(override[category][field])
    if selected == NETWORK_ANVIL:
        raise ValueError(
            "chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with deployed local addresses."
        )
    cfg = _sdk_addresses_for_chain(selected)
    return str(getattr(getattr(cfg, category), field))


def get_erc721_escrow_obligation_nontierable(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve ``ERC721EscrowObligation`` (non-tierable variant)."""
    return _escrow_obligation_address(
        chain_name,
        config_path=config_path,
        category="erc721_addresses",
        field="escrow_obligation_nontierable",
    )


def get_erc721_escrow_obligation_tierable(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve ``ERC721EscrowObligation`` (tierable variant)."""
    return _escrow_obligation_address(
        chain_name,
        config_path=config_path,
        category="erc721_addresses",
        field="escrow_obligation_tierable",
    )


def get_erc1155_escrow_obligation_nontierable(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve ``ERC1155EscrowObligation`` (non-tierable variant)."""
    return _escrow_obligation_address(
        chain_name,
        config_path=config_path,
        category="erc1155_addresses",
        field="escrow_obligation_nontierable",
    )


def get_erc1155_escrow_obligation_tierable(
    chain_name: str,
    *,
    config_path: str | None = None,
) -> str:
    """Resolve ``ERC1155EscrowObligation`` (tierable variant)."""
    return _escrow_obligation_address(
        chain_name,
        config_path=config_path,
        category="erc1155_addresses",
        field="escrow_obligation_tierable",
    )


_ADDRESS_CATEGORIES: tuple[tuple[str, str], ...] = (
    # (attribute on DefaultExtensionConfig, prefix for slot name).
    # Arbiters' field names are already ``*_arbiter``-suffixed, so the
    # empty prefix produces e.g. ``recipient_arbiter`` rather than
    # the redundant ``arbiters_recipient_arbiter``.
    ("arbiters_addresses", ""),
    ("string_obligation_addresses", "string_obligation"),
    ("commit_reveal_obligation_addresses", "commit_reveal_obligation"),
    ("erc20_addresses", "erc20"),
    ("erc721_addresses", "erc721"),
    ("erc1155_addresses", "erc1155"),
    ("native_token_addresses", "native_token"),
    ("token_bundle_addresses", "token_bundle"),
    ("attestation_addresses", "attestation"),
)


def _list_category_fields(category: Any) -> list[str]:
    """Best-effort enumeration of address-field names on a category.

    SimpleNamespace (override JSON path) → ``vars()``; pyo3 binding
    (SDK path) → ``dir()`` filtering. Both produce the same set of
    field names for valid configs.
    """
    if hasattr(category, "__dict__"):
        return [k for k in vars(category).keys() if not k.startswith("_")]
    return [
        k for k in dir(category)
        if not k.startswith("_") and not callable(getattr(category, k, None))
    ]


@lru_cache(maxsize=64)
def _reverse_address_map(
    chain_name: str, config_path_or_none: str,
) -> dict[str, str]:
    """Build ``{lowercase_address: slot_name}`` for a chain.

    Slot name format: ``<category_prefix>_<field>`` (e.g.
    ``erc20_escrow_obligation_nontierable``); arbiters keep their
    field names unprefixed. Zero-address slots are skipped — they
    represent contracts not yet deployed on this chain.

    Cache key is a flat ``(chain_name, config_path_str)`` tuple so the
    lru_cache works against hashable arguments; pass empty string for
    "no config path."
    """
    config_path = config_path_or_none or None
    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    source: Any
    if override is not None:
        source = _dict_to_namespace(override)
    elif selected == NETWORK_ANVIL:
        raise ValueError(
            "chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with deployed local addresses."
        )
    else:
        source = _sdk_addresses_for_chain(selected)

    result: dict[str, str] = {}
    for category_attr, prefix in _ADDRESS_CATEGORIES:
        category = getattr(source, category_attr, None)
        if category is None:
            continue
        for field_name in _list_category_fields(category):
            try:
                value = getattr(category, field_name)
            except Exception:
                continue
            if not isinstance(value, str) or not value.startswith("0x"):
                continue
            if len(value) != 42:
                continue
            try:
                if int(value, 16) == 0:
                    continue  # undeployed slot placeholder
            except ValueError:
                continue
            slot = f"{prefix}_{field_name}" if prefix else field_name
            result[value.lower()] = slot
    return result


def address_to_slot(
    chain_name: str,
    address: str,
    *,
    config_path: str | None = None,
) -> str | None:
    """Return the slot name for a deployed address on a chain.

    Returns ``None`` when the address isn't registered in the chain's
    DefaultExtensionConfig — typically a non-alkahest contract such as
    the payment ERC20 token itself, which lives on-chain but isn't part
    of any alkahest deployment slot.
    """
    return _reverse_address_map(chain_name, config_path or "").get(address.lower())


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


@dataclass(frozen=True, init=False)
class AgreementContext:
    """Negotiated values an arbiter codec might read to encode its demand.

    Captures the cross-codec contract: every codec receives the same
    bag of agreed-to fields and uses what it needs. Adding a field for
    a new codec doesn't break existing ones.

    Today only ``recipient`` is read (by RecipientArbiterCodec).
    Future codecs that bind more of the agreement into the demand
    (TrustedOracle, AttestationProperty, etc.) read the other fields.

    ``agreed_amount`` is the absolute payment total in base units of
    the escrow's payment token (post-negotiation; per-hour rates only
    appear as listing broadcasts). ``duration_seconds`` is the lease
    window the seller commits to.
    """

    recipient: str
    agreed_amount: int
    duration_seconds: int

    def __init__(
        self,
        recipient: str | None = None,
        agreed_amount: int = 0,
        duration_seconds: int = 0,
        *,
        seller_wallet: str | None = None,
    ) -> None:
        effective_recipient = recipient or seller_wallet
        if not effective_recipient:
            raise ValueError("AgreementContext recipient is required")
        object.__setattr__(self, "recipient", effective_recipient)
        object.__setattr__(self, "agreed_amount", agreed_amount)
        object.__setattr__(self, "duration_seconds", duration_seconds)

    @property
    def seller_wallet(self) -> str:
        """Legacy alias for older tests/callers; use ``recipient``."""
        return self.recipient


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

    def encode_demand_data(self, demand_data: dict[str, Any]) -> bytes: ...


class RecipientArbiterCodec:
    """The escrow releases on any fulfillment attestation whose
    ``recipient`` equals the encoded demand recipient.

    Demand bytes: ``abi.encode(["address"], [recipient])``.

    Trust-based: the fulfiller can release with any attestation as long
    as its recipient is the escrow's negotiated recipient. The on-chain release condition
    binds zero of the negotiated provision details — the seller's
    commitment to actually deliver the agreed compute is honor-system.
    Future codecs that bind more of the agreement (TrustedOracle,
    AttestationProperty) tighten this.

    ``kind`` matches the alkahest slot name (``recipient_arbiter``)
    so the codec is keyed by the same identifier ``address_to_slot``
    produces when handed the deployed arbiter address. The address is
    the natural identity; the slot name is the codec lookup key.
    """

    kind = "recipient_arbiter"

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str:
        return get_recipient_arbiter(chain_name, config_path=config_path)

    def encode_demand(self, agreement: AgreementContext) -> bytes:
        return encode_recipient_demand(agreement.recipient)

    def encode_demand_data(self, demand_data: dict[str, Any]) -> bytes:
        recipient = demand_data.get("recipient")
        if not isinstance(recipient, str) or not recipient:
            raise ValueError("RecipientArbiter demand_data.recipient is required")
        return encode_recipient_demand(recipient)


_ARBITER_CODECS: dict[str, ArbiterCodec] = {
    "recipient_arbiter": RecipientArbiterCodec(),
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
    demands: list[dict[str, Any]] | None = None,
    recipient: str | None = None,
    seller_wallet: str | None = None,
    agreed_amount: int,
    duration_seconds: int,
    token_contract_address: str,
    chain_name: str,
    addr_config_path: str | None = None,
    arbiter_kind: str = "recipient_arbiter",
) -> dict[str, Any]:
    """Canonical obligation_data for an ERC20 + arbiter-kind payment escrow.

    Both the buyer (at escrow creation) and the seller (at verification)
    call this helper with the negotiated inputs and the chain config, so
    they produce identical expected obligation_data. Any divergence
    between sides means a misconfiguration somewhere — wrong token,
    wrong chain config, wrong amount, wrong arbiter kind — and the
    seller's verifier flags it before any provisioning side-effect.

    Returns the literal ``ERC20EscrowObligation.ObligationData`` struct:

        {arbiter: <kind-specific address for chain_name>,
         demand:  "0x" + <kind-specific demand bytes>,
         token:   token_contract_address,
         amount:  agreed_amount}

    ``agreed_amount`` is the absolute payment total in base units of
    ``token_contract_address`` — already multiplied out from any per-hour
    rate during negotiation. The middleware chain owns price math; this
    helper just wires obligation bytes.

    The arbiter address and demand bytes are produced by the registered
    ``ArbiterCodec`` matching ``arbiter_kind``.
    """
    if demands:
        first = demands[0]
        if not isinstance(first, dict):
            raise ValueError("demands entries must be objects")
        arbiter_address = first.get("arbiter")
        if not isinstance(arbiter_address, str) or not arbiter_address:
            raise ValueError("demands[0].arbiter is required")
        demand_data = first.get("demand_data")
        if not isinstance(demand_data, dict):
            raise ValueError("demands[0].demand_data must be an object")
        resolved_kind = address_to_slot(
            chain_name,
            arbiter_address,
            config_path=addr_config_path,
        )
        if not resolved_kind:
            raise ValueError(
                f"Cannot resolve arbiter codec for demand arbiter "
                f"{arbiter_address!r} on chain {chain_name!r}"
            )
        codec = get_arbiter_codec(resolved_kind)
        demand_bytes = codec.encode_demand_data(demand_data)
    else:
        effective_recipient = recipient or seller_wallet
        if not effective_recipient:
            raise ValueError(
                "recipient or demands must be supplied to build payment obligation data"
            )
        codec = get_arbiter_codec(arbiter_kind)
        agreement = AgreementContext(
            recipient=effective_recipient,
            agreed_amount=int(agreed_amount),
            duration_seconds=duration_seconds,
        )
        arbiter_address = codec.resolve_address(chain_name, config_path=addr_config_path)
        demand_bytes = codec.encode_demand(agreement)
    return {
        "arbiter": arbiter_address,
        "demand": "0x" + demand_bytes.hex(),
        "token": token_contract_address,
        "amount": int(agreed_amount),
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

    ``kind`` matches the alkahest slot name produced by
    ``address_to_slot`` so codecs and reverse address lookups share
    the same identifier namespace.
    """

    kind = "erc20_escrow_obligation_nontierable"

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


class _Erc721EscrowCodecBase:
    """Common ERC721 escrow SDK adapter.

    Solidity ObligationData layout:
        (address arbiter, bytes demand, address token, uint256 tokenId)

    SDK call shape splits the NFT fields into:
      - ``price_data = {"address": token, "id": tokenId}``
      - ``arbiter_data = {"arbiter": arbiter, "demand": <bytes>}``
      - ``expiration`` as a separate uint64
    """

    tier_attr: str
    address_field: str
    approve_via_sdk: bool = True

    def _price_data(self, obligation_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "address": obligation_data["token"],
            "id": int(obligation_data["tokenId"]),
        }

    def _arbiter_data(self, obligation_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "arbiter": obligation_data["arbiter"],
            "demand": _normalize_demand_bytes(obligation_data["demand"]),
        }

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str:
        return _escrow_obligation_address(
            chain_name,
            config_path=config_path,
            category="erc721_addresses",
            field=self.address_field,
        )

    async def create_obligation(
        self,
        client: Any,
        obligation_data: dict[str, Any],
        expiration_unix: int,
    ) -> str:
        price_data = self._price_data(obligation_data)
        arbiter_data = self._arbiter_data(obligation_data)
        if self.approve_via_sdk:
            await client.erc721.util.approve(price_data, "escrow")
        tier_client = getattr(client.erc721.escrow, self.tier_attr)
        receipt = await tier_client.create(
            price_data, arbiter_data, expiration_unix,
        )
        uid = (receipt or {}).get("log", {}).get("uid")
        if not uid:
            raise RuntimeError(
                f"escrow.create did not return a uid: {receipt!r}"
            )
        return uid

    async def get_obligation(self, client: Any, uid: str) -> Any:
        tier_client = getattr(client.erc721.escrow, self.tier_attr)
        return await tier_client.get_obligation(uid)


class Erc721NonTierableEscrowCodec(_Erc721EscrowCodecBase):
    """``ERC721EscrowObligation`` (non-tierable variant)."""

    kind = "erc721_escrow_obligation_nontierable"
    tier_attr = "non_tierable"
    address_field = "escrow_obligation_nontierable"


class Erc721TierableEscrowCodec(_Erc721EscrowCodecBase):
    """``ERC721EscrowObligation`` (tierable variant)."""

    kind = "erc721_escrow_obligation_tierable"
    tier_attr = "tierable"
    address_field = "escrow_obligation_tierable"
    approve_via_sdk = False


class _Erc1155EscrowCodecBase:
    """Common ERC1155 escrow SDK adapter.

    Solidity ObligationData layout:
        (address arbiter, bytes demand, address token, uint256 tokenId, uint256 amount)

    SDK call shape splits the token fields into:
      - ``price_data = {"address": token, "id": tokenId, "value": amount}``
      - ``arbiter_data = {"arbiter": arbiter, "demand": <bytes>}``
      - ``expiration`` as a separate uint64
    """

    tier_attr: str
    address_field: str

    def _price_data(self, obligation_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "address": obligation_data["token"],
            "id": int(obligation_data["tokenId"]),
            "value": int(obligation_data["amount"]),
        }

    def _arbiter_data(self, obligation_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "arbiter": obligation_data["arbiter"],
            "demand": _normalize_demand_bytes(obligation_data["demand"]),
        }

    def resolve_address(
        self, chain_name: str, *, config_path: str | None
    ) -> str:
        return _escrow_obligation_address(
            chain_name,
            config_path=config_path,
            category="erc1155_addresses",
            field=self.address_field,
        )

    async def create_obligation(
        self,
        client: Any,
        obligation_data: dict[str, Any],
        expiration_unix: int,
    ) -> str:
        price_data = self._price_data(obligation_data)
        arbiter_data = self._arbiter_data(obligation_data)
        await client.erc1155.util.approve_all(price_data["address"], "escrow")
        tier_client = getattr(client.erc1155.escrow, self.tier_attr)
        receipt = await tier_client.create(
            price_data, arbiter_data, expiration_unix,
        )
        uid = (receipt or {}).get("log", {}).get("uid")
        if not uid:
            raise RuntimeError(
                f"escrow.create did not return a uid: {receipt!r}"
            )
        return uid

    async def get_obligation(self, client: Any, uid: str) -> Any:
        tier_client = getattr(client.erc1155.escrow, self.tier_attr)
        return await tier_client.get_obligation(uid)


class Erc1155NonTierableEscrowCodec(_Erc1155EscrowCodecBase):
    """``ERC1155EscrowObligation`` (non-tierable variant)."""

    kind = "erc1155_escrow_obligation_nontierable"
    tier_attr = "non_tierable"
    address_field = "escrow_obligation_nontierable"


class Erc1155TierableEscrowCodec(_Erc1155EscrowCodecBase):
    """``ERC1155EscrowObligation`` (tierable variant)."""

    kind = "erc1155_escrow_obligation_tierable"
    tier_attr = "tierable"
    address_field = "escrow_obligation_tierable"


_ESCROW_KIND_CODECS: dict[str, EscrowKindCodec] = {
    "erc20_escrow_obligation_nontierable": Erc20NonTierableEscrowCodec(),
    "erc721_escrow_obligation_nontierable": Erc721NonTierableEscrowCodec(),
    "erc721_escrow_obligation_tierable": Erc721TierableEscrowCodec(),
    "erc1155_escrow_obligation_nontierable": Erc1155NonTierableEscrowCodec(),
    "erc1155_escrow_obligation_tierable": Erc1155TierableEscrowCodec(),
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


def get_escrow_codec_for(
    chain_name: str,
    escrow_address: str,
    *,
    config_path: str | None = None,
) -> EscrowKindCodec:
    """Resolve a codec by (chain, address) via ``address_to_slot``.

    Convenience wrapper that bridges the reverse-address-map lookup
    with the codec registry: first look up which alkahest slot the
    address occupies on this chain, then find the codec keyed on that
    slot. Falls back to the iterative ``get_escrow_kind_codec_by_address``
    when the address isn't a registered alkahest slot (e.g. a freshly
    deployed contract whose address isn't yet in the SDK's defaults).

    Raises ``ValueError`` when no codec matches — typically a sign the
    listing was built against a different chain config than what's
    currently active.
    """
    slot = address_to_slot(chain_name, escrow_address, config_path=config_path)
    if slot is not None:
        codec = _ESCROW_KIND_CODECS.get(slot)
        if codec is not None:
            return codec
    return get_escrow_kind_codec_by_address(
        escrow_address, chain_name, config_path=config_path,
    )


def get_arbiter_codec_for(
    chain_name: str,
    arbiter_address: str,
    *,
    config_path: str | None = None,
) -> ArbiterCodec:
    """Resolve an arbiter codec by (chain, address) via ``address_to_slot``.

    Mirror of ``get_escrow_codec_for`` for arbiter codecs. Falls back
    to an iterative scan if the slot lookup misses; raises if no codec
    can resolve the address on this chain.
    """
    slot = address_to_slot(chain_name, arbiter_address, config_path=config_path)
    if slot is not None:
        codec = _ARBITER_CODECS.get(slot)
        if codec is not None:
            return codec
    target = arbiter_address.lower()
    for codec in _ARBITER_CODECS.values():
        try:
            resolved = codec.resolve_address(chain_name, config_path=config_path)
        except Exception:
            continue
        if resolved.lower() == target:
            return codec
    raise ValueError(
        f"No arbiter codec found for address={arbiter_address!r} "
        f"on chain={chain_name!r}; registered: {sorted(_ARBITER_CODECS)}"
    )
