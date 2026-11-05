"""A relay's grant-signing keys: their profile form, their ids, and their public halves.

Each relay holds its own Ed25519 grant-signing key, and the relay's admission
plugin is configured with its public halves. Three forms cross a boundary, and
each is the one the other side reads:

* The **profile form** of a private key is the single-line standard base64 of
  its PKCS#8 DER, which ``openssl genpkey -algorithm ed25519 -outform DER |
  base64 -w0`` prints. It is how an operator supplies a key, in the secrets
  profile or in a staging request, and how the service stores one, encrypted.
* A key's **id** is its RFC 7638 JWK thumbprint. The plugin derives the same id
  from each public key it is configured with and knows no other, so the id
  carries no prefix and no counter.
* A **public half** is the single-line standard base64 of its DER
  SubjectPublicKeyInfo, the form the plugin's configuration takes, so an
  operator pastes it unchanged.

A refusal never carries the value it refuses: the value is a private key.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


class GrantKeyError(ValueError):
    """A supplied grant key is not a key in the profile's form.

    The message says what is wrong and never includes the value.
    """


def _unpadded_base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def thumbprint(public_key: Ed25519PublicKey) -> str:
    """The key's RFC 7638 JWK thumbprint, the id the admission plugin derives.

    The base64url SHA-256 of the JWK's required members in lexicographic
    order, with no whitespace: ``{"crv":"Ed25519","kty":"OKP","x":"<raw public
    key, base64url>"}``.
    """
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )
    members = {"crv": "Ed25519", "kty": "OKP", "x": _unpadded_base64url(raw)}
    canonical = json.dumps(members, sort_keys=True, separators=(",", ":"))
    return _unpadded_base64url(hashlib.sha256(canonical.encode("ascii")).digest())


def public_key_text(public_key: Ed25519PublicKey) -> str:
    """The public half as the plugin's configuration takes it."""
    der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return base64.b64encode(der).decode("ascii")


@dataclass(frozen=True)
class GrantKey:
    """One Ed25519 grant-signing key, with the id and public half derived from it."""

    private_key: Ed25519PrivateKey = field(repr=False)

    @classmethod
    def generate(cls) -> "GrantKey":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_profile_form(cls, value: str) -> "GrantKey":
        """Load a key from the profile's form, refusing anything else.

        Surrounding whitespace is stripped first, since secret stores commonly
        add a trailing newline; whitespace inside the value is not base64 and is
        refused.
        """
        if not isinstance(value, str):
            raise GrantKeyError("the grant key is not a string")
        try:
            der = base64.b64decode(value.strip(), validate=True)
        except (binascii.Error, ValueError):
            raise GrantKeyError(
                "the grant key is not single-line standard base64"
            ) from None
        try:
            loaded = serialization.load_der_private_key(der, password=None)
        except Exception:
            # Whatever the parser raises is replaced, not chained: its message
            # or its arguments may carry the bytes it was given.
            raise GrantKeyError(
                "the grant key is not the PKCS#8 DER of a private key"
            ) from None
        if not isinstance(loaded, Ed25519PrivateKey):
            raise GrantKeyError("the grant key is not an Ed25519 key")
        return cls(loaded)

    def profile_form(self) -> str:
        """The private key in the profile's form, which is how it is stored."""
        der = self.private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return base64.b64encode(der).decode("ascii")

    @property
    def kid(self) -> str:
        return thumbprint(self.private_key.public_key())

    @property
    def public_key(self) -> str:
        return public_key_text(self.private_key.public_key())


__all__ = ["GrantKey", "GrantKeyError", "public_key_text", "thumbprint"]
