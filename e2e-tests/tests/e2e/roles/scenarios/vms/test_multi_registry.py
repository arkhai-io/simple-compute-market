"""Multi-registry e2e scenario — 2 providers, 2 registries, mixed footprint.

Why a separate file
-------------------
``test_full_deal.py`` is the happy-path lifecycle and stops checking
the registry after stage 04a — it's deliberately agnostic to topology.
The multi-registry assertions live here because they only matter up
through negotiation start, and they only become non-trivial with two
*different* providers whose per-provider registry sets differ.

The docker-compose stack runs:
  * ``registry``    on host port 8080 — public, signed reads without a bearer gate
  * ``registry-b``  on host port 8082 — read + write gated, seeded with
                    the stack's single write-scoped bootstrap key
  * ``bob-storefront``   (Bob)   on host port 8001 — Anvil acct #2,
                         [registry] urls = [registry, registry-b]
  * ``alice-storefront`` (Alice) on host port 8002 — Anvil acct #4,
                         [registry] urls = [registry]
  * ``provisioning`` serves Bob; ``alice-provisioning`` serves Alice,
    each with a distinct service identity and independent state.

Provider topology
-----------------
Bob fans publishes out to both registries (matches the "operator
mirrors to a private registry alongside the public one" scenario).
Alice only publishes to the public registry (matches the "provider
trusts only one registry" scenario). After both have a listing, the
buyer's view retains three authority-scoped records for this scenario:
Bob at A, Bob at B, and Alice at A. An identical listing ID across independent
registry authorities does not establish equivalent ownership or trust.

What this exercises that test_full_deal doesn't
-----------------------------------------------
1. A storefront can publish to a subset of available registries (Alice).
2. The buyer's discovery is the *union* across configured registries.
3. Production buyer discovery preserves independent registry authorities
   when the same listing ID appears in both.
4. Independent negotiations against different providers don't
   collide on shared infrastructure (negotiation rounds, event stream).

Stage map
---------
Phase 0 — readiness
  00a  Bob healthy
  00b  Alice healthy
  00c  Bob sees both registries (his checks.registry probes both URLs)
  00d  Alice sees registry-A (her checks.registry probes A only)
  00e  Registry-B reachable from this test process (sanity check on
       host-port mapping; needed for 04 assertions)
  00f  Bob's negotiation strategy viable
  00g  Alice's negotiation strategy viable

Phase 1 — policy seed on both storefronts
  01a  Bob policy seed
  01b  Alice policy seed

Phase 2 — inventory seed on both storefronts
  02a  Bob inventory seed (distinct resource_id)
  02b  Alice inventory seed (distinct resource_id)

Phase 3 — create + publish listings on both
  03c  Bob creates + resumes listing → fanned out to A + B
       (publisher created lazily on this first signed publish)
  03d  Alice creates + resumes listing → published to A only

Phase 4 — registry footprints differ as configured
  04a  Bob's listing present in registry-A
  04b  Bob's listing present in registry-B (with bearer)
  04c  Alice's listing present in registry-A
  04d  Alice's listing **absent** from registry-B (404)

Phase 5 — buyer-side discovery
  05a  Fan-in over [A, B] retains Bob at A and B, plus Alice at A
  05b  Fan-in over [A, DEAD] still returns both (A has both)

Phase 6 — simultaneous negotiations
  06a  Buyer starts negotiation against Bob via bob-storefront
  06b  Buyer starts negotiation against Alice via alice-storefront
  06c  Both negotiations independently recorded round-0 counter
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest

from core_buyer.orchestrator import query_registry_for_matches_multi
from core_buyer.registry_config import RegistryAuthority
from registry_client import RegistryClientError, SyncRegistryClient
from market_site_client import SiteCapacityAdminClient
from storefront_client import SyncStorefrontClient
from vm_provisioning_operator import SyncProvisioningClient

from market_identity import (
    Identity,
    TrustedIdentitySet,
    create_signer,
)
from e2e_harness.settings import settings
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_HOST_GPU_COUNT,
    E2E_MULTI_REGISTRY_HOST,
    E2E_MULTI_REGISTRY_POOL_ID,
    provision_e2e_executor,
    refresh_storefront_projections,
)
from tests.e2e.roles.scenarios.vms.conftest import _require_setting, _signer, _trust, capacity_source_for, pause_storefront

log = logging.getLogger(__name__)

pytestmark = pytest.mark.multi_registry


# ---------------------------------------------------------------------------
# Topology — host-network URLs for local runs, service DNS names for
# buyer-machine runs inside the compose network.
# ---------------------------------------------------------------------------

def _registry_urls() -> tuple[str, str, str]:
    profiles = {
        profile.strip()
        for profile in os.environ.get("ACTIVE_PROFILES", "").split(",")
        if profile.strip()
    }
    if "docker" in profiles:
        return (
            "http://registry:8080",
            "http://registry-b:8080",
            "http://registry:9",
        )
    return (
        "http://localhost:8080",
        "http://localhost:8082",
        "http://localhost:9",
    )


_REGISTRY_A, _REGISTRY_B, _REGISTRY_DEAD = _registry_urls()
# The private registry seeds exactly one write-scoped key at startup, from
# the stack's bootstrap value. Reading it from configuration rather than
# restating it keeps the test and the stack from drifting apart.
_REGISTRY_B_TOKEN = str(
    settings.REGISTRY.get("bootstrap_api_key", "") or ""
)


# ---------------------------------------------------------------------------
# Offer / demand specs — Bob and Alice get distinct resource_ids so that
# the registry rows are obviously different and a missing fanout would
# produce a clear assertion failure rather than a silent "the listing's
# still there from last run".
# ---------------------------------------------------------------------------

DURATION_HOURS = 1
# Base units of an 18-decimal asset, so past the JSON safe-integer range:
# these amounts ride the wire as decimal-digit strings, which is the shape
# canonical JSON can sign. 10 tokens/hour asking price, so the opening bid
# sits under the floor (round-0 counter) and the ceiling over it (the buyer
# accepts the seller's first counter). Both stay far inside the 1 000 tokens
# the dev chain funds this buyer with — every scenario in a run escrows
# against the same wallet.
BUYER_INITIAL_PRICE = 7 * 10**18

DEMAND_RESOURCE = {
    "token": {
        "symbol": "MOCK",
        "contract_address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
        # 18, which is what the contract reports. A listing claiming 0 was
        # the fiction that made display prices look like base units: the
        # funding script mints whole tokens (1 000 of them to this buyer),
        # and the buyer CLI scales its price flags by the decimals it reads
        # from the chain, not by what a listing advertises.
        "decimals": 18,
    },
    "amount": 10 * 10**18,
}
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": DEMAND_RESOURCE["token"]["contract_address"]},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_RESOURCE["amount"])}],
}]

BOB_OFFER = {
    # The storefront refuses a listing whose resource does not declare the
    # offering mode its domain binding selected.
    "offering_mode": "vm",
    "resource_id": "compute-mr-bob-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
ALICE_OFFER = {
    "offering_mode": "vm",
    "resource_id": "compute-mr-alice-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    # New York rather than California so the two providers' inventory is
    # visibly distinct in registry payloads. (The Region enum currently
    # admits California, New York, and Tokyo — see domain_models.Region.)
    "region": "New York, US",
}

# ---------------------------------------------------------------------------
# Local state
# ---------------------------------------------------------------------------

@dataclass
class MRState:
    bob_healthy: bool = False
    alice_healthy: bool = False
    bob_sees_both: bool = False
    alice_sees_a: bool = False
    registry_b_reachable: bool = False
    bob_strategy_ok: bool = False
    alice_strategy_ok: bool = False
    bob_inventory_seeded: bool = False
    alice_inventory_seeded: bool = False
    bob_listing_id: Optional[str] = None
    alice_listing_id: Optional[str] = None
    bob_in_a: bool = False
    bob_in_b: bool = False
    alice_in_a: bool = False
    alice_absent_from_b: bool = False
    fanin_ok: bool = False
    fanin_resilient_ok: bool = False
    negotiation_ids: dict[str, str] = field(default_factory=dict)


@pytest.fixture(scope="module")
def mr_state() -> MRState:
    return MRState()


def _require(state: MRState, *fields: str) -> None:
    for f in fields:
        val = getattr(state, f, None)
        if not val:
            pytest.skip(
                f"Prerequisite not satisfied: MRState.{f} is {val!r}. "
                f"An earlier test likely failed."
            )


# ---------------------------------------------------------------------------
# Bob is covered by the shared conftest fixtures (storefront_admin_client,
# storefront_client, seller_wallet, seller_agent_id). Alice needs her own
# parallel set.
# ---------------------------------------------------------------------------

def _alice_url() -> str:
    return _require_setting(
        getattr(settings, "ALICE", None) and settings.ALICE.API_URL, "ALICE.API_URL"
    )


def _alice_publisher_trust():
    identity = create_signer(
        "eip191",
        _require_setting(settings.ALICE.PRIVATE_KEY, "ALICE.PRIVATE_KEY"),
    ).identity
    return TrustedIdentitySet(
        identities=(
            Identity(scheme="eip191", identifier=identity.identifier),
        )
    )


@pytest.fixture(scope="module")
def alice_admin_client():
    """Admin-role client for Alice's storefront: system controls only.

    Alice's administrator is a distinct principal from Alice's seller, exactly
    as Bob's is, and is pinned as ``Identity.administrators.operator`` in
    ``storefront.alice.toml``.
    """

    client = SyncStorefrontClient(
        _alice_url(),
        create_signer(
            str(settings.ALICE.get("admin_scheme", "eip191") or "eip191"),
            _require_setting(
                settings.ALICE.get("admin_credential", ""), "ALICE.ADMIN_CREDENTIAL"
            ),
        ),
        caller_role="admin",
        expected_publishers=_alice_publisher_trust(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def alice_seller_client():
    """Seller-role client for Alice's storefront: publishing listings."""

    client = SyncStorefrontClient(
        _alice_url(),
        create_signer(
            "eip191",
            _require_setting(settings.ALICE.PRIVATE_KEY, "ALICE.PRIVATE_KEY"),
        ),
        caller_role="seller",
        expected_publishers=_alice_publisher_trust(),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def alice_wallet() -> str:
    return _require_setting(settings.ALICE.WALLET_ADDRESS, "ALICE.WALLET_ADDRESS")


@pytest.fixture(scope="module")
def alice_agent_id(alice_admin_client) -> str:
    """Alice's live on-chain agent_id, looked up the same way as Bob's."""
    status = alice_admin_client.get_system_status()
    live = getattr(status, "agent_id", None)
    if not live:
        pytest.skip(
            "Alice has no live agent_id — the alice-storefront container hasn't "
            "completed on-chain registration yet."
        )
    return str(live)


# ---------------------------------------------------------------------------
# Registry trust configuration and typed client composition.
# ---------------------------------------------------------------------------

def _buyer_signer():
    return _signer(
        "eip191", settings.BUYER.MARKETPLACE_CREDENTIAL,
        "BUYER.MARKETPLACE_CREDENTIAL",
    )


def _registry_client(url: str) -> SyncRegistryClient:
    pins = _registry_pins(url)
    return SyncRegistryClient(
        url, signer=_buyer_signer(), caller_role="buyer",
        expected_registries=_trust(pins["identifier"]),
        registry_authority=pins["authority_id"],
        api_key=_REGISTRY_B_TOKEN if url == _REGISTRY_B else None,
        timeout=5.0,
    )


def _registry_authority(url: str) -> RegistryAuthority:
    pins = _registry_pins(url)
    return RegistryAuthority(
        authority=pins["authority_id"], principals=_trust(pins["identifier"]),
    )


def _registry_pins(url: str) -> dict[str, str]:
    """Authority id and signing principal for one registry, matched by URL."""
    normalized = url.rstrip("/")
    for section in ("REGISTRY", "REGISTRY_B"):
        block = getattr(settings, section, None)
        if block is None:
            continue
        if str(block.get("api_url", "") or "").rstrip("/") == normalized:
            return {
                "authority_id": _require_setting(
                    block.get("authority_id", ""), f"{section}.AUTHORITY_ID"
                ),
                "identifier": _require_setting(
                    block.get("identifier", ""), f"{section}.IDENTIFIER"
                ),
            }
    raise AssertionError(
        f"no configured registry pins for {url!r}; add them rather than "
        "reading it unsigned"
    )


# ===========================================================================
# Phase 0 — readiness
# ===========================================================================

class TestStage00_PausesBothStorefronts:
    def test_00_pauses_both_storefronts_loops(
        self, storefront_admin_client, alice_admin_client
    ):
        """Hold both storefronts' timer loops before any listing is created.

        Each storefront publishes what its sites declare on its own publication
        loop. This scenario creates its listings explicitly, so a loop left
        running could bind the same slice first and the explicit create would
        be refused. It holds the loops rather than relying on an earlier
        scenario having done so, which a marker-selected run would not.
        """
        pause_storefront(storefront_admin_client)
        pause_storefront(alice_admin_client)


class TestStage00a_BobHealth:
    def test_00a_bob_healthy(self, storefront_admin_client, mr_state):
        health = storefront_admin_client.get_health()
        assert health.status == "ok", f"Bob unhealthy: {health}"
        mr_state.bob_healthy = True
        log.info("[00a] bob healthy")


class TestStage00b_AliceHealth:
    def test_00b_alice_healthy(self, alice_admin_client, mr_state):
        health = alice_admin_client.get_health()
        assert health.status == "ok", f"Alice unhealthy: {health}"
        mr_state.alice_healthy = True
        log.info("[00b] alice healthy")


class TestStage00c_BobSeesBothRegistries:
    def test_00c_bob_can_reach_both_registries(
        self, storefront_admin_client, mr_state
    ):
        """Bob's checks.registry=ok means every URL in his
        CONFIG.indexer_urls probe succeeded — including the bearer-gated
        registry-b. One assertion covers both URLs."""
        _require(mr_state, "bob_healthy")
        status = storefront_admin_client.get_system_status()
        check = (status.checks or {}).get("registry", "absent")
        assert check == "ok", (
            f"Bob cannot reach all configured registries: checks.registry={check!r}.\n"
            "Verify [registry] urls in config.bob.toml and the [registry.auth] "
            "bearer matches REGISTRY_BOOTSTRAP_API_KEY on registry-b."
        )
        mr_state.bob_sees_both = True


class TestStage00d_AliceSeesRegistryA:
    def test_00d_alice_can_reach_registry_a(
        self, alice_admin_client, mr_state
    ):
        """Alice's checks.registry=ok with urls=[registry-A] means
        registry-A is reachable; it does NOT confirm registry-B is
        reachable because Alice doesn't have it in her config — by
        design."""
        _require(mr_state, "alice_healthy")
        status = alice_admin_client.get_system_status()
        check = (status.checks or {}).get("registry", "absent")
        assert check == "ok", (
            f"Alice cannot reach registry-A: checks.registry={check!r}.\n"
            "Verify [registry] urls in config.alice.toml."
        )
        mr_state.alice_sees_a = True


class TestStage00e_RegistryBDirectFromHost:
    def test_00e_registry_b_reachable(self, mr_state):
        """Sanity-check host-port mapping for registry-b — Phase 4
        assertions hit :8082 directly from this test process."""
        _require(mr_state, "bob_sees_both")
        with _registry_client(_REGISTRY_B) as client:
            assert client.get_health().status == "ok"
        mr_state.registry_b_reachable = True


class TestStage00f_BobStrategy:
    def test_00f_bob_strategy_viable(self, storefront_admin_client, mr_state):
        _require(mr_state, "bob_healthy")
        status = storefront_admin_client.get_system_status()
        strat = (status.checks or {}).get("negotiation_strategy", "absent")
        assert "exit_on_probe" not in strat, f"Bob strategy={strat!r}"
        mr_state.bob_strategy_ok = True


class TestStage00g_AliceStrategy:
    def test_00g_alice_strategy_viable(self, alice_admin_client, mr_state):
        _require(mr_state, "alice_healthy")
        status = alice_admin_client.get_system_status()
        strat = (status.checks or {}).get("negotiation_strategy", "absent")
        assert "exit_on_probe" not in strat, f"Alice strategy={strat!r}"
        mr_state.alice_strategy_ok = True


# ===========================================================================
# Phase 2 — inventory seed
# ===========================================================================

@pytest.fixture(scope="module")
def alice_provisioning_client():
    config = settings.ALICE_PROVISIONING
    with SyncProvisioningClient(
        _require_setting(config.API_URL, "ALICE_PROVISIONING.API_URL"),
        _signer(config.ADMIN_SCHEME, config.ADMIN_CREDENTIAL,
                "ALICE_PROVISIONING.ADMIN_CREDENTIAL"),
        _trust(config.AUTHORITY_IDENTIFIER, scheme=config.AUTHORITY_SCHEME),
    ) as client:
        yield client


@pytest.fixture(scope="module")
def alice_site_capacity_admin_client():
    config = settings.ALICE_PROVISIONING
    return SiteCapacityAdminClient(
        _require_setting(config.API_URL, "ALICE_PROVISIONING.API_URL"),
        _signer("eip191", settings.ALICE.PRIVATE_KEY, "ALICE.PRIVATE_KEY"),
        _trust(config.AUTHORITY_IDENTIFIER, scheme=config.AUTHORITY_SCHEME),
    )


class TestStage02a_BobInventory:
    def test_02a_bob_seeds_inventory(
        self, provisioning_client, site_capacity_admin_client,
        storefront_admin_client, mr_state,
    ):
        _require(mr_state, "bob_healthy")
        host = provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=E2E_MULTI_REGISTRY_HOST,
            pool_id=E2E_MULTI_REGISTRY_POOL_ID,
            resource_id=BOB_OFFER["resource_id"],
            sellable_units=1,
            attributes={"gpu_model": "RTX 5080", "region": BOB_OFFER["region"],
                        "sla": "90.0"},
        )
        assert (host.gpu_count or 0) >= E2E_HOST_GPU_COUNT
        refresh_storefront_projections(storefront_admin_client)
        mr_state.bob_inventory_seeded = True


