"""Transaction identities and service-signed approval receipt verification."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_identity import (
    Identity as MarketplaceIdentity,
    IdentityScheme,
    SignatureProof as MarketplaceSignatureProof,
    get_identity_verifier,
)
from market_identity.canonical import _frame
from pydantic import BaseModel, ValidationError

from market_arkhai_payments.canonical import agreement_hash, jcs_sha256
from market_arkhai_payments.models import Mandate, SignedReceipt

RECEIPT_PROTOCOL = "arkhai.payments.receipt.v1"


def transaction_id(mandate: Mandate | Mapping[str, Any]) -> str:
    """Return the service transaction identity: SHA-256(JCS(mandate))."""

    parsed = Mandate.model_validate(mandate)
    return jcs_sha256(parsed)


def verify_receipt_signature(
    signed_receipt: SignedReceipt | Mapping[str, Any],
    trusted_service_identity: MarketplaceIdentity | Mapping[str, Any] | BaseModel,
) -> bool:
    """Verify the payments receipt signature against a configured identity pin."""

    try:
        signed = SignedReceipt.model_validate(signed_receipt)
        trusted_value = (
            trusted_service_identity.model_dump(mode="json", by_alias=True)
            if isinstance(trusted_service_identity, BaseModel)
            else trusted_service_identity
        )
        trusted = MarketplaceIdentity.model_validate(trusted_value)
        if trusted.scheme != IdentityScheme.ED25519:
            return False
        issuer = signed.receipt.issuer
        if issuer.scheme != trusted.scheme.value or issuer.identifier != trusted.identifier:
            return False
        receipt_json = signed.receipt.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        digest = jcs_sha256(receipt_json)
        message = _frame((RECEIPT_PROTOCOL, digest))
        proof = MarketplaceSignatureProof.model_validate(
            signed.proof.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        verifier = get_identity_verifier(trusted.scheme)
        return verifier.verify_signature(trusted, message, proof.to_bytes())
    except (KeyError, TypeError, ValueError, ValidationError):
        return False


def verify_receipt(
    signed_receipt: SignedReceipt | Mapping[str, Any],
    trusted_service_identity: MarketplaceIdentity | Mapping[str, Any] | BaseModel,
    *,
    mandate: Mandate | Mapping[str, Any],
    agreement_json: Mapping[str, Any],
) -> bool:
    """Verify a receipt and bind it to the exact Agreement and mandate."""

    try:
        signed = SignedReceipt.model_validate(signed_receipt)
        expected_mandate = Mandate.model_validate(mandate)
        expected_transaction = transaction_id(expected_mandate)
        expected_deal = agreement_hash(agreement_json)
    except (TypeError, ValueError, ValidationError):
        return False

    receipt = signed.receipt
    mandate_values = expected_mandate.model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    return (
        verify_receipt_signature(signed, trusted_service_identity)
        and receipt.transaction.root == expected_transaction
        and receipt.deal.root.root == expected_deal
        and receipt.deal.root.root == mandate_values["deal"]
        and receipt.from_.root == mandate_values["from"]
        and receipt.to.root == mandate_values["to"]
    )
