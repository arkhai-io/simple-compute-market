"""Transaction identities and service-signed approval receipt verification."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from market_identity import (
    Identity as MarketplaceIdentity,
)
from market_identity import (
    IdentityScheme,
    frame_fields,
    get_identity_verifier,
)
from market_identity import (
    SignatureProof as MarketplaceSignatureProof,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from market_arkhai_payments.canonical import agreement_hash, jcs_sha256, wire_json
from market_arkhai_payments.models import Mandate, SignedReceipt, SignedTransactionSnapshot

RECEIPT_PROTOCOL = "arkhai.payments.receipt.v1"
SNAPSHOT_PROTOCOL = "arkhai.payments.snapshot.v1"
SnapshotVerifier = Callable[[SignedTransactionSnapshot, int], bool]


class ReceiptIdentity(BaseModel):
    """A current or retiring receipt key, valid on a half-open Unix interval.

    A current key may attest the exact embedded receipt of a fresh snapshot;
    retiring keys may verify historical receipts but cannot re-anchor them.
    """
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    identity: MarketplaceIdentity
    valid_from: int = Field(default=0, ge=0)
    valid_until: int | None = Field(default=None, ge=0)
    retiring: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> ReceiptIdentity:
        if self.identity.scheme != IdentityScheme.ED25519:
            raise ValueError("receipt identities must be Ed25519")
        if self.retiring and self.valid_until is None:
            raise ValueError("retiring receipt identities require valid_until")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValueError("identity validity window is empty")
        return self

    def valid_at(self, instant: int) -> bool:
        return self.valid_from <= instant and (self.valid_until is None or instant < self.valid_until)


def snapshot_message(snapshot: Mapping[str, Any] | BaseModel) -> bytes:
    """Return the publisher's exact snapshot signature frame."""
    body = (snapshot.model_dump(mode="json", by_alias=True, exclude_unset=True)
            if isinstance(snapshot, BaseModel) else dict(snapshot))
    return frame_fields((SNAPSHOT_PROTOCOL, jcs_sha256(body)))


def _snapshot_signature(signed: SignedTransactionSnapshot, pin: ReceiptIdentity) -> bool:
    issuer = signed.snapshot.issuer
    trusted = pin.identity
    if issuer.scheme != trusted.scheme.value or issuer.identifier != trusted.identifier:
        return False
    proof = MarketplaceSignatureProof.model_validate(
        signed.proof.model_dump(mode="json", by_alias=True, exclude_none=True)
    )
    return get_identity_verifier(trusted.scheme).verify_signature(
        trusted, snapshot_message(signed.snapshot), proof.to_bytes(),
    )


def verify_snapshot(
    signed_snapshot: SignedTransactionSnapshot | Mapping[str, Any],
    trusted_service_identities: MarketplaceIdentity | Sequence[ReceiptIdentity],
    *, mandate: Mandate | Mapping[str, Any], agreement_json: Mapping[str, Any],
    livemode: bool, minimum_sequence: int = 0,
) -> bool:
    """Verify authority state before use, binding deal, mode and cursor.

    Attestation binds the embedded receipt as signed, including its original
    proof. It never rewrites or replaces the receipt with a current-key one.
    The caller owns freshness by supplying its durable minimum sequence.
    """
    try:
        if type(minimum_sequence) is not int or minimum_sequence < 0:
            return False
        signed = (
            SignedTransactionSnapshot.model_validate_json(json.dumps(dict(signed_snapshot)), strict=True)
            if isinstance(signed_snapshot, Mapping)
            else SignedTransactionSnapshot.model_validate(signed_snapshot)
        )
        expected = Mandate.model_validate(mandate)
        pins = ((ReceiptIdentity(identity=trusted_service_identities),)
                if isinstance(trusted_service_identities, MarketplaceIdentity)
                else tuple(trusted_service_identities))
        snapshot = signed.snapshot
        pin = next((item for item in pins if item.valid_at(snapshot.observedAt)
                    and _snapshot_signature(signed, item)), None)
        if pin is None:
            return False
        receipt = snapshot.receipt.receipt
        sequence = snapshot.latestEventSequence or 0
        if (snapshot.livemode is not livemode or receipt.livemode is not livemode
                or snapshot.transaction.root != transaction_id(expected)
                or receipt.transaction != snapshot.transaction
                or receipt.deal.root.root != agreement_hash(agreement_json)
                or receipt.deal != expected.deal
                or receipt.from_ != expected.from_ or receipt.to != expected.to
                or snapshot.observedAt < receipt.approvedAt
                or sequence < minimum_sequence):
            return False
        receipt_verified = any(
            item.valid_at(receipt.approvedAt)
            and verify_receipt_signature(snapshot.receipt, item.identity) for item in pins
        )
        historical_issuer = any(
            item.retiring and item.valid_at(receipt.approvedAt)
            and receipt.issuer.scheme == item.identity.scheme.value
            and receipt.issuer.identifier == item.identity.identifier for item in pins
        )
        return receipt_verified or (not pin.retiring and historical_issuer)
    except (KeyError, TypeError, ValueError, ValidationError):
        return False


def transaction_id(mandate: Mandate | Mapping[str, Any]) -> str:
    """Return the service transaction identity: SHA-256(JCS(mandate))."""

    parsed = Mandate.model_validate(mandate)
    return jcs_sha256(parsed)


def receipt_message(receipt: Mapping[str, Any] | BaseModel) -> bytes:
    """Return the exact bytes the payments service signs for one receipt."""

    receipt_json = (
        wire_json(receipt)
        if isinstance(receipt, BaseModel)
        else dict(receipt)
    )
    return frame_fields((RECEIPT_PROTOCOL, jcs_sha256(receipt_json)))


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
        message = receipt_message(signed.receipt)
        proof = MarketplaceSignatureProof.model_validate(
            wire_json(signed.proof)
        )
        verifier = get_identity_verifier(trusted.scheme)
        return verifier.verify_signature(trusted, message, proof.to_bytes())
    except (KeyError, TypeError, ValueError, ValidationError):
        return False


def verify_receipt(
    signed_receipt: SignedReceipt | Mapping[str, Any],
    trusted_service_identity: MarketplaceIdentity | Mapping[str, Any] | BaseModel | Sequence[ReceiptIdentity],
    *,
    mandate: Mandate | Mapping[str, Any],
    agreement_json: Mapping[str, Any],
    livemode: bool,
) -> bool:
    """Verify a receipt and bind it to the exact Agreement, mandate and mode.

    `livemode` is the mode the caller expects: a test-mode receipt never proves
    a live payment, and a live receipt never satisfies a test deployment.
    """

    try:
        signed = SignedReceipt.model_validate(signed_receipt)
        expected_mandate = Mandate.model_validate(mandate)
        expected_transaction = transaction_id(expected_mandate)
        expected_deal = agreement_hash(agreement_json)
    except (TypeError, ValueError, ValidationError):
        return False

    receipt = signed.receipt
    mandate_values = wire_json(expected_mandate)
    identities = trusted_service_identity
    if isinstance(identities, (Mapping, BaseModel)):
        signature_valid = verify_receipt_signature(signed, identities)
    else:
        signature_valid = any(
            pin.valid_at(receipt.approvedAt) and verify_receipt_signature(signed, pin.identity)
            for pin in identities
        )
    return (
        signature_valid
        and receipt.livemode is livemode
        and receipt.transaction.root == expected_transaction
        and wire_json(receipt.deal) == expected_deal
        and wire_json(receipt.deal) == mandate_values["deal"]
        and receipt.from_.root == mandate_values["from"]
        and receipt.to.root == mandate_values["to"]
    )
