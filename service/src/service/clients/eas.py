"""EVM-side helpers for reading EAS attestations.

Used by `market escrow show` and `market-storefront escrow show` to
inspect on-chain escrow state by uid, and by the storefront's pre-
settlement verifier. Wraps web3.py around the vendored `IEAS` ABI;
the alkahest_py SDK does not expose a direct "get attestation by uid"
method (its `get_escrow_attestation` indexes by fulfillment uid, the
wrong direction).

The ERC-20 escrow obligation payload is decoded inline against its
known schema:

    address arbiter, bytes demand, address token, uint256 amount

(matches `ERC20EscrowObligation.ObligationData` in the alkahest
contracts).

The reader is async-first (`AsyncWeb3`); a thin `read_attestation_sync`
wrapper exists for the typer CLI sites that can't easily go async.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from eth_abi import decode as abi_decode
from web3 import AsyncWeb3
from web3.providers import AsyncHTTPProvider
from web3.providers.persistent.websocket import WebSocketProvider

from service.abi import load_abi


# Tuple-encoded layout of ERC20EscrowObligation.ObligationData.
# Wrapped in a struct ABI type because alkahest emits the data via
# `abi.encode(obligationData)` (a single struct argument) — that form
# carries a leading 32-byte tuple-offset that flat-tuple decoding rejects.
_ERC20_ESCROW_OBLIGATION_TYPES = ("(address,bytes,address,uint256)",)


@dataclass(frozen=True)
class EscrowAttestation:
    """Read-only view of an EAS attestation, decoded for ERC-20 escrow."""
    uid: str
    schema: str
    attester: str
    recipient: str
    time: int
    expiration_time: int
    revocation_time: int
    ref_uid: str
    revocable: bool
    raw_data: bytes
    # Decoded ObligationData fields (None when raw_data couldn't be
    # decoded under the ERC-20 escrow schema — e.g. the uid points at
    # an obligation of a different type).
    arbiter: Optional[str] = None
    demand: Optional[bytes] = None
    token: Optional[str] = None
    amount: Optional[int] = None
    decode_error: Optional[str] = None

    @property
    def is_revoked(self) -> bool:
        return self.revocation_time != 0

    @property
    def is_expired_at(self) -> Optional[int]:
        return self.expiration_time if self.expiration_time != 0 else None


def _is_websocket_url(rpc_url: str) -> bool:
    return rpc_url.strip().startswith(("ws://", "wss://"))


def _hex(b: bytes | str) -> str:
    if isinstance(b, str):
        return b if b.startswith("0x") else "0x" + b
    return "0x" + b.hex()


async def read_attestation(
    rpc_url: str,
    eas_address: str,
    uid: str,
) -> EscrowAttestation:
    """Fetch an EAS attestation by uid via `IEAS.getAttestation(bytes32)`.

    Decodes the data payload against the ERC-20 escrow obligation schema.
    Other obligation shapes will populate `decode_error` and leave the
    decoded fields as None — the caller can still display the raw
    attestation envelope.
    """
    uid_bytes = bytes.fromhex(uid[2:] if uid.startswith("0x") else uid)
    if len(uid_bytes) != 32:
        raise ValueError(
            f"Attestation uid must be 32 bytes (0x + 64 hex chars); got {uid!r}"
        )

    s = rpc_url.strip()
    eas_addr = AsyncWeb3.to_checksum_address(eas_address)
    abi = load_abi("IEAS")
    if _is_websocket_url(s):
        # WebSocketProvider is a persistent provider — needs the async
        # context manager to open the socket. For a one-shot read this
        # opens, calls, and closes within the same `await`.
        async with AsyncWeb3(WebSocketProvider(s)) as w3:
            contract = w3.eth.contract(address=eas_addr, abi=abi)
            raw = await contract.functions.getAttestation(uid_bytes).call()
    else:
        w3 = AsyncWeb3(AsyncHTTPProvider(s))
        contract = w3.eth.contract(address=eas_addr, abi=abi)
        raw = await contract.functions.getAttestation(uid_bytes).call()
    # IEAS.Attestation tuple layout (per eas-contracts/IEAS.sol):
    #   uid, schema, time, expirationTime, revocationTime,
    #   refUID, recipient, attester, revocable, data
    (
        ret_uid,
        schema,
        time,
        expiration_time,
        revocation_time,
        ref_uid,
        recipient,
        attester,
        revocable,
        data,
    ) = raw

    arbiter = demand = token = amount = None
    decode_error: Optional[str] = None
    try:
        (decoded,) = abi_decode(
            list(_ERC20_ESCROW_OBLIGATION_TYPES),
            bytes(data),
        )
        arbiter, demand, token, amount = decoded
    except Exception as exc:
        decode_error = (
            f"Could not decode data as ERC20EscrowObligation: {exc}. "
            f"Likely a different obligation type."
        )

    return EscrowAttestation(
        uid=_hex(ret_uid),
        schema=_hex(schema),
        attester=AsyncWeb3.to_checksum_address(attester),
        recipient=AsyncWeb3.to_checksum_address(recipient),
        time=int(time),
        expiration_time=int(expiration_time),
        revocation_time=int(revocation_time),
        ref_uid=_hex(ref_uid),
        revocable=bool(revocable),
        raw_data=bytes(data),
        arbiter=AsyncWeb3.to_checksum_address(arbiter) if arbiter else None,
        demand=bytes(demand) if demand else None,
        token=AsyncWeb3.to_checksum_address(token) if token else None,
        amount=int(amount) if amount is not None else None,
        decode_error=decode_error,
    )


def read_attestation_sync(
    rpc_url: str,
    eas_address: str,
    uid: str,
) -> EscrowAttestation:
    """Sync wrapper around ``read_attestation`` for CLI call sites that
    aren't running inside an event loop. Don't call from async code —
    use ``read_attestation`` directly there."""
    return asyncio.run(read_attestation(rpc_url, eas_address, uid))


def resolve_eas_address(
    chain_name: str,
    *,
    config_path: Optional[str] = None,
) -> str:
    """Resolve the EAS contract address from the alkahest address config.

    Override JSON wins; otherwise pull from the SDK's
    ``DefaultExtensionConfig.for_chain`` (alkahest-py >= 0.3.0).
    """
    from service.clients.alkahest import (
        NETWORK_ANVIL,
        _load_override_config,
        _sdk_addresses_for_chain,
        get_alkahest_network,
    )

    selected = get_alkahest_network(chain_name)
    override = _load_override_config(config_path)
    if override is not None:
        addr = override.get("attestation_addresses", {}).get("eas")
        if addr:
            return str(addr)
    if selected == NETWORK_ANVIL:
        raise ValueError(
            f"chain_name='anvil' requires an explicit alkahest_address_config_path "
            "with attestation_addresses.eas."
        )
    cfg = _sdk_addresses_for_chain(selected)
    addr = cfg.attestation_addresses.eas
    if addr:
        return str(addr)
    raise ValueError(
        f"Could not resolve EAS address for chain={chain_name!r}. "
        f"Pass an alkahest_address_config_path with attestation_addresses.eas."
    )
