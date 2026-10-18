"""Trusted site bindings, the durable reservation-to-site map, and the site
clients the storefront builds.

The site's trust is its service peer's, seeded into a real SQLite identity
state as startup seeds it; rotations go through that trust's identity
authority, the one the storefront's rotation routes commit through.
"""

from __future__ import annotations

import sqlite3
import time
from types import SimpleNamespace

import pytest
from compute_provisioning_client import ComputeProvisioningAuthenticationError
from core_storefront.identity_authority import SERVICE_PEER_AUTHORITY
from core_storefront.service_peers import ServicePeerTrust
from market_identity import (
    Eip191Signer,
    Identity,
    RotationIntent,
    TrustedIdentitySet,
    sign_rotation,
)
from market_site_client import SiteCapacityAuthenticationError

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.site_clients import (
    DurableReservationSiteMap,
    SelectedSiteFulfillmentClient,
    build_trusted_site_clients,
    parse_site_bindings,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from signed_sites import SignedSite, SignedSites
from site_trust import peer_id, seeded_sites


PRINCIPAL = {
    "scheme": "eip191",
    "identifier": "0x1111111111111111111111111111111111111111",
}

# Development keys; never used on any public network.
SITE_A = Eip191Signer(bytes.fromhex("41" * 32))
SITE_A_NEXT = Eip191Signer(bytes.fromhex("42" * 32))
SITE_B = Eip191Signer(bytes.fromhex("43" * 32))
STOREFRONT = Eip191Signer(bytes.fromhex("44" * 32))
OPERATOR = Eip191Signer(bytes.fromhex("45" * 32))

_NONCE = "rotate-site-a-1"
_OVERLAP_SECONDS = 600


def _peers(*site_ids: str) -> dict:
    """One service peer for each site named, as the configuration states them."""
    principals = TrustedIdentitySet(identities=(Identity.model_validate(PRINCIPAL),))
    return {f"{site_id}-peer": ("service", site_id, principals) for site_id in site_ids}


def _database(tmp_path) -> str:
    db_path = str(tmp_path / "storefront.db")
    SQLiteClient(db_path, domain=get_market_domain_contract())
    return db_path


def _rotation(expires_at: int):
    return sign_rotation(
        current_signer=SITE_A,
        replacement_signer=SITE_A_NEXT,
        intent=RotationIntent(
            current=SITE_A.identity,
            replacement=SITE_A_NEXT.identity,
            subject=peer_id("site-a"),
            authority=SERVICE_PEER_AUTHORITY,
            nonce=_NONCE,
            overlap_seconds=_OVERLAP_SECONDS,
            expires_at=expires_at,
        ),
    )


def _rotate(trust: ServicePeerTrust, *, complete: bool) -> None:
    """Rotate site-a's peer from SITE_A to SITE_A_NEXT through the trust's
    identity authority; ``complete`` retires SITE_A, ending the overlap."""
    now = int(time.time())
    rotation = _rotation(now + 300)
    authority = trust.identity_authority()
    authority.apply_rotation(rotation, operator=OPERATOR.identity, now=now)
    if complete:
        authority.complete_rotation(
            authority=SERVICE_PEER_AUTHORITY,
            subject=peer_id("site-a"),
            rotation_nonce=_NONCE,
            principal=SITE_A.identity,
            operator=OPERATOR.identity,
            now=now,
        )


def test_a_binding_names_its_peer_and_diagnoses_its_principals_without_its_url(
    tmp_path,
) -> None:
    bindings, trust = seeded_sites(_database(tmp_path), {"site-a": SITE_A.identity})
    binding = parse_site_bindings(
        {"site-a": "https://provisioning.internal:8443"}, trust.peers
    )[0]

    assert bindings[0].service_peer == binding.service_peer == peer_id("site-a")
    assert binding.diagnostic(trust) == {
        "site_id": "site-a",
        "service_peer": peer_id("site-a"),
        "authority_principals": [SITE_A.identity.model_dump(mode="json")],
    }
    assert binding.diagnostic(None)["authority_principals"] == []
    assert "provisioning.internal" not in repr(binding)
    assert "authority_url" not in binding.diagnostic(trust)


@pytest.mark.parametrize(
    ("sites", "peers"),
    [
        pytest.param({}, {}, id="no site"),
        pytest.param({"site-a": "https://user:secret@example.test"}, _peers("site-a"),
                     id="credentials in the URL"),
        pytest.param({"site-a": "https://user:secret＠example.test"}, _peers("site-a"),
                     id="a full-width at sign"),
        pytest.param({"site-a": "https://one.example.test?secret=1"}, _peers("site-a"),
                     id="a query"),
        pytest.param({"site-a": "https://one.example.test/secret"}, _peers("site-a"),
                     id="a path"),
        pytest.param({"site-a": "https://one.example.test:secret"}, _peers("site-a"),
                     id="a port that is not a number"),
        pytest.param({"site a": "https://one.example.test"}, _peers("site a"),
                     id="an invalid site ID"),
        pytest.param({"site-a": "https://one.example.test"}, {}, id="no service peer"),
        pytest.param({"site-a": "https://one.example.test"},
                     {**_peers("site-a"), "second": _peers("site-a")["site-a-peer"]},
                     id="two service peers"),
    ],
)
def test_invalid_site_bindings_fail_closed_without_echoing_payload(sites, peers) -> None:
    with pytest.raises(ValueError) as raised:
        parse_site_bindings(sites, peers)
    assert "secret" not in str(raised.value)
    assert "one.example.test" not in str(raised.value)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        pytest.param("https://one.example.test/v1", "without a path", id="a path"),
        pytest.param("https://one.example.test:bad", "with a numeric port",
                     id="a port that is not a number"),
    ],
)
def test_a_site_url_that_is_not_an_origin_is_refused_naming_the_site(url, reason) -> None:
    """A path would prefix every route the site's clients join to it, and a
    port that is not a number fails only when a client is built."""
    with pytest.raises(
        ValueError, match=rf"site 'site-a' authority_url must be an HTTP\(S\) origin {reason}$"
    ):
        parse_site_bindings({"site-a": url}, _peers("site-a"))


