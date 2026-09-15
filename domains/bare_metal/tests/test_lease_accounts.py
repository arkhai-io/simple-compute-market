from __future__ import annotations

from datetime import datetime, timezone

import pytest

from arkhai_bare_metal import (
    LEASE_ACCOUNT_PATTERN,
    BareMetalLeaseAccountError,
    BareMetalMaterialization,
    admissible_lease_account,
    canonical_lease_account,
    materialization_to_lease_create,
)


def _materialization(**overrides) -> BareMetalMaterialization:
    values = {
        "escrow_uid": "escrow-abc",
        "machine_id": "node-1",
        "physical_host_id": "host-1",
        "lease_start_utc": datetime(2030, 1, 1, tzinfo=timezone.utc),
        "lease_end_utc": datetime(2030, 1, 2, tzinfo=timezone.utc),
        "access_method": "ssh",
        "ssh_public_key": "ssh-ed25519 AAAA test",
    }
    values.update(overrides)
    return BareMetalMaterialization(**values)


def test_canonical_account_is_derived_from_the_settlement_identity() -> None:
    account = canonical_lease_account("escrow-abc")

    assert LEASE_ACCOUNT_PATTERN.fullmatch(account)
    assert account == canonical_lease_account("escrow-abc")
    assert account != canonical_lease_account("escrow-abd")


def test_canonical_account_requires_a_settlement_identity() -> None:
    with pytest.raises(BareMetalLeaseAccountError):
        canonical_lease_account("")
    with pytest.raises(BareMetalLeaseAccountError):
        canonical_lease_account(None)


# Leases already granted under these names must keep resolving to them, so the
# values may not change without an account migration.
@pytest.mark.parametrize(
    ("identity", "expected"),
    [
        ("escrow-abc", "arkhai-70f5f19cca87f7e6"),
        (" escrow-abc ", "arkhai-213bfec90f53c7e3"),
        ("escrow-abc\n", "arkhai-1c4100fd06c8b517"),
        ("  ", "arkhai-6c179f21e6f62b62"),
    ],
)
def test_derivation_matches_the_identity_as_accepted(identity, expected) -> None:
    assert canonical_lease_account(identity) == expected


def test_whitespace_bearing_identities_stay_distinct() -> None:
    """Persisted models keep surrounding whitespace, so these are four leases.

    Folding them onto one account would let one lease's reclaim act on another
    lease's account on the same host.
    """
    accounts = {
        canonical_lease_account(value)
        for value in ("escrow-abc", " escrow-abc", "escrow-abc ", " escrow-abc ")
    }

    assert len(accounts) == 4


@pytest.mark.parametrize(
    "candidate",
    [
        "root",
        "admin",
        "ubuntu",
        "opsadmin",
        "arkhai",
        "arkhai-",
        "arkhai-root",
        "arkhai-0123456789abcde",
        "arkhai-0123456789abcdef0",
        "arkhai-0123456789ABCDEF",
        "arkhai-0123456789abcde/",
        "../root",
        "root\narkhai-0123456789abcdef",
        "arkhai-0123456789abcdef\n",
    ],
)
def test_non_canonical_names_are_refused(candidate: str) -> None:
    """The canonical form is the whole allowlist.

    Any name outside it could name an operator or system account on the host.
    """
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(candidate, settlement_identity=None)


def test_admission_binds_the_account_to_its_settlement_identity() -> None:
    expected = canonical_lease_account("escrow-abc")

    assert (
        admissible_lease_account(expected, settlement_identity="escrow-abc") == expected
    )

    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(
            canonical_lease_account("escrow-xyz"),
            settlement_identity="escrow-abc",
        )


def test_admission_without_an_identity_still_requires_the_canonical_shape() -> None:
    account = canonical_lease_account("escrow-abc")

    assert admissible_lease_account(account, settlement_identity=None) == account


def test_missing_account_is_refused() -> None:
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(None, settlement_identity="escrow-abc")
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account("", settlement_identity="escrow-abc")


def test_materialization_default_account_is_admissible() -> None:
    lease = materialization_to_lease_create(_materialization())
    account = (lease.access_ref or {})["ssh_user"]

    assert account == canonical_lease_account("escrow-abc")
    assert admissible_lease_account(account, settlement_identity=lease.settlement_identity) == account


def test_obligation_backed_materialization_derives_from_the_obligation() -> None:
    lease = materialization_to_lease_create(
        _materialization(escrow_uid=None, settlement_obligation_ref="obligation-1")
    )

    assert lease.access_ref["ssh_user"] == canonical_lease_account("obligation-1")


def test_supplied_account_is_kept_so_admission_can_refuse_it() -> None:
    """A caller-supplied name survives materialization and fails admission."""
    lease = materialization_to_lease_create(
        _materialization(access_ref={"ssh_user": "root"})
    )

    assert lease.access_ref["ssh_user"] == "root"
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(
            lease.access_ref["ssh_user"],
            settlement_identity=lease.settlement_identity,
        )
