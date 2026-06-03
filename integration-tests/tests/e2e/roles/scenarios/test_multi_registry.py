"""Multi-registry e2e scenario — 2 providers, 2 registries, mixed footprint.

Why a separate file
-------------------
``test_full_deal.py`` is the happy-path lifecycle and stops checking
the registry after stage 04a — it's deliberately agnostic to topology.
The multi-registry assertions live here because they only matter up
through negotiation start, and they only become non-trivial with two
*different* providers whose per-provider registry sets differ.

The docker-compose stack runs:
  * ``registry``    on host port 8080 — public, no auth
  * ``registry-b``  on host port 8082 — read + write gated, seeded with
                    a write-scoped bearer ``test-buyer-token``
  * ``bob-storefront``   (Bob)   on host port 8001 — Anvil acct #2,
                         [registry] urls = [registry, registry-b]
  * ``alice-storefront`` (Alice) on host port 8002 — Anvil acct #4,
                         [registry] urls = [registry]

Provider topology
-----------------
Bob fans publishes out to both registries (matches the "operator
mirrors to a private registry alongside the public one" scenario).
Alice only publishes to the public registry (matches the "provider
trusts only one registry" scenario). After both have a listing, the
buyer's union view over [A, B] contains exactly two listings — Bob's
is in *both* registries but should appear in the union once, Alice's
is in *one* and should also appear once.

What this exercises that test_full_deal doesn't
-----------------------------------------------
1. A storefront can publish to a subset of available registries (Alice).
2. The buyer's discovery is the *union* across configured registries.
3. The buyer-side dedupe is by listing_id, so cross-registry mirrors
   don't produce duplicate negotiation kickoffs.
4. Two concurrent negotiations against different providers don't
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
  05a  Fan-in over [A, B] returns exactly 2 unique listings:
       Bob's once (deduped across mirrors) and Alice's once
  05b  Fan-in over [A, DEAD] still returns both (A has both)

Phase 6 — simultaneous negotiations
  06a  Buyer starts negotiation against Bob via bob-storefront
  06b  Buyer starts negotiation against Alice via alice-storefront
  06c  Both negotiations independently recorded round-0 counter
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx
import pytest

from src.settings import settings
from tests.e2e.roles.scenarios.conftest import _require_setting

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
_REGISTRY_B_TOKEN = "test-buyer-token"


# ---------------------------------------------------------------------------
# Offer / demand specs — Bob and Alice get distinct resource_ids so that
# the registry rows are obviously different and a missing fanout would
# produce a clear assertion failure rather than a silent "the listing's
# still there from last run".
# ---------------------------------------------------------------------------

DURATION_HOURS = 1
BUYER_INITIAL_PRICE = 7_000

DEMAND_RESOURCE = {
    "token": {
        "symbol": "MOCK",
        "contract_address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
        "decimals": 0,
    },
    "amount": 10_000,
}
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": DEMAND_RESOURCE["token"]["contract_address"]},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_RESOURCE["amount"])}],
}]

BOB_OFFER = {
    "resource_id": "compute-mr-bob-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
ALICE_OFFER = {
    "resource_id": "compute-mr-alice-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    # New York rather than California so the two providers' inventory is
    # visibly distinct in registry payloads. (The Region enum currently
    # admits California, New York, and Tokyo — see domain_models.Region.)
    "region": "New York, US",
}

_BOB_CSV = (
    "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,"
    "max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,"
    "attribute.vm_host\n"
    'compute-mr-bob-001,compute.gpu,rtx5080,count,1,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
    'RTX 5080,90.0,"California, US",kvm1\n'
)
_ALICE_CSV = (
    "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,"
    "max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,"
    "attribute.vm_host\n"
    'compute-mr-alice-001,compute.gpu,rtx5080,count,1,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,'
    'RTX 5080,90.0,"New York, US",ny1\n'
)


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

@pytest.fixture(scope="module")
def alice_admin_client():
    from storefront_client import SyncStorefrontClient
    url = _require_setting(getattr(settings, "ALICE", None) and settings.ALICE.API_URL, "ALICE.API_URL")
    private_key = _require_setting(settings.ALICE.PRIVATE_KEY, "ALICE.PRIVATE_KEY")
    admin_key = _require_setting(settings.ALICE.ADMIN_API_KEY, "ALICE.ADMIN_API_KEY")
    client = SyncStorefrontClient(
        base_url=url,
        private_key=str(private_key),
        admin_key=str(admin_key),
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
# Inline buyer-side fan-in helper — same shape as in v1 of this file.
# ---------------------------------------------------------------------------

def _list_listings(
    url: str,
    *,
    api_key: Optional[str] = None,
    timeout: float = 5.0,
) -> list[dict[str, Any]]:
    full = url.rstrip("/") + "/listings?status=open&limit=200"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(full, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if isinstance(body, dict):
        return list(body.get("items") or body.get("listings") or [])
    return list(body)


def _list_listings_multi(
    urls: list[str],
    *,
    auth: Optional[dict[str, str]] = None,
    timeout: float = 5.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    auth = auth or {}
    merged: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for url in urls:
        try:
            items = _list_listings(url, api_key=auth.get(url), timeout=timeout)
        except Exception as exc:
            log.warning("[multi-registry] %s list failed: %s", url, exc)
            errors.append(url)
            continue
        for item in items:
            lid = item.get("listing_id") or item.get("id")
            if lid is None:
                continue
            merged.setdefault(str(lid), item)
    return list(merged.values()), errors


# ===========================================================================
# Phase 0 — readiness
# ===========================================================================

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
        resp = httpx.get(
            f"{_REGISTRY_B}/health", timeout=5.0,
            headers={"Authorization": f"Bearer {_REGISTRY_B_TOKEN}"},
        )
        assert resp.status_code == 200, (
            f"registry-b /health returned {resp.status_code}: {resp.text[:200]}"
        )
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

class TestStage02a_BobInventory:
    def test_02a_bob_seeds_inventory(self, storefront_admin_client, mr_state):
        _require(mr_state, "bob_healthy")
        result = storefront_admin_client.admin_import_resources(
            _BOB_CSV.encode("utf-8"), filename="mr-bob-resources.csv",
        )
        assert result.failed_count == 0, f"bob import failed: {result}"
        assert result.imported_count >= 1
        mr_state.bob_inventory_seeded = True


class TestStage02b_AliceInventory:
    def test_02b_alice_seeds_inventory(self, alice_admin_client, mr_state):
        _require(mr_state, "alice_healthy")
        result = alice_admin_client.admin_import_resources(
            _ALICE_CSV.encode("utf-8"), filename="mr-alice-resources.csv",
        )
        assert result.failed_count == 0, f"alice import failed: {result}"
        assert result.imported_count >= 1
        mr_state.alice_inventory_seeded = True


# ===========================================================================
# Phase 3 — create + publish listings on both storefronts
# ===========================================================================

class TestStage03c_BobPublishes:
    def test_03c_bob_creates_and_resumes(
        self, storefront_admin_client, seller_wallet, mr_state
    ):
        _require(
            mr_state, "bob_sees_both", "bob_inventory_seeded"
        )

        resp = storefront_admin_client.create_listing(
            agent_wallet_address=seller_wallet,
            offer=BOB_OFFER,
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
        self, alice_admin_client, alice_wallet, mr_state
    ):
        _require(
            mr_state, "alice_sees_a", "alice_inventory_seeded",
        )

        resp = alice_admin_client.create_listing(
            agent_wallet_address=alice_wallet,
            offer=ALICE_OFFER,
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
        resp = httpx.get(
            f"{_REGISTRY_A}/listings/{mr_state.bob_listing_id}", timeout=5.0,
        )
        assert resp.status_code == 200, (
            f"registry-A {resp.status_code} for bob's listing: {resp.text[:200]}"
        )
        mr_state.bob_in_a = True


class TestStage04b_BobInRegistryB:
    def test_04b_bob_in_b_with_bearer(self, mr_state):
        _require(mr_state, "bob_listing_id")
        resp = httpx.get(
            f"{_REGISTRY_B}/listings/{mr_state.bob_listing_id}",
            timeout=5.0,
            headers={"Authorization": f"Bearer {_REGISTRY_B_TOKEN}"},
        )
        assert resp.status_code == 200, (
            f"registry-B {resp.status_code} for bob's listing: {resp.text[:200]}.\n"
            "If 404: fanout-publish only hit registry-A. Check Bob's "
            "[registry].urls in config.bob.toml."
        )
        mr_state.bob_in_b = True


class TestStage04c_AliceInRegistryA:
    def test_04c_alice_in_a(self, mr_state):
        _require(mr_state, "alice_listing_id")
        resp = httpx.get(
            f"{_REGISTRY_A}/listings/{mr_state.alice_listing_id}", timeout=5.0,
        )
        assert resp.status_code == 200, (
            f"registry-A {resp.status_code} for alice's listing: {resp.text[:200]}"
        )
        mr_state.alice_in_a = True


class TestStage04d_AliceAbsentFromRegistryB:
    def test_04d_alice_not_in_b(self, mr_state):
        """The whole point of Alice's single-registry config: her
        listing must NOT appear in registry-B. If it does, either
        registry-B did some cross-registry sync (it shouldn't) or
        Alice's config was misread and she fanned out to both."""
        _require(mr_state, "alice_listing_id")
        resp = httpx.get(
            f"{_REGISTRY_B}/listings/{mr_state.alice_listing_id}",
            timeout=5.0,
            headers={"Authorization": f"Bearer {_REGISTRY_B_TOKEN}"},
        )
        assert resp.status_code == 404, (
            f"Alice's listing {mr_state.alice_listing_id} unexpectedly present "
            f"in registry-B: status={resp.status_code} body={resp.text[:200]}.\n"
            "Either config.alice.toml grew an extra URL in [registry].urls, or "
            "the registries are syncing across each other."
        )
        mr_state.alice_absent_from_b = True
        log.info("[04d] alice's listing correctly absent from registry-B")


# ===========================================================================
# Phase 5 — buyer-side fan-in discovery
# ===========================================================================

class TestStage05a_FanInUniqueListings:
    def test_05a_fanin_returns_two_unique_listings(self, mr_state):
        """The union over [A, B] should contain exactly two listings:
        Bob's (deduped across A and B) and Alice's (only in A). Without
        per-listing-id dedupe this returns 3 (Bob in A + Bob in B + Alice in A)."""
        _require(
            mr_state, "bob_in_a", "bob_in_b", "alice_in_a", "alice_absent_from_b",
        )
        merged, errors = _list_listings_multi(
            [_REGISTRY_A, _REGISTRY_B],
            auth={_REGISTRY_B: _REGISTRY_B_TOKEN},
        )
        assert errors == [], f"per-URL errors: {errors}"
        all_ids = {str(r.get("listing_id") or r.get("id")) for r in merged}
        assert mr_state.bob_listing_id in all_ids, (
            f"Bob's listing {mr_state.bob_listing_id} missing from union {all_ids}"
        )
        assert mr_state.alice_listing_id in all_ids, (
            f"Alice's listing {mr_state.alice_listing_id} missing from union {all_ids}"
        )
        # Dedupe assertion: each listing appears exactly once.
        ids_list = [str(r.get("listing_id") or r.get("id")) for r in merged]
        assert ids_list.count(mr_state.bob_listing_id) == 1, (
            f"Bob's listing appears {ids_list.count(mr_state.bob_listing_id)} "
            "times in the union — fan-in dedupe regression?"
        )
        assert ids_list.count(mr_state.alice_listing_id) == 1
        mr_state.fanin_ok = True
        log.info(
            "[05a] union over [A, B] = bob + alice, each once "
            "(merged size %d)", len(merged),
        )


class TestStage05b_FanInResilientToDeadRegistry:
    def test_05b_one_dead_registry_doesnt_break_discovery(self, mr_state):
        """Union over [A, DEAD] still finds both listings (both live in
        A; the DEAD URL just errors and gets skipped)."""
        _require(mr_state, "bob_in_a", "alice_in_a")
        merged, errors = _list_listings_multi(
            [_REGISTRY_A, _REGISTRY_DEAD], timeout=2.0,
        )
        assert _REGISTRY_DEAD in errors, f"expected dead URL in errors, got {errors}"
        ids = {str(r.get("listing_id") or r.get("id")) for r in merged}
        assert mr_state.bob_listing_id in ids, f"bob's missing: ids={ids}"
        assert mr_state.alice_listing_id in ids, f"alice's missing: ids={ids}"
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
        from storefront_client import SyncStorefrontClient
        buyer_to_bob = SyncStorefrontClient(
            base_url=str(settings.SELLER.API_URL),
            private_key=str(settings.BUYER.PRIVATE_KEY),
        )
        try:
            resp = buyer_to_bob.negotiate_new(
                listing_id=mr_state.bob_listing_id,
                buyer_address=buyer_config["wallet_address"],
                initial_amount=BUYER_INITIAL_PRICE,
                duration_seconds=DURATION_HOURS * 3600,
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
        from storefront_client import SyncStorefrontClient
        buyer_to_alice = SyncStorefrontClient(
            base_url=str(settings.ALICE.API_URL),
            private_key=str(settings.BUYER.PRIVATE_KEY),
        )
        try:
            resp = buyer_to_alice.negotiate_new(
                listing_id=mr_state.alice_listing_id,
                buyer_address=buyer_config["wallet_address"],
                initial_amount=BUYER_INITIAL_PRICE,
                duration_seconds=DURATION_HOURS * 3600,
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
            pytest.skip("upstream negotiation stages didn't both complete")

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
