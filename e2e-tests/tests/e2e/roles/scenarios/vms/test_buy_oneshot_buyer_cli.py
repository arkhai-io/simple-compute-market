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
B5  Seller + lease:   listing closes while capacity is held, primary escrow ready with a
                      fulfillment_uid, provisioning lease registered
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
from tests.e2e.roles.buyer_cli import MarketRun
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_BUY_HOST,
    E2E_BUY_POOL_ID,
    E2E_HOST_GPU_COUNT,
    provision_e2e_executor,
    refresh_storefront_projections,
)
from tests.e2e.roles.scenarios.vms.conftest import (
    DealState,
    advance_storefront,
    capacity_source_for,
    delete_mock_rules_if_present,
    dry_run_storefront,
    one_site,
    pause_storefront,
    require_state,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_buy

# ---------------------------------------------------------------------------
# Offer / demand spec — distinct from the full-deal suite so the two can
# share a stack: a different resource_id and gpu_model mean the typed resource
# query below returns only this listing.
# ---------------------------------------------------------------------------

BUY_RESOURCE_ID = "compute-e2e-buy-001"
BUY_GPU_MODEL = "RTX 4090"
OFFER_RESOURCE = {
    # The storefront refuses a listing whose resource does not declare the
    # offering mode its domain binding selected.
    "offering_mode": "vm",
    "resource_id": BUY_RESOURCE_ID,
    "gpu_model": BUY_GPU_MODEL,
    "gpu_count": 1,
    "sla": 90.0,
    "region": "California, US",
}
# MockERC20 at the deterministic alkahest address; buyer (account #1) is
# funded with 1 000 whole tokens in the baked chain state (see
# dev-env/generate_state.py). The contract reports 18 decimals, so the
# advertised rate is in base units and the CLI's price flags below are in
# whole tokens — the CLI scales them by the decimals it reads on chain.
DEMAND_TOKEN_ADDRESS = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
DEMAND_AMOUNT = 10 * 10**18

_ALKAHEST_ADDRESSES_PATH = str(
    resources.files("market_storefront.data").joinpath("alkahest_anvil_addresses.json")
)
_ALKAHEST_CFG = resolve_alkahest_address_config(
    get_alkahest_network("anvil"),
    config_path=_ALKAHEST_ADDRESSES_PATH,
)
ACCEPTED_ESCROWS = [
    {
        "chain_name": "anvil",
        "escrow_address": str(_ALKAHEST_CFG.erc20_addresses.escrow_obligation_default).lower(),
        "literal_fields": {"token": DEMAND_TOKEN_ADDRESS},
        "rates": [{"field": "amount", "per": "hour", "value": str(DEMAND_AMOUNT)}],
    }
]


#: Run-log fields safe to print into CI output, and sufficient to say what
#: the buy did. The whole event carries proposals, accepted terms and
#: tenant credentials; an assertion message is not the place for those.
_REPORTABLE_EVENT_FIELDS = (
    "event",
    "status",
    "reason",
    "error",
    "listing_id",
    "seller_url",
    "negotiation_id",
    "round",
    "rounds",
    "agreed_amount",
    "attempts",
)


def _run_log_digest(run: MarketRun) -> str:
    """Summarize a finished `market buy` run-log for a failure message.

    ``market buy`` reports one aggregate reason for a buy that agreed with
    nobody, and stdout carries no per-candidate detail. The run-log does:
    the negotiation events say whether the buyer opened, what the seller
    answered, and what the outcome was. Read without waiting — the process
    has exited, so the log is final and ``run_id`` would only raise a
    second, less informative failure.
    """
    events = run.events_or_empty()
    if not events:
        return "run-log: none written"
    lines = []
    for event in events:
        fields = {
            key: event[key]
            for key in _REPORTABLE_EVENT_FIELDS
            if key in event and event[key] is not None
        }
        lines.append(" ".join(f"{k}={v!r}" for k, v in fields.items()))
    return "run-log events:\n  " + "\n  ".join(lines)


def _recipient_demands(seller_wallet: str) -> list[dict]:
    return [
        {
            "chain_name": "anvil",
            "arbiter": get_recipient_arbiter(
                "anvil",
                config_path=_ALKAHEST_ADDRESSES_PATH,
            ).lower(),
            "demand_data": {"recipient": seller_wallet.lower()},
        }
    ]


DURATION_HOURS = 1
#: Whole tokens, as `market buy` takes them: under the 10-token asking
#: rate so round 0 counters, ceiling over it so the buyer accepts the
#: seller's counter. In base units these become 7e18 and 1.2e19, past the
#: JSON safe-integer range and so carried as decimal-digit strings.
BUYER_INITIAL_PRICE = 7
BUYER_MAX_PRICE = 12
BUY_RULE_ID = "e2e-buy-create"  # non-pausing mock rule: create job returns immediately

BUY_RESOURCE_CSV = (
    "resource_id,resource_type,resource_subtype,unit,value,state,min_price,token,"
    "max_duration_seconds,attribute.gpu_model,attribute.sla,attribute.region,attribute.vm_host\n"
    f"{BUY_RESOURCE_ID},compute.gpu,rtx4090,count,1,available,10,{DEMAND_TOKEN_ADDRESS},,"
    f'{BUY_GPU_MODEL},90.0,"California, US",kvm1\n'
)

_REGISTRY_A = str(settings.REGISTRY.API_URL or "http://registry:8080")


# ===========================================================================
# Phase B0 — readiness
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


class TestStageB1a_ExecutorHostRegistry:
    def test_b1a_registers_executor_host_and_syncs_projection(
        self, provisioning_client, storefront_admin_client,
        site_capacity_admin_client, deal_state: DealState,
    ):
        """Register the executor host the seeded buy resource sits on.

        The site authority projects capacity by iterating host rows. With no host
        registered the projection is empty, so B4's negotiation is refused with
        `no_matching_inventory` even though discovery found the listing —
        the failure lands three stages from its cause.

        Registered through the admin API rather than a mounted inventory file:
        `inventory_path` is docker-compose-specific while the canonical Helm
        deployment supplies inventory as an inline secret, and a mount is shared
        state no scenario declares. The storefront is then told to pull
        projections immediately and the pull is asserted, rather than sleeping
        out the poller interval.
        """
        require_state(deal_state, "_resources_seeded")

        # The host is executor identity; the capacity declaration is what `probe`,
        # `reserve`, and the seller's inventory guard match against, and only a
        # declaration creates one. With the host alone, B4's negotiation is refused
        # `no_matching_inventory` even though discovery found the listing. The
        # declared attributes mirror this scenario's listing, since the guard
        # compares region and gpu_model by equality.
        host = provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=E2E_BUY_HOST,
            pool_id=E2E_BUY_POOL_ID,
            resource_id=BUY_RESOURCE_ID,
            sellable_units=1,
            attributes={
                "gpu_model": BUY_GPU_MODEL,
                "region": "California, US",
                "sla": "90.0",
            },
        )
        assert host.name == E2E_BUY_HOST
        assert (host.gpu_count or 0) >= E2E_HOST_GPU_COUNT, (
            f"executor host {E2E_BUY_HOST} reports {host.gpu_count} GPU(s); "
            f"scenarios reserve up to {E2E_HOST_GPU_COUNT}"
        )

        sites = refresh_storefront_projections(storefront_admin_client)

        deal_state._executor_host_registered = True
        log.info(
            "[B1a] Executor host %s registered (gpus=%s); projections confirmed for %s",
            E2E_BUY_HOST, host.gpu_count, sorted(sites),
        )


