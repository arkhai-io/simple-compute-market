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
  08b  Settlement submitted + job queued:
         POST /api/v1/settle/{uid} → status=provisioning
         wait_for_stage_event(provision, job_submitted)
         GET /settle/{uid}/status → provisioning_job_id present
         job_submitted.resource_id == compute-e2e-deal-001

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

Phase 10 — Lease expiry setup and watchdog advance to releasing
  10a  Setup: pause watchdog, arm remove mock rule, patch lease_end_utc to past,
       dry-run evaluate_job → rule_matched=remove-gate, would_pause=True
  10b  Trigger check-leases cycle → lease transitions to releasing,
       remove_job_id written; storefront resource still leased

Phase 11 — VM cleanup confirmation and resource release
  11a  Assert releasing state holds: vm_remove job paused, resource still leased.
       Represents stable "VM being torn down, not yet available" invariant —
       structurally identical to the planned vm_destroy rework.
  11b  Release remove gate, trigger another check-leases cycle →
       lease released, storefront resource available; resume watchdog
"""

from __future__ import annotations

import logging
import os
from importlib import resources

import pytest

from market_alkahest.alkahest import get_recipient_arbiter
from src.settings import settings
from tests.e2e.roles.scenarios.vms.conftest import (
    DealLease,
    DealState,
    delete_mock_rules_if_present,
    require_state,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal

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
REMOVE_RULE_ID = "e2e-remove-pause"   # mock rule that pauses the vm_remove job
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
            f"Strategy accepted at round 0 for BUYER_INITIAL_PRICE={BUYER_INITIAL_PRICE}. "
            "This means BUYER_INITIAL_PRICE >= seller floor. Lower it so the strategy "
            "counters at round 0 — otherwise force_accept in 06b will 409 on an "
            "already-terminal negotiation."
        )
        deal_state._evaluate_negotiate_passed = True
        log.info("[05a] Evaluate-negotiate: decision=%s reason=%s strategy=%s",
                 result.decision, result.decision_reason, result.strategy)


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
            duration_seconds=DURATION_HOURS * 3600,
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
        """Settlement submitted + provisioning job queued — advance + async observe.

        Advance: POST /api/v1/settle/{uid} → status=provisioning.
        Observe (event-driven): wait_for_stage_event(provision, job_submitted)
          then single GET /settle/{uid}/status → provisioning_job_id.
        Confirms: job visible in provisioning API with status queued/running/succeeded.
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
        log.info("[08b] Provisioning job %s in state %s", prov_job_id, job.status)


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
        assert lease.get("vm_host") == deal_state._evaluate_settle_vm_host
        assert lease.get("create_job_id") in (None, deal_state.provisioning_job_id)
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease after happy-path settlement, got: {lease}"
        )

        deal_state.deal_lease = lease_view
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

# ===========================================================================
# Phase 10 — Lease expiry setup and watchdog advance to releasing
# ===========================================================================

