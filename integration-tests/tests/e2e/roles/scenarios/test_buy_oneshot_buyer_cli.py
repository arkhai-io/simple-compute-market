"""One-shot `market buy` lifecycle — buyer-machine e2e.

Companion to ``test_full_deal_buyer_cli.py``. That suite drives the deal
as two explicit buyer commands (``market negotiate`` then
``market settle --from <run_id>``) so it can pause mid-flight and observe
intermediate seller state. This suite exercises the *other* buyer entry
point: the single ``market buy`` command, which discovers → negotiates →
escrows → settles → polls end to end in one subprocess (the
``run_buy``/``_settle_one`` orchestrator, untested at the live-subprocess
level until now).

Crucially, ``market buy`` is discovery-driven — it has no ``--seller``
override — so it reaches the seller at the URL the registry advertises
(``bob-storefront:8001``). That only resolves from inside the compose
network, which is why this runs on the buyer machine (the ``buyer``
service / ``make test-buyer-machine``), not the host.

Stage map
---------
B0  Readiness:        storefront health + provisioning mock mode + alkahest
B1  Resource seed:    import the buy-specific compute row (distinct gpu_model
                      so discovery returns only this listing)
B2  Publish listing:  create paused → resume → confirm present in registry
B3  Arm provisioning: non-pausing mock create rule that returns tenant creds
B4  market buy:       discovery-driven one-shot reaches status=ready, exit 0
B5  Seller + lease:   listing accepted/closed, primary escrow ready with a
                      fulfillment_uid, provisioning lease registered
"""

from __future__ import annotations

import logging
from importlib import resources

import pytest

from service.clients.alkahest import (
    get_alkahest_network,
    resolve_alkahest_address_config,
)
from src.settings import settings
from tests.e2e.roles.scenarios.conftest import (
    DealState,
    delete_mock_rules_if_present,
    require_state,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_buy

# ---------------------------------------------------------------------------
# Offer / demand spec — distinct from the full-deal suite so the two can
# share a stack: a different resource_id and gpu_model mean discovery
# (filtered by --gpu-model below) returns only this listing.
# ---------------------------------------------------------------------------

BUY_RESOURCE_ID = "compute-e2e-buy-001"
BUY_GPU_MODEL = "RTX 4090"
OFFER_RESOURCE = {
    "resource_id": BUY_RESOURCE_ID,
    "gpu_model": BUY_GPU_MODEL,
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
# MockERC20 at the deterministic alkahest address; buyer (account #1) is
# pre-funded with it in the baked chain state. decimals=0 → raw == display.
DEMAND_TOKEN_ADDRESS = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
DEMAND_AMOUNT = 10_000

_ALKAHEST_ADDRESSES_PATH = str(
    resources.files("market_storefront.data").joinpath("alkahest_anvil_addresses.json")
)
_ALKAHEST_CFG = resolve_alkahest_address_config(
    get_alkahest_network("anvil"), config_path=_ALKAHEST_ADDRESSES_PATH,
)
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": str(
        _ALKAHEST_CFG.erc20_addresses.escrow_obligation_nontierable
    ).lower(),
    "literal_fields": {"token": DEMAND_TOKEN_ADDRESS},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_AMOUNT)}],
}]

DURATION_HOURS = 1
BUYER_INITIAL_PRICE = 7_000     # below the seller floor (10_000) — forces a round-0 counter
BUYER_MAX_PRICE = 12_000        # above floor — buyer accepts the seller's first counter
BUY_RULE_ID = "e2e-buy-create"  # non-pausing mock rule: create job returns immediately

BUY_RESOURCE_CSV = (
    "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,"
    "max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
    f"{BUY_RESOURCE_ID},compute.gpu,rtx4090,count,1,available,10000,{DEMAND_TOKEN_ADDRESS},,"
    f"{BUY_GPU_MODEL},90.0,\"California, US\",kvm1\n"
)

_REGISTRY_A = str(settings.REGISTRY.API_URL or "http://registry:8080")


# ===========================================================================
# Phase B0 — readiness
# ===========================================================================

class TestStageB0_Readiness:
    def test_b0_services_ready_for_buy(
        self, storefront_admin_client, provisioning_client, deal_state: DealState
    ):
        """Storefront healthy, provisioning in mock mode, alkahest configured.

        The buy will create a real on-chain escrow and drive mock
        provisioning, so all three must hold before we seed anything.
        """
        health = storefront_admin_client.get_health()
        assert health.status == "ok", f"Storefront unhealthy: {health}"
        deal_state._storefront_healthy = True

        resp = provisioning_client.get_ansible_readiness()
        mode = resp.get("ansible_mode", "real")
        assert mode == "mock", (
            f"Provisioning must be in mock mode for the e2e buy, got {mode!r}. "
            "Set ACTIVE_PROFILES=...,mock on the provisioning container."
        )
        deal_state._provisioning_mock_mode = True

        status = storefront_admin_client.get_system_status()
        alkahest_check = (status.checks or {}).get("alkahest", "absent")
        assert "anvil" in alkahest_check, (
            f"Storefront alkahest client not configured for anvil: {alkahest_check!r}"
        )
        deal_state._alkahest_configured = True
        log.info("[B0] Ready: storefront=ok provisioning_mode=mock alkahest=%s", alkahest_check)


