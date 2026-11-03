"""A relay grant: its header, its claims and their types, and its signature.

Level 1, per `docs/development/TESTING.md`: the builder and signer over a lease
value, with no database. The admission plugin refuses a grant whose header or
claims differ from its specification, so each is pinned here, and a verifier
written to that specification in this file checks what the signer produces:
the signature, the type, the key id, an integer expiry, string subject and
identifier, and no issue time or critical header.
"""

from __future__ import annotations

import base64
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization

from compute_provisioning.relays import (
    GRANT_TYPE,
    GrantKey,
    RelayPortLease,
    check_relay_usable,
    epoch_seconds,
    grant_expiry,
    sign_grant,
)
from market_fulfillment import ProviderConfigInvalidError


def _lease(**overrides) -> RelayPortLease:
    fields = {
        "id": "lease-1",
        "relay_id": "relay-bm",
        "remote_port": 6203,
        "host_id": "example-bm-1",
        "owner_kind": "fulfillment",
        "owner_id": "res-3f0a9c2e",
        "grant_expires_at": datetime(2027, 1, 1, 17, 0, 0),
    }
    fields.update(overrides)
    return RelayPortLease(**fields)


def _decoded(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _verify(token: str, key: GrantKey) -> dict:
    """The plugin's checks as its specification states them, or ValueError."""
    header_part, claims_part, signature_part = token.split(".")
    public = serialization.load_der_public_key(base64.b64decode(key.public_key))
    try:
        public.verify(_decoded(signature_part), f"{header_part}.{claims_part}".encode())
    except InvalidSignature:
        raise ValueError("bad signature") from None
    header = json.loads(_decoded(header_part))
    claims = json.loads(_decoded(claims_part))
    if header.get("typ") != GRANT_TYPE or header.get("alg") != "EdDSA":
        raise ValueError("wrong type or algorithm")
    if "crit" in header or header.get("kid") != key.kid:
        raise ValueError("bad header")
    if type(claims.get("exp")) is not int:
        raise ValueError("exp is not an integer")
    for name in ("sub", "jti"):
        if name in claims and not isinstance(claims[name], str):
            raise ValueError(f"{name} is not a string")
    if "iat" in claims or "nbf" in claims:
        raise ValueError("issue or not-before time present")
    return claims


class TestTheGrant:
    def test_the_header_has_exactly_three_members(self):
        key = GrantKey.generate()
        header = json.loads(_decoded(sign_grant(_lease(), key).split(".")[0]))
        assert header == {"alg": "EdDSA", "kid": key.kid, "typ": "frp-grant+jwt"}

    def test_the_claims_of_a_lease_with_a_host(self):
        key = GrantKey.generate()
        claims = _verify(sign_grant(_lease(), key), key)
        assert claims == {
            "aud": "relay-bm",
            "exp": 1798822800,
            "jti": "res-3f0a9c2e",
            "port": 6203,
            "sub": "example-bm-1",
        }

    def test_a_lease_with_no_host_has_no_subject(self):
        key = GrantKey.generate()
        claims = _verify(sign_grant(_lease(host_id=None), key), key)
        assert "sub" not in claims
        assert claims["jti"] == "res-3f0a9c2e"

    def test_header_and_claims_are_canonical_json(self):
        """Keys sorted, no whitespace: the serialization the specification's
        vector is produced with."""
        token = sign_grant(_lease(), GrantKey.generate())
        header, claims, _ = token.split(".")
        assert _decoded(claims) == (
            b'{"aud":"relay-bm","exp":1798822800,"jti":"res-3f0a9c2e",'
            b'"port":6203,"sub":"example-bm-1"}'
        )
        assert _decoded(header).startswith(b'{"alg":"EdDSA","kid":"')

    def test_the_expiry_is_utc_whatever_the_process_time_zone(self, monkeypatch):
        """A naive ``timestamp()`` would read the stored time as local."""
        monkeypatch.setenv("TZ", "America/New_York")
        time.tzset()
        try:
            stored = datetime(2027, 1, 1, 17, 0, 0)
            assert epoch_seconds(stored) == 1798822800
            assert stored.timestamp() != 1798822800
            key = GrantKey.generate()
            assert _verify(sign_grant(_lease(grant_expires_at=stored), key), key)["exp"] == (
                1798822800
            )
        finally:
            monkeypatch.undo()
            time.tzset()

    def test_a_tampered_grant_is_refused(self):
        key = GrantKey.generate()
        header, claims, signature = sign_grant(_lease(), key).split(".")
        forged = json.loads(_decoded(claims)) | {"port": 6204}
        forged_part = base64.urlsafe_b64encode(
            json.dumps(forged, separators=(",", ":"), sort_keys=True).encode()
        ).rstrip(b"=").decode()
        with pytest.raises(ValueError, match="bad signature"):
            _verify(f"{header}.{forged_part}.{signature}", key)

    def test_a_grant_signed_by_another_key_is_refused(self):
        with pytest.raises(ValueError):
            _verify(sign_grant(_lease(), GrantKey.generate()), GrantKey.generate())

    def test_a_lease_with_no_expiry_is_not_signed(self):
        with pytest.raises(ValueError, match="no grant expiry"):
            sign_grant(_lease(grant_expires_at=None), GrantKey.generate())


class TestTheGrantExpiry:
    def test_it_is_the_lease_end_plus_the_grace_rounded_up_to_the_second(self):
        end = datetime(2027, 1, 1, 16, 59, 59, 1, tzinfo=timezone.utc)
        assert grant_expiry(end, timedelta(seconds=0)) == datetime(2027, 1, 1, 17, 0, 0)

    def test_a_whole_second_is_not_rounded(self):
        end = datetime(2027, 1, 1, 16, 0, 0, tzinfo=timezone.utc)
        assert grant_expiry(end, timedelta(hours=1)) == datetime(2027, 1, 1, 17, 0, 0)


class TestTheRelayUsabilityCheck:
    _USABLE = {
        "relay_addr": "203.0.113.9",
        "vm_port_range_start": 6100,
        "vm_port_range_count": 100,
        "relay_token": "admission-token",
        "grant_key_id": "kPrK_qmxVWaYVA9wwBF6Iuo3vVzz7TxHCTwXBygrS4k",
    }

    def test_a_relay_with_everything_passes(self):
        check_relay_usable("relay-bm", self._USABLE)

    def test_a_relay_with_no_active_key_is_refused_naming_it(self):
        with pytest.raises(ProviderConfigInvalidError) as refused:
            check_relay_usable("relay-bm", self._USABLE | {"grant_key_id": None})
        assert "'relay-bm'" in str(refused.value)
        assert "no active grant key" in str(refused.value)
        assert "admission token" not in str(refused.value)

    def test_a_disabled_relay_lacks_everything(self):
        with pytest.raises(ProviderConfigInvalidError) as refused:
            check_relay_usable("relay-bm", {})
        for name in ("relay address", "admission token", "active grant key"):
            assert name in str(refused.value)
