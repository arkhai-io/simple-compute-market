"""Full buyer-seller deal lifecycle — sequential e2e test suite.

Stage map
---------
Phase 0 — E2E readiness (all services healthy, no state changes)
  00a  Storefront reachable:    GET /health → status=ok, database=ok
  00b  Registry reachable:      GET /api/v1/system/status → checks.registry=ok
  00c  Provisioning reachable:  GET provisioning /health → status=ok
  00d  Negotiation strategy viable: checks.negotiation_strategy not exit-on-probe
  00e  Provisioning mock mode:  GET /api/v1/system/ansible/readiness → ansible_mode=mock
  00f  Resource seed:           POST /api/v1/admin/portfolio/resources/import
                                upserts the compute row this test needs
  00g  Alkahest configured:     GET /api/v1/system/status → checks.alkahest=ok
                                gates Phase 7b (on-chain escrow verification)
  00h  Provisioning→storefront: GET provisioning /api/v1/system/status →
                                checks.storefront=ok, checks.storefront_auth=ok

Phase 2 — Listing creation (paused)
  02b  Create listing paused + confirm:
         POST /listings/create paused=True → listing_id
         GET /api/v1/listings/{id} → status=open, paused=True
         GET registry/listings → listing absent (publish suppressed)

Phase 3 — Registry publication
  03a  Validate listing publishable: POST registry /api/v1/listings/validate-publish → valid=True
  03b  Resume + registry confirm:
         POST /api/v1/listings/{id}/resume → registry_status=published
         (the publisher is created lazily on this first signed publish)
         GET registry/listings → listing present

Phase 4 — Registry publication
  04a  Primary registry: listing visible in the registry used by this topology

Phase 5 — Negotiation lifecycle
  05a  Evaluate-negotiate dry-run:
         POST /api/v1/admin/listings/{id}/evaluate-negotiate → would_negotiate=True
  05b  Negotiation starts + visible + round confirmed:
         POST /api/v1/negotiate/new → negotiation_id
         GET /api/v1/listings/{id}/negotiations → thread visible
         stage_events: round_decided with decision != exit

Phase 6 — Negotiation settlement
  06b  Force-accept + terminal state:
         Guard: no exit events before force-accept
         POST .../force-accept → action=accept
         GET .../negotiations/{neg_id} → terminal_state=success;
                                          escrows=[] (none until phase 7)

Phase 7 — On-chain escrow + provisioning gate setup
  07   Create real escrow_uid; add provisioning mock rule (pause_before_result=True)
  07b  Verify escrow via storefront dry-run

Phase 8 — Settlement pipeline
  08b  Settlement submitted + fulfillment dispatched:
         POST /api/v1/settle/{uid} → status=provisioning
         wait_for_stage_event(provision, job_submitted)
         GET /settle/{uid}/status → fulfillment_id present, state=dispatching
         (resource identity is confirmed later, via admin introspection, at 09c)

Phase 9 — Provisioning completion
  09a  Release gate + job completes: resume_rule; wait_for_job → succeeded
  09b  Settlement ready + credentials + listing closed:
         wait_for_settlement (server-side long-poll) → ready=True, status=ready
         GET /settle/{uid}/status → status=ready, tenant_credentials present
         GET /api/v1/listings/{id} → status=closed
         GET .../negotiations/{neg_id} → primary escrow status=ready,
                                          fulfillment_uid populated
  09c  Lease registered:
         GET provisioning /api/v1/leases/by-escrow/{uid} -> active/pending lease

Phase 10 — Lease expiry and durable teardown
  10a  Pause automatic lease servicing, arm the provider teardown gate, and
       interrupt the deal through the storefront admin control plane.
  10b  Run one lease cycle → reservation releasing, fulfillment id recorded,
       fulfillment teardown_dispatch_pending, capacity still held.

Phase 11 — Fulfillment convergence and resource release
  11a  Run one fulfillment cycle → tearing_down while capacity remains held.
  11b  Complete provider teardown, converge to torn_down, run one lease cycle →
       released; observe storefront release, capacity reuse, and cleanup.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from importlib import resources

import pytest
from market_alkahest.alkahest import get_recipient_arbiter

from tests.e2e.roles.scenarios.vms.conftest import (
    DealLease,
    DealState,
    delete_mock_rules_if_present,
    require_state,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DEAL_HOST,
    E2E_DEAL_POOL_ID,
    E2E_HOST_GPU_COUNT,
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal

# ---------------------------------------------------------------------------
# Offer / demand spec — constants shared across all stages
# ---------------------------------------------------------------------------

OFFER_RESOURCE = {
    "interruptible": True,
    # Matches E2E_RESOURCE_CSV below. The test imports that CSV through the
    # storefront admin API so it does not depend on a mounted resource file.
    "resource_id": "compute-e2e-deal-001",
    "gpu_model": "RTX 5080",
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
DEMAND_RESOURCE = {
    "token": {
        "symbol": "MOCK",
        # MockERC20 deployed by alkahest at a fixed deterministic address.
        # The buyer (account #1) is pre-funded with it in the baked chain
        # state (see dev-env/generate_state.py). Stage 07 escrows real
        # tokens against this contract so the storefront's pre-settlement
        # on-chain verifier (commit 03e47bf) finds the EAS attestation.
        "contract_address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
        "decimals": 0,   # listing-display only; raw amounts are what land on-chain
    },
    "amount": 10_000,
}
# Listing-side accepted_escrows advertisement. The escrow_address here is a
# stub — the buyer sends the placeholder zero address on its EscrowProposal
# (see negotiate_new's defaults), which skips the accepted-escrow
# (chain, address) strict match; field-level equality on
# literal_fields["token"] is what gates the proposal. The real
# escrow_address used on-chain is what the buyer's CLI resolves through
# alkahest at settle time.
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": DEMAND_RESOURCE["token"]["contract_address"]},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_RESOURCE["amount"])}],
}]

_ALKAHEST_ADDRESSES_PATH = str(
    resources.files("market_storefront.data").joinpath("alkahest_anvil_addresses.json")
)


def _recipient_demands(seller_wallet: str) -> list[dict]:
    return [{
        "chain_name": "anvil",
        "arbiter": get_recipient_arbiter(
            "anvil", config_path=_ALKAHEST_ADDRESSES_PATH,
        ).lower(),
        "demand_data": {"recipient": seller_wallet.lower()},
    }]


DURATION_HOURS = 1
BUYER_INITIAL_PRICE = 7_000    # below seller floor (10_000) — forces counter at round 0
BUYER_MAX_PRICE = 12_000
PROV_RULE_ID = "e2e-create-pause"
REMOVE_RULE_ID = "e2e-remove-pause"   # mock rule that pauses provider teardown
E2E_RESOURCE_ID = "compute-e2e-deal-001"
E2E_RESOURCE_CSV = """resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-e2e-deal-001,compute.gpu,rtx5080,count,1,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm-deal
"""

# ===========================================================================
# Phase 0 — E2E readiness
# ===========================================================================

class TestStage00a_StorefrontHealth:
    def test_00a_storefront_is_healthy(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /health → status=ok, database=ok.

        Validates storefront process is up and SQLite is reachable before
        any state-changing call is made.
        """
        health = storefront_admin_client.get_health()
        assert health.status == "ok", (
            f"Storefront health degraded before test run: {health}"
        )
        db_check = (health.checks or {}).get("database", "absent")
        assert db_check == "ok", (
            f"Storefront database check failed: checks.database={db_check!r}"
        )
        deal_state._storefront_healthy = True
        log.info("[00a] Storefront healthy: status=%s database=%s", health.status, db_check)


