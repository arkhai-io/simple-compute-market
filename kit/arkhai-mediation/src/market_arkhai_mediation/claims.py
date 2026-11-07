"""Published delivery-end claim framing and marketplace signature operations."""

from jsonschema.exceptions import ValidationError as SchemaValidationError
from market_identity import (
    Identity, SignatureProof, Signer, frame_fields, get_identity_verifier,
)

from .contract import validate, wire
from .models import DeliveryEndClaim, SignedDeliveryEndClaim


def claim_message(*, agreement: str, claim: DeliveryEndClaim, signer: Identity) -> bytes:
    validate("Sha256Hex", agreement)
    value = wire(claim)
    validate("DeliveryEndClaim", value)
    identity = signer.model_dump(mode="json")
    validate("MarketIdentity", identity)
    return frame_fields((
        "arkhai.mediation.delivery-end-claim.v1", agreement,
        identity["scheme"], identity["identifier"], str(value["ended_at"]),
        "true" if value["delivered"] else "false", value["cause"],
    ))


def sign_claim(*, agreement: str, claim: DeliveryEndClaim, signer: Signer) -> SignedDeliveryEndClaim:
    message = claim_message(agreement=agreement, claim=claim, signer=signer.identity)
    proof = SignatureProof.from_bytes(signer.identity.scheme, signer.sign(message))
    value = {
        "agreement": agreement, "claim": wire(claim),
        "signer": signer.identity.model_dump(mode="json"), "proof": proof.model_dump(mode="json"),
    }
    validate("SignedDeliveryEndClaim", value)
    return SignedDeliveryEndClaim.model_validate(value)


def verify_claim(
    signed: SignedDeliveryEndClaim, *, agreement: str, seller: Identity,
    claim: DeliveryEndClaim | None = None,
) -> bool:
    """Check proof plus Agreement, seller and optional exact case-claim binding."""
    value = wire(signed)
    try:
        validate("SignedDeliveryEndClaim", value)
        identity = Identity.model_validate(value["signer"])
        proof = SignatureProof.model_validate(value["proof"])
        return (
            value["agreement"] == agreement
            and identity == seller
            and (claim is None or value["claim"] == wire(claim))
            and proof.scheme == identity.scheme
            and get_identity_verifier(identity.scheme).verify_signature(
                identity,
                claim_message(
                    agreement=value["agreement"],
                    claim=DeliveryEndClaim.model_validate(value["claim"]), signer=identity,
                ),
                proof.to_bytes(),
            )
        )
    except (ValueError, TypeError, SchemaValidationError):
        return False
