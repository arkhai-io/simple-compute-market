"""Full buyer-seller deal lifecycle — sequential e2e test suite.

Stage map
---------
Phase 0 — E2E readiness (all services healthy, no state changes)
  00a  Storefront reachable:    GET /health → status=ok, database=ok
  00b  Registry reachable:      GET /api/v1/system/status → checks.registry=ok
  00c  Provisioning reachable:  GET provisioning /health → status=ok
  00d  Negotiation strategy viable: checks.negotiation_strategy not exit-on-probe

Phase 1 — Policy pipeline ready
  01a  Policy dry-run:  POST /api/v1/system/policy/evaluate → action=make_offer
  01b  Policy seed:     POST /admin/policy/seed → callable_count > 0

Phase 2 — Listing creation (paused)
  02a  Evaluate-create dry-run: POST /api/v1/admin/listings/evaluate-create → would_create=True
  02b  Create listing paused + confirm:
         POST /listings/create paused=True → listing_id
         GET /api/v1/listings/{id} → status=open, paused=True
         GET registry/listings → listing absent (publish suppressed)

Phase 3 — Registry publication
  03a  Validate listing publishable: POST registry /api/v1/listings/validate-publish → valid=True
  03b  Resume + registry confirm:
         POST /api/v1/listings/{id}/resume → registry_status=published
         GET registry/listings → listing present

Phase 4 — (removed; admin pause/resume tested in storefront smoke suite)
  TODO: Add test_admin_pause_resume to tests/smoke/test_storefront_smoke.py

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
         GET .../negotiations/{neg_id} → terminal_state=success

Phase 7 — Mock escrow + provisioning gate setup
  07   Capture mock escrow_uid; add provisioning mock rule (pause_before_result=True)

Phase 8 — Settlement pipeline
  08b  Settlement submitted + job queued:
         POST /api/v1/settle/{uid} → status=provisioning
         wait_for_stage_event(provision, resource_reserved)
         GET /settle/{uid}/status → provisioning_job_id present

Phase 9 — Provisioning completion
  09a  Release gate + job completes: resume_rule; wait_for_job → succeeded
  09b  Settlement ready + credentials + listing closed:
         wait_for_stage_event(provision, fulfilled)
         GET /settle/{uid}/status → status=ready, tenant_credentials present
         GET /api/v1/listings/{id} → status=accepted or closed
"""

from __future__ import annotations

import logging
import uuid

import pytest

from src.settings import settings
from tests.e2e.roles.scenarios.conftest import DealState, require_state

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal

# ---------------------------------------------------------------------------
# Offer / demand spec — constants shared across all stages
# ---------------------------------------------------------------------------

OFFER_RESOURCE = {
    "gpu_model": "H200",
    "gpu_count": 1,
    "sla": 99.0,
    "region": "California, US",
}
DEMAND_RESOURCE = {
    "token": {
        "symbol": "MOCK",
        "contract_address": "0x0000000000000000000000000000000000000001",
        "decimals": 0,   # test token — no decimal scaling so amount is already base units
    },
    "amount": 10_000,
}
DURATION_HOURS = 1
BUYER_INITIAL_PRICE = 10_000   # at seller's floor — policy will counter or accept
BUYER_MAX_PRICE = 12_000
MOCK_ESCROW_UID = f"escrow-e2e-{uuid.uuid4().hex[:8]}"
PROV_RULE_ID = "e2e-create-pause"


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
        """GET provisioning /health → status=ok.

        Validates provisioning service is up and its mock profile is active
        before settlement stages attempt to submit jobs.
        """
        require_state(deal_state, "_storefront_healthy")
        health = provisioning_client.get_health()
        assert health.get("status") == "ok", (
            f"Provisioning service unhealthy: {health}\n"
            "Ensure ACTIVE_PROFILES=mock is set on the provisioning container."
        )
        deal_state._provisioning_healthy = True
        log.info("[00c] Provisioning healthy: %s", health.get("status"))


