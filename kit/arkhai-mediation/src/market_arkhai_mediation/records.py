"""Verify authority records using only the Agreement's pinned record key."""

import hashlib

from market_identity import (
    Identity, IdentityScheme, SignatureProof, canonical_json, frame_fields, get_identity_verifier,
)

from .contract import validate, wire
from .models import SignedRecordEntry


class RecordVerificationError(ValueError):
    pass


def record_message(entry: dict) -> bytes:
    validate("RecordEntry", entry)
    digest = hashlib.sha256(canonical_json(entry)).hexdigest()
    return frame_fields(("arkhai.mediation.record.v1", digest))


def verify_record(
    signed: SignedRecordEntry, *, record_key: str, agreement: str,
    transaction: str, sequence: int | None = None, case_ref: str | None = None,
) -> SignedRecordEntry:
    raw = wire(signed)
    validate("RecordKey", record_key)
    trusted = Identity(scheme=IdentityScheme.ED25519, identifier=record_key.removeprefix("ed25519:"))
    entry = raw["entry"]
    proof = SignatureProof.model_validate(raw["proof"])
    if (
        entry["issuer"] != trusted.model_dump(mode="json")
        or entry["agreement"] != agreement
        or entry["transaction"] != transaction
        or sequence is not None and entry["sequence"] != sequence
        or case_ref is not None and entry["case_ref"] != case_ref
        or not get_identity_verifier(trusted.scheme).verify_signature(
            trusted, record_message(entry), proof.to_bytes(),
        )
    ):
        raise RecordVerificationError("record signature or deal/sequence/case binding mismatch")
    if entry["kind"] == "filed":
        filing = entry["filing"]
        if (
            filing["transaction"] != transaction
            or hashlib.sha256(canonical_json(filing["agreement"])).hexdigest() != agreement
        ):
            raise RecordVerificationError("filed record carries another Agreement")
    return signed