class TestStage00b_RegistryReachable:
    def test_00b_registry_reachable_from_storefront(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.registry=ok.

        Uses the storefront's own registry connectivity check — the relevant
        oracle, since it's the storefront that must reach the registry to
        publish listings.
        """
        require_state(deal_state, "_storefront_healthy")
        status = storefront_admin_client.get_system_status()
        registry_check = (status.checks or {}).get("registry", "absent")
        assert registry_check == "ok", (
            f"Storefront cannot reach registry. checks.registry={registry_check!r}.\n"
            f"Verify registry.url in the storefront config points to a reachable "
            f"endpoint from inside the storefront container."
        )
        deal_state._registry_reachable = True
        log.info("[00b] Registry reachable from storefront: checks.registry=%s", registry_check)


class TestStage00c_ProvisioningHealth:
    def test_00c_provisioning_is_healthy(
        self, provisioning_client, deal_state: DealState
    ):
        """GET /api/v1/system/ansible/readiness → playbook.exists=True.

        Uses the ansible readiness endpoint rather than /health because it
        confirms the mock profile is correctly configured — not just that
        the HTTP server is running. In mock mode the playbook points to
        /dev/null which always exists; a missing playbook means the mock
        profile isn't active.
        """
        require_state(deal_state, "_storefront_healthy", "_registry_reachable")
        resp = provisioning_client.get_ansible_readiness()
        playbook_exists = resp.get("playbook", {}).get("exists", False)
        assert playbook_exists, (
            f"Provisioning playbook path does not exist: {resp.get('playbook')}\n"
            "Ensure ACTIVE_PROFILES=mock is set on the provisioning container.\n"
            f"Full response: {resp}"
        )
        deal_state._provisioning_healthy = True
        log.info("[00c] Provisioning ansible readiness: playbook.exists=%s ansible=%s",
                 playbook_exists, resp.get("ansible_version"))


class TestStage00d_NegotiationStrategy:
    def test_00d_negotiation_strategy_is_viable(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.negotiation_strategy not exit-on-probe.

        Catches the rl-strategy-but-no-torch failure mode before any negotiation
        attempt. If this fails, set [seller.negotiation] policies = ['has_matching_inventory_guard', 'escrow_shape_guard', 'bisection']
        in config.toml and restart the storefront.
        """
        require_state(deal_state, "_storefront_healthy", "_registry_reachable")
        status = storefront_admin_client.get_system_status()
        strat = (status.checks or {}).get("negotiation_strategy", "absent")
        assert strat != "absent", (
            "checks.negotiation_strategy missing from /api/v1/system/status. "
            "Rebuild the storefront image with the updated system_controller.py."
        )
        assert "exit_on_probe" not in strat, (
            f"Negotiation strategy would exit every round: {strat!r}\n"
            "Set [seller.negotiation] policies = ['has_matching_inventory_guard', 'escrow_shape_guard', 'bisection'] in config.toml "
            "and restart the storefront."
        )
        deal_state._negotiation_strategy_viable = True
        log.info("[00d] Negotiation strategy viable: %s", strat)


class TestStage00e_ProvisioningMockMode:
    def test_00e_provisioning_is_in_mock_mode(
        self, provisioning_client, deal_state: DealState
    ):
        """GET /api/v1/system/ansible/readiness → ansible_mode=mock.

        Guards the full e2e deal flow from accidentally targeting a production
        provisioning service. If ansible_mode is 'real', any settlement attempt
        would run an actual Ansible playbook against a real KVM host.

        Fix: set provisioning.mockMode=true in the helm values and redeploy,
        or set ACTIVE_PROFILES=production,provisioning-secrets,mock on the
        provisioning container.
        """
        require_state(deal_state, "_provisioning_healthy")
        resp = provisioning_client.get_ansible_readiness()
        mode = resp.get("ansible_mode", "real")
        assert mode == "mock", (
            f"Provisioning service is running in '{mode}' mode, not 'mock'.\n"
            "The e2e deal flow requires mock mode to avoid running real Ansible "
            "playbooks against live infrastructure.\n"
            "Fix: set provisioning.mockMode=true in values.yaml and redeploy, or\n"
            "set ACTIVE_PROFILES=production,provisioning-secrets,mock on the "
            "provisioning container."
        )
        deal_state._provisioning_mock_mode = True
        log.info("[00e] Provisioning mock mode confirmed: ansible_mode=%s", mode)


class TestStage00f_ResourceSeed:
    def test_00f_imports_e2e_resource_inventory(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Import the compute resource row required by this scenario.

        The e2e deal should not depend on a container-mounted CSV. Importing
        an inline fixture through the admin API keeps this scenario
        self-contained while exercising the same upsert path operators use.
        """
        require_state(deal_state, "_storefront_healthy", "_provisioning_mock_mode")

        result = storefront_admin_client.admin_import_resources(
            E2E_RESOURCE_CSV.encode("utf-8"),
            filename="e2e-deal-resources.csv",
        )
        assert result.failed_count == 0, (
            f"E2E resource import failed for {result.failed_count} row(s): {result}"
        )
        assert result.imported_count >= 1, (
            f"Expected at least one imported resource row, got: {result}"
        )

        status = storefront_admin_client.get_system_status()
        assert (status.resource_count or 0) >= 1, (
            f"Storefront still reports no resources after import: {status}"
        )

        deal_state._resources_seeded = True
        log.info(
            "[00f] Imported e2e resource inventory row %s (resource_count=%s)",
            E2E_RESOURCE_ID,
            status.resource_count,
        )


class TestStage00f1_ExecutorHostRegistry:
    def test_00f1_registers_executor_host_and_syncs_projection(
        self, provisioning_client, storefront_admin_client,
        site_capacity_admin_client, deal_state: DealState,
    ):
        """Register this scenario's executor and declare its sellable capacity.

        Two separate stores, and both are required. The host is executor identity;
        the capacity declaration is what `probe`, `reserve`, and the seller's
        inventory guard all match against, and only a declaration creates one.
        With the host alone, every inventory match fails and the storefront refuses
        each negotiation with `no_matching_inventory` — several stages from the
        cause. The declaration's categorical attributes mirror the seeded listing,
        because the guard compares `region` and `gpu_model` by equality.

        The executor is this scenario's own. Sharing one across scenarios is
        incompatible with one declaration per executor, and previously let one
        scenario's GPU count decide another's reservation.

        Registered through the admin API rather than a mounted inventory file:
        `inventory_path` is docker-compose-specific while the canonical Helm
        deployment supplies inventory as an inline secret, and a mount is shared
        state no scenario declares. The storefront is then told to pull
        projections immediately and the pull is asserted, rather than sleeping
        out the poller interval.
        """
        require_state(deal_state, "_resources_seeded")

        host = provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=E2E_DEAL_HOST,
            pool_id=E2E_DEAL_POOL_ID,
            resource_id="compute-e2e-deal-001",
            sellable_units=1,
            attributes={
                "gpu_model": "RTX 5080",
                "region": "California, US",
                "sla": "90.0",
            },
        )
        assert host.name == E2E_DEAL_HOST
        assert (host.gpu_count or 0) >= E2E_HOST_GPU_COUNT, (
            f"executor host {E2E_DEAL_HOST} reports {host.gpu_count} GPU(s); "
            f"scenarios reserve up to {E2E_HOST_GPU_COUNT}"
        )

        sites = refresh_storefront_projections(storefront_admin_client)

        deal_state._executor_host_registered = True
        log.info(
            "[00f1] Executor host %s registered (gpus=%s); projections confirmed for %s",
            E2E_DEAL_HOST, host.gpu_count, sorted(sites),
        )


class TestStage00g_AlkahestConfigured:
    def test_00g_alkahest_is_configured(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.alkahest reports configured chain names.

        Alkahest must be configured before the on-chain escrow phases (07/07b).
        If this fails with alkahest='unconfigured', the storefront config.toml
        is missing all [chains.<name>] entries or none initialised successfully.
        After the multi-chain refactor, ``checks.alkahest`` is a comma-joined
        list of chain names ("anvil,base_sepolia"); the test only requires that
        the expected chain (``anvil`` for this e2e) is present in that list.

        Fix for docker-compose, ensure config.bob.toml contains::

            [chains.anvil]
            rpc_url = "http://anvil:8545"
            alkahest_address_config_path = "/app/src/.../alkahest_anvil_addresses.json"
        """
        require_state(deal_state, "_storefront_healthy")
        status = storefront_admin_client.get_system_status()
        alkahest_check = (status.checks or {}).get("alkahest", "absent")
        assert "anvil" in alkahest_check, (
            f"Storefront alkahest client is not configured for anvil: "
            f"checks.alkahest={alkahest_check!r}\n"
            "The on-chain escrow phases (07, 07b) will fail without a working AlkahestClient.\n"
            "Fix for docker-compose: ensure [chains.anvil] in config.bob.toml has "
            "rpc_url + alkahest_address_config_path set."
        )
        deal_state._alkahest_configured = True
        log.info("[00g] Alkahest configured: checks.alkahest=%s", alkahest_check)


class TestStage00h_ProvisioningStorefrontLink:
    def test_00h_provisioning_can_reach_storefront(
        self, provisioning_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.storefront=ok, checks.storefront_auth=ok.

        Validates that the provisioning service's lease watchdog can reach and
        authenticate to the storefront admin API. This is the connectivity path
        the watchdog uses when it releases leases at expiry:

            provisioning LeaseWatchdog
              → PATCH {storefront_url}/api/v1/admin/portfolio/resources/{id}
                  X-Admin-Key: {storefront_admin_key}

        Two sub-checks from the provisioning health endpoint:
          - storefront      — GET {storefront_url}/health responded 200
          - storefront_auth — GET {storefront_url}/api/v1/system/status with
                              X-Admin-Key responded 200

        If this fails with storefront='unconfigured':
          - For deploy-docker: ensure storefront_url and storefront_admin_key
            are set in provisioning/compute/service/src/compute_provisioning_service/config/config-docker.yml.
            The compose service name resolved by docker DNS is 'bob-storefront'.
          - For Helm: provisioning.storefront.url defaults to the release's
            bob storefront Service; provisioning.storefront.adminKey defaults
            to global.adminApiKey.

        If this fails with storefront='unreachable':
          - Both services must be on the same Docker network.
          - Check that the storefront container is running and healthy (00a/00c).

        If this fails with storefront_auth='unauthorized':
          - The admin key in config-docker.yml / provisioning-secrets must
            match the storefront's admin_api_key in config.bob.toml.
        """
        require_state(deal_state, "_provisioning_healthy", "_storefront_healthy")

        health = provisioning_client.get_system_status()
        checks = health.get("checks", {})

        sf_check = checks.get("storefront", "absent")
        assert sf_check == "ok", (
            f"Provisioning cannot reach storefront: checks.storefront={sf_check!r}\n"
            "The lease watchdog will not be able to release resources when leases expire.\n"
            "For deploy-docker: verify storefront_url in "
            "provisioning/compute/service/src/compute_provisioning_service/config/config-docker.yml points to "
            "'http://bob-storefront:8001' and both containers share the compose "
            "project's default network.\n"
            f"Full health response: {health}"
        )

        auth_check = checks.get("storefront_auth", "absent")
        assert auth_check == "ok", (
            f"Provisioning storefront auth failed: checks.storefront_auth={auth_check!r}\n"
            "The lease watchdog uses X-Admin-Key to authenticate; 'unauthorized' means\n"
            "storefront_admin_key in config-docker.yml does not match the storefront's\n"
            "admin_api_key in config.bob.toml.\n"
            f"Full health response: {health}"
        )

        deal_state._provisioning_storefront_ok = True
        log.info(
            "[00h] Provisioning→storefront link ok: storefront=%s storefront_auth=%s",
            sf_check, auth_check,
        )


# ===========================================================================
# Phase 2 — Listing creation (paused)
# ===========================================================================

class TestStage02b_CreateListingPaused:
    def test_02b_create_listing_paused_local_only(
        self, storefront_admin_client, seller_wallet, registry_client, deal_state: DealState
    ):
        """Create listing with paused=True; confirm locally visible and registry absent.

        Three assertions in one advance step — all validate the single decision
        that paused=True suppresses registry publication:
          1. listing_id returned from create
          2. local GET shows status=open, paused=True
          3. registry GET does NOT contain the listing
        """
        require_state(deal_state, "_resources_seeded", "_registry_reachable")

        resp = storefront_admin_client.create_listing(
            agent_wallet_address=seller_wallet,
            offer=OFFER_RESOURCE,
            accepted_escrows=ACCEPTED_ESCROWS,
            demands=_recipient_demands(seller_wallet),
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, (
            f"No listing_id in response — listing-create returned no id.\n"
            f"Response: {resp}\n"
            f"Check storefront logs for create_listing errors."
        )

        # Confirm locally visible with paused=True
        listing = storefront_admin_client.get_listing(listing_id)
        assert listing.status == "open", (
            f"Expected status=open, got {listing.status!r}"
        )
        assert listing.paused is True, (
            f"Expected paused=True after paused create, got paused={listing.paused}"
        )

        # Confirm registry does NOT yet contain the listing
        result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in result.listings}
        assert listing_id not in ids, (
            f"Listing {listing_id} found in registry before resume — "
            f"paused=True did not suppress the publish."
        )

        deal_state.seller_listing_id = listing_id
        log.info("[02b] Listing %s created (paused=True, absent from registry)", listing_id)


# ===========================================================================
# Phase 3 — Registry publication
# ===========================================================================

# ===========================================================================
# Phase 3a — Validate publish payload (registry dry-run)
# ===========================================================================

class TestStage03a_ValidatePublish:
    def test_03a_listing_payload_validates_against_registry(
        self, registry_client, deal_state: DealState
    ):
        """POST registry /api/v1/listings/validate-publish → valid=True (dry-run).

        Structural pre-flight: confirms the listing's offer/escrows payload
        is recognisable to the registry before resume triggers the actual
        publish. Uses the same ``ACCEPTED_ESCROWS`` constant the create_listing
        call advertised so the dry-run matches the to-be-published shape.
        """
        require_state(deal_state, "seller_listing_id")
        from registry_client import ValidatePublishRequest
        req = ValidatePublishRequest(
            listing_id=deal_state.seller_listing_id,
            storefront_url="http://bob-storefront:8001/",
            offer_resource=OFFER_RESOURCE,
            accepted_escrows=ACCEPTED_ESCROWS,
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        result = registry_client.validate_publish_listing(req)
        assert result.valid, (
            f"Registry validate-publish returned valid=False for listing "
            f"{deal_state.seller_listing_id}.\n"
            f"Errors: {result.errors}\n"
            f"offer_resource_type={result.offer_resource_type!r} "
            f"accepted_escrows_count={result.accepted_escrows_count}"
        )
        deal_state._registry_validate_passed = True
        log.info("[03a] Registry validate-publish: valid=%s offer=%s escrows=%d",
                 result.valid, result.offer_resource_type, result.accepted_escrows_count)


class TestStage03b_ResumePublishesToRegistry:
    def test_03b_resume_listing_publishes_and_registry_confirms(
        self, storefront_admin_client, registry_client, deal_state: DealState
    ):
        """Resume listing → registry_status=published; registry confirms immediately.

        Combined advance + confirm: resume_listing awaits publish_order_to_registry
        synchronously, so when registry_status=published is in the response the
        registry row already exists — no polling required.
        """
        require_state(deal_state, "seller_listing_id", "_registry_validate_passed")

        result = storefront_admin_client.resume_listing(deal_state.seller_listing_id)
        assert result.paused is False, (
            f"Expected paused=False after resume, got: {result}"
        )
        assert result.registry_status == "published", (
            f"Registry publish failed during resume. registry_status={result.registry_status!r}.\n"
            f"Check that registry.url in config.toml is reachable from the storefront container.\n"
            f"Run GET /api/v1/system/status and inspect checks.registry for diagnosis.\n"
            f"Current response: {result}"
        )

        # Confirm local paused flag cleared
        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.paused is False, (
            f"Local listing still shows paused=True after resume: {listing}"
        )

        # Confirm registry now contains the listing (synchronous — publish already committed)
        reg_result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in reg_result.listings}
        assert deal_state.seller_listing_id in ids, (
            f"Listing {deal_state.seller_listing_id} absent from registry immediately after "
            f"resume.\nregistry_status was 'published' but listing not found — "
            f"possible registry indexing inconsistency.\n"
            f"Registry returned {len(ids)} open listings."
        )

        deal_state.resume_confirmed = True
        log.info("[03b] Listing %s resumed; registry_status=%s, registry confirmed",
                 deal_state.seller_listing_id, result.registry_status)


# ===========================================================================
# Phase 4 — Registry publication
# The full-deal happy path uses the primary registry only. Multi-registry
# fan-out/fan-in and private registry auth belong in separate topology-specific
# e2e tests.
# ===========================================================================

# The e2e-tests venv reaches the primary registry directly rather than
# going through CONFIG.indexer_urls, which lives inside the storefront container.
_REGISTRY_A = (
    "http://registry:8080"
    if "docker" in {p.strip() for p in os.environ.get("ACTIVE_PROFILES", "").split(",")}
    else "http://localhost:8080"
)

class TestStage04a_PrimaryRegistryPublish:
    def test_04a_listing_appears_in_primary_registry(
        self, deal_state: DealState
    ):
        """The seller publishes the resumed listing to the primary registry."""
        require_state(deal_state, "resume_confirmed", "seller_listing_id")
        import httpx

        listing_id = deal_state.seller_listing_id
        for url in (_REGISTRY_A,):
            resp = httpx.get(
                f"{url}/listings/{listing_id}", timeout=5.0,
            )
            assert resp.status_code == 200, (
                f"{url} returned {resp.status_code} for listing "
                f"{listing_id} — expected 200. Body: {resp.text[:200]}"
            )
            body = resp.json()
            row = body.get("listing", body)
            assert str(row.get("listing_id") or row.get("id")) == listing_id, (
                f"{url} returned a listing with the wrong id: {row}"
            )
        log.info("[04a] Listing %s present in primary registry", listing_id)


# ===========================================================================
# Phase 5 — Negotiation lifecycle
# (Phase 4 admin pause/resume removed from e2e — see smoke test TODO above)
# ===========================================================================

class TestStage05a_EvaluateNegotiate:
    def test_05a_evaluate_negotiate_would_not_exit(
        self, storefront_admin_client, buyer_config, deal_state: DealState
    ):
        """POST /api/v1/admin/listings/{id}/evaluate-negotiate → would_negotiate=True (dry-run).

        Runs the configured negotiation strategy against BUYER_INITIAL_PRICE
        without creating a thread. Catches price_unreasonable and
        torch_unavailable before committing a real negotiation.
        """
        require_state(deal_state, "seller_listing_id", "resume_confirmed")

        result = storefront_admin_client.evaluate_negotiate(
            deal_state.seller_listing_id,
            proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "0" * 40,
                "fields": {
                    "amount": BUYER_INITIAL_PRICE,
                    "token": DEMAND_RESOURCE["token"]["contract_address"],
                },
                "expiration_unix": 2_000_000_000,
            },
            requested_duration_seconds=DURATION_HOURS * 3600,
            buyer_address=buyer_config["wallet_address"],
        )
        assert result.would_negotiate, (
            f"Strategy would exit at round 0 for BUYER_INITIAL_PRICE={BUYER_INITIAL_PRICE}.\n"
            f"decision={result.decision!r} reason={result.decision_reason!r}\n"
            f"our_reference_amount={result.our_reference_amount} "
            f"their_proposed_amount={result.their_proposed_amount}\n"
            "If reason is 'torch_unavailable': set policies=['has_matching_inventory_guard', 'escrow_shape_guard', 'bisection'] in config.toml.\n"
            "If reason is 'price_unreasonable': increase BUYER_INITIAL_PRICE to >= "
            f"{result.our_reference_amount} (seller floor)."
        )
        assert result.decision == "counter", (
            f"Round-0 strategy returned {result.decision!r}, expected 'counter'. "
            "'accept' means BUYER_INITIAL_PRICE >= the seller floor — lower it, or "
            "force_accept in 06b will 409 on an already-terminal negotiation. "
            "'reject' is a different failure and price is not involved: the seller's "
            "guards run before any concession, and the inventory guard vetoes when no "
            "available capacity declaration matches this listing's region and "
            "gpu_model. Check that stage 00f1's declaration exists and carries both."
        )
        # Every stage from 05b onward gates on this. Nothing set it, so the whole
        # tail of this scenario — negotiation, escrow, settlement, provisioning,
        # lease, teardown — has been skipping rather than running, and a skip
        # reports as a pass at the suite level.
        deal_state._evaluate_negotiate_passed = True


class TestStage05b_NegotiationStartsAndVisible:
    def test_05b_buyer_starts_negotiation_and_thread_confirmed(
        self, storefront_client, storefront_admin_client, buyer_config, deal_state: DealState
    ):
        """Negotiation starts + visible + round-0 confirmed in event stream.

        Combined advance + confirm:
          1. POST /api/v1/negotiate/new → negotiation_id
          2. GET /api/v1/listings/{id}/negotiations → thread listed
          3. GET stage_events → round_decided event with decision != exit
        """
        require_state(deal_state, "seller_listing_id", "_evaluate_negotiate_passed")

        resp = storefront_client.negotiate_new(
            listing_id=deal_state.seller_listing_id,
            buyer_address=buyer_config["wallet_address"],
            initial_amount=BUYER_INITIAL_PRICE,
            provision_terms={
                "kind": "compute.v1",
                "version": 1,
                "payload": {
                    "duration_seconds": DURATION_HOURS * 3600,
                    "ssh_public_key": "",
                },
            },
            token=DEMAND_RESOURCE["token"]["contract_address"],
        )
        neg_id = resp.get("negotiation_id") if isinstance(resp, dict) else None
        assert neg_id, (
            f"No negotiation_id in response: {resp}\n"
            f"POST /api/v1/negotiate/new returned unexpected shape."
        )

        # Confirm thread visible on the listing's negotiations list
        neg_list = storefront_admin_client.list_negotiations(deal_state.seller_listing_id)
        ids = {n.negotiation_id for n in neg_list.negotiations}
        assert neg_id in ids, (
            f"Negotiation {neg_id} not found in "
            f"GET /api/v1/listings/{deal_state.seller_listing_id}/negotiations. Found: {ids}"
        )

        # Verify round-0 decision via stage events — catches strategy misconfiguration
        events_result = storefront_admin_client.get_events(
            stage="negotiation",
            negotiation_id=neg_id,
        )
        round0_events = [e for e in events_result.events if e.event == "round_decided"]
        assert round0_events, (
            f"No 'negotiation/round_decided' stage event found for {neg_id}. "
            "Check that sync_negotiation.py emits stage_event after decide()."
        )
        round0 = round0_events[0]
        assert round0.data.get("decision") == "counter", (
            f"Expected seller to counter at round 0, got decision={round0.data.get('decision')!r}. "
            f"reason={round0.data.get('decision_reason')!r}. "
            f"our_price={round0.data.get('our_amount')} their_price={round0.data.get('their_amount')}.\n"
            "If decision='accept': BUYER_INITIAL_PRICE is at or above the seller's floor — "
            "lower it so round 0 counters rather than accepts immediately "
            "(force_accept in 06b will 409 on an already-terminal negotiation).\n"
            "If decision='exit': increase BUYER_INITIAL_PRICE or check strategy config."
        )

        deal_state.negotiation_id = neg_id
        log.info("[05b] Negotiation %s started; thread visible; round_decided=%s reason=%s",
                 neg_id, round0.data.get("decision"), round0.data.get("decision_reason"))


# ===========================================================================
# Phase 6 — Negotiation settlement
# (06a skipped — force-accept has no meaningful dry-run)
# ===========================================================================

class TestStage06b_ForceAcceptAndTerminal:
    def test_06b_force_accept_and_terminal_success(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Guard + force-accept + terminal state — combined advance + confirm.

        Guard: reads stage events to ensure no exit before force-accept
        (avoids confusing 409 if strategy already exited).
        Advance: POST .../force-accept → action=accept.
        Confirm: GET .../negotiations/{neg_id} → terminal_state=success.
        """
        require_state(deal_state, "seller_listing_id", "negotiation_id")

        # Guard: confirm negotiation is still open (not already terminal)
        events_result = storefront_admin_client.get_events(
            stage="negotiation",
            negotiation_id=deal_state.negotiation_id,
        )
        terminal_events = [
            e for e in events_result.events
            if e.event == "round_decided" and e.data.get("decision") in ("exit", "accept")
        ]
        assert not terminal_events, (
            f"Negotiation {deal_state.negotiation_id} is already terminal before force-accept. "
            f"decision={terminal_events[0].data.get('decision')!r} "
            f"reason={terminal_events[0].data.get('decision_reason')!r}.\n"
            "If decision='accept': BUYER_INITIAL_PRICE is at or above the seller floor — "
            "lower it so the strategy counters at round 0 rather than accepting immediately.\n"
            "If decision='exit': check stage 05b's round_decided event for root cause."
        )

        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        result = storefront_admin_client.force_accept_negotiation(deal_state.seller_listing_id,
            deal_state.negotiation_id,
            amount=agreed,)
        assert result.action == "accept", (
            f"Unexpected action from force-accept: {result}"
        )
        assert result.amount == agreed

        # Confirm terminal state
        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, deal_state.negotiation_id
        )
        assert detail.terminal_state == "success", (
            f"Expected terminal_state=success, got {detail.terminal_state!r}"
        )
        assert detail.agreed_amount == agreed
        # No escrow rows yet — settlement (phase 7+) is what writes them.
        assert detail.escrows == [], (
            f"Expected escrows=[] before phase 7, got {detail.escrows!r}"
        )

        deal_state.agreed_amount = agreed
        deal_state.negotiation_terminal_state = detail.terminal_state
        log.info("[06b] Force-accepted at price %d; terminal_state=%s",
                 agreed, detail.terminal_state)


# ===========================================================================
# Phase 7 — On-chain escrow + provisioning gate setup
# ===========================================================================

class TestStage07_OnChainEscrowAndProvGate:
    def test_07_create_real_escrow_and_arm_gate(
        self, provisioning_test_client, buyer_config, seller_wallet,
        deal_state: DealState,
    ):
        """Create a real on-chain escrow attestation + arm provisioning pause gate.

        Why on-chain (not a placeholder uid): commit 03e47bf added pre-settlement
        verification — the storefront reads the EAS attestation by uid before
        kicking off provisioning. A placeholder uid fails verification.

        What's "buyer interaction" vs "anvil setup": token *distribution*
        is baked into the chain state (account #1 holds MockERC20 — see
        dev-env/generate_state.py). Token *escrow* is part of the deal flow — in
        production the buyer signs and sends this transaction themselves —
        so we do it here from the buyer's wallet, against the just-finalized
        negotiation terms.

        The pause gate (pause_before_result=True) holds the mock provisioning
        job before it reports success, giving stage 08b a window to assert
        queued/running before stage 09a releases it.
        """
        require_state(deal_state, "negotiation_terminal_state", "agreed_amount",
                      "_provisioning_mock_mode")

        from tests.e2e.roles.scenarios.vms.escrow_helper import create_buyer_escrow

        escrow_uid = create_buyer_escrow(
            buyer_private_key=buyer_config["private_key"],
            seller_wallet_address=seller_wallet,
            agreed_amount=int(deal_state.agreed_amount),
            duration_seconds=DURATION_HOURS * 3600,
            token_contract_address=DEMAND_RESOURCE["token"]["contract_address"],
            rpc_url=buyer_config["rpc_url"],
        )
        deal_state.real_escrow_uid = escrow_uid
        log.info("[07] Created on-chain escrow %s for negotiation %s",
                 escrow_uid, deal_state.negotiation_id)

        delete_mock_rules_if_present(
            provisioning_test_client,
            "e2e-buy-create",
            PROV_RULE_ID,
        )
        provisioning_test_client.add_mock_rule(
            rule_id=PROV_RULE_ID,
            match={"vm_action": "create"},
            pause_before_result=True,
            result_stdout=(
                '{"vm_name": "e2e-test-vm", "tenant_user": "vmuser", '
                '"tenant_ssh_key_path": "/tmp/e2e.key", '
                '"frp": {"enabled": false}, '
                '"authentication": {"tenant": {"ssh_commands": '
                '{"external": "ssh vmuser@localhost", '
                '"internal": "ssh vmuser@10.0.0.1"}}}}'
            ),
            fail_with=None,
        )
        deal_state.provisioning_gate_armed = True
        log.info("[07] Provisioning gate armed with rule=%s", PROV_RULE_ID)


# ===========================================================================
# Phase 7b — Verify on-chain escrow via storefront (getRecordFromChain dry-run)
# ===========================================================================

class TestStage07b_VerifyEscrow:
    def test_07b_storefront_verifies_on_chain_escrow(
        self, storefront_admin_client, seller_wallet, deal_state: DealState
    ):
        """POST /api/v1/admin/settle/{uid}/verify → valid=True (dry-run).

        Exercises getRecordFromChain in isolation: reads the escrow from chain
        and confirms token, amount, and seller recipient match. No DB writes.
        """
        require_state(deal_state, "real_escrow_uid", "seller_listing_id", "agreed_amount",
                      "_alkahest_configured")

        result = storefront_admin_client.verify_settle(
            deal_state.real_escrow_uid,
            seller_wallet=seller_wallet,
            agreed_price=deal_state.agreed_amount,
            agreed_duration_seconds=DURATION_HOURS * 3600,
            listing_id=deal_state.seller_listing_id,
        )
        assert result.get("valid") is True, (
            f"Storefront could not verify on-chain escrow {deal_state.real_escrow_uid}.\n"
            f"reason={result.get('reason')!r}\n"
            "Check that the token address, amount, arbiter, and seller wallet "
            "all match what was set at escrow creation time."
        )
        log.info("[07b] Storefront verified escrow %s: valid=True", deal_state.real_escrow_uid)


# ===========================================================================
# Phase 8a — Evaluate settlement job spec (doWork dry-run)
# ===========================================================================

class TestStage08a_EvaluateSettle:
    def test_08a_evaluate_settle_would_submit(
        self, storefront_admin_client, buyer_config, deal_state: DealState
    ):
        """POST /api/v1/admin/settle/{uid}/evaluate → would_submit=True (dry-run).

        Exercises doWork in isolation: resolves a host from inventory and
        builds the provisioning job spec without chain reads, DB writes, or
        provisioning calls (read-only select_available_compute_vm). Confirms
        a matching host exists before committing to settle.
        """
        require_state(deal_state, "real_escrow_uid", "seller_listing_id")

        result = storefront_admin_client.evaluate_settle(
            deal_state.real_escrow_uid,
            listing_id=deal_state.seller_listing_id,
            ssh_public_key=buyer_config["ssh_public_key"],
            duration_seconds=DURATION_HOURS * 3600,
        )
        assert result.get("would_submit") is True, (
            f"evaluate_settle returned would_submit=False.\n"
            f"reason={result.get('reason')!r}\n"
            "Check that at least one compute resource is registered in the "
            "storefront's resource inventory with state='available' and a "
            "vm_host matching the listing's region/gpu_model requirements."
        )
        deal_state._evaluate_settle_vm_host = result.get("vm_host")
        deal_state._evaluate_settle_vm_target = result.get("vm_target")
        deal_state._evaluate_settle_passed = True
        log.info("[08a] Evaluate settle: vm_host=%s vm_target=%s",
                 result.get("vm_host"), result.get("vm_target"))


# ===========================================================================
# Phase 8c — Evaluate provisioning job (provisioning service dry-run)
# ===========================================================================

class TestStage08c_EvaluateProvisioningJob:
    def test_08c_evaluate_provisioning_job(
        self, provisioning_test_client, deal_state: DealState
    ):
        """POST /test/evaluate-job → params_valid=True, rule_matched=PROV_RULE_ID (dry-run).

        Exercises the provisioning service's job routing in isolation:
        confirms the host exists in inventory, the job params are valid,
        and the armed mock rule would match and pause. No job is created.
        """
        require_state(deal_state, "_evaluate_settle_passed", "provisioning_gate_armed")

        vm_host = deal_state._evaluate_settle_vm_host
        assert vm_host, (
            "vm_host not captured from stage 08a — cannot evaluate provisioning job."
        )

        result = provisioning_test_client.evaluate_job(
            vm_host,
            vm_target=deal_state._evaluate_settle_vm_target or "eval-target",
            vm_action="create",
        )
        assert result.get("params_valid") is True, (
            f"Provisioning job params invalid. errors={result.get('errors')!r}"
        )
        assert result.get("host_exists") is True, (
            f"Host {vm_host!r} not found in provisioning inventory."
        )
        assert result.get("rule_matched") == PROV_RULE_ID, (
            f"Expected mock rule {PROV_RULE_ID!r} to match, "
            f"got rule_matched={result.get('rule_matched')!r}."
        )
        assert result.get("would_pause") is True
        deal_state._provision_job_evaluated = True
        log.info("[08c] Provisioning job evaluate: host=%s rule=%s",
                 vm_host, result.get("rule_matched"))


# ===========================================================================
# Phase 8b — Settlement pipeline (advance)
# ===========================================================================

class TestStage08b_SettlementSubmittedAndJobQueued:
    def test_08b_settlement_submitted_and_provisioning_job_queued(
        self, storefront_client, storefront_admin_client, provisioning_client,
        buyer_config, deal_state: DealState
    ):
        """Settlement submitted + fulfillment dispatched — advance + async observe.

        Advance: POST /api/v1/settle/{uid} → status=provisioning.
        Observe (event-driven): wait_for_stage_event(provision, job_submitted)
          then single GET /settle/{uid}/status → fulfillment_id.
        Confirms: fulfillment visible in provisioning API, gated in
          "dispatching" state by the paused mock rule armed in stage 08c.
        """
        require_state(deal_state, "negotiation_id", "real_escrow_uid", "_provision_job_evaluated")

        settle_resp = storefront_client.settle(
            deal_state.real_escrow_uid,
            negotiation_id=deal_state.negotiation_id,
            buyer_address=buyer_config["wallet_address"],
            ssh_public_key=buyer_config["ssh_public_key"],
        )
        assert settle_resp.status == "provisioning", (
            f"Expected status=provisioning, got: {settle_resp.status!r}. "
            f"Full response: {settle_resp}"
        )
        deal_state.settlement_submitted = True

        # job_submitted fires after the DB row is updated; resource_reserved
        # would race because it fires before the job_id exists.
        from tests.e2e.roles.scenarios.vms.conftest import wait_for_stage_event as _wait
        event = _wait(
            storefront_admin_client,
            "provision", "job_submitted",
            listing_id=deal_state.seller_listing_id,
            timeout=15.0,
        )

        status_resp = storefront_client.get_settle_status(
            deal_state.real_escrow_uid,
            buyer_address=buyer_config["wallet_address"],
        )
        # provisioning_job_id is always None for a fulfillment on the
        # durable path (no raw executor job id crosses the buyer-facing
        # boundary); fulfillment_id is that path's durable identity. See
        # core_storefront.models.settle_models.SettleStatusResponse.
        fulfillment_id = status_resp.fulfillment_id
        assert fulfillment_id, (
            f"fulfillment_id absent from settle status after job_submitted event: "
            f"{status_resp}"
        )

        status = provisioning_client.get_fulfillment_status(fulfillment_id)
        assert status.get("state") == "dispatching", (
            f"Expected fulfillment dispatched but gated on the paused mock "
            f"rule, got: {status}"
        )
        deal_state.fulfillment_id = fulfillment_id
        log.info("[08b] Fulfillment %s in state %s", fulfillment_id, status.get("state"))



# ===========================================================================
# Phase 9 — Provisioning completion
# ===========================================================================

class TestStage09a_ProvisioningCompletes:
    def test_09a_release_gate_and_job_succeeds(
        self, provisioning_test_client, provisioning_client, deal_state: DealState
    ):
        """Release the provisioning gate, then deterministically converge
        the fulfillment to a terminal state.

        The durable fulfillment path no longer surfaces a raw Ansible job
        id to the storefront (see stage 08b), so this can't
        ``wait_for_job(<id>)`` the way the legacy direct-dispatch path
        could. Two separate things must happen, neither implied by the
        other:

        1. The gated Ansible job actually finishes once the mock rule
           releases it -- ``drain()`` waits for every outstanding test job
           to reach a terminal state without needing to know its id,
           which is equivalent to waiting for this one specific job in
           this single-deal, single-job e2e scenario.
        2. The *fulfillment* record separately converges to ``active`` only
           once the convergence watchdog observes the provider's terminal
           status (openspec/specs/fulfillment/spec.md's fulfillment
           convergence worker requirement) -- job completion alone doesn't
           advance it. ``run_fulfillment_convergence_cycle()`` triggers
           that deterministically instead of sleeping against its real
           background interval.
        """
        require_state(deal_state, "fulfillment_id")

        provisioning_test_client.resume_rule(PROV_RULE_ID)
        provisioning_test_client.drain(timeout=30)
        provisioning_client.run_fulfillment_convergence_cycle()

        status = provisioning_client.get_fulfillment_status(deal_state.fulfillment_id)
        assert status.get("state") == "active", (
            f"Expected fulfillment to converge to active, got: {status}"
        )
        deal_state.provisioning_result_injected = True
        log.info(
            "[09a] Fulfillment %s converged to active", deal_state.fulfillment_id
        )


class TestStage09b_SettlementReadyAndCredentials:
    def test_09b_settlement_ready_credentials_and_listing_open(
        self, storefront_client, storefront_admin_client, buyer_config, deal_state: DealState
    ):
        """Settlement status=ready, tenant credentials present, listing still open.

        Combined observation of all post-provisioning state:
          1. wait_for_settlement — server-side long-poll until job terminal (no client polling)
          2. GET /settle/{uid}/status → status=ready + tenant_credentials
          3. GET /api/v1/listings/{id} → status=closed
          4. GET .../negotiations/{neg_id} → primary escrow ready + fulfillment_uid
        """
        require_state(deal_state, "real_escrow_uid", "provisioning_result_injected",
                      "seller_listing_id", "negotiation_id")

        wait_result = storefront_admin_client.wait_for_settlement(
            deal_state.real_escrow_uid,
            timeout=60.0,
        )
        assert wait_result.ready, (
            f"Settlement did not reach a terminal state within timeout. "
            f"Last status: {wait_result.status!r} (elapsed {wait_result.elapsed_ms}ms)"
        )
        assert wait_result.status == "ready", (
            f"Settlement reached terminal state but status is not 'ready': {wait_result.status!r}"
        )

        status_resp = storefront_client.get_settle_status(
            deal_state.real_escrow_uid,
            buyer_address=buyer_config["wallet_address"],
        )
        assert status_resp.status == "ready", (
            f"Settlement not 'ready' after provision fulfilled event. "
            f"Got: {status_resp.status!r}"
        )
        assert status_resp.tenant_credentials, (
            f"tenant_credentials missing from settlement status: {status_resp}"
        )

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "closed", (
            f"Expected listing status=closed while capacity is held, got {listing.status!r}"
        )

        # The per-negotiation endpoint is the canonical home for per-deal
        # attestation data (was previously rolled up into the registry's
        # now-removed /system/stats/attestations). After settlement the
        # primary escrow must surface status=ready + a fulfillment_uid.
        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, deal_state.negotiation_id,
        )
        assert detail.escrows, (
            f"Expected escrows[] non-empty after settlement, got {detail.escrows!r}"
        )
        primary = next((e for e in detail.escrows if e["is_primary"]), None)
        assert primary is not None, (
            f"Expected a primary escrow on the negotiation, got {detail.escrows!r}"
        )
        assert primary["escrow_uid"] == deal_state.real_escrow_uid, (
            f"Primary escrow_uid mismatch — endpoint={primary['escrow_uid']!r} "
            f"deal_state={deal_state.real_escrow_uid!r}"
        )
        assert primary["status"] == "ready", (
            f"Expected primary escrow status=ready, got {primary['status']!r}"
        )
        assert primary["fulfillment_uid"], (
            f"Primary escrow missing fulfillment_uid after settlement: {primary!r}"
        )

        deal_state.settlement_status = status_resp.status
        deal_state.tenant_credentials = status_resp.tenant_credentials
        deal_state.seller_listing_final_status = listing.status
        log.info("[09b] Settlement ready; credentials present; listing status=%s; "
                 "primary escrow fulfillment_uid=%s",
                 listing.status, primary["fulfillment_uid"])


class TestStage09c_LeaseRegistered:
    def test_09c_provisioning_lease_registered(
        self, provisioning_client, deal_state: DealState
    ):
        """Provisioning owns the happy-path lease row after fulfillment.

        Resource identity is confirmed here, not at stage 08b, because
        ``resource_id``/``vm_host`` are intentionally opaque across the
        ordinary buyer-facing reservation boundary
        (openspec/specs/site-capacity/spec.md's "Capacity accounting is
        private to the site authority" requirement) -- this admin-only
        ``DealLease`` view (backed by ``get_capacity_reservation``) is a
        legitimate, separate introspection channel from that guarantee,
        not a way around it.
        """
        require_state(
            deal_state,
            "real_escrow_uid",
            "settlement_status",
            "fulfillment_id",
        )

        # DealLease resolves where this deal's lease lives: a site-ledger
        # reservation (remote-capacity mode) or a vm_leases row (embedded).
        lease_view = DealLease(provisioning_client, deal_state.real_escrow_uid)
        lease = lease_view.refresh()
        assert lease.get("escrow_uid") == deal_state.real_escrow_uid
        assert lease.get("settlement_resource_id") == E2E_RESOURCE_ID, (
            "scheduling bound this deal to "
            f"{lease.get('settlement_resource_id')!r}, not the resource it was "
            f"sold as ({E2E_RESOURCE_ID!r})"
        )
        assert lease.get("vm_host") == deal_state._evaluate_settle_vm_host
        # Not `create_job_id`. That field is the legacy executor-job identity and
        # is only ever written by a caller registering a lease with an Ansible job
        # id; a deal that went through the durable fulfillment path has none, by
        # the same rule that keeps `provisioning_job_id` empty on settle status.
        # The durable identity is the fulfillment id, captured at 08b.
        assert deal_state.fulfillment_id, (
            "no durable fulfillment identity for this deal — 08b should have "
            f"recorded one. Lease: {lease}"
        )
        fulfillment = provisioning_client.get_fulfillment_status(
            deal_state.fulfillment_id
        )
        assert fulfillment.get("state"), (
            f"fulfillment {deal_state.fulfillment_id} has no state: {fulfillment}"
        )
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease after happy-path settlement, got: {lease}"
        )

        deal_state.deal_lease = lease_view
        deal_state.reserved_resource_id = lease.get("settlement_resource_id")
        deal_state.lease_id = lease.get("id")
        deal_state.lease_status = lease.get("status")
        log.info(
            "[09c] Lease %s registered for escrow %s (resource=%s status=%s mode=%s)",
            deal_state.lease_id,
            deal_state.real_escrow_uid,
            deal_state.reserved_resource_id,
            deal_state.lease_status,
            "ledger" if lease_view.is_ledger else "legacy",
        )