class TestStage10a_LeaseExpirySetup:
    def test_10a_setup_lease_expiry_and_arm_remove_gate(
        self,
        provisioning_client,
        provisioning_test_client,
        deal_state: DealState,
    ):
        """Prepare deterministic control over the lease expiry lifecycle.

        Three setup steps run before any watchdog cycle is triggered:

        1. Pause the watchdog — no background timer cycles will fire from this
           point. The test drives all advances explicitly via check-leases.
        2. Arm remove mock rule — a paused ProgrammableMockAnsibleService rule
           for vm_action=vm_remove will hold the vm_remove job in a non-terminal state,
           keeping the lease in 'releasing' long enough for phase 10b and 11a
           assertions.
        3. Back-date lease_end_utc to the past — the watchdog sees an expired
           active lease on the next check-leases cycle.

        Dry-run validation via evaluate_job confirms the remove rule is armed
        before any live cycle is triggered.

        Forward-compatibility note: when the planned rework replaces the check
        job with a vm_destroy Ansible job, only the mock rule's vm_action field
        changes (check → vm_remove — already done). The structural test shape — pause, arm rule,
        back-date, cycle, assert releasing, release gate, cycle, assert released
        — is identical regardless of the underlying Ansible action.
        """
        require_state(deal_state, "lease_id", "settlement_status",
                      "_evaluate_settle_vm_host", "_evaluate_settle_vm_target",
                      "_provisioning_storefront_ok")

        # Step 1 — pause the watchdog timer
        result = provisioning_client.pause_lease_watchdog()
        assert result.get("paused") is True, (
            f"Failed to pause watchdog: {result}"
        )
        log.info("[10a] Watchdog paused")

        # Step 2 — arm mock rule that pauses the vm_remove job
        provisioning_test_client.add_mock_rule(
            rule_id=REMOVE_RULE_ID,
            match={"vm_action": "vm_remove"},
            pause_before_result=True,
        )
        log.info("[10a] Remove mock rule %r armed (pause_before_result=True)", REMOVE_RULE_ID)

        # Dry-run: confirm evaluate_job sees the rule before we fire a real cycle
        eval_result = provisioning_test_client.evaluate_job(
            host=deal_state._evaluate_settle_vm_host,
            vm_target=deal_state._evaluate_settle_vm_target or "eval-target",
            vm_action="vm_remove",
        )
        assert eval_result.get("params_valid") is True, (
            f"evaluate_job params rejected: {eval_result.get('errors')}"
        )
        assert eval_result.get("rule_matched") == REMOVE_RULE_ID, (
            f"Expected remove mock rule {REMOVE_RULE_ID!r} to match, "
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
        """POST /api/v1/system/check-leases → lease=releasing, remove_job_id written.

        check-leases bypasses the watchdog pause flag, so this fires exactly
        one lifecycle cycle. The remove mock rule is still holding, so the
        submitted vm_remove job will pause before returning a result — this keeps
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

        # Fetch updated lease — expect 'releasing' now that vm_remove job was submitted
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "releasing", (
            f"Expected lease status='releasing' after check-leases cycle, "
            f"got {lease.get('status')!r}.\n"
            f"Full lease: {lease}\n"
            "If status='released' the vm_remove job completed before this assertion — "
            "ensure REMOVE_RULE_ID mock rule is armed and the job_service is wired."
        )
        assert lease.get("vm_remove_job_id") is not None, (
            f"vm_remove_job_id should be set after transitioning to 'releasing': {lease}"
        )
        log.info("[10b] Lease %s is releasing (remove_job=%s)",
                 deal_state.lease_id, lease.get("vm_remove_job_id"))

        # The deal's capacity must still be held — VM not yet confirmed gone
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id,
        ), (
            f"Capacity for {deal_state.reserved_resource_id!r} should still be "
            "held while the vm_remove job is pending."
        )
        log.info("[10b] Capacity for %s still held (VM not yet confirmed gone)",
                 deal_state.reserved_resource_id)

        deal_state.remove_job_id = lease.get("vm_remove_job_id")
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
        """Assert the 'releasing' invariant: vm_remove job not yet done, resource still leased.

        This stage has no side effects — it only reads state. It validates the
        boundary condition where:
          - The provisioning service knows the lease is expiring (status=releasing)
          - The Ansible vm_remove job is submitted but not yet complete (paused by mock)
          - The storefront resource has not been released yet (state=leased)

        This observable invariant is structurally identical to the state the
        system will enter when the planned rework replaces the check action with
        a vm_destroy Ansible job. In both cases, 'releasing' means "cleanup
        initiated, not yet confirmed" and the storefront resource must remain
        unavailable until the provisioning service confirms cleanup is done.

        If the lease is already 'released' here, the vm_remove job completed before
        this assertion — ensure the REMOVE_RULE_ID mock gate is still armed.
        """
        require_state(deal_state, "lease_status", "vm_remove_job_id", "reserved_resource_id")
        assert deal_state.lease_status == "releasing", (
            f"Stage 10b did not leave lease in 'releasing' state. "
            f"Current: {deal_state.lease_status!r}"
        )

        # vm_remove job must be in a non-terminal state (paused by mock rule)
        job = provisioning_client.get_job(deal_state.remove_job_id)
        assert job.status in ("queued", "running"), (
            f"vm_remove job {deal_state.remove_job_id!r} is already terminal: "
            f"status={job.status!r}.\n"
            "The mock pause gate may not be armed — REMOVE_RULE_ID rule may be missing."
        )
        log.info("[11a] vm_remove job %s is %s (paused by mock gate — VM not yet confirmed gone)",
                 deal_state.remove_job_id, job.status)

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
        """Release remove gate → vm_remove job succeeds → watchdog patches resource to available.

        Three steps:
        1. resume_rule(REMOVE_RULE_ID) — unblocks the vm_remove job; mock returns success.
        2. wait_for_job(remove_job_id) — long-poll until the job reaches a terminal state.
        3. check-leases — watchdog sees the succeeded vm_remove job, patches storefront,
           transitions lease to 'released'.

        Final assertions:
          - lease.status == 'released'
          - storefront resource.state == 'available'

        Teardown: resume_watchdog() so background timer cycles work normally
        after the test module completes.
        """
        require_state(deal_state, "vm_remove_job_id", "lease_id",
                      "reserved_resource_id", "_lease_expiry_armed")

        # Step 1 — unblock the vm_remove job
        provisioning_test_client.resume_rule(REMOVE_RULE_ID)
        log.info("[11b] Released check gate (rule=%s)", REMOVE_RULE_ID)

        # Step 2 — wait for the vm_remove job to complete
        job_result = provisioning_test_client.wait_for_job(
            deal_state.remove_job_id, timeout=30
        )
        assert job_result.get("status") == "succeeded", (
            f"vm_remove job {deal_state.remove_job_id!r} did not succeed: {job_result}"
        )
        log.info("[11b] vm_remove job %s succeeded", deal_state.remove_job_id)

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

        # Step 3 — trigger the lifecycle cycle that processes the completed vm_remove job
        result = provisioning_client.check_leases()
        assert result.get("released", 0) >= 1, (
            f"Expected at least one lease released, got: {result}\n"
            "The vm_remove job succeeded but the watchdog cycle did not release the lease. "
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
        provisioning_client.resume_lease_watchdog()
        log.info("[11b] Watchdog resumed — lease lifecycle test complete")
