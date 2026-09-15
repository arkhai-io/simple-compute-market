"""Admission rules for the tenant account name a whole-host lease uses.

A bare-metal grant installs a buyer-supplied key for this account, and a reclaim
acts on it. The name therefore decides whose access a privileged host action
changes. ``access_ref`` is open provider metadata that reaches the executor
from storefront materialization and from the provisioning lease API, so the
executing authority re-admits the name immediately before it becomes an
argument to a privileged play.

The canonical name is a pure function of the lease's settlement identity. It
names the tenant identity; it does not imply that a host account is created
under that name, and admitting it does not establish that the host's current
state belongs to this lease. Host-side ownership verification and the tenant
environment's own user database are separate checks made where host state is
visible.
"""

from __future__ import annotations

import hashlib
import re

LEASE_ACCOUNT_PREFIX = "arkhai-"
LEASE_ACCOUNT_DIGEST_LENGTH = 16

# Anchored, lowercase hex only. The canonical form is the entire allowlist: any
# other name could resolve to an operator or system account on the host.
LEASE_ACCOUNT_PATTERN = re.compile(
    rf"{LEASE_ACCOUNT_PREFIX}[0-9a-f]{{{LEASE_ACCOUNT_DIGEST_LENGTH}}}"
)


class BareMetalLeaseAccountError(ValueError):
    """A lease account name is not admissible for a privileged host action."""


def canonical_lease_account(settlement_identity: str | None) -> str:
    """Return the only account name a lease for *settlement_identity* may use.

    The identity is hashed exactly as accepted, without trimming or case
    folding: persisted identities that differ only in surrounding whitespace
    are distinct settlements, and folding them onto one name would let one
    lease's reclaim act on another's account. Malformed identities are
    rejected where they are accepted, not repaired here.
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
    """Return *ssh_user* when it may be named by a privileged host action.

    ``fullmatch`` rather than ``match``: a trailing newline would otherwise let
    a second, unchecked name ride along into the play's variables.

    When *settlement_identity* is known the name must equal its derivation, so
    one lease's action cannot target another lease's account. A stored
    reservation that no longer carries its identity still requires the
    canonical shape, so it cannot aim a reclaim at an operator account.
    """
    candidate = "" if ssh_user is None else str(ssh_user)
    if not candidate:
        raise BareMetalLeaseAccountError("a lease account name is required")
    if not LEASE_ACCOUNT_PATTERN.fullmatch(candidate):
        raise BareMetalLeaseAccountError(
            "lease account name is not the canonical marketplace lease form"
        )
    if settlement_identity is not None:
        if candidate != canonical_lease_account(settlement_identity):
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