#: How far back to move a lease end so the watchdog treats it as expired.
#:
#: Bounded on both sides, which is why it is not simply "a long time ago". The
#: lease must be past its end for the watchdog to begin releasing, but it must
#: NOT be past `lease_watchdog_grace_period_seconds` (300s), because the release
#: path marks `release_failed` the moment grace elapses with `vm_remove`
#: unfinished — and stages 11a/11b deliberately hold `vm_remove` at a mock gate.
#: Back-dating two hours put the lease past grace immediately, so the first cycle
#: both dispatched the removal and timed it out.
#:
#: One minute expires the lease and leaves roughly four minutes for the gated
#: stages, which is ample for three stages that make no network waits.
E2E_LEASE_EXPIRY_BACKDATE = timedelta(minutes=1)


def _expired_lease_end() -> str:
    """A lease end the watchdog reads as expired but still inside its grace."""
    return (
        datetime.now(timezone.utc) - E2E_LEASE_EXPIRY_BACKDATE
    ).isoformat().replace("+00:00", "Z")

# ===========================================================================
# Phase 10 — Lease expiry enters durable teardown
# ===========================================================================

class TestStage10a_LeaseExpirySetup:
    def test_10a_expire_lease_and_arm_teardown_gate(
        self, provisioning_client, provisioning_test_client,
        deal_state: DealState,
    ):
        """Expire the deal's lease and hold provider teardown at its gate.

        The watchdog is paused first so the expiry sits unobserved until 10b runs
        one cycle: that keeps the trigger and the reaction as separate, asserted
        steps rather than one race.
        """
        # `deal_lease` is now a dependency: this stage back-dates through it
        # rather than posting an interrupt, so a missing lease view must skip here
        # rather than raise an AttributeError two lines down.
        require_state(deal_state, "lease_id", "real_escrow_uid",
                      "reserved_resource_id", "deal_lease")
        assert provisioning_client.pause_lease_watchdog().get("paused") is True
        delete_mock_rules_if_present(provisioning_test_client, REMOVE_RULE_ID)
        provisioning_test_client.add_mock_rule(
            rule_id=REMOVE_RULE_ID,
            match={"vm_action": "vm_remove"},
            pause_before_result=True,
        )
        # Expire the lease rather than interrupting the deal. Expiry is what ends
        # a lease in production; interruption is an operator escape hatch for a
        # deal sold as interruptible, and driving the main teardown path with the
        # escape hatch left the ordinary path uncovered — `DealLease.backdate`
        # was written for exactly this and had never been called by anything.
        #
        # The watchdog is paused above, so nothing acts on the expiry until 10b
        # runs one cycle deliberately.
        lease = deal_state.deal_lease.backdate(_expired_lease_end())
        assert lease.get("id") == deal_state.lease_id, (
            f"back-dated the wrong reservation: {lease}"
        )
        assert lease.get("status") == "active", (
            "the lease should still read active until a watchdog cycle observes "
            f"the expiry — 10b is what advances it: {lease}"
        )
        deal_state._termination_requested = True


