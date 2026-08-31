"""Ed25519 signer and offline verifier."""

from __future__ import annotations

import base64
import binascii
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from market_identity.models import Identity, IdentityScheme
from market_identity.registry import SecretMaterial, register_identity_scheme

_BASE64URL = re.compile(r"^[A-Za-z0-9_-]{43}$")


class Ed25519Signer:
    """Local Ed25519 signer whose seed is retained only by this implementation."""

    __slots__ = ("_identity", "_private_key")

    def __init__(self, private_key: SecretMaterial) -> None:
        raw = _private_key_bytes(private_key)
        self._private_key = Ed25519PrivateKey.from_private_bytes(raw)
        public_key = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self._identity = Identity(
            scheme=IdentityScheme.ED25519,
            identifier=_encode_base64url(public_key),
        )

    @property
    def identity(self) -> Identity:
        return self._identity

    def sign(self, message: bytes) -> bytes:
        if not isinstance(message, bytes):
            raise TypeError("message must be bytes")
        return self._private_key.sign(message)

    def __repr__(self) -> str:
        return f"Ed25519Signer(identity={self._identity!r})"

    def __reduce_ex__(self, _protocol: int) -> object:
        raise TypeError("identity signers cannot be serialized")


class Ed25519Verifier:
    """Offline Ed25519 verifier."""

    name = IdentityScheme.ED25519

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
            or len(proof) != 64
        ):
            return False
        try:
            public_key = Ed25519PublicKey.from_public_bytes(
                _decode_base64url(identity.identifier)
            )
            public_key.verify(proof, message)
        except (InvalidSignature, ValueError):
            return False
        return True


class Ed25519SignerFactory:
    """Factory for Ed25519 signers."""

    name = IdentityScheme.ED25519

    def create(self, secret: SecretMaterial) -> Ed25519Signer:
        return Ed25519Signer(secret)



def _private_key_bytes(private_key: SecretMaterial) -> bytes:
    if isinstance(private_key, bytes):
        if len(private_key) == 32:
            return private_key
        try:
            encoded = private_key.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError(
                "ed25519 private key must be raw bytes or canonical base64url bytes"
            ) from exc
    elif isinstance(private_key, str):
        encoded = private_key
    else:
        raise TypeError("ed25519 private key must be bytes or base64url text")
    if not _BASE64URL.fullmatch(encoded):
        raise ValueError("ed25519 private key must be canonical unpadded base64url")
    raw = _decode_base64url(encoded)
    if encoded != _encode_base64url(raw):
        raise ValueError("ed25519 private key must be canonical unpadded base64url")
    if len(raw) != 32:
        raise ValueError("ed25519 private key must contain exactly 32 bytes")
    return raw



def _decode_base64url(value: str) -> bytes:
    try:
        return base64.b64decode(
            value + "=" * (-len(value) % 4),
            altchars=b"-_",
            validate=True,
        )
    except (binascii.Error, ValueError) as exc:
        raise ValueError("value is not valid base64url") from exc



def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


register_identity_scheme(Ed25519Verifier(), Ed25519SignerFactory())
