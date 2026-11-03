"""A relay's grant key: its profile form, its id, and its public half.

Level 1, per `docs/development/TESTING.md`: pure functions over bytes, with no
collaborator. The three forms are the ones the relay's admission plugin reads,
so each is pinned against a published value rather than against this module's
own output.

The fixed key is the secret key of RFC 8032's first Ed25519 test vector
("TEST 1"), a published value known to everyone: an example only, which must
never sign anything on a network. RFC 8037's examples publish its JWK
thumbprint.
"""

from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from compute_provisioning.relays import GrantKey, GrantKeyError, public_key_text, thumbprint

_RFC8032_TEST1_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
_RFC8037_THUMBPRINT = "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k"
_RFC8037_X = "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo"
# The PKCS#8 DER prefix of an Ed25519 private key, as RFC 8410 gives it: the
# version, the algorithm identifier 1.3.101.112, and the 32-byte octet string.
_ED25519_PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")


def _profile_form(der: bytes) -> str:
    return base64.b64encode(der).decode("ascii")


_RFC8032_PROFILE_FORM = _profile_form(_ED25519_PKCS8_PREFIX + _RFC8032_TEST1_SEED)


class TestTheProfileForm:
    def test_the_published_key_loads(self):
        key = GrantKey.from_profile_form(_RFC8032_PROFILE_FORM)
        assert key.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        ) == _RFC8032_TEST1_SEED

    def test_a_trailing_newline_is_stripped(self):
        key = GrantKey.from_profile_form(f"  {_RFC8032_PROFILE_FORM}\n")
        assert key.kid == _RFC8037_THUMBPRINT

    def test_a_key_round_trips_through_its_profile_form(self):
        key = GrantKey.generate()
        assert GrantKey.from_profile_form(key.profile_form()).kid == key.kid

    def test_the_profile_form_is_the_pkcs8_der_base64(self):
        key = GrantKey.from_profile_form(_RFC8032_PROFILE_FORM)
        assert key.profile_form() == _RFC8032_PROFILE_FORM

    @pytest.mark.parametrize(
        "value, problem",
        [
            ("not base64 at all!", "not single-line standard base64"),
            (
                _RFC8032_PROFILE_FORM[:20] + "\n" + _RFC8032_PROFILE_FORM[20:],
                "not single-line standard base64",
            ),
            (_profile_form(b"\x30\x03\x02\x01\x00"), "not the PKCS#8 DER"),
            (_profile_form(_RFC8032_TEST1_SEED), "not the PKCS#8 DER"),
        ],
        ids=["not-base64", "broken-line", "not-a-key", "raw-seed"],
    )
    def test_a_malformed_value_is_refused_without_the_value(self, value, problem):
        with pytest.raises(GrantKeyError) as refused:
            GrantKey.from_profile_form(value)
        assert problem in str(refused.value)
        assert value.strip() not in str(refused.value)
        assert refused.value.__cause__ is None
        assert refused.value.__suppress_context__ is True

    def test_a_key_of_another_algorithm_is_refused(self):
        der = generate_private_key(SECP256R1()).private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        value = _profile_form(der)
        with pytest.raises(GrantKeyError) as refused:
            GrantKey.from_profile_form(value)
        assert "not an Ed25519 key" in str(refused.value)
        assert value not in str(refused.value)
        assert refused.value.__cause__ is None

    def test_a_key_does_not_show_its_private_half(self):
        key = GrantKey.from_profile_form(_RFC8032_PROFILE_FORM)
        assert _RFC8032_PROFILE_FORM not in repr(key)
        assert "private_key" not in repr(key)


class TestTheKeyId:
    def test_the_published_key_has_the_published_thumbprint(self):
        public = Ed25519PrivateKey.from_private_bytes(_RFC8032_TEST1_SEED).public_key()
        assert thumbprint(public) == _RFC8037_THUMBPRINT

    def test_the_thumbprint_is_of_the_published_public_key(self):
        raw = base64.urlsafe_b64decode(_RFC8037_X + "=")
        assert thumbprint(Ed25519PublicKey.from_public_bytes(raw)) == _RFC8037_THUMBPRINT

    def test_a_grant_keys_id_is_its_thumbprint(self):
        key = GrantKey.from_profile_form(_RFC8032_PROFILE_FORM)
        assert key.kid == _RFC8037_THUMBPRINT


class TestThePublicHalf:
    def test_the_published_key_has_its_subject_public_key_info(self):
        """The form the admission plugin's configuration takes a public key in."""
        key = GrantKey.from_profile_form(_RFC8032_PROFILE_FORM)
        assert key.public_key == "MCowBQYDK2VwAyEA11qYAYKxCrfVS/7TyWQHOg7hcvPapiMlrwIaaPcHURo="

    def test_the_public_half_round_trips(self):
        key = GrantKey.generate()
        loaded = serialization.load_der_public_key(base64.b64decode(key.public_key))
        assert isinstance(loaded, Ed25519PublicKey)
        assert public_key_text(loaded) == key.public_key
        assert thumbprint(loaded) == key.kid