class TestStage10b_LeaseCycleBeginsTeardown:
    def test_10b_lease_cycle_records_fulfillment_id(
        self, provisioning_client, storefront_admin_client, deal_state: DealState,
    ):
        require_state(deal_state, "_termination_requested", "deal_lease",
                      "reserved_resource_id")
        summary = provisioning_client.check_leases()
        assert summary.get("checked", 0) >= 1, summary
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "releasing", lease
        fulfillment_id = lease.get("fulfillment_id")
        assert fulfillment_id, lease
        fulfillment = provisioning_client.get_fulfillment_status(fulfillment_id)
        assert fulfillment.get("state") == "teardown_dispatch_pending", fulfillment
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )
        deal_state.fulfillment_id = fulfillment_id
        deal_state.lease_status = "releasing"


# ===========================================================================
# Phase 11 — Fulfillment convergence and observable release
# ===========================================================================

class TestStage11a_TeardownDispatch:
    def test_11a_convergence_dispatches_teardown_while_capacity_stays_held(
        self, provisioning_client, storefront_admin_client, deal_state: DealState,
    ):
        require_state(deal_state, "fulfillment_id", "reserved_resource_id")
        diagnostics = provisioning_client.run_fulfillment_convergence_cycle()
        assert "before" in diagnostics and "after" in diagnostics
        fulfillment = provisioning_client.get_fulfillment_status(deal_state.fulfillment_id)
        assert fulfillment.get("state") == "tearing_down", fulfillment
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )


