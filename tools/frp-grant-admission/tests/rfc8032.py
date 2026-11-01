"""RFC 8032's Ed25519 test vector keys, the only keys the tests and the vector use.

These are published, deterministic test values: anyone can read their private keys.
They must never be used on any network.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@dataclass(frozen=True)
class Rfc8032Key:
    name: str
    seed_hex: str
    public_hex: str

    @property
    def private_key(self) -> Ed25519PrivateKey:
        return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(self.seed_hex))

    @property
    def spki_base64(self) -> str:
        """The public key as the configuration writes it: base64 of its DER SPKI."""
        der = self.private_key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return base64.b64encode(der).decode("ascii")


TEST_1 = Rfc8032Key(
    "RFC 8032 TEST 1",
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
)
TEST_2 = Rfc8032Key(
    "RFC 8032 TEST 2",
    "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
    "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
)
TEST_3 = Rfc8032Key(
    "RFC 8032 TEST 3",
    "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
    "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
)

# RFC 8037 Appendix A.3: the JWK thumbprint of TEST 1's public key.
TEST_1_THUMBPRINT = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
