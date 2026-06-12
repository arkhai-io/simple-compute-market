"""Compatibility shim — settle-time escrow verification moved to
``core_storefront.escrow_verification`` when the API-tokens domain
became the second storefront composition root."""

from core_storefront.escrow_verification import (  # noqa: F401
    EscrowVerificationError,
    _extract_token_contract_from_listing,
    _normalize_address,
    _normalize_bytes,
    _normalize_obligation_data,
    _plain_attestation_request,
    _read_chain_obligation_data,
    verify_escrow_for_settlement,
)
