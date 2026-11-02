"""Public deterministic contract fixtures; never use their keys in a deployment."""

from market_identity import Ed25519Signer, SignatureProof

from ..contract import validate, vectors
from ..models import SignedRecordEntry
from ..records import record_message


def record_signer() -> Ed25519Signer:
    """Use only the producer's public fixture seed, never operator credentials."""
    return Ed25519Signer(bytes.fromhex(vectors()["keys"]["mediation_seed_hex"]))


def sign_record(entry: dict) -> SignedRecordEntry:
    signer = record_signer()
    if entry["issuer"] != signer.identity.model_dump(mode="json"):
        raise ValueError("fixture issuer differs from the public vector key")
    proof = SignatureProof.from_bytes(signer.identity.scheme, signer.sign(record_message(entry)))
    value = {"entry": entry, "proof": proof.model_dump(mode="json")}
    validate("SignedRecordEntry", value)
    return SignedRecordEntry.model_validate(value)
