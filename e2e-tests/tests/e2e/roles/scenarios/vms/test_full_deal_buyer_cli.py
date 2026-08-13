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
         GET registry/listings → listing present

Phase 4 — Registry publication
  04a  Primary registry: listing visible in the registry used by this topology

Phase 5 — Negotiation lifecycle (buyer driven by `market` CLI subprocess)
  05a  Evaluate-negotiate dry-run:
         POST /api/v1/admin/listings/{id}/evaluate-negotiate → would_negotiate=True
  05b  Buyer CLI drives negotiation to agreed terminal:
         `market negotiate --listing-id ... --max-price ...` subprocess
         run_log → run_ended.status="agreed" with agreed_price + negotiation_id
         stage_events on the seller side confirm round_decided

Phase 7 — Provisioning gate setup (no inline buyer action)
  07   Arm provisioning mock rule (pause_before_result=True) for create job

Phase 8 — Settlement pipeline (buyer driven by `market settle` background)
  08i  Buyer CLI initiates settlement:
         `market settle --from <run_id>` background subprocess
         creates the on-chain escrow under the buyer's wallet, POSTs
         /settle/{uid}, then polls; pauses at the provisioning gate.
         wait_for_event("escrow_created") → capture escrow_uid into deal_state
  07b  Verify escrow via storefront dry-run (against the uid emitted above)
  08a  Evaluate-settle dry-run: would_submit=True (post-escrow)
  08c  Evaluate provisioning job: rule_matched=PROV_RULE_ID, would_pause=True
  08b  Post-submit observation:
         wait_for_event("settle_submitted")
         GET /settle/{uid}/status → fulfillment_id present, state=dispatching
         stage_events: provision/job_submitted confirms dispatch started
         (resource identity confirmed later, via admin introspection, at 09c)

Phase 9 — Provisioning completion
  09a  Release gate + job completes: resume_rule; wait_for_job → succeeded
  09b  Buyer observes ready + clean subprocess exit + seller-side state:
         wait_for_event("settle_terminal", predicate=status=="ready")
         body.tenant_credentials present
         Popen.wait → returncode 0
         GET /api/v1/listings/{id} → status=closed
         GET .../negotiations/{neg_id} → primary escrow ready + fulfillment_uid
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

from datetime import datetime, timedelta, timezone
import logging
from importlib import resources

import pytest
from market_alkahest.alkahest import (
    get_alkahest_network,
    get_recipient_arbiter,
    resolve_alkahest_address_config,
)