class TestStageB2_PublishListing:
    def test_b2_create_and_publish_listing(
        self, storefront_admin_client,
        storefront_seller_client, seller_wallet, registry_client, deal_state: DealState
    ):
        """Create the listing paused, resume to publish, confirm in registry.

        Discovery reads the registry, so the listing must be published (open)
        there before ``market buy`` runs. Resume publishes synchronously, so
        the registry row exists by the time resume returns.
        """
        require_state(deal_state, "_resources_seeded")

        resp = storefront_seller_client.create_listing(
            listing_resource=OFFER_RESOURCE,
            capacity_source=capacity_source_for(OFFER_RESOURCE),
            accepted_escrows=ACCEPTED_ESCROWS,
            demands=_recipient_demands(seller_wallet),
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
    def test_b3_arm_create_rule_no_pause(self, provisioning_test_client, deal_state: DealState):
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
    def test_b4_market_buy_reaches_ready(self, buyer_cli, deal_state: DealState):
        """`market buy` discovers, negotiates, escrows, settles, polls → ready.

        Pure discovery (no seller override): the buyer resolves the seller from
        the registry-advertised storefront URL and reaches it over the network.
        The typed resource query returns only this suite's listing, and the
        settlement clause selects its advertised Alkahest token option.

        Explicit negotiation prices mirror the full-deal suite, in whole
        tokens as the CLI takes them: initial 7 (below the 10-token asking
        rate → round-0 counter), max 12 (above the
        floor → buyer accepts the seller's first counter).
        """
        require_state(deal_state, "seller_listing_id", "provisioning_gate_armed")

        run = buyer_cli.run(
            [
                "buy",
                "--resource",
                f'gpu_model="{BUY_GPU_MODEL}"',
                "--settlement",
                f"mechanism=alkahest.v1 asset={DEMAND_TOKEN_ADDRESS}",
                "--initial-price",
                str(BUYER_INITIAL_PRICE),
                "--max-price",
                str(BUYER_MAX_PRICE),
                "--duration-hours",
                str(DURATION_HOURS),
                "--max-matches",
                "5",
                "--max-rounds",
                "10",
                "--poll-interval",
                "1.0",
                "--settlement-timeout",
                "300",
                "--expiration",
                "3600",
                "--yes",
            ],
            timeout=300.0,
        )

        assert run.returncode == 0, (
            f"`market buy` exited {run.returncode}; expected 0 (ready).\n"
            f"stdout (tail): {run.stdout()[-2500:]}\n"
            f"stderr (tail): {run.stderr()[-2500:]}\n"
            f"{_run_log_digest(run)}"
        )

        events = run.read_events()
        terminal = next(
            (e for e in reversed(events) if e.get("event") == "run_ended"),
            None,
        )
        assert terminal is not None, (
            f"Buy run-log missing run_ended. events tail: {[e.get('event') for e in events[-6:]]}"
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
            run.run_id,
            escrow_uid,
            neg_id,
            terminal.get("fulfillment_uid"),
        )


# ===========================================================================
# Phase B4c — capacity-event reconciliation, stepped
# ===========================================================================


class TestStageB4c_CapacityEventCycle:
    def test_b4c_capacity_events_dry_run_then_advance(
        self, storefront_admin_client, deal_state: DealState
    ):
        """Step the capacity-event loop: read the cause, then apply it.

        The deal holds this scenario's only sellable unit, so the 1x listing
        it was published from is no longer satisfiable. Nothing on the deal
        path closes it -- the settle route reserves capacity and leaves the
        derived-listing reconciliation to the capacity-delta subscriber, which
        this scenario holds paused. So the close is asserted where it is
        asked for rather than raced against a timer.

        Two halves on purpose. The dry run names the pending events while the
        listing is still open, which is the cause; the advance applies them
        and the listing closes, which is the effect. Asserting only the effect
        would pass for any reason the listing happened to close.
        """
        require_state(
            deal_state,
            "seller_listing_id",
            "settlement_status",
        )

        before = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert before.status == "open", (
            f"listing is {before.status!r} before the capacity cycle was "
            "advanced; something other than this stage reconciled it, and the "
            "assertions below no longer say what they claim"
        )

        preview = dry_run_storefront(storefront_admin_client, "capacity-events")
        assert preview["dry_run"] is True
        pending = one_site(preview)
        assert pending["error"] is None, (
            f"capacity-event dry run failed for site {pending['site']!r}: "
            f"{pending['error']}"
        )
        assert not pending["would_position"], (
            "the dry run reports it would position at the feed head, which "
            "means the poller's cursor was lost — a following advance would "
            "full-reconcile instead of applying the deal's own events"
        )
        assert pending["pending_count"] >= 1, (
            "the deal reserved capacity, so its authority has events waiting; "
            f"the feed reports none (cursor={pending['cursor']!r} "
            f"head={pending['feed_head']!r})"
        )

        # A dry run that changes something is not a dry run: same answer
        # twice, and the listing still open after both.
        repeated = one_site(dry_run_storefront(storefront_admin_client, "capacity-events"))
        assert repeated == pending, (
            "two consecutive dry runs disagree, so the first one had an "
            f"effect: {pending!r} then {repeated!r}"
        )
        unchanged = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert unchanged.status == "open", (
            f"the listing became {unchanged.status!r} across two dry runs, "
            "which are supposed to emit nothing and reconcile nothing"
        )

        # Projections before deltas. With `use_site_projection_for_listings`
        # on (the shipped default) the close path decides from the
        # storefront's own projection cache, and only the site-projections
        # loop refills it -- held here like every other loop. Applying the
        # deltas against a pre-deal projection closes nothing however many of
        # them there are, which is exactly what the previous run showed: four
        # events applied, listing still open.
        projections = advance_storefront(storefront_admin_client, "site-projections")
        assert projections.get("sites"), (
            "the site-projections advance reported no site state, so the "
            "projection the close path reads was not refreshed and the "
            "capacity cycle below would decide from stale availability"
        )

        # One cycle per call, so a truncated page is stepped rather than
        # drained behind the caller's back. Bounded: a feed that never
        # reaches its head is a failure to report, not a loop to keep running.
        applied_total = 0
        for step in range(5):
            cycle = one_site(advance_storefront(storefront_admin_client, "capacity-events"))
            assert cycle["error"] is None, (
                f"capacity-event cycle {step} failed for site "
                f"{cycle['site']!r}: {cycle['error']}"
            )
            applied_total += int(cycle["applied_count"])
            if not cycle["truncated"]:
                break
        else:
            raise AssertionError(
                "capacity-event feed still reports a truncated page after "
                f"five cycles (applied {applied_total} events)"
            )
        assert applied_total >= pending["pending_count"], (
            f"the advance applied {applied_total} event(s) where the dry run "
            f"named {pending['pending_count']} pending"
        )
        assert cycle["cursor"] == cycle["feed_head"], (
            f"cursor {cycle['cursor']!r} did not reach the feed head "
            f"{cycle['feed_head']!r} after draining"
        )

        drained = one_site(dry_run_storefront(storefront_admin_client, "capacity-events"))
        assert drained["pending_count"] == 0, (
            "the feed still reports pending events after draining, so the "
            f"cursor did not advance: {drained!r}"
        )

        closed = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert closed.status == "closed", (
            f"listing is {closed.status!r} after {applied_total} capacity "
            "event(s) were applied. The deal holds the only sellable unit, so "
            "reconciliation should have closed it — check the reconcile hook "
            "wired to the aggregate the advance route resolves, not the feed."
        )
        deal_state._capacity_events_advanced = True
        log.info(
            "[B4c] Capacity events stepped: %s pending, %s applied, listing closed",
            pending["pending_count"], applied_total,
        )


# ===========================================================================
# Phase B5 — seller-side + provisioning lease cross-checks
# ===========================================================================


class TestStageB5_SellerAndLease:
    def test_b5_seller_state_and_lease_registered(
        self, storefront_admin_client, provisioning_client, deal_state: DealState
    ):
        """Seller closes the listing while provisioning owns the lease.

        Cross-machine confirmation that the buyer's one-shot landed real
        state on the seller side: the listing is ``closed`` while the 1x
        capacity is held, the per-deal
        primary escrow is ``ready`` with a fulfillment_uid, and the
        provisioning service registered a lease for the escrow.
        """
        require_state(
            deal_state,
            "real_escrow_uid",
            "negotiation_id",
            "seller_listing_id",
            "settlement_status",
            # The listing closes when the capacity cycle is advanced, which
            # B4c does and asserts; without that dependency this stage races
            # a loop the scenario deliberately holds.
            "_capacity_events_advanced",
        )

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "closed", (
            f"Expected listing to close while capacity is held, got {listing.status!r}"
        )

        detail = storefront_admin_client.get_negotiation(
            deal_state.seller_listing_id,
            deal_state.negotiation_id,
        )
        primary = next((e for e in (detail.escrows or []) if e["is_primary"]), None)
        assert primary is not None, f"No primary escrow on the negotiation: {detail.escrows!r}"
        assert primary["escrow_uid"] == deal_state.real_escrow_uid, (
            f"Primary escrow_uid mismatch: endpoint={primary['escrow_uid']!r} "
            f"buy={deal_state.real_escrow_uid!r}"
        )
        assert primary["status"] == "ready", (
            f"Expected primary escrow status=ready, got {primary['status']!r}"
        )
        assert primary["fulfillment_uid"], f"Primary escrow missing fulfillment_uid: {primary!r}"

        # DealLease resolves where the lease lives: a site-ledger
        # reservation (remote-capacity mode) or a vm_leases row (embedded).
        from tests.e2e.roles.scenarios.vms.conftest import DealLease

        lease = DealLease(provisioning_client, deal_state.real_escrow_uid).refresh()
        assert lease.get("escrow_uid") == deal_state.real_escrow_uid
        # Not `resource_id`: the lease reports the executor it placed the deal
        # on, and physical identity is reported nowhere the commercial side
        # can read it -- the same strip that retired `resource_id` from the
        # reservation response. The host is what the authority does report,
        # and it is what an operator needs to find the VM.
        assert lease.get("vm_host") == E2E_BUY_HOST, (
            f"Lease bound to unexpected executor {lease.get('vm_host')!r}; "
            f"expected {E2E_BUY_HOST!r}. Lease: {lease}"
        )
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease, got {lease.get('status')!r}: {lease}"
        )
        deal_state.reserved_resource_id = BUY_RESOURCE_ID
        log.info(
            "[B5] Seller listing=%s; primary escrow ready (fulfillment=%s); lease=%s status=%s",
            listing.status,
            primary["fulfillment_uid"],
            lease.get("id"),
            lease.get("status"),
        )
