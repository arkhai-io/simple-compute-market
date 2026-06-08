from __future__ import annotations

import pytest

from market_identity import (
    Identity,
    IdentityVerifier,
    get_identity_verifier,
    list_identity_schemes,
    register_identity_scheme,
)
from market_identity.registry import _VERIFIERS

PRIVATE_KEY = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"
OWNER_ADDRESS = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"


def test_identity_lowercases_eip191_identifier():
    ident = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert ident.identifier == OWNER_ADDRESS.lower()


def test_identity_preserves_non_eip191_identifier_case():
    ident = Identity(scheme="did-key", identifier="did:key:zMixedCASE")
    assert ident.identifier == "did:key:zMixedCASE"


def test_default_scheme_is_registered_on_import():
    assert "eip191" in list_identity_schemes()


def test_get_identity_verifier_returns_eip191():
    verifier = get_identity_verifier("eip191")
    assert verifier.name == "eip191"


def test_get_identity_verifier_unknown_scheme_raises():
    with pytest.raises(KeyError):
        get_identity_verifier("definitely-not-a-real-scheme")


def test_register_identity_scheme_idempotent_for_same_object():
    verifier = get_identity_verifier("eip191")
    register_identity_scheme(verifier)


def test_register_identity_scheme_rejects_different_verifier_under_existing_name():
    class _Shadow:
        name = "eip191"

        def verify_signature(self, identity, message, proof):  # noqa: ARG002
            return True

    with pytest.raises(ValueError, match="already registered"):
        register_identity_scheme(_Shadow())


def test_register_and_unregister_custom_scheme():
    class _Toy:
        name = "_test_toy_scheme"

        def verify_signature(self, identity, message, proof):  # noqa: ARG002
            return identity.identifier == "ok"

    toy = _Toy()
    register_identity_scheme(toy)
    try:
        assert "_test_toy_scheme" in list_identity_schemes()
        v = get_identity_verifier("_test_toy_scheme")
        assert v.verify_signature(Identity(scheme="_test_toy_scheme", identifier="ok"), b"", b"")
        assert isinstance(v, IdentityVerifier)
    finally:
        _VERIFIERS.pop("_test_toy_scheme", None)


def _sign(message: str) -> bytes:
    pytest.importorskip("eth_account")
    from eth_account import Account
    from eth_account.messages import encode_defunct

    signed = Account.sign_message(encode_defunct(text=message), PRIVATE_KEY)
    return bytes(signed.signature)


def test_eip191_verify_signature_valid():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert verifier.verify_signature(ident, b"hello", _sign("hello")) is True


def test_eip191_verify_signature_wrong_address():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(
        scheme="eip191",
        identifier="0x000000000000000000000000000000000000dead",
    )
    assert verifier.verify_signature(ident, b"hello", _sign("hello")) is False


def test_eip191_verify_signature_wrong_message():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert verifier.verify_signature(ident, b"wrong message", _sign("hello")) is False


def test_eip191_verify_signature_rejects_non_matching_scheme():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(scheme="did-key", identifier=OWNER_ADDRESS)
    assert verifier.verify_signature(ident, b"hello", _sign("hello")) is False


def test_eip191_verify_signature_malformed_proof_returns_false():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert verifier.verify_signature(ident, b"hello", b"\x00" * 65) is False


def test_eip191_verify_signature_non_utf8_message_returns_false():
    pytest.importorskip("eth_account")
    verifier = get_identity_verifier("eip191")
    ident = Identity(scheme="eip191", identifier=OWNER_ADDRESS)
    assert verifier.verify_signature(ident, b"\xff\xfe\xfd", _sign("hello")) is False
