"""Sites bound to service peers seeded into a test storefront's identity state.

A storefront verifies each site's responses and callbacks against the site's
service-peer principals, which its durable identity state owns once startup
has seeded them. A test that builds its runtime directly seeds them here, as
startup does, and hands the runtime the bindings and the trust.

Every principal a caller passes is a development fixture, never for use on a
public network.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from core_storefront.service_peers import SERVICE_PEER_ROLE, ServicePeerTrust
from market_identity import Identity, TrustedIdentitySet

from arkhai_bare_metal_storefront.site_clients import (
    BareMetalSiteBinding,
    parse_site_bindings,
)


def peer_id(site_id: str) -> str:
    """The service peer a test binds ``site_id`` to."""
    return f"{site_id}-peer"


def site_peers(
    authorities: Mapping[str, Identity],
) -> dict[str, tuple[str, str, TrustedIdentitySet]]:
    """One service peer per site, seeded with that site's authority principal."""
    return {
        peer_id(site_id): (
            SERVICE_PEER_ROLE,
            site_id,
            TrustedIdentitySet(identities=(principal,)),
        )
        for site_id, principal in authorities.items()
    }


def seeded_sites(
    db_path: str | Path, authorities: Mapping[str, Identity]
) -> tuple[tuple[BareMetalSiteBinding, ...], ServicePeerTrust]:
    """Bind each site to its own peer and seed the peers into ``db_path``.

    The database must already carry the storefront's schema.
    """
    peers = site_peers(authorities)
    trust = ServicePeerTrust(str(db_path), peers)
    trust.seed()
    bindings = parse_site_bindings(
        {site_id: f"http://{site_id}" for site_id in authorities}, peers
    )
    return bindings, trust
