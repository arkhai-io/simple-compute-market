"""A site's service peer: seeded from configuration, trusted from durable state.

These run against a real SQLite database because the trust they resolve is the
durable identity state a rotation rewrites, not the configuration that seeded it.
"""

from __future__ import annotations

import sqlite3

import pytest
from market_identity import Ed25519Signer, RotationIntent, TrustedIdentitySet, sign_rotation

from core_storefront.auth import AuthError
from core_storefront.identity_authority import (
    SERVICE_PEER_AUTHORITY,
    StorefrontIdentityAuthority,
)
from core_storefront.service_peers import (
    ServicePeerConfigurationError,
    require_one_service_peer_per_site,
    seed_service_peers,
    site_active_principals,
    site_trusted_authorities,
)
from core_storefront.sqlite_client import SQLiteClient

# Deterministic development keys from fixed seeds; never use them on a public network.
_CURRENT = Ed25519Signer(b"\x41" * 32)
_REPLACEMENT = Ed25519Signer(b"\x42" * 32)
_OTHER_SITE = Ed25519Signer(b"\x43" * 32)


def _pins(*signers: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=tuple(signer.identity for signer in signers))


def _peers(*signers: Ed25519Signer):
    return {
        "provisioning-home": ("service", "home", _pins(*signers)),
        "provisioning-away": ("service", "away", _pins(_OTHER_SITE)),
    }


@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "storefront.db")
    SQLiteClient(path)
    return path


def _rotate(db_path: str, *, now: int, overlap_seconds: int = 30) -> None:
    StorefrontIdentityAuthority(db_path).apply_rotation(
        sign_rotation(
            current_signer=_CURRENT,
            replacement_signer=_REPLACEMENT,
            intent=RotationIntent(
                authority=SERVICE_PEER_AUTHORITY,
                subject="provisioning-home",
                nonce="rotate-home-1",
                current=_CURRENT.identity,
                replacement=_REPLACEMENT.identity,
                overlap_seconds=overlap_seconds,
                expires_at=now + 600,
            ),
        ),
        operator=_CURRENT.identity,
        now=now,
    )


def test_seeding_writes_each_configured_peer_once(db_path: str) -> None:
    seed_service_peers(db_path, _peers(_CURRENT), now=1_000)
    seed_service_peers(db_path, _peers(_CURRENT), now=1_001)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT peer_id, role, site_id, principal_identifier, status "
            "FROM service_peers ORDER BY peer_id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("provisioning-away", "service", "away", _OTHER_SITE.identity.identifier, "active"),
        ("provisioning-home", "service", "home", _CURRENT.identity.identifier, "active"),
    ]


def test_a_new_peer_needs_exactly_one_principal(db_path: str) -> None:
    with pytest.raises(AuthError, match="exactly one primary principal"):
        seed_service_peers(db_path, _peers(_CURRENT, _REPLACEMENT), now=1_000)


def test_a_seeded_peer_keeps_its_site_and_role(db_path: str) -> None:
    seed_service_peers(db_path, _peers(_CURRENT), now=1_000)
    moved = {"provisioning-home": ("service", "elsewhere", _pins(_CURRENT))}

    with pytest.raises(AuthError):
        seed_service_peers(db_path, moved, now=1_001)


def test_seeding_after_a_rotation_keeps_the_durable_principals(db_path: str) -> None:
    seed_service_peers(db_path, _peers(_CURRENT), now=1_000)
    _rotate(db_path, now=1_000)

    # Configuration covering both principals of the overlap restarts cleanly,
    # and durable state, not configuration, decides the primary.
    seed_service_peers(db_path, _peers(_CURRENT, _REPLACEMENT), now=1_001)
    assert site_active_principals(db_path, _peers(_CURRENT), "home", now=1_001) == {
        _CURRENT.identity,
        _REPLACEMENT.identity,
    }

    # Configuration that no longer covers an active principal is refused.
    with pytest.raises(AuthError, match="does not cover"):
        seed_service_peers(db_path, _peers(_CURRENT), now=1_001)


