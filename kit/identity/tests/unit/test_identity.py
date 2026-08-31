from __future__ import annotations

import base64

import pytest
from pydantic import ValidationError

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    Identity,
    IdentityScheme,
    IdentityVerifier,
    SignatureProof,
    Signer,
    SignerFactory,
    TrustedIdentitySet,
    create_signer,
    get_identity_verifier,
    get_signer_factory,
    list_identity_schemes,
    list_signer_schemes,
    register_identity_scheme,
    register_signer_factory,
)
from conftest import ED25519_SEED, EIP191_KEY


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def test_eip191_identity_is_canonical_and_frozen() -> None:
    identity = Identity(
        scheme="eip191",
        identifier="0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    )
    assert identity.identifier == "0x3c44cdddb6a900fa2b585dd299e03d12fa4293bc"
    assert hash(identity)
    with pytest.raises(ValidationError):
        identity.identifier = "0x0000000000000000000000000000000000000000"


@pytest.mark.parametrize(
    "identifier",
    (
        "0x" + "0" * 39,
        "0x" + "0" * 41,
        "0X" + "0" * 40,
        "0x" + "g" * 40,
        "not-an-address",
    ),
)
def test_eip191_identifier_rejects_malformed_values(identifier: str) -> None:
    with pytest.raises(ValidationError):
        Identity(scheme="eip191", identifier=identifier)


def test_ed25519_identity_requires_exact_canonical_public_key() -> None:
    identifier = _b64(bytes(range(32)))
    assert Identity(scheme="ed25519", identifier=identifier).identifier == identifier
    for malformed in (
        _b64(bytes(range(31))),
        _b64(bytes(range(33))),
        identifier + "=",
        identifier[:-1] + "+",
    ):
        with pytest.raises(ValidationError):
            Identity(scheme="ed25519", identifier=malformed)


@pytest.mark.parametrize("scheme", ("unknown", "EIP191", "", 7, None))
def test_identity_rejects_unknown_or_non_string_scheme(scheme: object) -> None:
    with pytest.raises(ValidationError):
        Identity(scheme=scheme, identifier="x")


def test_identity_rejects_extra_fields_and_non_string_identifier() -> None:
    with pytest.raises(ValidationError):
        Identity(
            scheme="eip191",
            identifier="0x" + "0" * 40,
            private_key="must-never-be-a-model-field",
        )
    with pytest.raises(ValidationError):
        Identity(scheme="ed25519", identifier=b"x" * 32)


def test_trusted_identity_set_is_ordered_exact_and_frozen(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    trusted = TrustedIdentitySet(
        identities=(ed25519_signer.identity, eip191_signer.identity)
    )
    assert trusted.identities == (ed25519_signer.identity, eip191_signer.identity)
    assert trusted.allows(ed25519_signer.identity)
    assert eip191_signer.identity in trusted
    assert Ed25519Signer(b"\x01" * 32).identity not in trusted
    colliding_text_other_scheme = Identity.model_construct(
        scheme=IdentityScheme.ED25519,
        identifier=eip191_signer.identity.identifier,
    )
    eip_only = TrustedIdentitySet(identities=(eip191_signer.identity,))
    assert colliding_text_other_scheme not in eip_only
    with pytest.raises(ValidationError):
        trusted.identities = (eip191_signer.identity,)


def test_trusted_identity_set_rejects_empty_duplicate_and_more_than_overlap(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    third = Ed25519Signer(b"\x01" * 32).identity
    with pytest.raises(ValidationError):
        TrustedIdentitySet(identities=())
    with pytest.raises(ValidationError, match="unique"):
        TrustedIdentitySet(
            identities=(ed25519_signer.identity, ed25519_signer.identity)
        )
    with pytest.raises(ValidationError):
        TrustedIdentitySet(
            identities=(ed25519_signer.identity, eip191_signer.identity, third)
        )


@pytest.mark.parametrize(
    ("scheme", "raw"),
    ((IdentityScheme.ED25519, b"s" * 64), (IdentityScheme.EIP191, b"s" * 65)),
)
def test_signature_proof_round_trip_is_scheme_specific(
    scheme: IdentityScheme,
    raw: bytes,
) -> None:
    proof = SignatureProof.from_bytes(scheme, raw)
    assert proof.scheme == scheme
    assert proof.to_bytes() == raw
    if scheme == IdentityScheme.EIP191:
        assert proof.value == "0x" + raw.hex()
    else:
        assert proof.value == _b64(raw)


@pytest.mark.parametrize(
    ("scheme", "value"),
    (
        ("eip191", "00" * 65),
        ("eip191", "0x" + "00" * 64),
        ("eip191", "0x" + "GG" * 65),
        ("eip191", "0x" + "AA" * 65),
        ("ed25519", _b64(b"x" * 63)),
        ("ed25519", _b64(b"x" * 65)),
        ("ed25519", _b64(b"x" * 64) + "="),
    ),
)
def test_signature_proof_rejects_malformed_encodings(scheme: str, value: str) -> None:
    with pytest.raises(ValidationError):
        SignatureProof(scheme=scheme, value=value)


def test_built_in_verifiers_and_factories_are_registered() -> None:
    assert list_identity_schemes() == ("ed25519", "eip191")
    assert list_signer_schemes() == ("ed25519", "eip191")
    for scheme in IdentityScheme:
        assert isinstance(get_identity_verifier(scheme), IdentityVerifier)
        assert isinstance(get_signer_factory(scheme), SignerFactory)

def test_registry_registration_is_idempotent_but_never_replaces() -> None:
    verifier = get_identity_verifier(IdentityScheme.ED25519)
    factory = get_signer_factory(IdentityScheme.ED25519)
    register_identity_scheme(verifier, factory)
    register_signer_factory(factory)

    class ShadowVerifier:
        name = IdentityScheme.ED25519

        def verify_signature(
            self,
            identity: Identity,
            message: bytes,
            proof: bytes,
        ) -> bool:
            return True

    class ShadowFactory:
        name = IdentityScheme.ED25519

        def create(self, secret: bytes | str) -> Signer:
            return Ed25519Signer(secret)

    with pytest.raises(ValueError, match="already registered"):
        register_identity_scheme(ShadowVerifier())
    with pytest.raises(ValueError, match="already registered"):
        register_signer_factory(ShadowFactory())


@pytest.mark.parametrize(
    ("scheme", "secret", "expected_type"),
    (
        ("ed25519", ED25519_SEED, Ed25519Signer),
        ("eip191", EIP191_KEY, Eip191Signer),
    ),
)
def test_create_signer_uses_explicit_scheme_dispatch(
    scheme: str,
    secret: bytes,
    expected_type: type,
) -> None:
    signer = create_signer(scheme, secret)
    assert isinstance(signer, expected_type)
    assert isinstance(signer, Signer)
    assert signer.identity.scheme.value == scheme


def test_registry_rejects_unknown_scheme() -> None:
    with pytest.raises(KeyError, match="unsupported identity scheme"):
        get_identity_verifier("unknown")
    with pytest.raises(KeyError, match="unsupported identity scheme"):
        create_signer("unknown", b"x" * 32)


def test_identifier_text_cannot_cross_scheme_boundary(eip191_signer: Eip191Signer) -> None:
    with pytest.raises(ValidationError):
        Identity(
            scheme=IdentityScheme.ED25519,
            identifier=eip191_signer.identity.identifier,
        )
    forged = Identity.model_construct(
        scheme=IdentityScheme.ED25519,
        identifier=eip191_signer.identity.identifier,
    )
    proof = eip191_signer.sign(b"same bytes")
    assert get_identity_verifier(IdentityScheme.ED25519).verify_signature(
        forged,
        b"same bytes",
        proof,
    ) is False
