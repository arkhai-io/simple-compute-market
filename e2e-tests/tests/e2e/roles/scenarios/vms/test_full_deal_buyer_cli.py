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
         GET /settle/{uid}/status → provisioning_job_id present
         stage_events: provision/job_submitted with resource_id==E2E_RESOURCE_ID

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

Phase 10 — Lease expiry setup and watchdog advance to releasing
  10a  Setup: pause watchdog, arm check mock rule, patch lease_end_utc to past,
       dry-run evaluate_job → rule_matched=check-gate, would_pause=True
  10b  Trigger check-leases cycle → lease transitions to releasing,
       check_job_id written; storefront resource still leased

Phase 11 — VM cleanup confirmation and resource release
  11a  Assert releasing state holds: check job paused, resource still leased.
       Represents stable "VM being torn down, not yet available" invariant —
       structurally identical to the planned vm_destroy rework.
  11b  Release check gate, trigger another check-leases cycle →
       lease released, storefront resource available; resume watchdog
"""

from __future__ import annotations

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
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal_buyer_cli

# ---------------------------------------------------------------------------
# Offer / demand spec — constants shared across all stages
# ---------------------------------------------------------------------------

OFFER_RESOURCE = {
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
        _ALKAHEST_CFG.erc20_addresses.escrow_obligation_nontierable
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
CHECK_RULE_ID = "e2e-check-pause"   # mock rule that pauses the lease check job
E2E_RESOURCE_ID = "compute-e2e-deal-001"
E2E_RESOURCE_CSV = """resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host
compute-e2e-deal-001,compute.gpu,rtx5080,count,1,available,10000,0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0,,RTX 5080,90.0,"California, US",kvm1
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
            are set in domains/vms/provisioning/service/src/config/config-docker.yml.
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
            "domains/vms/provisioning/service/src/config/config-docker.yml points to "
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
            f"Strategy accepted at round 0 for BUYER_INITIAL_PRICE={BUYER_INITIAL_PRICE}. "
            "This means BUYER_INITIAL_PRICE >= seller floor. Lower it so the strategy "
            "counters at round 0 — otherwise force_accept in 06b will 409 on an "
            "already-terminal negotiation."
        )
        deal_state._evaluate_negotiate_passed = True
        log.info("[05a] Evaluate-negotiate: decision=%s reason=%s strategy=%s",
                 result.decision, result.decision_reason, result.strategy)


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
# (evaluate_settle) and domains/vms/provisioning/service/src/tests/unit/services/
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
          2. Seller stage events: provision/job_submitted carries the
             reserved resource_id; assert it matches E2E_RESOURCE_ID.
          3. Storefront settle/status (buyer-signed): provisioning_job_id
             populated. Provisioning service confirms job exists.

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
        prov_job_id = status_resp.provisioning_job_id
        assert prov_job_id, (
            f"provisioning_job_id absent from settle status after job_submitted event: "
            f"{status_resp}"
        )

        job = provisioning_client.get_job(prov_job_id)
        assert job.status in ("queued", "running", "succeeded"), (
            f"Unexpected job status: {job.status}"
        )
        deal_state.provisioning_job_id = prov_job_id
        deal_state.reserved_resource_id = event.data.get("resource_id")
        assert deal_state.reserved_resource_id == E2E_RESOURCE_ID, (
            f"Settlement reserved unexpected resource "
            f"{deal_state.reserved_resource_id!r}; expected {E2E_RESOURCE_ID!r}. "
            f"job_submitted event: {event}"
        )
        log.info("[08b] Provisioning job %s in state %s (reserved=%s)",
                 prov_job_id, job.status, deal_state.reserved_resource_id)


# ===========================================================================
# Phase 9 — Provisioning completion
# ===========================================================================