class TestStage02b_AliceInventory:
    def test_02b_alice_seeds_inventory(
        self, alice_provisioning_client, alice_site_capacity_admin_client,
        alice_admin_client, mr_state,
    ):
        _require(mr_state, "alice_healthy")
        host = provision_e2e_executor(
            alice_provisioning_client,
            alice_site_capacity_admin_client,
            host=f"{E2E_MULTI_REGISTRY_HOST}-ny",
            pool_id=E2E_MULTI_REGISTRY_POOL_ID,
            resource_id=ALICE_OFFER["resource_id"],
            sellable_units=1,
            attributes={"gpu_model": "RTX 5080", "region": ALICE_OFFER["region"],
                        "sla": "90.0"},
        )
        assert (host.gpu_count or 0) >= E2E_HOST_GPU_COUNT
        refresh_storefront_projections(alice_admin_client)
        mr_state.alice_inventory_seeded = True


# ===========================================================================
# Phase 3 — create + publish listings on both storefronts
# ===========================================================================

class TestStage03c_BobPublishes:
    def test_03c_bob_creates_and_resumes(
        self, storefront_admin_client, storefront_seller_client, seller_wallet, mr_state
    ):
        _require(
            mr_state, "bob_sees_both", "bob_inventory_seeded"
        )

        resp = storefront_seller_client.create_listing(
            listing_resource=BOB_OFFER,
            capacity_source=capacity_source_for(BOB_OFFER),
            accepted_escrows=ACCEPTED_ESCROWS,
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, f"no listing_id from bob: {resp}"

        result = storefront_admin_client.resume_listing(listing_id)
        assert result.registry_status == "published", (
            f"Bob's publish failed: {result.registry_status!r}.\n"
            "MultiRegistryClient requires ≥1 registry to accept — all "
            "configured registries (A + B) rejected the publish."
        )
        mr_state.bob_listing_id = listing_id
        log.info("[03c] bob published listing %s", listing_id)


class TestStage03d_AlicePublishes:
    def test_03d_alice_creates_and_resumes(
        self, alice_admin_client, alice_seller_client, alice_wallet, mr_state
    ):
        _require(
            mr_state, "alice_sees_a", "alice_inventory_seeded",
        )

        resp = alice_seller_client.create_listing(
            listing_resource=ALICE_OFFER,
            capacity_source=capacity_source_for(ALICE_OFFER, site_id="default"),
            accepted_escrows=ACCEPTED_ESCROWS,
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, f"no listing_id from alice: {resp}"

        result = alice_admin_client.resume_listing(listing_id)
        assert result.registry_status == "published", (
            f"Alice's publish failed: {result.registry_status!r}"
        )
        mr_state.alice_listing_id = listing_id
        log.info("[03d] alice published listing %s", listing_id)





# ===========================================================================
# Phase 4 — registry footprints differ as configured
# ===========================================================================

class TestStage04a_BobInRegistryA:
    def test_04a_bob_in_a(self, mr_state):
        _require(mr_state, "bob_listing_id")
        with _registry_client(_REGISTRY_A) as client:
            assert client.get_listing(mr_state.bob_listing_id).id == mr_state.bob_listing_id
        mr_state.bob_in_a = True


class TestStage04b_BobInRegistryB:
    def test_04b_bob_in_b_with_bearer(self, mr_state):
        _require(mr_state, "bob_listing_id")
        with _registry_client(_REGISTRY_B) as client:
            assert client.get_listing(mr_state.bob_listing_id).id == mr_state.bob_listing_id
        mr_state.bob_in_b = True


class TestStage04c_AliceInRegistryA:
    def test_04c_alice_in_a(self, mr_state):
        _require(mr_state, "alice_listing_id")
        with _registry_client(_REGISTRY_A) as client:
            assert client.get_listing(mr_state.alice_listing_id).id == mr_state.alice_listing_id
        mr_state.alice_in_a = True


class TestStage04d_AliceAbsentFromRegistryB:
    def test_04d_alice_not_in_b(self, mr_state):
        _require(mr_state, "alice_listing_id")
        with _registry_client(_REGISTRY_B) as client:
            with pytest.raises(RegistryClientError) as caught:
                client.get_listing(mr_state.alice_listing_id)
        assert caught.value.status_code == 404
        mr_state.alice_absent_from_b = True


# ===========================================================================
# Phase 5 — production buyer discovery
# ===========================================================================

class TestStage05a_AuthorityScopedListings:
    def test_05a_fanin_preserves_independent_registry_authorities(self, mr_state):
        _require(
            mr_state, "bob_in_a", "bob_in_b", "alice_in_a", "alice_absent_from_b",
        )
        authorities = {url: _registry_authority(url) for url in (_REGISTRY_A, _REGISTRY_B)}
        assert authorities[_REGISTRY_A].authority != authorities[_REGISTRY_B].authority
        listings = query_registry_for_matches_multi(
            [_REGISTRY_A, _REGISTRY_B], signer=_buyer_signer(),
            registry_authorities=authorities,
            api_keys={_REGISTRY_B: _REGISTRY_B_TOKEN}, limit=200,
        )
        # Other scenarios may have published listings; count this scenario's
        # records exactly, including their authenticated source provenance.
        records = [
            (item["source_registry_authority"], item["source_registry_url"], item["listing_id"])
            for item in listings
            if item["listing_id"] in {mr_state.bob_listing_id, mr_state.alice_listing_id}
        ]
        expected = [
            (authorities[_REGISTRY_A].authority, _REGISTRY_A, mr_state.bob_listing_id),
            (authorities[_REGISTRY_A].authority, _REGISTRY_A, mr_state.alice_listing_id),
            (authorities[_REGISTRY_B].authority, _REGISTRY_B, mr_state.bob_listing_id),
        ]
        assert sorted(records) == sorted(expected)
        mr_state.fanin_ok = True


class TestStage05b_FanInResilientToDeadRegistry:
    def test_05b_one_dead_registry_doesnt_break_discovery(self, mr_state, capsys):
        _require(mr_state, "bob_in_a", "alice_in_a")
        authority = _registry_authority(_REGISTRY_A)
        # An unreachable endpoint of A has valid trust configuration; the
        # failure must occur during network access, not pin resolution.
        listings = query_registry_for_matches_multi(
            [_REGISTRY_A, _REGISTRY_DEAD], timeout=2.0, signer=_buyer_signer(),
            registry_authorities={_REGISTRY_A: authority, _REGISTRY_DEAD: authority},
            limit=200,
        )
        assert f"[registry] {_REGISTRY_DEAD}:" in capsys.readouterr().err
        ids = {item["listing_id"] for item in listings}
        assert {mr_state.bob_listing_id, mr_state.alice_listing_id} <= ids
        assert all(item["source_registry_url"] == _REGISTRY_A for item in listings)
        mr_state.fanin_resilient_ok = True


# ===========================================================================
# Phase 6 — simultaneous negotiations against the two providers
# ===========================================================================

class TestStage06a_NegotiateWithBob:
    def test_06a_buyer_starts_negotiation_with_bob(
        self, storefront_admin_client, buyer_config, mr_state
    ):
        """Buyer hits bob-storefront:8001 to start a negotiation against Bob's listing."""
        _require(mr_state, "bob_listing_id", "fanin_ok")
        # negotiate_new derives `buyer_principal` from the signer and asserts
        # the buyer role, so this client signs; the storefront records the
        # thread against whichever principal opened it.
        buyer_to_bob = SyncStorefrontClient(
            str(settings.SELLER.API_URL),
            _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL,
                    "BUYER.MARKETPLACE_CREDENTIAL"),
            caller_role="buyer",
            expected_publishers=_trust(
                _signer("eip191", settings.SELLER.PRIVATE_KEY,
                        "SELLER.PRIVATE_KEY").identity.identifier
            ),
        )
        try:
            resp = buyer_to_bob.negotiate_new(
                listing_id=mr_state.bob_listing_id,
                initial_amount=BUYER_INITIAL_PRICE,
                provision_terms={
                    "kind": "compute.v1",
                    "version": 1,
                    "payload": {
                        "duration_seconds": DURATION_HOURS * 3600,
                        # The key is a negotiated term, not a settle-time input:
                        # settle reads it from the accepted terms and refuses to
                        # substitute the caller's, so an empty value here cannot
                        # be supplied later.
                        "ssh_public_key": buyer_config["ssh_public_key"],
                    },
                },
                token=DEMAND_RESOURCE["token"]["contract_address"],
            )
        finally:
            buyer_to_bob.close()
        neg_id = resp.get("negotiation_id") if isinstance(resp, dict) else None
        assert neg_id, f"no negotiation_id from bob: {resp}"

        # Confirm visible + round-0 counter on Bob's storefront
        events = storefront_admin_client.get_events(
            stage="negotiation", negotiation_id=neg_id,
        )
        round0 = [e for e in events.events if e.event == "round_decided"]
        assert round0, f"no round_decided on bob for {neg_id}"
        assert round0[0].data.get("decision") == "counter"
        mr_state.negotiation_ids["bob"] = neg_id
        log.info("[06a] bob negotiation %s started", neg_id)


class TestStage06b_NegotiateWithAlice:
    def test_06b_buyer_starts_negotiation_with_alice(
        self, alice_admin_client, buyer_config, mr_state
    ):
        """Buyer hits alice-storefront:8002 to start a negotiation against Alice's listing.

        Confirms the buyer can route to a different storefront for a
        different provider — same wire protocol, different URL. The
        listing's ``agent_id`` field is how the buyer (in production)
        learns which storefront to dial; the test hardcodes the
        ``alice`` URL since it knows the topology.
        """
        _require(mr_state, "alice_listing_id", "fanin_ok")
        # This client signs as the buyer.
        buyer_to_alice = SyncStorefrontClient(
            str(settings.ALICE.API_URL),
            _signer("eip191", settings.BUYER.MARKETPLACE_CREDENTIAL,
                    "BUYER.MARKETPLACE_CREDENTIAL"),
            caller_role="buyer",
            expected_publishers=_alice_publisher_trust(),
        )
        try:
            resp = buyer_to_alice.negotiate_new(
                listing_id=mr_state.alice_listing_id,
                initial_amount=BUYER_INITIAL_PRICE,
                provision_terms={
                    "kind": "compute.v1",
                    "version": 1,
                    "payload": {
                        "duration_seconds": DURATION_HOURS * 3600,
                        # The key is a negotiated term, not a settle-time input:
                        # settle reads it from the accepted terms and refuses to
                        # substitute the caller's, so an empty value here cannot
                        # be supplied later.
                        "ssh_public_key": buyer_config["ssh_public_key"],
                    },
                },
                token=DEMAND_RESOURCE["token"]["contract_address"],
            )
        finally:
            buyer_to_alice.close()
        neg_id = resp.get("negotiation_id") if isinstance(resp, dict) else None
        assert neg_id, f"no negotiation_id from alice: {resp}"

        events = alice_admin_client.get_events(
            stage="negotiation", negotiation_id=neg_id,
        )
        round0 = [e for e in events.events if e.event == "round_decided"]
        assert round0, f"no round_decided on alice for {neg_id}"
        assert round0[0].data.get("decision") == "counter"
        mr_state.negotiation_ids["alice"] = neg_id
        log.info("[06b] alice negotiation %s started", neg_id)


class TestStage06c_NegotiationsIndependent:
    def test_06c_negotiations_are_distinct_objects_on_distinct_storefronts(
        self, storefront_admin_client, alice_admin_client, mr_state,
    ):
        """The two negotiation IDs must be different, and each storefront
        must only know about its own — confirms no shared state between
        the two storefronts on this layer."""
        _require(mr_state, "bob_listing_id", "alice_listing_id")
        bob_neg = mr_state.negotiation_ids.get("bob")
        alice_neg = mr_state.negotiation_ids.get("alice")
        if not bob_neg or not alice_neg:
            pytest.skip(
                "Missing MRState.negotiation_ids[bob] or [alice]: "
                "upstream negotiation stages did not both complete"
            )

        assert bob_neg != alice_neg, (
            "Bob and Alice returned the same negotiation_id — they share state?"
        )

        # Bob's storefront knows Bob's negotiation, not Alice's
        bob_threads = storefront_admin_client.list_negotiations(
            mr_state.bob_listing_id,
        )
        bob_ids = {n.negotiation_id for n in bob_threads.negotiations}
        assert bob_neg in bob_ids, f"bob doesn't see his own negotiation: {bob_ids}"
        assert alice_neg not in bob_ids, (
            f"bob unexpectedly sees alice's negotiation: {bob_ids}"
        )

        # Alice's storefront knows Alice's negotiation, not Bob's
        alice_threads = alice_admin_client.list_negotiations(
            mr_state.alice_listing_id,
        )
        alice_ids = {n.negotiation_id for n in alice_threads.negotiations}
        assert alice_neg in alice_ids, (
            f"alice doesn't see her own negotiation: {alice_ids}"
        )
        assert bob_neg not in alice_ids, (
            f"alice unexpectedly sees bob's negotiation: {alice_ids}"
        )
        log.info(
            "[06c] negotiations independent: bob=%s alice=%s",
            bob_neg, alice_neg,
        )
