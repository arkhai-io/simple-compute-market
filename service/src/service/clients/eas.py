"""EAS attestation reads for ERC-20 escrow verification.

Used by `market escrow show`, `market-storefront escrow show`, and the
storefront's pre-settlement verifier (`verify_escrow_for_settlement`).

The actual chain interaction is delegated to alkahest-py's
``client.erc20.escrow.non_tierable.get_obligation(uid)`` — that method
returns both the EAS attestation envelope and the typed
``ERC20EscrowObligation.ObligationData`` payload in one call, against
the alkahest-deployed obligation contract. This module just reshapes the
result into the ``EscrowAttestation`` dataclass that the verifier and
CLI commands expect.

Other obligation types (ERC-721, ERC-1155, native, bundle, attestation)
have analogous ``client.<asset>.escrow.<variant>.get_obligation`` paths;
we only wrap ERC-20 here because that's the only obligation type the
seller currently accepts.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional


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
    # Decoded ERC-20 escrow obligation fields. ``decode_error`` is
    # populated when the attestation is not an ERC-20 escrow obligation
    # (the alkahest call would have raised before we reach this struct,
    # so in practice this field is always None — kept for verifier
    # compatibility and future obligation-type dispatch).
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


async def read_attestation(client: Any, uid: str) -> EscrowAttestation:
    """Fetch an ERC-20 escrow attestation by uid through alkahest-py.

    ``client`` is an ``alkahest_py.AlkahestClient`` already bound to the
    target chain via its ``rpc_url`` and ``address_config``. The call
    targets the non-tierable ERC-20 escrow obligation contract — that's
    the only obligation type the seller's verifier currently accepts.

    For other obligation types, callers should reach into
    ``client.<asset>.escrow.<variant>.get_obligation`` directly rather
    than going through this wrapper.
    """
    decoded = await client.erc20.escrow.non_tierable.get_obligation(uid)
    att = decoded["attestation"]
    data = decoded["data"]

    return EscrowAttestation(
        uid=att.uid,
        schema=att.schema,
        attester=att.attester,
        recipient=att.recipient,
        time=int(att.time),
        expiration_time=int(att.expiration_time),
        revocation_time=int(att.revocation_time),
        ref_uid=att.ref_uid,
        revocable=bool(att.revocable),
        raw_data=bytes(att.data),
        arbiter=data.arbiter,
        demand=bytes(data.demand) if data.demand is not None else None,
        token=data.token,
        amount=int(data.amount) if data.amount is not None else None,
        decode_error=None,
    )


def read_attestation_sync(client: Any, uid: str) -> EscrowAttestation:
    """Sync wrapper around :func:`read_attestation` for typer CLI sites
    that aren't running inside an event loop. Don't call from async code."""
    return asyncio.run(read_attestation(client, uid))


def resolve_eas_address(
    chain_name: str,
    *,
    config_path: Optional[str] = None,
) -> str:
    """Resolve the EAS contract address from the alkahest address config.

    Override JSON wins; otherwise pull from the SDK's
    ``DefaultExtensionConfig.for_chain`` (alkahest-py >= 0.3.0).

    Kept here as a static lookup for CLI commands that print the address
    or need to override it explicitly. The actual EAS address is also
    embedded inside the ``AlkahestClient`` via ``address_config``, so
    runtime callers that already have a client can read it from there
    instead of going through this function.
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
