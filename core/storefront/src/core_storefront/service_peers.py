"""The service peer each site authority is trusted through.

A storefront's configuration names its service peers: each peer's role, the one
site it is bound to, and the principals that seed it. Seeding writes a peer into
the storefront's durable identity state once. From then on the principals that
authenticate the site are that state's, rotated through the two-proof rotation
operations, and configuration must keep covering them.

A site's callbacks and the responses its clients receive are verified against
the same active principals, read from durable state at each verification, so a
completed rotation reaches both at once and needs no restart. See
openspec/specs/storefront-publication/spec.md#requirement-site-authority-principals-rotate-with-bounded-overlap.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable, Mapping

from market_identity import Identity, TrustedIdentitySet

from core_storefront.auth import AuthError
from core_storefront.identity_authority import (
    SERVICE_PEER_AUTHORITY,
    IdentitySubjectStatus,
    StorefrontIdentityAuthority,
)

#: Peer ID to its role, the site it is bound to, and its configured principals,
#: as a storefront's configuration states its service peers.
ServicePeerConfigs = Mapping[str, tuple[str, str, TrustedIdentitySet]]

SERVICE_PEER_ROLE = "service"


class ServicePeerConfigurationError(ValueError):
    """Configured sites are not each bound to exactly one service peer."""


def _site_peer_ids(peers: ServicePeerConfigs, site_id: str) -> list[str]:
    return sorted(
        peer_id
        for peer_id, (role, peer_site, _principals) in peers.items()
        if role == SERVICE_PEER_ROLE and peer_site == site_id
    )


def require_one_service_peer_per_site(
    peers: ServicePeerConfigs, site_ids: Iterable[str]
) -> None:
    """Refuse configuration that binds a site to no service peer or to several.

    Every problem is named in one error, so an operator fixes them together.
    """

    problems: list[str] = []
    for site_id in sorted(set(site_ids)):
        bound = _site_peer_ids(peers, site_id)
        if not bound:
            problems.append(f"site {site_id!r} is bound to no service peer")
        elif len(bound) > 1:
            problems.append(
                f"site {site_id!r} is bound to {len(bound)} service peers "
                f"({', '.join(bound)}); exactly one is required"
            )
    if problems:
        raise ServicePeerConfigurationError("; ".join(problems))


def seed_service_peers(
    db_path: str, peers: ServicePeerConfigs, *, now: int | None = None
) -> None:
    """Write each configured service peer into durable identity state, idempotently.

    A peer seen for the first time needs exactly one configured principal, its
    primary. A peer already seeded keeps its durable principals, which may have
    rotated since; its configuration must still name its role and site and cover
    every principal durable state holds active.
    """

    timestamp = int(time.time()) if now is None else now
    authority = StorefrontIdentityAuthority(db_path)
    for peer_id, (role, site_id, principals) in peers.items():
        try:
            status = authority.status(
                authority=SERVICE_PEER_AUTHORITY,
                subject=peer_id,
            )
        except KeyError:
            if len(principals.identities) != 1:
                raise AuthError(
                    "A new service peer requires exactly one primary principal"
                ) from None
            status = authority.register_service_peer(
                peer_id=peer_id,
                role=role,
                site_id=site_id,
                principal=principals.identities[0],
                now=timestamp,
            )
        conn = sqlite3.connect(db_path)
        try:
            durable_peer = conn.execute(
                "SELECT role, site_id FROM service_peers WHERE peer_id=?",
                (peer_id,),
            ).fetchone()
        finally:
            conn.close()
        if durable_peer != (role, site_id):
            raise AuthError(
                "Service-peer config role/site differs from durable identity state"
            )
        configured = frozenset(principals.identities)
        active = status.active_principals(timestamp)
        if status.primary not in configured or not active.issubset(configured):
            raise AuthError(
                "Service-peer config does not cover durable active identities"
            )


def _site_peer_status(
    db_path: str, peers: ServicePeerConfigs, site_id: str
) -> IdentitySubjectStatus:
    """The durable identity status of the one service peer bound to a site.

    The peer's durable row must still carry its configured role and site, be
    active, and agree with its primary binding.
    """

    bound = _site_peer_ids(peers, site_id)
    if len(bound) != 1:
        raise AuthError(
            "Provisioning site must have exactly one configured service peer"
        )
    peer_id = bound[0]
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT role, site_id, principal_scheme, principal_identifier, status
            FROM service_peers WHERE peer_id=?
            """,
            (peer_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise AuthError("Configured provisioning service peer is not materialized")
    role, durable_site, scheme, identifier, peer_status = row
    if role != SERVICE_PEER_ROLE or durable_site != site_id:
        raise AuthError("Provisioning service peer binding differs from public config")
    if peer_status != "active":
        raise AuthError("Provisioning service peer is not active")
    try:
        status = StorefrontIdentityAuthority(db_path).status(
            authority=SERVICE_PEER_AUTHORITY,
            subject=peer_id,
        )
    except KeyError as exc:
        raise AuthError("Provisioning service peer trust binding is incomplete") from exc
    if status.primary != Identity(scheme=scheme, identifier=identifier):
        raise AuthError(
            "Provisioning service peer row differs from its durable primary binding"
        )
    return status


def _active_principals(status: IdentitySubjectStatus, now: int) -> frozenset[Identity]:
    principals = status.active_principals(now)
    if not principals:
        raise AuthError("Provisioning service peer has no active principal")
    return principals


def site_active_principals(
    db_path: str, peers: ServicePeerConfigs, site_id: str, *, now: int
) -> frozenset[Identity]:
    """The principals that authenticate a site at ``now``, from durable state."""

    return _active_principals(_site_peer_status(db_path, peers, site_id), now)


def site_trusted_authorities(
    db_path: str,
    peers: ServicePeerConfigs,
    site_id: str,
    *,
    clock: Callable[[], float] = time.time,
) -> Callable[[], TrustedIdentitySet]:
    """A provider of a site's active principals, read at each call.

    A site client verifies each response against what this returns, so a
    response follows the site's rotation as its callbacks do. The primary comes
    first; a principal still in its rotation overlap follows it.
    """

    def trusted_authorities() -> TrustedIdentitySet:
        status = _site_peer_status(db_path, peers, site_id)
        ordered = sorted(
            _active_principals(status, int(clock())),
            key=lambda principal: (
                principal != status.primary,
                principal.scheme.value,
                principal.identifier,
            ),
        )
        return TrustedIdentitySet(identities=tuple(ordered))

    return trusted_authorities


__all__ = [
    "SERVICE_PEER_ROLE",
    "ServicePeerConfigs",
    "ServicePeerConfigurationError",
    "require_one_service_peer_per_site",
    "seed_service_peers",
    "site_active_principals",
    "site_trusted_authorities",
]