class TestStage09a_ProvisioningCompletes:
    def test_09a_release_gate_and_job_succeeds(
        self, provisioning_test_client, deal_state: DealState
    ):
        """Release provisioning gate then long-poll until job succeeds."""
        require_state(deal_state, "provisioning_job_id")

        provisioning_test_client.resume_rule(PROV_RULE_ID)

        result = provisioning_test_client.wait_for_job(
            deal_state.provisioning_job_id, timeout=30
        )
        assert result["status"] == "succeeded", (
            f"Expected succeeded, got {result['status']!r}. "
            f"Error: {result.get('error')}"
        )
        deal_state.provisioning_result_injected = True
        log.info("[09a] Provisioning job %s succeeded", deal_state.provisioning_job_id)


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
        """Provisioning owns the happy-path lease row after fulfillment."""
        require_state(
            deal_state,
            "real_escrow_uid",
            "settlement_status",
            "reserved_resource_id",
            "provisioning_job_id",
        )

        # DealLease resolves where this deal's lease lives: a site-ledger
        # allocation (remote-capacity mode) or a vm_leases row (embedded).
        lease_view = DealLease(provisioning_client, deal_state.real_escrow_uid)
        lease = lease_view.refresh()
        assert lease.get("escrow_uid") == deal_state.real_escrow_uid
        assert lease.get("resource_id") == deal_state.reserved_resource_id
        assert lease.get("resource_id") == E2E_RESOURCE_ID
        vm_host = lease.get("vm_host")
        assert vm_host, (
            f"Lease missing vm_host; required for stage 10a check job: {lease!r}"
        )
        assert lease.get("create_job_id") in (None, deal_state.provisioning_job_id)
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease after happy-path settlement, got: {lease}"
        )

        deal_state.deal_lease = lease_view
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

# ===========================================================================
# Phase 10 — Lease expiry setup and watchdog advance to releasing
# ===========================================================================

class TestStage10a_LeaseExpirySetup:
    def test_10a_setup_lease_expiry_and_arm_check_gate(
        self,
        provisioning_client,
        provisioning_test_client,
        deal_state: DealState,
    ):
        """Prepare deterministic control over the lease expiry lifecycle.

        Three setup steps run before any watchdog cycle is triggered:

        1. Pause the watchdog — no background timer cycles will fire from this
           point. The test drives all advances explicitly via check-leases.
        2. Arm check mock rule — a paused ProgrammableMockAnsibleService rule
           for vm_action=check will hold the check job in a non-terminal state,
           keeping the lease in 'releasing' long enough for phase 10b and 11a
           assertions.
        3. Back-date lease_end_utc to the past — the watchdog sees an expired
           active lease on the next check-leases cycle.

        Dry-run validation via evaluate_job confirms the check rule is armed
        before any live cycle is triggered.

        Forward-compatibility note: when the planned rework replaces the check
        job with a vm_destroy Ansible job, only the mock rule's vm_action field
        changes (check → destroy). The structural test shape — pause, arm rule,
        back-date, cycle, assert releasing, release gate, cycle, assert released
        — is identical regardless of the underlying Ansible action.
        """
        require_state(deal_state, "lease_id", "settlement_status",
                      "vm_host", "_provisioning_storefront_ok")

        # Step 1 — pause the watchdog timer
        result = provisioning_test_client.pause_watchdog()
        assert result.get("paused") is True, (
            f"Failed to pause watchdog: {result}"
        )
        log.info("[10a] Watchdog paused")

        # Step 2 — arm mock rule that pauses the check job
        provisioning_test_client.add_mock_rule(
            rule_id=CHECK_RULE_ID,
            match={"vm_action": "check"},
            pause_before_result=True,
        )
        log.info("[10a] Check mock rule %r armed (pause_before_result=True)", CHECK_RULE_ID)

        # Dry-run: confirm evaluate_job sees the rule before we fire a real cycle.
        # vm_host comes from the lease (captured in 09c) — the synthetic
        # buyer flow used to source it from the 08a dry-run, dropped in
        # the buyer-CLI rewrite.
        eval_result = provisioning_test_client.evaluate_job(
            host=deal_state.vm_host,
            vm_target="eval-target",
            vm_action="check",
        )
        assert eval_result.get("params_valid") is True, (
            f"evaluate_job params rejected: {eval_result.get('errors')}"
        )
        assert eval_result.get("rule_matched") == CHECK_RULE_ID, (
            f"Expected check mock rule {CHECK_RULE_ID!r} to match, "
            f"got rule_matched={eval_result.get('rule_matched')!r}.\n"
            f"Registered rules: {provisioning_test_client.list_mock_rules()}"
        )
        assert eval_result.get("would_pause") is True, (
            f"Check rule matched but would_pause=False — rule not armed correctly: {eval_result}"
        )
        log.info("[10a] evaluate_job dry-run: rule_matched=%s would_pause=%s",
                 eval_result.get("rule_matched"), eval_result.get("would_pause"))

        # Step 3 — back-date lease_end_utc so the next cycle sees an expired lease
        from datetime import datetime, timedelta, timezone as _tz
        past_end = (datetime.now(_tz.utc) - timedelta(seconds=30)).isoformat()
        updated = deal_state.deal_lease.backdate(past_end)
        assert updated.get("id") == deal_state.lease_id, (
            f"backdate returned unexpected lease: {updated}"
        )
        log.info(
            "[10a] lease_end_utc back-dated to %s for lease %s",
            past_end, deal_state.lease_id,
        )

        deal_state._lease_expiry_armed = True


