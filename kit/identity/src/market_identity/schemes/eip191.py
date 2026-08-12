"""EIP-191 personal-sign signer and offline verifier."""

from __future__ import annotations

import re

from eth_account import Account
from eth_account.messages import encode_defunct

from market_identity.models import Identity, IdentityScheme
from market_identity.registry import SecretMaterial, register_identity_scheme

_PRIVATE_KEY = re.compile(r"^(?:0x)?[0-9a-fA-F]{64}$")


class Eip191Signer:
    """Local EIP-191 signer whose secret is retained only by this implementation."""

    __slots__ = ("_account", "_identity")

    def __init__(self, private_key: SecretMaterial) -> None:
        key = _private_key_bytes(private_key)
        self._account = Account.from_key(key)
        self._identity = Identity(
            scheme=IdentityScheme.EIP191,
            identifier=self._account.address,
        )

    @property
    def identity(self) -> Identity:
        return self._identity

    def sign(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise TypeError("message must be bytes")
        return bytes(
            self._account.sign_message(encode_defunct(primitive=message)).signature
        )

    def __repr__(self) -> str:
        return f"Eip191Signer(identity={self._identity!r})"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("identity signers cannot be serialized")


class Eip191Verifier:
    """Offline EIP-191 personal-sign verifier."""

    name = IdentityScheme.EIP191

    def verify_signature(
        self,
        identity: Identity,
        message: bytes,
        proof: bytes,
    ) -> bool:
        if (
            identity.scheme != self.name
            or not isinstance(message, bytes)
            or not isinstance(proof, bytes)
            or len(proof) != 65
        ):
            return False
        try:
            recovered = Account.recover_message(
                encode_defunct(primitive=message),
                signature=proof,
            )
        except Exception:
            return False
        return recovered.lower() == identity.identifier


class Eip191SignerFactory:
    """Factory for EIP-191 signers."""

    name = IdentityScheme.EIP191

    def create(self, secret: SecretMaterial) -> Eip191Signer:
        return Eip191Signer(secret)



def _private_key_bytes(private_key: SecretMaterial) -> bytes:
    if isinstance(private_key, bytes):
        if len(private_key) != 32:
            raise ValueError("eip191 private key must contain exactly 32 bytes")
        return private_key
    if not isinstance(private_key, str) or not _PRIVATE_KEY.fullmatch(private_key):
        raise ValueError("eip191 private key must be 32-byte hexadecimal text")
    value = private_key[2:] if private_key.startswith("0x") else private_key
    return bytes.fromhex(value)


register_identity_scheme(Eip191Verifier(), Eip191SignerFactory())