@pytest.mark.parametrize(
    "peers",
    [
        pytest.param({}, id="no service peer"),
        pytest.param({**_peers("site-a"), "second": _peers("site-a")["site-a-peer"]},
                     id="two service peers"),
    ],
)
def test_a_site_bound_to_no_peer_or_to_two_is_refused_by_name(peers) -> None:
    """Spec scenario "A site has no service peer", at the bindings; the startup
    refusal names it too (``test_app_composition``)."""
    with pytest.raises(ValueError, match="site 'site-a' must be bound to exactly one"):
        parse_site_bindings({"site-a": "https://one.example.test"}, peers)


def test_a_reservation_stays_bound_to_its_site_across_an_authorized_rotation(
    tmp_path,
) -> None:
    """Spec scenario "A bare-metal storefront restarts after a rotation".

    The reservation is pinned to the site's peer, so a restart after the peer's
    principal rotated keeps it bound; the principal recorded beside it stays
    the one active when it was made, for audit. Configuration names the
    replacement for the restart, as durable state then requires.
    """
    db_path = _database(tmp_path)
    bindings, trust = seeded_sites(db_path, {"site-a": SITE_A.identity})
    routes = DurableReservationSiteMap(
        db_path, {binding.site_id: binding for binding in bindings}, trust
    )
    routes["reservation-1"] = "site-a"
    _rotate(trust, complete=True)

    restarted_bindings, restarted_trust = seeded_sites(
        db_path, {"site-a": SITE_A_NEXT.identity}
    )
    restarted = DurableReservationSiteMap(
        db_path,
        {binding.site_id: binding for binding in restarted_bindings},
        restarted_trust,
    )

    assert restarted == {"reservation-1": "site-a"}
    with sqlite3.connect(db_path) as conn:
        recorded = conn.execute(
            "SELECT site_id, service_peer, authority_scheme, authority_identifier "
            "FROM bare_metal_selected_site_bindings"
        ).fetchall()
    assert recorded == [
        ("site-a", peer_id("site-a"), "eip191", SITE_A.identity.identifier)
    ]