class TestStage10b_WatchdogAdvancesToReleasing:
    def test_10b_check_leases_transitions_to_releasing(
        self,
        provisioning_client,
        storefront_admin_client,
        deal_state: DealState,
    ):
        """POST /api/v1/system/check-leases → lease=releasing, check_job_id written.

        check-leases bypasses the watchdog pause flag, so this fires exactly
        one lifecycle cycle. The check mock rule is still holding, so the
        submitted check job will pause before returning a result — this keeps
        the lease in 'releasing' for the 11a assertion.

        The storefront resource must still be 'leased' at this point — the
        watchdog has not confirmed VM cleanup yet.
        """
        require_state(deal_state, "_lease_expiry_armed", "lease_id",
                      "reserved_resource_id")

        result = provisioning_client.check_leases()
        assert result.get("checked", 0) >= 1 or result.get("released", 0) >= 1, (
            f"Expected at least one lease processed, got: {result}\n"
            "Ensure lease_end_utc was back-dated in stage 10a and the lease "
            "is in 'active' status."
        )
        log.info("[10b] check-leases result: %s", result)

        # Fetch updated lease — expect 'releasing' now that check job was submitted
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "releasing", (
            f"Expected lease status='releasing' after check-leases cycle, "
            f"got {lease.get('status')!r}.\n"
            f"Full lease: {lease}\n"
            "If status='released' the check job completed before this assertion — "
            "ensure CHECK_RULE_ID mock rule is armed and the job_service is wired."
        )
        assert lease.get("check_job_id") is not None, (
            f"check_job_id should be set after transitioning to 'releasing': {lease}"
        )
        log.info("[10b] Lease %s is releasing (check_job=%s)",
                 deal_state.lease_id, lease.get("check_job_id"))

        # The deal's capacity must still be held — VM not yet confirmed gone
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id,
        ), (
            f"Capacity for {deal_state.reserved_resource_id!r} should still be "
            "held while the check job is pending."
        )
        log.info("[10b] Capacity for %s still held (VM not yet confirmed gone)",
                 deal_state.reserved_resource_id)

        deal_state.check_job_id = lease.get("check_job_id")
        deal_state.lease_status = "releasing"


# ===========================================================================
# Phase 11 — VM cleanup confirmation and resource release
# ===========================================================================

class TestStage11a_VerifyReleasingState:
    def test_11a_releasing_state_holds_while_check_job_pending(
        self,
        provisioning_client,
        storefront_admin_client,
        deal_state: DealState,
    ):
        """Assert the 'releasing' invariant: check job not yet done, resource still leased.

        This stage has no side effects — it only reads state. It validates the
        boundary condition where:
          - The provisioning service knows the lease is expiring (status=releasing)
          - The Ansible check job is submitted but not yet complete (paused by mock)
          - The storefront resource has not been released yet (state=leased)

        This observable invariant is structurally identical to the state the
        system will enter when the planned rework replaces the check action with
        a vm_destroy Ansible job. In both cases, 'releasing' means "cleanup
        initiated, not yet confirmed" and the storefront resource must remain
        unavailable until the provisioning service confirms cleanup is done.

        If the lease is already 'released' here, the check job completed before
        this assertion — ensure the CHECK_RULE_ID mock gate is still armed.
        """
        require_state(deal_state, "lease_status", "check_job_id", "reserved_resource_id")
        assert deal_state.lease_status == "releasing", (
            f"Stage 10b did not leave lease in 'releasing' state. "
            f"Current: {deal_state.lease_status!r}"
        )

        # Check job must be in a non-terminal state (paused by mock rule)
        job = provisioning_client.get_job(deal_state.check_job_id)
        assert job.status in ("queued", "running"), (
            f"Check job {deal_state.check_job_id!r} is already terminal: "
            f"status={job.status!r}.\n"
            "The mock pause gate may not be armed — CHECK_RULE_ID rule may be missing."
        )
        log.info("[11a] Check job %s is %s (paused by mock gate — VM not yet confirmed gone)",
                 deal_state.check_job_id, job.status)

        # The deal's capacity must still be held
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id,
        ), (
            f"Capacity for {deal_state.reserved_resource_id!r} should remain "
            "held while VM cleanup is in progress."
        )
        log.info("[11a] Capacity for %s still held — watchdog has not released it yet",
                 deal_state.reserved_resource_id)