def test_every_site_must_be_bound_to_exactly_one_peer() -> None:
    peers = {
        "provisioning-home": ("service", "home", _pins(_CURRENT)),
        "provisioning-twin-a": ("service", "twin", _pins(_REPLACEMENT)),
        "provisioning-twin-b": ("service", "twin", _pins(_OTHER_SITE)),
    }

    require_one_service_peer_per_site(peers, ["home"])
    with pytest.raises(ServicePeerConfigurationError) as excinfo:
        require_one_service_peer_per_site(peers, ["home", "twin", "lonely"])

    message = str(excinfo.value)
    assert "site 'lonely' is bound to no service peer" in message
    assert (
        "site 'twin' is bound to 2 service peers "
        "(provisioning-twin-a, provisioning-twin-b)"
    ) in message
    assert "'home'" not in message


def test_a_site_with_no_peer_or_two_authenticates_nothing(db_path: str) -> None:
    peers = {
        **_peers(_CURRENT),
        "provisioning-home-second": ("service", "home", _pins(_REPLACEMENT)),
    }
    seed_service_peers(db_path, _peers(_CURRENT), now=1_000)

    for site_id, configured in (("unconfigured", _peers(_CURRENT)), ("home", peers)):
        with pytest.raises(AuthError, match="exactly one configured service peer"):
            site_active_principals(db_path, configured, site_id, now=1_000)
        with pytest.raises(AuthError, match="exactly one configured service peer"):
            site_trusted_authorities(db_path, configured, site_id)()


def test_active_principals_follow_a_rotation_through_its_overlap(db_path: str) -> None:
    peers = _peers(_CURRENT)
    seed_service_peers(db_path, peers, now=1_000)
    assert site_active_principals(db_path, peers, "home", now=1_000) == {
        _CURRENT.identity
    }

    _rotate(db_path, now=1_000, overlap_seconds=30)

    assert site_active_principals(db_path, peers, "home", now=1_029) == {
        _CURRENT.identity,
        _REPLACEMENT.identity,
    }
    assert site_active_principals(db_path, peers, "home", now=1_030) == {
        _REPLACEMENT.identity
    }
    # Another site's trust is its own peer's, untouched by this rotation.
    assert site_active_principals(db_path, peers, "away", now=1_030) == {
        _OTHER_SITE.identity
    }


def test_the_provider_reads_durable_state_at_each_call(db_path: str) -> None:
    peers = _peers(_CURRENT)
    seed_service_peers(db_path, peers, now=1_000)
    now = [1_000]
    provider = site_trusted_authorities(db_path, peers, "home", clock=lambda: now[0])

    assert provider() == _pins(_CURRENT)

    _rotate(db_path, now=1_000, overlap_seconds=30)
    now[0] = 1_010
    assert provider() == _pins(_REPLACEMENT, _CURRENT)

    now[0] = 1_030
    assert provider() == _pins(_REPLACEMENT)

    StorefrontIdentityAuthority(db_path).complete_rotation(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-home",
        rotation_nonce="rotate-home-1",
        principal=_CURRENT.identity,
        operator=_REPLACEMENT.identity,
        now=1_031,
    )
    now[0] = 1_031
    assert provider() == _pins(_REPLACEMENT)


def test_a_disabled_peer_authenticates_nothing(db_path: str) -> None:
    peers = _peers(_CURRENT)
    seed_service_peers(db_path, peers, now=1_000)
    StorefrontIdentityAuthority(db_path).disable(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-home",
        principal=_CURRENT.identity,
        operator=_CURRENT.identity,
        operation_id="disable-home",
        now=1_001,
    )

    with pytest.raises(AuthError, match="not active"):
        site_active_principals(db_path, peers, "home", now=1_002)
    with pytest.raises(AuthError, match="not active"):
        site_trusted_authorities(db_path, peers, "home", clock=lambda: 1_002)()
