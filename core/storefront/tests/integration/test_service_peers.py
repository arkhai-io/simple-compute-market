"""A site's service peer: seeded from configuration, trusted from durable state.

These run against a real SQLite database because the trust they resolve is the
durable identity state a rotation rewrites, not the configuration that seeded it.
The trust holds that state in memory, so verification reads no database; a
change reaches it when it commits through the trust's identity authority.
"""

from __future__ import annotations

import os
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
    ServicePeerTrust,
    require_one_service_peer_per_site,
    seed_service_peers,
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


def _rotate(
    db_path: str,
    *,
    now: int,
    overlap_seconds: int = 30,
    authority: StorefrontIdentityAuthority | None = None,
) -> None:
    (authority or StorefrontIdentityAuthority(db_path)).apply_rotation(
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
    trust = ServicePeerTrust(db_path, _peers(_CURRENT, _REPLACEMENT))
    trust.seed(now=1_001)
    assert trust.site_active_principals("home", now=1_001) == {
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
        trust = ServicePeerTrust(db_path, configured, clock=lambda: 1_000)
        trust.reload()
        with pytest.raises(AuthError, match="exactly one configured service peer"):
            trust.site_active_principals(site_id, now=1_000)
        with pytest.raises(AuthError, match="exactly one configured service peer"):
            trust.site_authorities(site_id)()


def test_nothing_authenticates_before_the_trust_is_loaded(db_path: str) -> None:
    trust = ServicePeerTrust(db_path, _peers(_CURRENT))

    with pytest.raises(AuthError, match="not loaded") as excinfo:
        trust.site_authorities("home")()
    assert excinfo.value.status_code == 503


def test_active_principals_follow_a_rotation_through_its_overlap(db_path: str) -> None:
    trust = ServicePeerTrust(db_path, _peers(_CURRENT))
    trust.seed(now=1_000)
    assert trust.site_active_principals("home", now=1_000) == {_CURRENT.identity}

    _rotate(db_path, now=1_000, overlap_seconds=30, authority=trust.identity_authority())

    assert trust.site_active_principals("home", now=1_029) == {
        _CURRENT.identity,
        _REPLACEMENT.identity,
    }
    assert trust.site_active_principals("home", now=1_030) == {_REPLACEMENT.identity}
    # Another site's trust is its own peer's, untouched by this rotation.
    assert trust.site_active_principals("away", now=1_030) == {_OTHER_SITE.identity}


def test_the_provider_follows_a_rotation_from_memory(db_path: str) -> None:
    """The provider reads no database: an overlap ends by the clock alone, and a
    change committed through the trust's authority is reloaded as it commits."""
    now = [1_000]
    trust = ServicePeerTrust(db_path, _peers(_CURRENT), clock=lambda: now[0])
    trust.seed(now=1_000)
    provider = trust.site_authorities("home")
    assert provider() == _pins(_CURRENT)

    authority = trust.identity_authority()
    _rotate(db_path, now=1_000, overlap_seconds=30, authority=authority)
    now[0] = 1_010
    assert provider() == _pins(_REPLACEMENT, _CURRENT)

    # With the database gone, verification still answers, and the overlap
    # still ends on time: nothing is read at a call.
    moved = db_path + ".moved"
    os.rename(db_path, moved)
    try:
        now[0] = 1_030
        assert provider() == _pins(_REPLACEMENT)
    finally:
        os.rename(moved, db_path)

    authority.complete_rotation(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-home",
        rotation_nonce="rotate-home-1",
        principal=_CURRENT.identity,
        operator=_REPLACEMENT.identity,
        now=1_031,
    )
    now[0] = 1_031
    assert provider() == _pins(_REPLACEMENT)
    assert trust.site_authorities("away")() == _pins(_OTHER_SITE)


def test_a_change_made_outside_the_trust_waits_for_a_reload(db_path: str) -> None:
    trust = ServicePeerTrust(db_path, _peers(_CURRENT), clock=lambda: 1_010)
    trust.seed(now=1_000)

    _rotate(db_path, now=1_000, overlap_seconds=30)
    assert trust.site_authorities("home")() == _pins(_CURRENT)

    trust.reload()
    assert trust.site_authorities("home")() == _pins(_REPLACEMENT, _CURRENT)


def test_a_disabled_peer_authenticates_nothing(db_path: str) -> None:
    trust = ServicePeerTrust(db_path, _peers(_CURRENT), clock=lambda: 1_002)
    trust.seed(now=1_000)
    trust.identity_authority().disable(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-home",
        principal=_CURRENT.identity,
        operator=_CURRENT.identity,
        operation_id="disable-home",
        now=1_001,
    )

    with pytest.raises(AuthError, match="not active"):
        trust.site_active_principals("home", now=1_002)
    with pytest.raises(AuthError, match="not active"):
        trust.site_authorities("home")()


class _ReloadFailingTrust(ServicePeerTrust):
    """A trust whose durable reads fail while ``failing`` names an error, as a
    busy or locked database fails them, and which counts them. Its writes go
    through untouched. A background retry is captured rather than started, and
    each wait before an attempt is recorded rather than slept, so a test runs
    the retry when it chooses. With ``recover_after`` set, the reads stop
    failing at that wait."""

    def __init__(self, *args, **kwargs) -> None:
        self.failing: Exception | None = None
        self.recover_after: int | None = None
        self.reads = 0
        self.retries: list = []
        self.waits: list[float] = []
        super().__init__(
            *args, retry_wait=self._wait, start_retry=self.retries.append, **kwargs
        )

    def _wait(self, seconds: float) -> None:
        self.waits.append(seconds)
        if len(self.waits) == self.recover_after:
            self.failing = None

    def _read_sites(self):
        self.reads += 1
        if self.failing is not None:
            raise self.failing
        return super()._read_sites()


def _refuses_at_once(trust: _ReloadFailingTrust) -> None:
    """Every read refuses with 503 from memory: no durable read is attempted."""
    reads = trust.reads
    with pytest.raises(AuthError, match="not loaded") as refused:
        trust.site_authorities("home")()
    assert refused.value.status_code == 503
    with pytest.raises(AuthError, match="not loaded"):
        trust.site_active_principals("away", now=1_010)
    assert trust.reads == reads


def test_a_failed_reload_never_masks_a_committed_change(db_path: str) -> None:
    """The rotation's result is returned although the reload after it failed;
    the trust then holds nothing, rather than verify against the records the
    rotation replaced, until a background reload succeeds."""
    trust = _ReloadFailingTrust(db_path, _peers(_CURRENT), clock=lambda: 1_010)
    trust.seed(now=1_000)
    trust.failing = sqlite3.OperationalError("database is locked")

    _rotate(db_path, now=1_000, overlap_seconds=30, authority=trust.identity_authority())

    status = StorefrontIdentityAuthority(db_path).status(
        authority=SERVICE_PEER_AUTHORITY, subject="provisioning-home"
    )
    assert status.active_principals(1_010) == {_CURRENT.identity, _REPLACEMENT.identity}
    _refuses_at_once(trust)
    (retry,) = trust.retries

    trust.failing = None
    retry()

    assert trust.waits == [0.5]
    assert trust.site_authorities("home")() == _pins(_REPLACEMENT, _CURRENT)
    assert trust.site_authorities("away")() == _pins(_OTHER_SITE)


def test_a_background_reload_backs_off_until_it_succeeds(db_path: str) -> None:
    trust = _ReloadFailingTrust(db_path, _peers(_CURRENT), clock=lambda: 1_010)
    trust.seed(now=1_000)
    trust.failing = sqlite3.OperationalError("database is locked")
    _rotate(db_path, now=1_000, overlap_seconds=30, authority=trust.identity_authority())
    # A second change failing to reload while the first's retry is pending
    # starts no second retry.
    trust.identity_authority().disable(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-away",
        principal=_OTHER_SITE.identity,
        operator=_OTHER_SITE.identity,
        operation_id="disable-away",
        now=1_005,
    )
    (retry,) = trust.retries

    # Every attempt fails until the fourth wait.
    trust.recover_after = 4
    retry()

    assert trust.waits == [0.5, 1.0, 2.0, 4.0]
    assert trust.site_authorities("home")() == _pins(_REPLACEMENT, _CURRENT)
    with pytest.raises(AuthError, match="not active"):
        trust.site_authorities("away")()
    # Recovered: the next failed reload starts a retry of its own.
    trust.failing = sqlite3.OperationalError("database is locked")
    trust.reload_after_change()
    assert len(trust.retries) == 2


def test_a_disable_whose_reload_failed_does_not_leave_its_principal_trusted(
    db_path: str,
) -> None:
    trust = _ReloadFailingTrust(db_path, _peers(_CURRENT), clock=lambda: 1_002)
    trust.seed(now=1_000)
    trust.failing = sqlite3.OperationalError("database is locked")

    trust.identity_authority().disable(
        authority=SERVICE_PEER_AUTHORITY,
        subject="provisioning-home",
        principal=_CURRENT.identity,
        operator=_CURRENT.identity,
        operation_id="disable-home",
        now=1_001,
    )

    _refuses_at_once(trust)
    trust.failing = None
    (retry,) = trust.retries
    retry()
    with pytest.raises(AuthError, match="not active"):
        trust.site_active_principals("home", now=1_002)


def test_a_refused_change_is_raised_whatever_the_reload_did(db_path: str) -> None:
    trust = _ReloadFailingTrust(db_path, _peers(_CURRENT), clock=lambda: 1_010)
    trust.seed(now=1_000)
    trust.failing = sqlite3.OperationalError("database is locked")

    with pytest.raises(Exception) as refused:
        trust.identity_authority().register_subject(
            authority=SERVICE_PEER_AUTHORITY,
            subject="provisioning-home",
            role="administrator",
            principal=_CURRENT.identity,
            now=1_005,
        )
    assert not isinstance(refused.value, sqlite3.OperationalError)
    assert "role cannot change" in str(refused.value)