def test_a_reservation_whose_site_is_bound_to_another_peer_refuses_restart(
    tmp_path,
) -> None:
    db_path = _database(tmp_path)
    bindings, trust = seeded_sites(db_path, {"site-a": SITE_A.identity})
    routes = DurableReservationSiteMap(
        db_path, {binding.site_id: binding for binding in bindings}, trust
    )
    routes["reservation-1"] = "site-a"
    # Configuration now binds the site to a peer the reservation was not made under.
    renamed = {
        "replacement-peer": ("service", "site-a", TrustedIdentitySet(identities=(SITE_B.identity,)))
    }
    rebound = parse_site_bindings({"site-a": "http://site-a"}, renamed)

    with pytest.raises(RuntimeError, match="bound to another service peer"):
        DurableReservationSiteMap(db_path, {b.site_id: b for b in rebound}, trust)


class _RecordingFulfillmentClient:
    def __init__(self, site_id: str) -> None:
        self.site_id = site_id
        self.calls = []

    async def schedule_resource(self, request):
        self.calls.append(("schedule", request.capacity_reservation_id))
        return self.site_id

    async def begin_fulfillment(self, request):
        self.calls.append(("begin", request.capacity_reservation_id))
        return self.site_id

    async def get_fulfillment_status(self, fulfillment_id):
        self.calls.append(("status", fulfillment_id))
        return self.site_id

    async def get_fulfillment_result(self, fulfillment_id):
        self.calls.append(("result", fulfillment_id))
        return self.site_id

    async def begin_fulfillment_teardown(self, fulfillment_id):
        self.calls.append(("teardown", fulfillment_id))
        return self.site_id

    async def get_lease(self, capacity_reservation_id):
        self.calls.append(("lease", capacity_reservation_id))
        return self.site_id

    async def terminate_lease(self, capacity_reservation_id, request):
        self.calls.append(("terminate", capacity_reservation_id, request.reason))
        return self.site_id