from src.settings import settings
from tests.e2e.roles.scenarios.vms.conftest import (
    DealLease,
    DealState,
    delete_mock_rules_if_present,
    require_state,
    advance_storefront,
    pause_storefront,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DEAL_CLI_HOST,
    E2E_DEAL_CLI_POOL_ID,
    E2E_HOST_GPU_COUNT,
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal_buyer_cli

# ---------------------------------------------------------------------------
# Offer / demand spec — constants shared across all stages
# ---------------------------------------------------------------------------

OFFER_RESOURCE = {
    "interruptible": True,
    # Matches E2E_RESOURCE_CSV below. The test imports that CSV through the
    # storefront admin API so it does not depend on a mounted resource file.
    "resource_id": "compute-e2e-deal-cli-001",
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
# Listing-side accepted_escrows. The escrow_address is resolved from the
# same alkahest_anvil_addresses.json that ships with market-storefront and
# that the seller's `market publish` flow reads at listing-create time —
# so the listing mirrors what a real seller would publish, and the buyer
# CLI's signed EscrowProposal (which derives the same address from the
# same file) matches under the storefront's strict (chain, address) check.
_ALKAHEST_ADDRESSES_PATH = str(
    resources.files("market_storefront.data").joinpath("alkahest_anvil_addresses.json")
)
_ALKAHEST_CFG = resolve_alkahest_address_config(
    get_alkahest_network("anvil"), config_path=_ALKAHEST_ADDRESSES_PATH,
)
ACCEPTED_ESCROWS = [{
    "chain_name": "anvil",
    "escrow_address": str(
        _ALKAHEST_CFG.erc20_addresses.escrow_obligation_default
    ).lower(),
    "literal_fields": {"token": DEMAND_RESOURCE["token"]["contract_address"]},
    "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_RESOURCE["amount"])}],
}]


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
E2E_RESOURCE_ID = "compute-e2e-deal-cli-001"
E2E_RESOURCE_CSV = """resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-e2e-deal-cli-001,compute.gpu,rtx5080,count,1,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm-deal-cli
"""

# ===========================================================================
# Phase 0 — E2E readiness
# ===========================================================================


class TestStage00_LifecyclePause:
    def test_00_pauses_the_storefront_loops(self, storefront_admin_client):
        """Hold the storefront's timer loops idle for the rest of this scenario.

        A named stage rather than a fixture because every later assertion depends
        on it: with the loops running, a listing status read after a reserve races
        the capacity poller's next cycle, and a defect that reorders two writes
        shows up as an intermittent failure instead of a reproducible one.

        Trading is unaffected — this pauses the loops, not the storefront's
        willingness to negotiate — so the deal stages below still work. Loops are
        held, not stopped: nothing is torn down and no cycle is cut in half. Work
        a loop would have done is requested explicitly from here on, through
        `advance_storefront`.
        """
        pause_storefront(storefront_admin_client)

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
            host=E2E_DEAL_CLI_HOST,
            pool_id=E2E_DEAL_CLI_POOL_ID,
            resource_id="compute-e2e-deal-cli-001",
            sellable_units=1,
            attributes={
                "gpu_model": "RTX 5080",
                "region": "California, US",
                "sla": "90.0",
            },
        )
        assert host.name == E2E_DEAL_CLI_HOST
        assert (host.gpu_count or 0) >= E2E_HOST_GPU_COUNT, (
            f"executor host {E2E_DEAL_CLI_HOST} reports {host.gpu_count} GPU(s); "
            f"scenarios reserve up to {E2E_HOST_GPU_COUNT}"
        )

        sites = refresh_storefront_projections(storefront_admin_client)

        deal_state._executor_host_registered = True
        log.info(
            "[00f1] Executor host %s registered (gpus=%s); projections confirmed for %s",
            E2E_DEAL_CLI_HOST, host.gpu_count, sorted(sites),
        )


class TestStage00g_AlkahestConfigured:
    def test_00g_alkahest_is_configured(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.alkahest reports configured chain names.

        After the multi-chain refactor, ``checks.alkahest`` is a comma-joined
        list of chain names; the test only requires that ``anvil`` is present.
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

        Structural pre-flight: confirms the listing's offer/escrows payload is
        recognisable to the registry before resume triggers the actual publish.
        Uses the same ``ACCEPTED_ESCROWS`` constant the create_listing call
        advertised so the dry-run matches the to-be-published shape.
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

# Primary registry, reached directly from the buyer machine — the same URL
# the seller publishes to. Under the docker profile (buyer running in-network)
# this is the service DNS (http://registry:8080); host/local profiles resolve
# it to the published port (http://localhost:8080).
_REGISTRY_A = str(settings.REGISTRY.API_URL or "http://registry:8080")

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


class TestStage05b_BuyerCliDrivesNegotiation:
    def test_05b_market_negotiate_subprocess_reaches_agreed(
        self, buyer_cli, storefront_admin_client, deal_state: DealState
    ):
        """`market negotiate` subprocess: buyer's wallet, real round-trips, agreed terminal.

        Spawns the buyer's installed ``market`` CLI exactly as a buyer
        would on their own machine. The subprocess:
          - POSTs /api/v1/negotiate/new with the buyer's EIP-191 signature
          - Loops rounds locally: the buyer's BisectionStrategy (minimize)
            decides whether each seller counter is accepted (at or under
            --max-price * 1.01) or itself countered. Convergence is
            deterministic.
          - Exits 0 on agreed, 4 on exited, 2 on usage errors, 3 on
            transport errors.

        With buyer_initial=7000 and seller_floor=10000 the seller counters
        at round 0; with buyer_max=12000 the buyer accepts the seller's
        first counter (8500 — midpoint of 10000 and 7000) because it's
        comfortably under the buyer ceiling. Single-round agreed terminal,
        no admin shortcuts.

        Asserts:
          - subprocess exits 0
          - run-log run_ended.status == "agreed" with agreed_price + negotiation_id
          - seller side recorded a round_decided event for the negotiation
        """
        require_state(deal_state, "seller_listing_id", "_evaluate_negotiate_passed")

        run = buyer_cli.run(
            [
                "negotiate",
                "--listing-id", deal_state.seller_listing_id,
                "--seller", str(settings.SELLER.API_URL),
                "--initial-price", str(BUYER_INITIAL_PRICE),
                "--max-price", str(BUYER_MAX_PRICE),
                "--duration-hours", str(DURATION_HOURS),
                "--token-contract", DEMAND_RESOURCE["token"]["contract_address"],
                "--token-decimals", str(DEMAND_RESOURCE["token"]["decimals"]),
                "--max-rounds", "10",
                "--yes",
            ],
            timeout=120.0,
        )

        assert run.returncode == 0, (
            f"`market negotiate` exited {run.returncode}; expected 0 (agreed).\n"
            f"stdout (tail): {run.stdout()[-2000:]}\n"
            f"stderr (tail): {run.stderr()[-2000:]}"
        )

        events = run.read_events()
        terminal = next(
            (e for e in reversed(events) if e.get("event") == "run_ended"),
            None,
        )
        assert terminal is not None, (
            f"Buyer run-log missing run_ended event. events tail: "
            f"{[e.get('event') for e in events[-5:]]}"
        )
        assert terminal.get("status") == "agreed", (
            f"Expected run_ended.status=agreed, got {terminal.get('status')!r}. "
            f"reason={terminal.get('reason')!r}"
        )
        neg_id = terminal.get("negotiation_id")
        agreed_amount = terminal.get("agreed_amount")
        assert neg_id, f"run_ended missing negotiation_id: {terminal!r}"
        assert agreed_amount is not None, f"run_ended missing agreed_amount: {terminal!r}"

        deal_state.buyer_run_id = run.run_id
        deal_state.negotiation_id = str(neg_id)
        deal_state.agreed_amount = int(agreed_amount)
        deal_state.negotiation_terminal_state = "success"

        # Seller-side sanity: the same round_decided event the synthetic
        # buyer relied on must surface for the real subprocess too.
        events_result = storefront_admin_client.get_events(
            stage="negotiation",
            negotiation_id=neg_id,
        )
        round_events = [e for e in events_result.events if e.event == "round_decided"]
        assert round_events, (
            f"No 'negotiation/round_decided' stage event found for {neg_id}. "
            "The buyer's POST /negotiate/new didn't reach the seller's decide() path."
        )
        log.info(
            "[05b] `market negotiate` run=%s agreed at %s after %s round(s); "
            "seller stage events: %d round_decided",
            run.run_id, agreed_amount, terminal.get("rounds"), len(round_events),
        )


# ===========================================================================
# Phase 7 — Provisioning gate setup (no buyer action — pure test infra)
# ===========================================================================

class TestStage07_ArmProvisioningGate:
    def test_07_arm_provisioning_gate(
        self, provisioning_test_client, deal_state: DealState,
    ):
        """Arm the provisioning mock rule (pause_before_result=True).

        This is test infrastructure, not a buyer action. The pause gate
        holds the mock create job after the buyer's `market settle`
        POSTs /settle/{uid} (in stage 08i) — letting stages 08b/08c
        observe the in-flight state ("provisioning, job submitted,
        not yet complete") before stage 09a releases the gate.

        Escrow creation moved out of this stage entirely: the buyer's
        `market settle` subprocess (stage 08i) creates the on-chain
        escrow under the buyer's wallet, the same way a buyer would in
        production. The test verifies the resulting uid in 07b.
        """
        require_state(deal_state, "negotiation_terminal_state", "agreed_amount",
                      "_provisioning_mock_mode")

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
# Phase 8i — Buyer CLI initiates settlement (background subprocess)
# ===========================================================================

class TestStage08i_BuyerCliInitiatesSettle:
    def test_08i_market_settle_creates_escrow_and_submits(
        self, buyer_cli, deal_state: DealState,
    ):
        """Spawn `market settle --from <run_id>` background; capture escrow uid.

        The subprocess performs three stages in order:
          1. Read the buyer run-log produced by stage 05b
          2. Create the on-chain escrow under the buyer's wallet
             (same alkahest path the storefront verifier reads)
          3. POST /settle/{escrow_uid} to the seller
          4. Poll /settle/{escrow_uid}/status until terminal

        We block here only until `escrow_created` surfaces in the run-log
        — that's enough to give downstream phases the uid for dry-run
        assertions. The rest of the subprocess keeps running, paused at
        the provisioning mock rule (armed in 07), until stage 09a
        releases it.
        """
        require_state(deal_state, "buyer_run_id", "provisioning_gate_armed")

        run = buyer_cli.run(
            [
                "settle",
                "--from", deal_state.buyer_run_id,
                "--token-contract", DEMAND_RESOURCE["token"]["contract_address"],
                "--token-decimals", str(DEMAND_RESOURCE["token"]["decimals"]),
                "--duration-hours", str(DURATION_HOURS),
                "--poll-interval", "1.0",
                "--settlement-timeout", "600",
                "--expiration", "3600",
            ],
            background=True,
        )
        deal_state.settle_run_handle = run

        evt = run.wait_for_event("escrow_created", timeout=60.0)
        uid = evt.get("escrow_uid")
        assert uid, f"escrow_created event missing escrow_uid: {evt!r}"
        deal_state.real_escrow_uid = str(uid)
        log.info(
            "[08i] `market settle` created on-chain escrow %s (run=%s)",
            uid, run.run_id,
        )


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
# Phase 8a/8c — Seller-side pre-flight dry-runs
#
# Both dropped from this scenario. They were "would this settle work?"
# inventory/job-routing checks that ran before the seller's real submit
# in the synthetic-buyer version of this test. With the buyer driving
# the real submit via `market settle`, the resource is reserved by the
# time we could run them — and their narrow coverage is already exercised
# by domains/vms/storefront/tests/integration/test_settle_controller.py
# (evaluate_settle) and provisioning/compute/service/tests/unit/services/
# test_programmable_mock.py (evaluate_job).
# ===========================================================================


# ===========================================================================
# Phase 8b — Settlement pipeline (post-submit observation)
# ===========================================================================

class TestStage08b_SettlementSubmittedAndJobQueued:
    def test_08b_settle_submitted_and_provisioning_job_queued(
        self, storefront_client, storefront_admin_client, provisioning_client,
        buyer_config, deal_state: DealState
    ):
        """Buyer's subprocess submitted /settle; observe in-flight state.

        Sync points (no buyer action — the subprocess is already running):
          1. Buyer run-log: settle_submitted event surfaces after the
             buyer's signed POST /settle/{uid} returns from the seller.
          2. Seller stage events: provision/job_submitted fires, confirming
             dispatch started (resource identity is confirmed later, via
             admin introspection, at 09c -- see that stage's docstring).
          3. Storefront settle/status (buyer-signed): fulfillment_id
             populated. Provisioning service confirms the fulfillment is
             dispatched and gated by the paused mock rule.

        The subprocess remains blocked on /settle/{uid}/status polling
        because the mock pause gate (armed in 07) holds the job before
        it returns success.
        """
        require_state(deal_state, "negotiation_id", "real_escrow_uid",
                      "provisioning_gate_armed", "settle_run_handle")

        run = deal_state.settle_run_handle
        submitted = run.wait_for_event("settle_submitted", timeout=30.0)
        deal_state.settlement_submitted = True
        log.info("[08b] settle_submitted event body: %s",
                 {k: submitted.get(k) for k in ("ts", "body")})

        from tests.e2e.roles.scenarios.vms.conftest import wait_for_stage_event as _wait
        _wait(
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
        # durable path; fulfillment_id is that path's durable identity.
        # See core_storefront.models.settle_models.SettleStatusResponse.
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

        See ``test_full_deal.py``'s stage 09a docstring for why this can't
        ``wait_for_job(<id>)`` the way the legacy direct-dispatch path
        could, and why job completion and fulfillment convergence are two
        separate things that must each be driven explicitly.
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


class TestStage09b_BuyerObservesReadyAndCleanExit:
    def test_09b_settle_terminal_ready_credentials_and_clean_exit(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Buyer subprocess reaches settle_terminal(ready) and exits 0.

        The mock provisioning job succeeded in 09a, so the seller's
        settlement state machine flips to 'ready'. The buyer's polling
        loop picks that up on its next /settle/{uid}/status call and
        appends `settle_terminal` with status=ready and the tenant
        credentials to its run-log, then `run_ended`, then exits.

        Seller-side cross-checks (HTTP, not in the run-log):
          - listing → status open
          - per-negotiation primary escrow → status=ready,
            fulfillment_uid populated
        """
        require_state(deal_state, "real_escrow_uid", "provisioning_result_injected",
                      "seller_listing_id", "negotiation_id", "settle_run_handle")

        run = deal_state.settle_run_handle
        terminal = run.wait_for_event(
            "settle_terminal",
            predicate=lambda e: (e.get("body") or {}).get("status") == "ready",
            timeout=120.0,
        )
        body = terminal.get("body") or {}
        assert body.get("status") == "ready", (
            f"settle_terminal status not ready: {body!r}"
        )
        tenant_credentials = body.get("tenant_credentials") or body.get("connection_details")
        assert tenant_credentials, (
            f"settle_terminal missing tenant credentials: {body!r}"
        )

        rc = run.wait(timeout=20.0)
        assert rc == 0, (
            f"`market settle` exited rc={rc}; expected 0 (ready).\n"
            f"stdout (tail): {run.stdout()[-1500:]}\n"
            f"stderr (tail): {run.stderr()[-1500:]}"
        )

        # Advance, then read. The order matters and is easy to get wrong: a
        # listing fetched before the reconcile reports the state that preceded it,
        # so the assertion passes or fails on when the row was captured rather
        # than on what reconciliation did.
        advance_storefront(storefront_admin_client, "capacity-events")
        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "closed", (
            f"Expected listing status=closed while capacity is held, got {listing.status!r}"
        )

        # Canonical per-deal attestation data on the negotiation endpoint
        # (was previously rolled up into the registry's now-removed
        # /system/stats/attestations).
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

        deal_state.settlement_status = "ready"
        deal_state.tenant_credentials = tenant_credentials
        deal_state.seller_listing_final_status = listing.status
        log.info(
            "[09b] Buyer subprocess settle_terminal=ready (rc=0); listing status=%s; "
            "primary escrow fulfillment_uid=%s",
            listing.status, primary["fulfillment_uid"],
        )


class TestStage09c_LeaseRegistered:
    def test_09c_provisioning_lease_registered(
        self, provisioning_client, deal_state: DealState
    ):
        """Provisioning owns the happy-path lease row after fulfillment.

        Resource identity is confirmed here, not at stage 08b -- see
        ``test_full_deal.py``'s stage 09c docstring for why (opaque
        buyer-facing boundary vs. legitimate admin introspection).
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
        vm_host = lease.get("vm_host")
        assert vm_host, (
            f"Lease missing vm_host; required for stage 10a provider teardown operation: {lease!r}"
        )
        # Not `create_job_id` — the legacy executor-job identity, written only when
        # a caller registers a lease with an Ansible job id. A deal on the durable
        # fulfillment path has none, by the same rule that keeps
        # `provisioning_job_id` empty on settle status.
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease after happy-path settlement, got: {lease}"
        )

        deal_state.deal_lease = lease_view
        deal_state.reserved_resource_id = lease.get("settlement_resource_id")
        deal_state.lease_id = lease.get("id")
        deal_state.lease_status = lease.get("status")
        deal_state.vm_host = vm_host
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

        # Clear the claim, then advance. `drain` has made the Ansible `vm_remove`
        # job terminal, but stage 11a's convergence cycle already read this record
        # while that job was queued and still holds its claim — a claim lease
        # outlives the cycle that took it, so no later cycle can re-read the
        # record until the lease lapses. Clearing it is the deliberate equivalent
        # of waiting the lease out, and is why this stage needs no timing at all.
        #
        # Then the chain in order: convergence sees the finished job and records
        # the fulfillment `torn_down`; the lease cycle polls that fulfillment —
        # the VM release port maps its state onto job status — and, seeing it
        # terminal, finishes the release and returns the units.
        provisioning_client.clear_fulfillment_convergence_claims()
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
        # `PATCH state=available` is the documented single-row release, and the
        # only one that exists: `admin_release_one_reservation` posts to
        # `/portfolio/resources/{id}/release-reservation`, a route no storefront
        # implements — the client method has always 404'd. The fleet-wide
        # endpoint's own docstring points here for "surgical single-row release".
        storefront_admin_client.patch_resource(
            reserved_again.resource_id, state="available"
        )
        deal_state.lease_status = "released"
        provisioning_client.resume_lease_watchdog()
