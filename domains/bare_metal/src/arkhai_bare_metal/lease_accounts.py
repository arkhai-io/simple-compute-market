"""Admission rules for the operating-system account a whole-host lease uses.

A bare-metal grant creates a login account on a host the marketplace does not
own and installs a buyer-supplied key into it. The account name therefore
decides whose `authorized_keys` the buyer's key lands in, and a reclaim policy
of `lock_user` or `delete_user` decides whose account is locked or removed.

`access_ref` is provider-specific metadata typed as an open mapping, and it
reaches the executor from the storefront materialization and from the
provisioning lease API, not only from the derivation below. Admission is
enforced at the executing authority because that is the last point before a
name becomes an argument to a privileged play.

This admits which account a grant or reclaim may name. It is not host-side
ownership and not tenant isolation: a host may already have an account at the
canonical name, and nothing here inspects host state.
"""

from __future__ import annotations

import hashlib
import re

LEASE_ACCOUNT_PREFIX = "arkhai-"
LEASE_ACCOUNT_DIGEST_LENGTH = 16

# Anchored, lowercase-hex only. The canonical form is the entire allowlist:
# anything outside it may name an account that already exists on the host.
LEASE_ACCOUNT_PATTERN = re.compile(
    rf"{LEASE_ACCOUNT_PREFIX}[0-9a-f]{{{LEASE_ACCOUNT_DIGEST_LENGTH}}}"
)


class BareMetalLeaseAccountError(ValueError):
    """A lease account name is not admissible for a privileged host action."""


def canonical_lease_account(settlement_identity: str) -> str:
    """Return the only account name a lease for *settlement_identity* may use.

    The identity is hashed exactly as accepted. It is deliberately not trimmed,
    lowercased, or otherwise repaired: two persisted identities that differ only
    in surrounding whitespace are distinct settlements, and folding them onto
    one account would let either one's reclaim lock or delete the other's. It
    would also move already-materialized leases off the account they were
    granted under. Malformed identities are rejected where they are accepted,
    not silently normalized here.
    """
    if settlement_identity is None or settlement_identity == "":
        raise BareMetalLeaseAccountError(
            "a lease account requires a non-empty settlement identity"
        )
    digest = hashlib.sha256(str(settlement_identity).encode("utf-8")).hexdigest()
    return f"{LEASE_ACCOUNT_PREFIX}{digest[:LEASE_ACCOUNT_DIGEST_LENGTH]}"


def admissible_lease_account(
    ssh_user: str | None,
    *,
    settlement_identity: str | None,
) -> str:
    """Return *ssh_user* when it may be used for a privileged host action.

    ``fullmatch`` rather than ``match``: a trailing newline would otherwise let
    a second, unchecked name ride along into the play's variables.

    When *settlement_identity* is known the name must equal the derivation for
    that identity, which makes the account non-injectable. Reclaim of a stored
    lease may not be able to recompute the identity; shape admission still
    holds there, so a stored reference cannot aim a destructive reclaim policy
    at an operator account.
    """
    candidate = str(ssh_user or "")
    if not candidate:
        raise BareMetalLeaseAccountError("a lease account name is required")
    if not LEASE_ACCOUNT_PATTERN.fullmatch(candidate):
        raise BareMetalLeaseAccountError(
            "lease account name is not the canonical marketplace lease form"
        )
    if settlement_identity is not None:
        expected = canonical_lease_account(settlement_identity)
        if candidate != expected:
            raise BareMetalLeaseAccountError(
                "lease account name is not derived from its settlement identity"
            )
    return candidate


__all__ = [
    "LEASE_ACCOUNT_DIGEST_LENGTH",
    "LEASE_ACCOUNT_PATTERN",
    "LEASE_ACCOUNT_PREFIX",
    "BareMetalLeaseAccountError",
    "admissible_lease_account",
    "canonical_lease_account",
]