class TestStage11b_WatchdogReleasesResource:
    def test_11b_release_check_gate_and_confirm_resource_available(
        self,
        provisioning_client,
        provisioning_test_client,
        storefront_admin_client,
        deal_state: DealState,
    ):
        """Release check gate → check job succeeds → watchdog patches resource to available.

        Three steps:
        1. resume_rule(CHECK_RULE_ID) — unblocks the check job; mock returns success.
        2. wait_for_job(check_job_id) — long-poll until the job reaches a terminal state.
        3. check-leases — watchdog sees the succeeded check job, patches storefront,
           transitions lease to 'released'.

        Final assertions:
          - lease.status == 'released'
          - storefront resource.state == 'available'

        Teardown: resume_watchdog() so background timer cycles work normally
        after the test module completes.
        """
        require_state(deal_state, "check_job_id", "lease_id",
                      "reserved_resource_id", "_lease_expiry_armed")

        # Step 1 — unblock the check job
        provisioning_test_client.resume_rule(CHECK_RULE_ID)
        log.info("[11b] Released check gate (rule=%s)", CHECK_RULE_ID)

        # Step 2 — wait for the check job to complete
        job_result = provisioning_test_client.wait_for_job(
            deal_state.check_job_id, timeout=30
        )
        assert job_result.get("status") == "succeeded", (
            f"Check job {deal_state.check_job_id!r} did not succeed: {job_result}"
        )
        log.info("[11b] Check job %s succeeded", deal_state.check_job_id)

        # Snapshot the storefront's latest release-notification event id
        # before triggering the watchdog cycle. Embedded mode delivers
        # the release as a resource PATCH (lease_lifecycle.resource_released);
        # ledger mode delivers a deal-scoped capacity-released event
        # (fulfillment.capacity_released). Either lands *after*
        # check_leases() returns — we need a sync point below.
        #
        # Filter by stage so the row count stays small (one event per
        # past test run); the events endpoint orders ASC and caps at
        # 500, so an unfiltered snapshot would miss the latest events
        # once enough total stage events accumulate across runs.
        sync_stage, sync_event = deal_state.deal_lease.released_stage_event
        existing_lifecycle = storefront_admin_client.get_events(
            limit=500, stage=sync_stage,
        )
        since_id = max((ev.id for ev in existing_lifecycle.events), default=0)

        # Step 3 — trigger the lifecycle cycle that processes the completed check job
        result = provisioning_client.check_leases()
        assert result.get("released", 0) >= 1, (
            f"Expected at least one lease released, got: {result}\n"
            "The check job succeeded but the watchdog cycle did not release the lease. "
            "Check _process_releasing_lease in lease_lifecycle_service.py."
        )
        log.info("[11b] check-leases result: %s", result)

        # Lease must be 'released'
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "released", (
            f"Expected lease status='released', got {lease.get('status')!r}.\n"
            f"Full lease: {lease}"
        )
        log.info("[11b] Lease %s released", deal_state.lease_id)

        # Wait for the storefront to confirm the release landed on its
        # side. The notification races check_leases()'s response — the
        # cycle finishes the release before the storefront call resolves.
        from tests.e2e.roles.scenarios.vms.conftest import wait_for_stage_event as _wait
        _wait(
            storefront_admin_client,
            sync_stage, sync_event,
            since_id=since_id,
            timeout=10.0,
        )

        # The deal's capacity must be back in the pool
        assert not deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id,
        ), (
            f"Capacity for {deal_state.reserved_resource_id!r} should be available "
            "after lease release.\n"
            "The watchdog may have failed to release/notify. Check provisioning "
            "logs for [LEASE_LIFECYCLE] errors and verify storefront_url / "
            "storefront_admin_key are configured in the provisioning service settings."
        )
        log.info("[11b] Capacity for %s is available — lease lifecycle complete",
                 deal_state.reserved_resource_id)

        deal_state.lease_status = "released"

        # Teardown — resume watchdog so background timer cycles work normally
        provisioning_test_client.resume_watchdog()
        log.info("[11b] Watchdog resumed — lease lifecycle test complete")