# ===========================================================================
# Phase B1 — resource seed
# ===========================================================================

class TestStageB1_ResourceSeed:
    def test_b1_imports_buy_resource_inventory(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Import the buy-specific compute row via the admin API."""
        require_state(deal_state, "_storefront_healthy", "_provisioning_mock_mode")

        result = storefront_admin_client.admin_import_resources(
            BUY_RESOURCE_CSV.encode("utf-8"),
            filename="e2e-buy-resources.csv",
        )
        assert result.failed_count == 0, f"Buy resource import failed: {result}"
        assert result.imported_count >= 1, f"No rows imported: {result}"
        deal_state._resources_seeded = True
        log.info("[B1] Imported buy resource %s", BUY_RESOURCE_ID)


# ===========================================================================
# Phase B2 — create + publish listing (so discovery can find it)
# ===========================================================================

class TestStageB2_PublishListing:
    def test_b2_create_and_publish_listing(
        self, storefront_admin_client, seller_wallet, registry_client, deal_state: DealState
    ):
        """Create the listing paused, resume to publish, confirm in registry.

        Discovery reads the registry, so the listing must be published (open)
        there before ``market buy`` runs. Resume publishes synchronously, so
        the registry row exists by the time resume returns.
        """
        require_state(deal_state, "_resources_seeded")

        resp = storefront_admin_client.create_listing(
            agent_wallet_address=seller_wallet,
            offer=OFFER_RESOURCE,
            accepted_escrows=ACCEPTED_ESCROWS,
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, f"No listing_id returned: {resp}"
        deal_state.seller_listing_id = listing_id

        result = storefront_admin_client.resume_listing(listing_id)
        assert result.registry_status == "published", (
            f"Resume did not publish to registry: {result}"
        )

        reg_result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in reg_result.listings}
        assert listing_id in ids, (
            f"Listing {listing_id} absent from registry after resume — discovery "
            f"would not find it. Registry returned {len(ids)} open listings."
        )
        deal_state.resume_confirmed = True
        log.info("[B2] Listing %s published and visible in registry", listing_id)


# ===========================================================================
# Phase B3 — arm provisioning (non-pausing: the one-shot buy runs to ready)
# ===========================================================================

class TestStageB3_ArmProvisioning:
    def test_b3_arm_create_rule_no_pause(
        self, provisioning_test_client, deal_state: DealState
    ):
        """Arm a mock create rule that returns tenant creds without pausing.

        Unlike the staged full-deal suite (which pauses the create job to
        observe in-flight state), the one-shot buy is a single blocking
        command — so the create job must complete on its own for the buy to
        reach status=ready.
        """
        require_state(deal_state, "_provisioning_mock_mode", "resume_confirmed")

        delete_mock_rules_if_present(
            provisioning_test_client,
            BUY_RULE_ID,
            "e2e-create-pause",
        )
        provisioning_test_client.add_mock_rule(
            rule_id=BUY_RULE_ID,
            match={"vm_action": "create"},
            pause_before_result=False,
            result_stdout=(
                '{"vm_name": "e2e-buy-vm", "tenant_user": "vmuser", '
                '"tenant_ssh_key_path": "/tmp/e2e-buy.key", '
                '"frp": {"enabled": false}, '
                '"authentication": {"tenant": {"ssh_commands": '
                '{"external": "ssh vmuser@localhost", '
                '"internal": "ssh vmuser@10.0.0.1"}}}}'
            ),
            fail_with=None,
        )
        deal_state.provisioning_gate_armed = True
        log.info("[B3] Provisioning create rule armed (no pause): %s", BUY_RULE_ID)


# ===========================================================================
# Phase B4 — the one-shot `market buy`
# ===========================================================================

class TestStageB4_MarketBuy:
    def test_b4_market_buy_reaches_ready(
        self, buyer_cli, deal_state: DealState
    ):
        """`market buy` discovers, negotiates, escrows, settles, polls → ready.

        Pure discovery (no --seller): the buyer resolves the seller from the
        registry-advertised storefront_url and reaches it over the network.
        Filtering by --gpu-model returns only this suite's listing.

        Explicit prices + --token-contract mirror the full-deal suite:
        initial 7000 (below the 10000 seller floor → round-0 counter), max
        12000 (above floor → buyer accepts the seller's first counter).
        """
        require_state(deal_state, "seller_listing_id", "provisioning_gate_armed")

        run = buyer_cli.run(
            [
                "buy",
                "--gpu-model", BUY_GPU_MODEL,
                "--initial-price", str(BUYER_INITIAL_PRICE),
                "--max-price", str(BUYER_MAX_PRICE),
                "--token-contract", DEMAND_TOKEN_ADDRESS,
                "--token-decimals", "0",
                "--duration-hours", str(DURATION_HOURS),
                "--chain", "anvil",
                "--max-matches", "5",
                "--max-rounds", "10",
                "--poll-interval", "1.0",
                "--settlement-timeout", "300",
                "--expiration", "3600",
                "--yes",
            ],
            timeout=300.0,
        )

        assert run.returncode == 0, (
            f"`market buy` exited {run.returncode}; expected 0 (ready).\n"
            f"stdout (tail): {run.stdout()[-2500:]}\n"
            f"stderr (tail): {run.stderr()[-2500:]}"
        )

        events = run.read_events()
        terminal = next(
            (e for e in reversed(events) if e.get("event") == "run_ended"), None,
        )
        assert terminal is not None, (
            f"Buy run-log missing run_ended. events tail: "
            f"{[e.get('event') for e in events[-6:]]}"
        )
        assert terminal.get("status") == "ready", (
            f"Expected run_ended.status=ready, got {terminal.get('status')!r}. "
            f"reason={terminal.get('reason')!r}"
        )
        escrow_uid = terminal.get("escrow_uid")
        neg_id = terminal.get("negotiation_id")
        assert escrow_uid, f"run_ended missing escrow_uid: {terminal!r}"
        assert neg_id, f"run_ended missing negotiation_id: {terminal!r}"
        assert terminal.get("fulfillment_uid"), (
            f"run_ended missing fulfillment_uid (settlement not attested): {terminal!r}"
        )

        # The escrow_created event must precede the terminal — confirms the
        # one-shot actually created an on-chain escrow under the buyer wallet.
        assert any(e.get("event") == "escrow_created" for e in events), (
            "No escrow_created event in the buy run-log."
        )

        deal_state.real_escrow_uid = str(escrow_uid)
        deal_state.negotiation_id = str(neg_id)
        deal_state.settlement_status = "ready"
        log.info(
            "[B4] `market buy` run=%s reached ready: escrow=%s negotiation=%s fulfillment=%s",
            run.run_id, escrow_uid, neg_id, terminal.get("fulfillment_uid"),
        )


# ===========================================================================
# Phase B5 — seller-side + provisioning lease cross-checks
# ===========================================================================

class TestStageB5_SellerAndLease:
    def test_b5_seller_state_and_lease_registered(
        self, storefront_admin_client, provisioning_client, deal_state: DealState
    ):
        """Seller marked the listing accepted/closed; provisioning owns a lease.

        Cross-machine confirmation that the buyer's one-shot landed real
        state on the seller side: the listing left ``open``, the per-deal
        primary escrow is ``ready`` with a fulfillment_uid, and the
        provisioning service registered a lease for the escrow.
        """
        require_state(deal_state, "real_escrow_uid", "negotiation_id",
                      "seller_listing_id", "settlement_status")

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status in ("accepted", "closed"), (
            f"Expected listing accepted/closed after buy, got {listing.status!r}"
        )

        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, deal_state.negotiation_id,
        )
        primary = next((e for e in (detail.escrows or []) if e["is_primary"]), None)
        assert primary is not None, (
            f"No primary escrow on the negotiation: {detail.escrows!r}"
        )
        assert primary["escrow_uid"] == deal_state.real_escrow_uid, (
            f"Primary escrow_uid mismatch: endpoint={primary['escrow_uid']!r} "
            f"buy={deal_state.real_escrow_uid!r}"
        )
        assert primary["status"] == "ready", (
            f"Expected primary escrow status=ready, got {primary['status']!r}"
        )
        assert primary["fulfillment_uid"], (
            f"Primary escrow missing fulfillment_uid: {primary!r}"
        )

        lease = provisioning_client.get_lease_by_escrow(deal_state.real_escrow_uid)
        assert lease.get("escrow_uid") == deal_state.real_escrow_uid
        assert lease.get("resource_id") == BUY_RESOURCE_ID, (
            f"Lease bound to unexpected resource {lease.get('resource_id')!r}; "
            f"expected {BUY_RESOURCE_ID!r}. Lease: {lease}"
        )
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease, got {lease.get('status')!r}: {lease}"
        )
        deal_state.reserved_resource_id = BUY_RESOURCE_ID
        log.info(
            "[B5] Seller listing=%s; primary escrow ready (fulfillment=%s); lease=%s status=%s",
            listing.status, primary["fulfillment_uid"], lease.get("id"), lease.get("status"),
        )
