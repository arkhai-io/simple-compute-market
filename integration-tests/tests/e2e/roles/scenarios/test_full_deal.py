"""Full buyer-seller deal lifecycle — sequential e2e test suite.

Stage map
---------
00a  Admin seeds policies (discover callables + write DB rows)
00b  Policy dry-run asserts make_offer action would fire
01   Seller creates listing with paused=True (local only, not in registry)
02   Storefront health ok; listing visible locally with paused=True
03   Registry does NOT yet contain the listing (publish was skipped)
04   POST /api/v1/listings/{listing_id}/resume → publishes to registry
05   Registry now contains the listing
06   Admin pause blocks /negotiate/new (503)
07   Admin resume re-enables negotiations
08   Buyer starts negotiation (POST /negotiate/new)
09   Negotiation visible via GET /orders/{id}/negotiations
10   Admin force-accepts negotiation at agreed price
11   Negotiation terminal_state=success confirmed
12   Mock escrow_uid captured
13   POST /settle/{uid} → status=provisioning
14   Provisioning job_id visible in settle status + provisioning API
15   Provisioning gate released; job completes (long-poll)
16   Settlement status=ready
17   Tenant credentials present
18   Seller listing status=accepted
"""

from __future__ import annotations

import logging
import time
import uuid

import pytest

from src.settings import settings
from tests.e2e.roles.scenarios.conftest import DealState, require_state

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_deal

# ---------------------------------------------------------------------------
# Offer / demand spec
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
BUYER_INITIAL_PRICE = 10_000   # at seller's floor (demand.amount) — policy will counter or accept
BUYER_MAX_PRICE = 12_000
MOCK_ESCROW_UID = f"escrow-e2e-{uuid.uuid4().hex[:8]}"
PROV_RULE_ID = "e2e-create-pause"


# ---------------------------------------------------------------------------
# Stage 00a — Policy seed
# ---------------------------------------------------------------------------

