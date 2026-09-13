from __future__ import annotations

import pytest

from arkhai_bare_metal import (
    LEASE_ACCOUNT_PATTERN,
    BareMetalLeaseAccountError,
    admissible_lease_account,
    canonical_lease_account,
)


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


# Pinned from the derivation as it stood before this guard existed. Leases
# already granted under those names must keep resolving to them, so these
# values may not change without a migration.
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
    """The persisted models keep surrounding whitespace, so these are two leases.

    Folding them onto one account would let either one's reclaim lock or delete
    the other's, on the same host.
    """
    accounts = {
        canonical_lease_account(value)
        for value in ("escrow-abc", " escrow-abc", "escrow-abc ", " escrow-abc ")
    }

    assert len(accounts) == 4


def test_whitespace_only_identity_is_not_repaired_into_a_refusal() -> None:
    """Admission is the place to reject a malformed identity, not this helper.

    Rejecting here would silently move an already-materialized lease off the
    account it was granted under.
    """
    assert canonical_lease_account("  ").startswith("arkhai-")


@pytest.mark.parametrize(
    "privileged",
    [
        "root",
        "admin",
        "ubuntu",
        "opsadmin",  # stands in for a site operator login
        "arkhai",
        "arkhai-",
        "arkhai-root",
        "arkhai-0123456789abcde",  # 15 hex, one short
        "arkhai-0123456789abcdef0",  # 17 hex, one long
        "arkhai-0123456789ABCDEF",  # uppercase is not the canonical form
        "arkhai-0123456789abcde/",
        "../root",
        "root\narkhai-0123456789abcdef",
    ],
)
def test_non_canonical_names_are_refused(privileged: str) -> None:
    """A lease account may never resolve to an operator or system account.

    The canonical form is the whole allowlist: any name outside it could name an
    existing account, and the grant play would then add a buyer key to it.
    """
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(privileged, settlement_identity=None)


def test_admission_binds_the_account_to_its_settlement_identity() -> None:
    expected = canonical_lease_account("escrow-abc")

    assert (
        admissible_lease_account(expected, settlement_identity="escrow-abc") == expected
    )

    other = canonical_lease_account("escrow-xyz")
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(other, settlement_identity="escrow-abc")


def test_admission_without_an_identity_still_requires_the_canonical_shape() -> None:
    """Reclaim of a stored lease may not be able to recompute the identity.

    Shape admission still holds, so a stored access reference cannot direct a
    destructive reclaim policy at an operator account.
    """
    account = canonical_lease_account("escrow-abc")

    assert admissible_lease_account(account, settlement_identity=None) == account


def test_missing_account_is_refused() -> None:
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(None, settlement_identity="escrow-abc")
    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account("", settlement_identity="escrow-abc")


def test_materialization_default_account_is_admissible() -> None:
    """The derivation the domain already performs must satisfy its own guard."""
    from datetime import datetime, timezone

    from arkhai_bare_metal import BareMetalMaterialization, materialization_to_lease_create

    materialization = BareMetalMaterialization(
        escrow_uid="escrow-abc",
        machine_id="node-1",
        physical_host_id="host-1",
        lease_start_utc=datetime(2030, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2030, 1, 2, tzinfo=timezone.utc),
        access_method="ssh",
        ssh_public_key="ssh-ed25519 AAAA test",
    )

    lease = materialization_to_lease_create(materialization)
    account = (lease.access_ref or {})["ssh_user"]

    assert admissible_lease_account(account, settlement_identity="escrow-abc") == account


def test_supplied_account_cannot_override_the_derivation() -> None:
    """`access_ref` reaches the executor from callers other than the buyer.

    The buyer cannot set it, but the storefront materialization and the
    provisioning lease API both can, so the override has to fail admission
    rather than be trusted.
    """
    from datetime import datetime, timezone

    from arkhai_bare_metal import BareMetalMaterialization, materialization_to_lease_create

    materialization = BareMetalMaterialization(
        escrow_uid="escrow-abc",
        machine_id="node-1",
        physical_host_id="host-1",
        lease_start_utc=datetime(2030, 1, 1, tzinfo=timezone.utc),
        lease_end_utc=datetime(2030, 1, 2, tzinfo=timezone.utc),
        access_method="ssh",
        ssh_public_key="ssh-ed25519 AAAA test",
        access_ref={"ssh_user": "root"},
    )

    lease = materialization_to_lease_create(materialization)

    with pytest.raises(BareMetalLeaseAccountError):
        admissible_lease_account(
            (lease.access_ref or {})["ssh_user"],
            settlement_identity="escrow-abc",
        )
