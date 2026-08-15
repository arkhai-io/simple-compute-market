from __future__ import annotations

import base64
import json
import pickle

import pytest

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    IdentityScheme,
    Signer,
    create_signer,
    get_identity_verifier,
    CredentialProviderKind,
    CredentialReference,
    EnvironmentCredentialProvider,
)
from conftest import ED25519_SEED, EIP191_KEY


@pytest.mark.parametrize("message", (b"", b"canonical bytes", b"\x00\xff\x80binary"))
def test_both_schemes_sign_and_verify_identical_bytes(
    signer: Signer,
    message: bytes,
) -> None:
    proof = signer.sign(message)
    verifier = get_identity_verifier(signer.identity.scheme)
    assert verifier.verify_signature(signer.identity, message, proof) is True
    assert verifier.verify_signature(signer.identity, message + b"!", proof) is False


def test_ed25519_signatures_are_deterministic(ed25519_signer: Ed25519Signer) -> None:
    message = b"arkhai deterministic fixture"
    assert ed25519_signer.sign(message) == ed25519_signer.sign(message)
    assert len(ed25519_signer.sign(message)) == 64


def test_eip191_signatures_have_exact_length(eip191_signer: Eip191Signer) -> None:
    assert len(eip191_signer.sign(b"market bytes")) == 65


def test_verifiers_reject_wrong_identity_and_malformed_lengths(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    message = b"one canonical message"
    ed_verifier = get_identity_verifier(IdentityScheme.ED25519)
    eip_verifier = get_identity_verifier(IdentityScheme.EIP191)
    assert ed_verifier.verify_signature(
        ed25519_signer.identity,
        message,
        ed25519_signer.sign(message)[:-1],
    ) is False
    assert eip_verifier.verify_signature(
        eip191_signer.identity,
        message,
        eip191_signer.sign(message) + b"\x00",
    ) is False
    assert ed_verifier.verify_signature(
        ed25519_signer.identity,
        message,
        eip191_signer.sign(message)[:64],
    ) is False
    assert eip_verifier.verify_signature(
        eip191_signer.identity,
        message,
        ed25519_signer.sign(message) + b"\x00",
    ) is False


def test_ed25519_factory_accepts_only_exact_canonical_seed() -> None:
    encoded = base64.urlsafe_b64encode(ED25519_SEED).rstrip(b"=").decode("ascii")
    assert create_signer("ed25519", encoded).identity == Ed25519Signer(
        ED25519_SEED
    ).identity
    for malformed in (
        ED25519_SEED[:-1],
        ED25519_SEED + b"x",
        encoded + "=",
        encoded[:-1] + "+",
    ):
        with pytest.raises((TypeError, ValueError)):
            create_signer("ed25519", malformed)


def test_eip191_factory_accepts_only_exact_key() -> None:
    encoded = "0x" + EIP191_KEY.hex()
    assert create_signer("eip191", encoded).identity == Eip191Signer(EIP191_KEY).identity
    for malformed in (
        EIP191_KEY[:-1],
        EIP191_KEY + b"x",
        encoded[:-2],
        "0x" + "gg" * 32,
    ):
        with pytest.raises((TypeError, ValueError)):
            create_signer("eip191", malformed)


@pytest.mark.parametrize(
    ("signer", "secret_text"),
    (
        (Ed25519Signer(ED25519_SEED), ED25519_SEED.hex()),
        (Eip191Signer(EIP191_KEY), EIP191_KEY.hex()),
    ),
)
def test_signer_secrets_are_not_representable_or_serializable(
    signer: Signer,
    secret_text: str,
) -> None:
    assert secret_text not in repr(signer).lower()
    assert "private" not in repr(signer).lower()
    with pytest.raises(TypeError):
        vars(signer)
    with pytest.raises(TypeError):
        json.dumps(signer)
    with pytest.raises(TypeError):
        pickle.dumps(signer)
    assert not hasattr(signer, "model_dump")
    assert signer.identity.model_dump() == {
        "scheme": signer.identity.scheme,
        "identifier": signer.identity.identifier,
    }


def test_provider_resolved_seed_derives_only_the_canonical_public_principal() -> None:
    encoded = base64.urlsafe_b64encode(ED25519_SEED).rstrip(b"=").decode("ascii")
    reference = CredentialReference(
        provider=CredentialProviderKind.ENVIRONMENT,
        locator="BUYER_SEED",
    )
    secret = EnvironmentCredentialProvider({"BUYER_SEED": encoded}).load(reference)
    signer = create_signer(IdentityScheme.ED25519, secret)
    assert signer.identity == Ed25519Signer(ED25519_SEED).identity
    assert encoded not in repr(reference)
    assert encoded not in repr(signer)