async def test_every_fulfillment_verb_routes_to_persisted_site_after_restart(
    tmp_path,
) -> None:
    db_path = _database(tmp_path)
    authorities = {"site-a": SITE_A.identity, "site-b": SITE_B.identity}
    bindings, trust = seeded_sites(db_path, authorities)
    by_site = {binding.site_id: binding for binding in bindings}
    first_routes = DurableReservationSiteMap(db_path, by_site, trust)
    first_routes["reservation-b"] = "site-b"

    restarted_routes = DurableReservationSiteMap(db_path, by_site, trust)
    clients = {
        site_id: _RecordingFulfillmentClient(site_id)
        for site_id in by_site
    }
    fulfillment = SelectedSiteFulfillmentClient(clients, restarted_routes)
    request = SimpleNamespace(capacity_reservation_id="reservation-b")

    assert await fulfillment.schedule_resource(request) == "site-b"
    assert await fulfillment.begin_fulfillment(request) == "site-b"
    assert (
        await fulfillment.get_fulfillment_status(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )
    assert (
        await fulfillment.get_fulfillment_result(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )
    assert (
        await fulfillment.begin_fulfillment_teardown(
            "fulfillment-b",
            capacity_reservation_id="reservation-b",
        )
        == "site-b"
    )

    assert await fulfillment.get_lease("reservation-b") == "site-b"
    assert (
        await fulfillment.terminate_lease("reservation-b", reason="settlement_reclaimed")
        == "site-b"
    )

    assert clients["site-a"].calls == []
    assert clients["site-b"].calls == [
        ("schedule", "reservation-b"),
        ("begin", "reservation-b"),
        ("status", "fulfillment-b"),
        ("result", "fulfillment-b"),
        ("teardown", "fulfillment-b"),
        ("lease", "reservation-b"),
        ("terminate", "reservation-b", "settlement_reclaimed"),
    ]


def test_reservation_site_binding_is_immutable(tmp_path) -> None:
    db_path = _database(tmp_path)
    bindings, trust = seeded_sites(
        db_path, {"site-a": SITE_A.identity, "site-b": SITE_B.identity}
    )
    by_site = {binding.site_id: binding for binding in bindings}
    routes = DurableReservationSiteMap(db_path, by_site, trust)
    routes["reservation-1"] = "site-a"

    with pytest.raises(RuntimeError, match="conflicts with its persisted"):
        routes["reservation-1"] = "site-b"

    assert routes["reservation-1"] == "site-a"
    assert DurableReservationSiteMap(db_path, by_site, trust) == {
        "reservation-1": "site-a"
    }


async def test_each_sites_clients_verify_against_its_peers_active_principals(
    tmp_path,
) -> None:
    """Composition: the storefront's site-client builder over a real SQLite
    trust, with only the sites' transports replaced, its built clients called
    directly. Both of a site's clients verify its responses against its peer's
    active principals as they are at each response, so a rotation reaches them
    with no rebuild, and one site's principal verifies nothing of another's."""
    db_path = _database(tmp_path)
    bindings, trust = seeded_sites(
        db_path, {"site-a": SITE_A.identity, "site-b": SITE_B.identity}
    )
    sites = SignedSites({"site-a": SignedSite(SITE_A), "site-b": SignedSite(SITE_B)})
    capacity, fulfillment = build_trusted_site_clients(
        bindings=bindings,
        signer=STOREFRONT,
        db_path=db_path,
        placement="fill_first",
        trust=trust,
        factories=sites.factories(),
    )
    capacity.reservation_sites["reservation-a"] = "site-a"

    async def verifies(site_id: str, signer: Eip191Signer) -> tuple[bool, bool]:
        sites.sites[site_id].signer = signer
        try:
            await capacity.site(site_id).resource_pool_projection_version()
            capacity_verified = True
        except SiteCapacityAuthenticationError:
            capacity_verified = False
        try:
            await fulfillment.get_lease("reservation-a")
            fulfillment_verified = True
        except ComputeProvisioningAuthenticationError:
            fulfillment_verified = False
        return capacity_verified, fulfillment_verified

    assert await verifies("site-a", SITE_A) == (True, True)
    assert await verifies("site-a", SITE_A_NEXT) == (False, False)
    assert await verifies("site-a", SITE_B) == (False, False)

    _rotate(trust, complete=False)
    # During the overlap either principal verifies.
    assert await verifies("site-a", SITE_A_NEXT) == (True, True)
    assert await verifies("site-a", SITE_A) == (True, True)

    authority = trust.identity_authority()
    authority.complete_rotation(
        authority=SERVICE_PEER_AUTHORITY,
        subject=peer_id("site-a"),
        rotation_nonce=_NONCE,
        principal=SITE_A.identity,
        operator=OPERATOR.identity,
        now=int(time.time()),
    )
    # The overlap has ended: only the replacement verifies, same clients.
    assert await verifies("site-a", SITE_A_NEXT) == (True, True)
    assert await verifies("site-a", SITE_A) == (False, False)
    # The other site keeps its own peer's trust.
    sites.sites["site-b"].signer = SITE_B
    await capacity.site("site-b").resource_pool_projection_version()
    sites.sites["site-b"].signer = SITE_A_NEXT
    with pytest.raises(SiteCapacityAuthenticationError):
        await capacity.site("site-b").resource_pool_projection_version()