class TestStage00a_PolicySeed:
    def test_00a_admin_seeds_policies(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /admin/policy/seed populates CALLABLE_REGISTRY and seeds DB rows.

        Idempotent — safe to call on a fresh deployment or one where
        discover_and_register silently failed at startup (e.g. missing gymnasium).
        Reports per-module import errors in the response so failures are
        visible in test output without reading container logs.
        """
        result = storefront_admin_client.policy_seed()
        assert isinstance(result, dict), f"Unexpected response: {result}"

        # Surface any per-module import failures for diagnosis
        import_errors = result.get("import_errors", [])
        if import_errors:
            log.warning("[00a] %d module(s) failed to import during seed:", len(import_errors))
            for err in import_errors:
                log.warning("  %s: %s", err.get("module"), err.get("error"))

        callable_count = result.get("callable_registry_count", 0)
        assert callable_count > 0, (
            f"CALLABLE_REGISTRY is still empty after seed.\n"
            f"Import errors ({len(import_errors)}):\n"
            + "\n".join(f"  {e['module']}: {e['error']}" for e in import_errors)
            + f"\nFull response: {result}"
        )
        seeded = result.get("seeded_policies", [])
        assert any("order_create" in p for p in seeded), (
            f"order_create policy not seeded. Got: {seeded}"
        )
        deal_state._policies_seeded = True
        log.info("[00a] Policy seed: callable_count=%d seeded=%s import_errors=%d",
                 callable_count, seeded, len(import_errors))


# ---------------------------------------------------------------------------
# Stage 00b — Policy dry-run
# ---------------------------------------------------------------------------

class TestStage00b_PolicyDryRun:
    def test_00b_policy_evaluate_returns_make_offer(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /api/v1/system/policy/evaluate returns action=make_offer."""
        require_state(deal_state, "_policies_seeded")

        result = storefront_admin_client.policy_evaluate(
            offer=OFFER_RESOURCE,
            demand=DEMAND_RESOURCE,
            max_duration_seconds=DURATION_HOURS * 3600,
        )
        assert isinstance(result, dict), f"Unexpected response: {result}"
        assert result.get("resolvable") is True, (
            f"Policy components not resolvable: {result}"
        )
        action = result.get("action", "")
        assert "make_offer" in action.lower(), (
            f"Expected action=make_offer, got {action!r}. Full response: {result}"
        )
        deal_state._policy_evaluated = True
        log.info("[00b] Policy dry-run: action=%s policy=%s",
                 action, result.get("policy_used"))


# ---------------------------------------------------------------------------
# Stage 00c — Negotiation strategy viability
# ---------------------------------------------------------------------------

class TestStage00c_NegotiationStrategy:
    def test_00c_negotiation_strategy_is_viable(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/system/status → checks.negotiation_strategy is not exit-on-probe.

        Catches the rl-strategy-but-no-torch failure mode before any negotiation
        attempt.  If this fails, set [seller.negotiation] policy_mode = 'bisection'
        in config.toml and restart the storefront.
        """
        require_state(deal_state, "_policy_evaluated")
        status = storefront_admin_client.get_system_status()
        strat = status.checks.get("negotiation_strategy", "absent")
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
        log.info("[00c] Negotiation strategy: %s", strat)


# ---------------------------------------------------------------------------
# Stage 01 — Create order (paused)
# ---------------------------------------------------------------------------

class TestStage01_CreateListingPaused:
    def test_01_seller_creates_listing_paused(
        self, storefront_admin_client, seller_wallet, deal_state: DealState
    ):
        """POST /api/v1/listings/create with paused=True creates listing in local SQLite
        but does NOT publish to the registry.
        """
        require_state(deal_state, "_policy_evaluated")
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
            f"Ensure stage 00a (policy seed) passed."
        )
        deal_state.seller_listing_id = listing_id
        log.info("[01] Order %s created (paused, not yet in registry)", order_id)


# ---------------------------------------------------------------------------
# Stage 02 — Order visible locally with paused=True
# ---------------------------------------------------------------------------

class TestStage02_ListingLocallyPaused:
    def test_02_order_visible_locally_and_paused(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/listings/{listing_id} shows the listing as paused=True locally."""
        require_state(deal_state, "seller_listing_id")

        health = storefront_admin_client.get_health()
        assert health.status == "ok", f"Storefront health degraded: {health}"

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "open", f"Expected status=open, got {order.status!r}"
        assert listing.paused is True, (
            f"Expected paused=True after paused create, got paused={listing.paused}"
        )
        deal_state.paused_create_confirmed = True
        log.info("[02] Order %s visible locally: status=%s paused=%s",
                 deal_state.seller_listing_id, listing.status, listing.paused)


# ---------------------------------------------------------------------------
# Stage 03 — Registry does NOT yet contain the order
# ---------------------------------------------------------------------------

class TestStage03_RegistryDoesNotSeeOrder:
    def test_03_registry_does_not_yet_contain_listing(
        self, registry_client, deal_state: DealState
    ):
        """The registry has no record of this listing_id — publish was skipped."""
        require_state(deal_state, "seller_listing_id")

        result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in result.listings}
        assert deal_state.seller_listing_id not in ids, (
            f"Order {deal_state.seller_listing_id} found in registry before resume. "
            f"The paused=True path did not suppress the publish."
        )
        deal_state.registry_absent_confirmed = True
        log.info("[03] Confirmed order %s absent from registry (as expected)",
                 deal_state.seller_listing_id)


# ---------------------------------------------------------------------------
# Stage 04 — Resume publishes to registry
# ---------------------------------------------------------------------------

class TestStage04_ResumePublishesToRegistry:
    def test_04_resume_order_publishes_to_registry(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /api/v1/listings/{listing_id}/resume clears paused flag and publishes."""
        require_state(deal_state, "seller_listing_id", "paused_create_confirmed", "registry_absent_confirmed")

        result = storefront_admin_client.resume_listing(deal_state.seller_listing_id)
        assert result.paused is False, f"Expected paused=False after resume, got: {result}"
        assert result.registry_status == "published", (
            f"Registry publish failed during resume. registry_status={result.registry_status!r}.\n"
            f"Check that registry.url in config.toml is reachable from the storefront container.\n"
            f"Current response: {result}"
        )

        # Confirm locally
        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.paused is False, f"Local listing still paused after resume: {listing}"

        deal_state.resume_confirmed = True
        log.info("[04] Order %s resumed; registry_status=%s",
                 deal_state.seller_listing_id, result.registry_status)


# ---------------------------------------------------------------------------
# Stage 05 — Registry now contains the order
# ---------------------------------------------------------------------------

class TestStage05_RegistrySeesOrder:
    def test_05_registry_now_contains_listing(
        self, registry_client, deal_state: DealState
    ):
        """After resume, the listing is immediately visible in the registry.

        No polling: resume_listing calls publish_order_to_registry synchronously
        and stage 04 already asserted registry_status=published.  By the time
        we reach this test the listing is provably in the registry DB.
        """
        require_state(deal_state, "seller_listing_id", "resume_confirmed")

        result = registry_client.list_listings(status="open", limit=200)
        ids = {o.id for o in result.listings}
        assert deal_state.seller_listing_id in ids, (
            f"Order {deal_state.seller_listing_id} not visible in registry immediately after resume.\n"
            f"registry_status was 'published' but listing is absent — possible registry indexing delay.\n"
            f"Registry returned {len(ids)} open listings."
        )
        deal_state.registry_order_confirmed = True
        log.info("[05] Order %s confirmed in registry", deal_state.seller_listing_id)


# ---------------------------------------------------------------------------
# Stages 06-07 — Global admin pause / resume
# ---------------------------------------------------------------------------

class TestStage06_AdminPauseBlocks:
    def test_06_admin_pause_blocks_negotiations(
        self, storefront_admin_client, storefront_client, buyer_config, deal_state: DealState
    ):
        """POST /admin/pause → /negotiate/new returns 503.

        Must use real buyer credentials: the storefront validates the EIP-191
        signature before checking the global pause flag, so an invalid signature
        produces 403 rather than 503.  We need the signature to pass so the
        pause check is reached.
        """
        require_state(deal_state, "seller_listing_id", "registry_order_confirmed")

        storefront_admin_client.admin_pause()

        from storefront_client.client import _sign_eip191
        ts = str(int(time.time()))
        sig = _sign_eip191(
            buyer_config["private_key"],
            f"negotiate_new:{deal_state.seller_listing_id}:{ts}",
        )
        resp = storefront_client._client.post(
            "/negotiate/new",
            json={
                "listing_id": deal_state.seller_listing_id,
                "buyer_address": buyer_config["wallet_address"],
                "initial_price": BUYER_INITIAL_PRICE,
                "duration_seconds": DURATION_HOURS * 3600,
            },
            headers={"X-Signature": sig, "X-Timestamp": ts},
        )
        assert resp.status_code == 503, (
            f"Expected 503 from paused storefront, got {resp.status_code}: {resp.text[:200]}"
        )
        deal_state.pause_confirmed = True
        log.info("[06] Admin pause blocks negotiation correctly")


class TestStage07_AdminResumeAllows:
    def test_07_admin_resume_re_enables_negotiations(
        self, storefront_admin_client, deal_state: DealState
    ):
        """POST /admin/resume clears the global pause flag."""
        require_state(deal_state, "pause_confirmed")

        result = storefront_admin_client.admin_resume()
        assert result.paused is False

        status = storefront_admin_client.get_system_status()
        assert status.paused is False

        deal_state.admin_resume_confirmed = True
        log.info("[07] Admin resume: storefront accepting negotiations")


# ---------------------------------------------------------------------------
# Stages 08-11 — Negotiation lifecycle
# ---------------------------------------------------------------------------

class TestStage08_NegotiationStarts:
    def test_08_buyer_starts_negotiation(
        self, storefront_client, buyer_config, deal_state: DealState
    ):
        """POST /negotiate/new — buyer opens with initial_price."""
        require_state(deal_state, "seller_listing_id", "admin_resume_confirmed",
                      "_negotiation_strategy_viable")

        from storefront_client.client import _sign_eip191
        ts = str(int(time.time()))
        sig = _sign_eip191(
            buyer_config["private_key"],
            f"negotiate_new:{deal_state.seller_listing_id}:{ts}",
        )
        resp = storefront_client._client.post(
            "/negotiate/new",
            json={
                "listing_id": deal_state.seller_listing_id,
                "buyer_address": buyer_config["wallet_address"],
                "initial_price": BUYER_INITIAL_PRICE,
                "duration_seconds": DURATION_HOURS * 3600,
            },
            headers={"X-Signature": sig, "X-Timestamp": ts},
        )
        assert resp.status_code == 200, (
            f"POST /negotiate/new returned {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        neg_id = body.get("negotiation_id")
        assert neg_id, f"No negotiation_id in response: {body}"

        # Verify the seller's round 0 decision via stage events — catches
        # strategy misconfiguration (e.g. rl without torch) before it surfaces
        # as a 409 at stage 10.
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
            f"our_price={round0.data.get('our_price')} their_price={round0.data.get('their_price')}.\n"
            "If reason is 'torch_unavailable': set policy_mode='bisection' in config.toml.\n"
            "If reason is 'price_unreasonable': increase BUYER_INITIAL_PRICE to meet the seller floor."
        )

        deal_state.negotiation_id = neg_id
        deal_state.negotiation_round_count = 1
        log.info("[08] Negotiation %s started; seller action=%s reason=%s",
                 neg_id, body.get("action"),
                 round0.data.get("decision_reason"))


class TestStage09_NegotiationVisible:
    def test_09_negotiation_visible_on_storefront_api(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/listings/{listing_id}/negotiations lists the active thread."""
        require_state(deal_state, "seller_listing_id", "negotiation_id")

        result = storefront_admin_client.list_negotiations(deal_state.seller_listing_id)
        ids = {n.negotiation_id for n in result.negotiations}
        assert deal_state.negotiation_id in ids, (
            f"Negotiation {deal_state.negotiation_id} not in "
            f"GET /orders/{deal_state.seller_listing_id}/negotiations. Found: {ids}"
        )
        log.info("[09] Negotiation %s visible on storefront API", deal_state.negotiation_id)


class TestStage10_NegotiationForceAccepted:
    def test_10_admin_force_accepts_negotiation(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Admin force-accepts at agreed_price to converge without round-trips."""
        require_state(deal_state, "seller_listing_id", "negotiation_id")

        # Guard: confirm the negotiation is still open before force-accepting.
        # If round 0 exited (e.g. strategy misconfiguration), force-accept
        # returns 409.  Checking stage events here gives a better failure message.
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
            "Check stage 08's round_decided event for root cause."
        )

        agreed = (BUYER_INITIAL_PRICE + BUYER_MAX_PRICE) // 2
        result = storefront_admin_client.force_accept_negotiation(
            deal_state.seller_listing_id,
            deal_state.negotiation_id,
            price=agreed,
        )
        assert result.action == "accept", f"Unexpected action: {result}"
        assert result.price == agreed

        deal_state.agreed_price = agreed
        log.info("[10] Force-accepted at price %d", agreed)


class TestStage11_NegotiationTerminal:
    def test_11_negotiation_terminal_success(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET .../negotiations/{neg_id} shows terminal_state=success."""
        require_state(deal_state, "seller_listing_id", "negotiation_id", "agreed_price")

        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id, deal_state.negotiation_id
        )
        assert detail.terminal_state == "success", (
            f"Expected terminal_state=success, got {detail.terminal_state!r}"
        )
        assert detail.agreed_price == deal_state.agreed_price

        deal_state.negotiation_terminal_state = detail.terminal_state
        log.info("[11] Negotiation terminal: state=%s price=%d",
                 detail.terminal_state, detail.agreed_price)


# ---------------------------------------------------------------------------
# Stage 12 — Mock escrow
# ---------------------------------------------------------------------------

class TestStage12_MockEscrow:
    def test_12_mock_escrow_uid_captured(self, deal_state: DealState):
        """Capture a deterministic mock escrow_uid (no real chain call)."""
        require_state(deal_state, "negotiation_terminal_state")
        deal_state.escrow_uid = MOCK_ESCROW_UID
        log.info("[12] Mock escrow: %s", MOCK_ESCROW_UID)


# ---------------------------------------------------------------------------
# Stages 13-18 — Settlement + provisioning
# ---------------------------------------------------------------------------

class TestStage13_SettlementSubmitted:
    def test_13_settlement_submitted(
        self, storefront_client, buyer_config, deal_state: DealState
    ):
        """POST /settle/{uid} returns status=provisioning."""
        require_state(deal_state, "negotiation_id", "escrow_uid")

        resp = storefront_client._client.post(
            f"/settle/{deal_state.escrow_uid}",
            json={
                "negotiation_id": deal_state.negotiation_id,
                "ssh_public_key": buyer_config["ssh_public_key"],
                "buyer_address": buyer_config["wallet_address"],
            },
        )
        assert resp.status_code in (200, 202), (
            f"POST /settle/{deal_state.escrow_uid} returned {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert body.get("status") == "provisioning", (
            f"Expected status=provisioning, got: {body}"
        )
        deal_state.settlement_submitted = True
        log.info("[13] Settlement submitted for escrow %s", deal_state.escrow_uid)


class TestStage14_ProvisioningJobQueued:
    def test_14_provisioning_job_id_surfaces(
        self, storefront_admin_client, storefront_client, provisioning_client, buyer_config, deal_state: DealState
    ):
        """provisioning_job_id appears in settle status; job exists in provisioning API.

        Uses wait_for_stage_event (stage=provision, event=resource_reserved) rather
        than polling /settle/{uid}/status so the test is driven by the storefront's
        own event log — no arbitrary sleep or deadline needed.
        """
        require_state(deal_state, "escrow_uid", "settlement_submitted")

        from tests.e2e.roles.scenarios.conftest import wait_for_stage_event as _wait
        _wait(
            storefront_admin_client,
            "provision", "resource_reserved",
            listing_id=deal_state.seller_listing_id,
            timeout=15.0,
        )

        # Now poll once — the event confirms the job was queued
        resp = storefront_client._client.get(
            f"/settle/{deal_state.escrow_uid}/status",
            params={"buyer_address": buyer_config["wallet_address"]},
        )
        assert resp.status_code == 200, f"Settle status returned {resp.status_code}"
        prov_job_id = resp.json().get("provisioning_job_id")
        assert prov_job_id, f"provisioning_job_id absent from settle status: {resp.json()}"

        job = provisioning_client.get_job(prov_job_id)
        assert job.status in ("queued", "running", "succeeded"), (
            f"Unexpected job status: {job.status}"
        )
        deal_state.provisioning_job_id = prov_job_id
        log.info("[14] Provisioning job %s in state %s", prov_job_id, job.status)


class TestStage15_ProvisioningCompletes:
    def test_15_provisioning_job_completes(
        self, provisioning_test_client, deal_state: DealState
    ):
        """Long-poll via /test/jobs/{id}/wait until job reaches succeeded."""
        require_state(deal_state, "provisioning_job_id")

        try:
            provisioning_test_client.resume_rule(PROV_RULE_ID)
        except Exception as exc:
            log.debug("[15] resume_rule no-op (may not have been paused): %s", exc)

        result = provisioning_test_client.wait_for_job(
            deal_state.provisioning_job_id, timeout=30
        )
        assert result["status"] == "succeeded", (
            f"Expected succeeded, got {result['status']!r}. Error: {result.get('error')}"
        )
        deal_state.provisioning_result_injected = True
        log.info("[15] Provisioning job %s succeeded", deal_state.provisioning_job_id)


class TestStage16_SettlementReady:
    def test_16_settlement_status_ready(
        self, storefront_admin_client, storefront_client, buyer_config, deal_state: DealState
    ):
        """GET /settle/{uid}/status shows status=ready after provisioning succeeds.

        Uses wait_for_stage_event (stage=provision, event=fulfilled) to avoid
        polling /settle/{uid}/status in a tight loop.
        """
        require_state(deal_state, "escrow_uid", "provisioning_result_injected")

        from tests.e2e.roles.scenarios.conftest import wait_for_stage_event as _wait
        _wait(
            storefront_admin_client,
            "provision", "fulfilled",
            listing_id=deal_state.seller_listing_id,
            timeout=20.0,
        )

        resp = storefront_client._client.get(
            f"/settle/{deal_state.escrow_uid}/status",
            params={"buyer_address": buyer_config["wallet_address"]},
        )
        assert resp.status_code == 200, f"Settle status returned {resp.status_code}"
        final_status = resp.json().get("status")
        assert final_status == "ready", (
            f"Settlement not 'ready' after provision fulfilled event. Got: {final_status!r}"
        )
        deal_state.settlement_status = final_status
        log.info("[16] Settlement status=ready")


class TestStage17_TenantCredentials:
    def test_17_tenant_credentials_present(
        self, storefront_client, buyer_config, deal_state: DealState
    ):
        """Settlement response includes tenant_credentials."""
        require_state(deal_state, "escrow_uid", "settlement_status")

        resp = storefront_client._client.get(
            f"/settle/{deal_state.escrow_uid}/status",
            params={"buyer_address": buyer_config["wallet_address"]},
        )
        assert resp.status_code == 200
        creds = resp.json().get("tenant_credentials")
        assert creds, f"tenant_credentials missing: {resp.json()}"

        deal_state.tenant_credentials = creds
        log.info("[17] Tenant credentials received: keys=%s", list(creds.keys()))


class TestStage18_SellerOrderAccepted:
    def test_18_seller_order_status_accepted(
        self, storefront_admin_client, deal_state: DealState
    ):
        """GET /api/v1/listings/{listing_id} shows status=accepted after settlement."""
        require_state(deal_state, "seller_listing_id", "settlement_submitted")

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status in ("accepted", "closed"), (
            f"Expected accepted/closed, got {listing.status!r}"
        )
        deal_state.seller_order_final_status = listing.status
        log.info("[18] Seller order %s status=%s",
                 deal_state.seller_listing_id, listing.status)