class TestStage11b_TeardownCompletion:
    def test_11b_provider_completion_releases_lease_and_capacity(
        self, provisioning_client, provisioning_test_client,
        storefront_admin_client, deal_state: DealState,
    ):
        require_state(deal_state, "fulfillment_id", "lease_id",
                      "reserved_resource_id")
        sync_stage, sync_event = deal_state.deal_lease.released_stage_event
        existing = storefront_admin_client.get_events(limit=500, stage=sync_stage)
        since_id = max((ev.id for ev in existing.events), default=0)

        provisioning_test_client.resume_rule(REMOVE_RULE_ID)
        provisioning_test_client.drain(timeout=30)
        provisioning_client.run_fulfillment_convergence_cycle()
        fulfillment = provisioning_client.get_fulfillment_status(deal_state.fulfillment_id)
        assert fulfillment.get("state") == "torn_down", fulfillment

        release_summary = provisioning_client.check_leases()
        assert release_summary.get("released", 0) >= 1, release_summary
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "released", lease

        from tests.e2e.roles.scenarios.vms.conftest import wait_for_stage_event as _wait
        _wait(storefront_admin_client, sync_stage, sync_event,
              since_id=since_id, timeout=10.0)
        assert not deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )

        reserved_again = storefront_admin_client.admin_reserve_capacity(
            required_attributes={"resource_id": deal_state.reserved_resource_id, "gpu_count": 1},
            escrow_uid=f"{deal_state.real_escrow_uid}-reuse",
        )
        assert reserved_again.resource_id == deal_state.reserved_resource_id
        storefront_admin_client.admin_release_one_reservation(
            reserved_again.resource_id
        )
        deal_state.lease_status = "released"
        provisioning_client.resume_lease_watchdog()