class TestStage00d_NegotiationStrategy:
    def test_00d_negotiation_strategy_is_viable(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.negotiation_strategy not exit-on-probe.

        Catches the rl-strategy-but-no-torch failure mode before any negotiation
        attempt. If this fails, set [seller.negotiation] policy_mode = 'bisection'
        in config.toml and restart the storefront.
        """
        require_state(deal_state, "_storefront_healthy")
        status = storefront_admin_client.get_system_status()
        strat = (status.checks or {}).get("negotiation_strategy", "absent")
        assert strat != "absent", (
            "checks.negotiation_strategy missing from /api/v1/system/status. "
            "Rebuild the storefront image with the updated system_controller.py."
        )
        assert "exit_on_probe" not in strat, (
            f"Negotiation strategy would exit every round: {strat!r}\n"
            "Set [seller.negotiation] policy_mode = 'bisection' in config.toml "
            "and restart the storefront."
        )
        deal_state._negotiation_strategy_viable = True
        log.info("[00d] Negotiation strategy viable: %s", strat)


# ===========================================================================
# Phase 1 — Policy pipeline ready
# ===========================================================================

class TestStage01a_PolicyDryRun:
    def test_01a_policy_evaluate_returns_make_offer(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /api/v1/system/policy/evaluate → action=make_offer (dry-run).

        Verifies the policy pipeline can produce a decision for the offer/demand
        spec before the seed advance writes any DB rows.
        """
        require_state(deal_state, "_negotiation_strategy_viable")
        result = storefront_admin_client.policy_evaluate(
            offer=OFFER_RESOURCE,
            demand=DEMAND_RESOURCE,
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        assert isinstance(result, dict), f"Unexpected response type: {result}"
        action = result.get("action", "")
        assert "make_offer" in action.lower(), (
            f"Expected action=make_offer, got {action!r}. Full response: {result}"
        )
        deal_state._policy_dry_run_passed = True
        log.info("[01a] Policy dry-run: action=%s policy=%s",
                 action, result.get("policy_used"))


class TestStage01b_PolicySeed:
    def test_01b_admin_seeds_policies(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /admin/policy/seed → callable_count > 0, order_create seeded.

        Idempotent advance — discovers @policy_callable decorators and writes
        default DB rows. Safe to call on a fresh deployment or one where
        startup seeding silently failed (e.g. missing gymnasium).
        """
        require_state(deal_state, "_policy_dry_run_passed")
        result = storefront_admin_client.policy_seed()
        assert isinstance(result, dict), f"Unexpected response: {result}"

        import_errors = result.get("import_errors", [])
        if import_errors:
            log.warning("[01b] %d module(s) failed to import during seed:", len(import_errors))
            for err in import_errors:
                log.warning("  %s: %s", err.get("module"), err.get("error"))

        callable_count = result.get("callable_registry_count", 0)
        assert callable_count > 0, (
            f"CALLABLE_REGISTRY still empty after seed.\n"
            f"Import errors ({len(import_errors)}):\n"
            + "\n".join(f"  {e['module']}: {e['error']}" for e in import_errors)
            + f"\nFull response: {result}"
        )
        seeded = result.get("seeded_policies", [])
        assert any("order_create" in p for p in seeded), (
            f"order_create policy not seeded. Got: {seeded}"
        )
        deal_state._policies_seeded = True
        log.info("[01b] Policy seed: callable_count=%d seeded=%s import_errors=%d",
                 callable_count, seeded, len(import_errors))


# ===========================================================================
# Phase 2 — Listing creation (paused)
# ===========================================================================

class TestStage02a_EvaluateCreate:
    def test_02a_evaluate_create_would_create(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /api/v1/admin/listings/evaluate-create → would_create=True (dry-run).

        Validates the offer/demand spec against the policy pipeline without
        writing to SQLite or the registry. If this fails, listing creation
        in 02b will also fail.
        """
        require_state(deal_state, "_policies_seeded")
        result = storefront_admin_client.evaluate_create_listing(
            offer=OFFER_RESOURCE,
            demand=DEMAND_RESOURCE,
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        assert isinstance(result, dict), f"Unexpected response: {result}"
        assert result.get("would_create") is True, (
            f"evaluate-create returned would_create=False. action={result.get('action')!r}. "
            f"reason={result.get('reason')!r}. Ensure stage 01b (policy seed) passed."
        )
        deal_state._evaluate_create_passed = True
        log.info("[02a] Evaluate-create: would_create=%s action=%s",
                 result.get("would_create"), result.get("action"))


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
        require_state(deal_state, "_evaluate_create_passed")

        resp = storefront_admin_client.create_listing(
            agent_wallet_address=seller_wallet,
            offer=OFFER_RESOURCE,
            demand=DEMAND_RESOURCE,
            max_duration_seconds=DURATION_HOURS * 3600,
            paused=True,
        )
        listing_id = resp.listing_id
        assert listing_id, (
            f"No listing_id in response — policy pipeline returned no action.\n"
            f"Response: {resp}\n"
            f"Ensure stage 01b (policy seed) passed."
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

class TestStage03a_ValidatePublish:
    def test_03a_listing_payload_validates_against_registry(
        self, registry_client, deal_state: DealState
    ):
        """POST registry /api/v1/listings/validate-publish → valid=True (dry-run).

        Structural pre-flight: confirms the listing's offer/demand payload is
        recognisable to the registry before resume triggers the actual publish.
        Uses the test's known offer/demand spec directly — no need to fetch
        the listing back from the storefront.
        """
        require_state(deal_state, "seller_listing_id")
        from registry_client import ValidatePublishRequest
        req = ValidatePublishRequest(
            listing_id=deal_state.seller_listing_id,
            offer_resource=OFFER_RESOURCE,
            demand_resource=DEMAND_RESOURCE,
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        result = registry_client.validate_publish_listing(req)
        assert result.valid, (
            f"Registry validate-publish returned valid=False for listing "
            f"{deal_state.seller_listing_id}.\n"
            f"Errors: {result.errors}\n"
            f"offer_resource_type={result.offer_resource_type!r} "
            f"demand_resource_type={result.demand_resource_type!r}"
        )
        deal_state._registry_validate_passed = True
        log.info("[03a] Registry validate-publish: valid=%s offer=%s demand=%s",
                 result.valid, result.offer_resource_type, result.demand_resource_type)


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
            their_proposed_price=BUYER_INITIAL_PRICE,
            buyer_address=buyer_config["wallet_address"],
        )
        assert result.would_negotiate, (
            f"Strategy would exit at round 0 for BUYER_INITIAL_PRICE={BUYER_INITIAL_PRICE}.\n"
            f"decision={result.decision!r} reason={result.decision_reason!r}\n"
            f"our_reference_price={result.our_reference_price} "
            f"their_proposed_price={result.their_proposed_price}\n"
            "If reason is 'torch_unavailable': set policy_mode='bisection' in config.toml.\n"
            "If reason is 'price_unreasonable': increase BUYER_INITIAL_PRICE to >= "
            f"{result.our_reference_price} (seller floor)."
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
            initial_price=BUYER_INITIAL_PRICE,
            duration_seconds=DURATION_HOURS * 3600,
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
        assert round0.data.get("decision") != "exit", (
            f"Seller exited at round 0. reason={round0.data.get('decision_reason')!r}. "
            f"our_price={round0.data.get('our_price')} "
            f"their_price={round0.data.get('their_price')}.\n"
            "If reason is 'torch_unavailable': set policy_mode='bisection' in config.toml.\n"
            "If reason is 'price_unreasonable': increase BUYER_INITIAL_PRICE."
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

        # Guard: confirm negotiation is still open
        events_result = storefront_admin_client.get_events(
            stage="negotiation",
            negotiation_id=deal_state.negotiation_id,
        )
        terminal_exits = [
            e for e in events_result.events
            if e.event == "round_decided" and e.data.get("decision") == "exit"
        ]
        assert not terminal_exits, (
            f"Negotiation {deal_state.negotiation_id} already exited before force-accept. "
            f"Exit reason: {terminal_exits[0].data.get('decision_reason')!r}. "
            "Check stage 05b's round_decided event for root cause."
        )

        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        result = storefront_admin_client.force_accept_negotiation(
            deal_state.seller_listing_id,
            deal_state.negotiation_id,
            price=agreed,
        )
        assert result.action == "accept", (
            f"Unexpected action from force-accept: {result}"
        )
        assert result.price == agreed

        # Confirm terminal state
        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, deal_state.negotiation_id
        )
        assert detail.terminal_state == "success", (
            f"Expected terminal_state=success, got {detail.terminal_state!r}"
        )
        assert detail.agreed_price == agreed

        deal_state.agreed_price = agreed
        deal_state.negotiation_terminal_state = detail.terminal_state
        log.info("[06b] Force-accepted at price %d; terminal_state=%s",
                 agreed, detail.terminal_state)


# ===========================================================================
# Phase 7 — Mock escrow + provisioning gate setup
# ===========================================================================

class TestStage07_MockEscrowAndProvGate:
    def test_07_mock_escrow_and_provision_gate_armed(
        self, provisioning_test_client, deal_state: DealState
    ):
        """Capture deterministic mock escrow_uid and arm provisioning pause gate.

        The pause gate (pause_before_result=True) holds the mock job before it
        reports success, giving stage 08b a window to assert the job is
        queued/running before stage 09a releases it. Without the gate the mock
        may complete before the assertion and the test races.
        """
        require_state(deal_state, "negotiation_terminal_state")

        deal_state.escrow_uid = MOCK_ESCROW_UID

        provisioning_test_client.add_mock_rule({
            "rule_id": PROV_RULE_ID,
            "match": {"vm_action": "create"},
            "pause_before_result": True,
            "result_stdout": (
                '{"vm_name": "e2e-test-vm", "tenant_user": "vmuser", '
                '"tenant_ssh_key_path": "/tmp/e2e.key", '
                '"frp": {"enabled": false}, '
                '"authentication": {"tenant": {"ssh_commands": '
                '{"external": "ssh vmuser@localhost", '
                '"internal": "ssh vmuser@10.0.0.1"}}}}'
            ),
            "fail_with": None,
        })
        deal_state.provisioning_gate_armed = True
        log.info("[07] Mock escrow: %s; provisioning gate armed with rule=%s",
                 MOCK_ESCROW_UID, PROV_RULE_ID)


# ===========================================================================
# Phase 8 — Settlement pipeline
# (08a skipped — no meaningful dry-run for settle with mocked provisioning)
# ===========================================================================

class TestStage08b_SettlementSubmittedAndJobQueued:
    def test_08b_settlement_submitted_and_provisioning_job_queued(
        self, storefront_client, storefront_admin_client, provisioning_client,
        buyer_config, deal_state: DealState
    ):
        """Settlement submitted + provisioning job queued — advance + async observe.

        Advance: POST /api/v1/settle/{uid} → status=provisioning.
        Observe (event-driven): wait_for_stage_event(provision, resource_reserved)
          then single GET /settle/{uid}/status → provisioning_job_id.
        Confirms: job visible in provisioning API with status queued/running/succeeded.
        """
        require_state(deal_state, "negotiation_id", "escrow_uid", "provisioning_gate_armed")

        settle_resp = storefront_client.settle(
            deal_state.escrow_uid,
            negotiation_id=deal_state.negotiation_id,
            buyer_address=buyer_config["wallet_address"],
            ssh_public_key=buyer_config["ssh_public_key"],
        )
        assert settle_resp.status == "provisioning", (
            f"Expected status=provisioning, got: {settle_resp.status!r}. "
            f"Full response: {settle_resp}"
        )
        deal_state.settlement_submitted = True

        # Wait for the storefront to queue the provisioning job (event-driven)
        from tests.e2e.roles.scenarios.conftest import wait_for_stage_event as _wait
        _wait(
            storefront_admin_client,
            "provision", "resource_reserved",
            listing_id=deal_state.seller_listing_id,
            timeout=15.0,
        )

        # Single read — event confirms job is queued
        status_resp = storefront_client.get_settle_status(
            deal_state.escrow_uid,
            buyer_address=buyer_config["wallet_address"],
        )
        prov_job_id = status_resp.provisioning_job_id
        assert prov_job_id, (
            f"provisioning_job_id absent from settle status after resource_reserved event: "
            f"{status_resp}"
        )

        job = provisioning_client.get_job(prov_job_id)
        assert job.status in ("queued", "running", "succeeded"), (
            f"Unexpected job status: {job.status}"
        )
        deal_state.provisioning_job_id = prov_job_id
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
    def test_09b_settlement_ready_credentials_and_listing_closed(
        self, storefront_client, storefront_admin_client, buyer_config, deal_state: DealState
    ):
        """Settlement status=ready, tenant credentials present, listing accepted/closed.

        Combined observation of all post-provisioning state:
          1. wait_for_stage_event(provision, fulfilled) — event-driven, no sleep
          2. GET /settle/{uid}/status → status=ready + tenant_credentials
          3. GET /api/v1/listings/{id} → status=accepted or closed
        """
        require_state(deal_state, "escrow_uid", "provisioning_result_injected",
                      "seller_listing_id")

        from tests.e2e.roles.scenarios.conftest import wait_for_stage_event as _wait
        _wait(
            storefront_admin_client,
            "provision", "fulfilled",
            listing_id=deal_state.seller_listing_id,
            timeout=20.0,
        )

        status_resp = storefront_client.get_settle_status(
            deal_state.escrow_uid,
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
        assert listing.status in ("accepted", "closed"), (
            f"Expected listing status=accepted/closed, got {listing.status!r}"
        )

        deal_state.settlement_status = status_resp.status
        deal_state.tenant_credentials = status_resp.tenant_credentials
        deal_state.seller_listing_final_status = listing.status
        log.info("[09b] Settlement ready; credentials present; listing status=%s",
                 listing.status)
