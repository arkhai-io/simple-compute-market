"""Compatibility shim — settle-time escrow verification is owned by the
Alkahest mechanism kit (``market_alkahest.escrow_verification``) and
reached through its registration's ``settlement_verifier`` hook."""

from market_alkahest.escrow_verification import (  # noqa: F401
    EscrowVerificationError,
    _extract_token_contract_from_listing,
    _normalize_address,
    _normalize_bytes,
    _normalize_obligation_data,
    _plain_attestation_request,
    _read_chain_obligation_data,
    verify_escrow_for_settlement,
)
