"""Public deterministic contract fixtures; never use their keys in a deployment."""

from market_identity import Ed25519Signer, Eip191Signer, SignatureProof, Signer

from ..contract import validate, vectors
from ..models import SignedRecordEntry
from ..records import record_message


def record_signer() -> Ed25519Signer:
    """Use only the producer's public fixture seed, never operator credentials."""
    return Ed25519Signer(bytes.fromhex(vectors()["keys"]["mediation_seed_hex"]))


def market_signer(scheme: str) -> Signer:
    """Public vector keys only; never use either signer in a deployment."""
    if scheme == "ed25519":
        return record_signer()
    if scheme == "eip191":
        return Eip191Signer(bytes.fromhex(vectors()["keys"]["market_eip191_private_key_hex"]))
    raise ValueError("unknown vector signature scheme")


def sign_record(entry: dict) -> SignedRecordEntry:
    signer = record_signer()
    if entry["issuer"] != signer.identity.model_dump(mode="json"):
        raise ValueError("fixture issuer differs from the public vector key")
    proof = SignatureProof.from_bytes(signer.identity.scheme, signer.sign(record_message(entry)))
    value = {"entry": entry, "proof": proof.model_dump(mode="json")}
    validate("SignedRecordEntry", value)
    return SignedRecordEntry.model_validate(value)
