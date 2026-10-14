"""Stages of the compute family's canonical complete deal, defined once.

The canonical deal settles through Alkahest on the dev chain and delivers through
the provisioning service's mock profile. Each stage here is one a compute domain
runs identically; a domain's scenario module declares its stages in order by
subclassing these with an empty body::

    class TestStage05b_NegotiationStartsAndVisible(Stage05b_NegotiationStartsAndVisible):
        pass

and inserts its own stages between them. A domain never replaces a shared stage's
body, so a change here runs in every lane that uses it; a stage whose body would
differ between domains is not shared and stays each domain's own. The classes are
not named ``Test*``, so pytest collects them only through those subclasses.

What differs between domains reaches a stage two ways. Fixtures supply who is
calling, under one set of names every compute domain's conftest provides:
``storefront_client`` (buyer), ``storefront_admin_client``, ``registry_client``
(buyer),
``provisioning_client``, ``provisioning_test_client``, ``buyer_config``,
``seller_wallet``, ``buyer_principal``, ``deal_state``, and ``deal_driver``. The
``deal_driver`` fixture supplies what is the domain's own, through
``ComputeDealDriver``.

Every stage previews a transition before it advances it, and names each earlier
result it depends on with ``require_state``, so a failed stage skips its
dependents rather than letting them fail far from the cause.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Protocol

from tests.e2e.roles.helpers.compute_deal import (
    advance_fulfillment_to,
    pause_storefront,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.domain_deal import DomainDealState, require_state
from tests.e2e.roles.helpers.escrow import create_buyer_escrow

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The deal's commercial terms
#
# Every lane running the canonical deal lists its supply at LISTED_HOURLY_RATE
# of DEAL_TOKEN, so these prices mean the same thing to every seller policy.
# ---------------------------------------------------------------------------

DEAL_TOKEN = {
    "symbol": "MOCK",
    # MockERC20 deployed by alkahest at a fixed deterministic address on the
    # dev chain. The buyer (account #1) is pre-funded with it in the baked
    # chain state (see dev-env/generate_state.py), and stage 07 escrows real
    # tokens against this contract so the storefront's pre-settlement on-chain
    # verifier finds the EAS attestation.
    "contract_address": "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0",
    # 18, which is what the contract reports. The funding script mints whole
    # tokens (1 000 of them to this buyer), and the buyer CLI scales its price
    # flags by the decimals it reads from the chain, not by what a listing
    # advertises.
    "decimals": 18,
}
#: The asking rate every lane's listing advertises, in base units per hour.
LISTED_HOURLY_RATE = 10 * 10**18
DURATION_HOURS = 1
#: Escrow deadline, pinned at negotiation and written on chain unchanged.
ESCROW_TTL_SECONDS = 3600
# Base units of an 18-decimal asset, so past the JSON safe-integer range:
# these amounts ride the wire as decimal-digit strings, which is the shape
# canonical JSON can sign. Against the 10 tokens/hour asking rate, the opening
# bid sits under the floor (round-0 counter) and the ceiling over it (the buyer
# accepts the seller's first counter). Both stay far inside the 1 000 tokens
# the dev chain funds this buyer with — every scenario in a run escrows
# against the same wallet.
BUYER_INITIAL_PRICE = 7 * 10**18
BUYER_MAX_PRICE = 12 * 10**18

#: How far back to move a lease end so the watchdog treats it as expired.
#:
#: Bounded on both sides, which is why it is not simply "a long time ago". The
#: lease must be past its end for the watchdog to begin releasing, but it must
#: NOT be past `lease_watchdog_grace_period_seconds` (300s), because the release
#: path marks `release_failed` the moment grace elapses with teardown
#: unfinished — and stages 11a/11b deliberately hold teardown at a mock gate.
#: A back-date past grace would have the first cycle both dispatch the removal
#: and time it out.
#:
#: One minute expires the lease and leaves roughly four minutes for the gated
#: stages, which is ample for three stages that make no network waits.
E2E_LEASE_EXPIRY_BACKDATE = timedelta(minutes=1)


def _expired_lease_end() -> str:
    """A lease end the watchdog reads as expired but still inside its grace."""
    return (
        datetime.now(timezone.utc) - E2E_LEASE_EXPIRY_BACKDATE
    ).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# State and the domain's part
# ---------------------------------------------------------------------------

@dataclass
class ComputeDealState(DomainDealState):
    """What the shared stages hand each other, one field per producer.

    Each field is declared, with a default that reads as absent, because
    `require_state` reads through `getattr`: an undeclared sentinel skips its
    dependents identically whether the producing stage failed or the name was
    misspelled on one side, and a scenario that silently skips forever looks
    like a passing run.

    Three fields are produced by a domain's own stages rather than a shared
    one, since how a listing comes to exist and closes is the domain's:
    `seller_listing_id` and `listing_published` by its listing stages, and
    `_listing_reconciled` by the stage that steps its listing's reconciliation
    after the deal holds the capacity. `_supply_seeded` is produced here and
    required by each domain's first listing stage.
    """

    # Phase 0 — readiness. Each check gates the stages that depend on it.
    #: The storefront's timer loops are held, so every later effect is one a
    #: stage asked for. Required before the first write.
    _lifecycle_paused: bool = False
    _storefront_healthy: bool = False
    _registry_reachable: bool = False
    _provisioning_healthy: bool = False
    #: Both ends of the storefront-to-provisioning wire reported an agreeing
    #: contract major. Required before the first write over that wire, so a
    #: later failure cannot be explained away as version skew.
    _contract_pins_agree: bool = False
    _negotiation_strategy_viable: bool = False
    _provisioning_mock_mode: bool = False
    #: The deal's supply is declared at the site and the storefront holds its
    #: projection.
    _supply_seeded: bool = False
    _alkahest_configured: bool = False
    #: Provisioning reaches and authenticates to the storefront, which release
    #: needs for the capacity-released callback.
    _provisioning_storefront_ok: bool = False
    # Publication — produced by the domain's own listing stages.
    seller_listing_id: Optional[str] = None
    listing_published: bool = False
    # Negotiation.
    _evaluate_negotiate_passed: bool = False
    #: The escrow deadline the negotiation pinned, reused on chain at stage 07.
    _escrow_expiration_unix: Optional[int] = None
    negotiation_terminal_state: Optional[str] = None
    agreed_amount: Optional[int] = None
    # Settlement and delivery.
    real_escrow_uid: Optional[str] = None
    provisioning_gate_armed: bool = False
    _evaluate_settle_host_id: Optional[str] = None
    _evaluate_settle_passed: bool = False
    _provision_job_evaluated: bool = False
    #: Durable fulfillment identity, from the settle-status response at 08b;
    #: the buyer-facing path surfaces no raw executor job id.
    fulfillment_id: Optional[str] = None
    provisioning_result_injected: bool = False
    #: The domain stepped its listing's reconciliation after the deal took the
    #: capacity, so 09b's closed listing is an effect the scenario asked for.
    _listing_reconciled: bool = False
    settlement_status: Optional[str] = None
    # Lease, teardown, and release.
    #: The domain's lease view (`LeaseView`), resolved at 09c.
    deal_lease: Optional[Any] = None
    lease_id: Optional[str] = None
    #: The fulfillment the lease names once its release begins, observed at
    #: 10b. A separate field from `fulfillment_id` so the teardown stages skip
    #: when 10b did not observe release, rather than run against a fulfillment
    #: still active.
    teardown_fulfillment_id: Optional[str] = None
    #: The resource the deal holds, as the domain's driver names it. Captured
    #: at 09c from the driver, never from a buyer-facing response: physical
    #: identity is opaque across the ordinary reservation boundary.
    reserved_resource_id: Optional[str] = None
    _termination_requested: bool = False


class LeaseView(Protocol):
    """One deal's lease as the shared lease, teardown, and release stages read it."""

    lease_id: str
    is_ledger: bool
    # The deal reference the lease was found by, and its value.
    deal_field: str
    deal_value: str

    def refresh(self) -> dict: ...

    def backdate(self, lease_end_utc: str) -> dict: ...

    def resource_consumed(self, storefront_admin_client: Any, resource_id: str) -> bool: ...

    @property
    def released_stage_event(self) -> tuple[str, str]: ...


class ComputeDealDriver(Protocol):
    """What a compute domain supplies to the shared stages.

    A driver holds its domain's own clients and constants; a stage passes it
    only the deal's identities. Negotiation needs nothing from it: a domain
    that negotiates differently resolves that in its storefront composition.
    """

    #: The mock rule that holds the create job before it reports (07, 08c, 09a).
    create_rule_id: str
    #: The mock rule that holds provider teardown (10a, 11b).
    teardown_rule_id: str
    #: The resource the deal holds, as the storefront's capacity reads name it.
    reserved_resource_id: str

    def seed_supply(self) -> None:
        """Declare the deal's supply at the site and load the storefront's projection."""

    def provision_terms(self) -> dict[str, Any]:
        """The provision terms the buyer negotiates."""

    def arm_create_gate(self) -> None:
        """Arm `create_rule_id` so the create job pauses before its result."""

    def release_create_gate(self) -> None:
        """Release the create job `arm_create_gate` held."""

    def evaluate_create_job(self, host_id: str) -> dict[str, Any]:
        """The provisioning job evaluation: `params_valid`, `host_exists`,
        `rule_matched`, and `would_pause`."""

    def evaluate_settle_arguments(self) -> dict[str, Any]:
        """The domain's arguments to the settlement preview."""

    def check_evaluate_settle(self, result: dict[str, Any]) -> str:
        """Assert the domain's preview expectations; return the host it placed."""

    def settle_dispatched(self, settle_response: Any, deal_state: ComputeDealState) -> str:
        """Assert the domain's settle response and return the fulfillment it
        dispatched, read where the domain reports it."""

    def assert_delivery(self, deal_state: ComputeDealState) -> None:
        """Assert the ready settlement's result and access, where the domain
        delivers them."""

    def opening_selection(
        self, alkahest_option: dict, expiration_unix: int
    ) -> dict | None:
        """The settlement selection the buyer's opening names beside its escrow
        carrier, or ``None`` when the domain's storefront reads the selection from
        the escrow carrier itself."""

    def lease_view(self, deal_state: ComputeDealState) -> LeaseView:
        """The deal's lease, found by the deal reference its hold names."""

    def arm_teardown_gate(self) -> None:
        """Arm `teardown_rule_id` so provider teardown pauses before its result."""

    def release_teardown_gate(self) -> None:
        """Release the provider teardown `arm_teardown_gate` held."""

    def reserve_released_capacity(
        self, storefront_admin_client: Any, *, listing_id: str, escrow_uid: str
    ) -> Any:
        """Re-reserve the released supply through the deal's listing, asserting
        the domain's reservation, and return it."""

    def release_reserved(self, reservation: Any) -> None:
        """Release a reservation `reserve_released_capacity` made, as the site
        would, so no hold outlives the scenario."""


# ===========================================================================
# Phase 0 — readiness
# ===========================================================================

class Stage00_LifecyclePause:
    def test_00_pauses_the_storefront_loops(
        self, storefront_admin_client, deal_state: ComputeDealState
    ):
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
        deal_state._lifecycle_paused = True


class Stage00a_StorefrontHealth:
    def test_00a_storefront_is_healthy(
        self, storefront_admin_client, deal_state: ComputeDealState
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


class Stage00b_RegistryReachable:
    def test_00b_registry_reachable_from_storefront(
        self, storefront_admin_client, deal_state: ComputeDealState
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


class Stage00c_ProvisioningHealth:
    def test_00c_provisioning_is_healthy(
        self, provisioning_client, deal_state: ComputeDealState
    ):
        """GET /api/v1/system/status → every execution component is ready.

        Uses status rather than /health because status reports the readiness
        each composed execution distribution contributes — not just that the
        HTTP server is running. `checks.execution` is `ok` only when every
        component is ready. Mocked executors are ready without their real
        tooling; a component that is not ready means real executors that cannot
        run.
        """
        require_state(deal_state, "_storefront_healthy", "_registry_reachable")
        status = provisioning_client.get_system_status()
        execution = (status.checks or {}).get("execution", "absent")
        not_ready = [c.name for c in status.components if not c.ready]
        assert execution == "ok" and status.components and not not_ready, (
            f"Provisioning execution is not ready: checks.execution={execution!r}, "
            f"components not ready={not_ready!r}, "
            f"components={[c.name for c in status.components]!r}\n"
            "Ensure ACTIVE_PROFILES=mock is set on the provisioning container.\n"
            f"Full status: {status!r}"
        )
        deal_state._provisioning_healthy = True
        log.info(
            "[00c] Provisioning execution ready: components=%s",
            {c.name: c.detail.payload for c in status.components},
        )


class Stage00c2_ProvisioningContractPins:
    def test_00c2_both_participants_report_an_agreeing_contract_pin(
        self, storefront_admin_client, provisioning_client, deal_state: ComputeDealState
    ):
        """Both sides of the provisioning wire report the same contract major.

        The cutover for this wire requires every participant to report its
        pinned version *before mutations resume*, so a half-deployed fleet
        cannot quietly write rows in two spellings of the same field. This is
        that check, run against the live deployment rather than inferred from
        the source both services happen to be built from.

        A preflight on purpose. Stage 00f1, the first write over this wire,
        requires it, so the stages that follow -- which publish, negotiate,
        settle and provision -- are known to have been driven across a wire
        whose two ends agree, and a later failure cannot be quietly explained
        by version skew.

        The rejection of an unsupported major is a separate property and is
        covered where it belongs, against the route itself, in the
        provisioning service's own contract suite. This asserts agreement,
        not refusal: in a single-version stack the two cannot disagree, so
        what earns its keep here is that both sides *report* a pin at all
        and that the reported value is one the service admits.
        """
        require_state(
            deal_state,
            "_storefront_healthy",
            "_registry_reachable",
            "_provisioning_healthy",
        )
        provisioning_status = provisioning_client.get_system_status()
        seller_status = storefront_admin_client.get_system_status()

        service_pin = provisioning_status.provisioning_contract_version
        supported = provisioning_status.provisioning_contract_supported_majors
        caller_pin = seller_status.provisioning_contract_version

        assert service_pin, (
            "the provisioning service reports no contract pin, so a fleet "
            f"cannot be checked for skew: {provisioning_status!r}"
        )
        assert caller_pin, (
            "the storefront reports no provisioning contract pin, so the "
            "caller's half of the wire is unverifiable"
        )

        service_major = int(str(service_pin).split(".")[0])
        caller_major = int(str(caller_pin).split(".")[0])
        assert caller_major == service_major, (
            f"provisioning wire skew: the storefront speaks major "
            f"{caller_major} ({caller_pin!r}) and the service speaks "
            f"{service_major} ({service_pin!r}). Mutations must not resume "
            "until both sides agree."
        )
        assert supported and service_major in supported, (
            f"the service reports pin {service_pin!r} but admits majors "
            f"{supported!r}, so it does not accept its own declared version"
        )

        deal_state._contract_pins_agree = True
        log.info(
            "[00c2] provisioning contract pin agreed: storefront=%s "
            "service=%s supported=%s",
            caller_pin, service_pin, supported,
        )


class Stage00d_NegotiationStrategy:
    def test_00d_negotiation_strategy_is_viable(
        self, storefront_admin_client, deal_state: ComputeDealState
    ):
        """GET /api/v1/system/status → checks.negotiation_strategy not exit-on-probe.

        Catches the rl-strategy-but-no-torch failure mode before any negotiation
        attempt. If this fails, set the seller's negotiation policies to
        ['has_matching_inventory_guard', 'escrow_shape_guard', 'bisection']
        and restart the storefront.
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


class Stage00e_ProvisioningMockMode:
    def test_00e_provisioning_is_in_mock_mode(
        self, provisioning_client, deal_state: ComputeDealState
    ):
        """GET /api/v1/system/status → execution.mocked.

        Guards the full e2e deal flow from accidentally targeting a production
        provisioning service. If any composed executor is real, a settlement
        attempt would run an actual playbook against a real host.

        Fix: set provisioning.mockMode=true in the helm values and redeploy,
        or set ACTIVE_PROFILES=production,provisioning-secrets,mock on the
        provisioning container.
        """
        require_state(deal_state, "_provisioning_healthy")
        execution = provisioning_client.get_system_status().execution
        assert execution.mocked, (
            f"Provisioning executes jobs for real: {execution!r}.\n"
            "The e2e deal flow requires mock mode to avoid running real Ansible "
            "playbooks against live infrastructure.\n"
            "Fix: set provisioning.mockMode=true in values.yaml and redeploy, or\n"
            "set ACTIVE_PROFILES=production,provisioning-secrets,mock on the "
            "provisioning container."
        )
        deal_state._provisioning_mock_mode = True
        log.info("[00e] Provisioning mock mode confirmed: %s", execution.executors)


class Stage00f1_ExecutorHostRegistry:
    def test_00f1_registers_executor_host_and_syncs_projection(
        self, deal_driver: ComputeDealDriver, deal_state: ComputeDealState,
    ):
        """Declare this scenario's supply at the site and load its projection.

        Two separate stores, and both are required. The host is executor
        identity; the capacity declaration is what `probe`, `reserve`, and the
        seller's inventory guard all match against, and only a declaration
        creates one. With the host alone, every inventory match fails and the
        storefront refuses each negotiation with `no_matching_inventory` —
        several stages from the cause.

        The supply is this scenario's own. Sharing it across scenarios is
        incompatible with one declaration per executor, and would let one
        scenario's GPU count decide another's reservation.

        Declared through the site's administration API rather than a mounted
        inventory file, which is shared state no scenario declares. The
        storefront is then told to pull projections immediately and the pull
        is asserted, rather than sleeping out the poller interval. What a
        domain declares is its driver's: the shape it sells and the host it
        sells it on.

        The first write over the provisioning wire, so it requires the
        contract pins to agree and the storefront's loops held.
        """
        require_state(
            deal_state,
            "_lifecycle_paused",
            "_storefront_healthy",
            "_provisioning_mock_mode",
            "_contract_pins_agree",
        )
        deal_driver.seed_supply()
        deal_state._supply_seeded = True
        log.info("[00f1] Supply declared and the storefront's projection refreshed")


class Stage00g_AlkahestConfigured:
    def test_00g_alkahest_is_configured(
        self, storefront_admin_client, deal_state: ComputeDealState
    ):
        """GET /api/v1/system/status → checks.alkahest reports configured chain names.

        Alkahest must be configured before the on-chain escrow phases (07/07b).
        If this fails with alkahest='unconfigured', the storefront configuration
        is missing all chain entries or none initialised successfully.
        ``checks.alkahest`` is a comma-joined list of chain names
        ("anvil,base_sepolia"); the test only requires that the expected chain
        (``anvil`` for this e2e) is present in that list.
        """
        require_state(deal_state, "_storefront_healthy")
        status = storefront_admin_client.get_system_status()
        alkahest_check = (status.checks or {}).get("alkahest", "absent")
        assert "anvil" in alkahest_check, (
            f"Storefront alkahest client is not configured for anvil: "
            f"checks.alkahest={alkahest_check!r}\n"
            "The on-chain escrow phases (07, 07b) will fail without a working AlkahestClient.\n"
            "Fix: configure the anvil chain's rpc_url and "
            "alkahest_address_config_path for the storefront."
        )
        deal_state._alkahest_configured = True
        log.info("[00g] Alkahest configured: checks.alkahest=%s", alkahest_check)


class Stage00h_ProvisioningStorefrontLink:
    def test_00h_provisioning_can_reach_storefront(
        self, provisioning_client, deal_state: ComputeDealState
    ):
        """GET /api/v1/system/status → checks.storefront=ok, checks.storefront_auth=ok.

        Validates that the provisioning service can reach and authenticate to
        the storefront. This is the path the site's lease release uses to tell
        the storefront a reservation's capacity was released, so 10a, where
        release begins, requires it.

        Two sub-checks from the provisioning health endpoint:
          - storefront      — GET {storefront_url}/health responded 200
          - storefront_auth — GET {storefront_url}/api/v1/system/status, signed
                              under the `service` role, responded 200 with a
                              response signed by the pinned storefront principal

        If this fails with storefront='unconfigured': the provisioning
        service's storefront_url and service-peer identity are not configured.

        If this fails with storefront='unreachable': both services must be on
        the same network, and the storefront container running and healthy.

        If this fails with storefront_auth='unauthorized': the provisioning
        service signs as its own principal, which the storefront must pin as a
        service peer.
        """
        require_state(deal_state, "_provisioning_healthy", "_storefront_healthy")

        health = provisioning_client.get_system_status()
        checks = health.checks

        sf_check = checks.get("storefront", "absent")
        assert sf_check == "ok", (
            f"Provisioning cannot reach storefront: checks.storefront={sf_check!r}\n"
            "Provisioning will not be able to tell the storefront when a lease's capacity is released.\n"
            "Verify the provisioning service's storefront_url points to the "
            "storefront and both containers share the compose project's network.\n"
            f"Full health response: {health}"
        )

        auth_check = checks.get("storefront_auth", "absent")
        assert auth_check == "ok", (
            f"Provisioning storefront auth failed: checks.storefront_auth={auth_check!r}\n"
            "Provisioning signs as its own service identity; 'unauthorized'\n"
            "means its principal is not the one the storefront pins as a\n"
            "service peer.\n"
            f"Full health response: {health}"
        )

        deal_state._provisioning_storefront_ok = True
        log.info(
            "[00h] Provisioning→storefront link ok: storefront=%s storefront_auth=%s",
            sf_check, auth_check,
        )


# ===========================================================================
# Phase 4 — Registry publication
# The full-deal happy path uses the primary registry only. Multi-registry
# fan-out/fan-in and private registry auth belong in separate topology-specific
# e2e tests.
# ===========================================================================

class Stage04a_PrimaryRegistryPublish:
    def test_04a_listing_appears_in_primary_registry(
        self, registry_client, deal_state: ComputeDealState
    ):
        """The seller publishes the listing to the primary registry.

        Read as a buyer reads it, through the registry's typed client: a listing
        the registry does not hold is refused, which fails this stage.
        """
        require_state(deal_state, "listing_published", "seller_listing_id")
        listing_id = deal_state.seller_listing_id
        listing = registry_client.get_listing(listing_id)
        assert str(listing.id) == listing_id, (
            f"the registry returned a listing with the wrong id: {listing!r}"
        )
        log.info("[04a] Listing %s present in primary registry", listing_id)


# ===========================================================================
# Phase 5 — Negotiation lifecycle
# ===========================================================================

class Stage05a_EvaluateNegotiate:
    def test_05a_evaluate_negotiate_would_not_exit(
        self, storefront_admin_client, buyer_principal, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        """POST /api/v1/admin/listings/{id}/evaluate-negotiate → would_negotiate=True (dry-run).

        Runs the configured negotiation strategy against BUYER_INITIAL_PRICE
        without creating a thread. Catches price_unreasonable and
        torch_unavailable before committing a real negotiation.
        """
        require_state(
            deal_state, "seller_listing_id", "listing_published",
            "_negotiation_strategy_viable",
        )

        result = storefront_admin_client.evaluate_negotiate(
            deal_state.seller_listing_id,
            proposal={
                "chain_name": "anvil",
                "escrow_address": "0x" + "0" * 40,
                "fields": {
                    # Decimal-digit string: the request body is
                    # canonicalized for signing, and a base-unit
                    # amount has no JSON number form.
                    "amount": str(BUYER_INITIAL_PRICE),
                    "token": DEAL_TOKEN["contract_address"],
                },
                "expiration_unix": 2_000_000_000,
            },
            provision_terms=deal_driver.provision_terms(),
            # The evaluation identifies the buyer by marketplace principal, not
            # by EVM wallet: the strategy is asked what it would do for this
            # caller, and the caller is the signing identity.
            buyer_principal=buyer_principal,
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
            f"Strategy returned decision={result.decision!r} "
            f"reason={result.decision_reason!r} at round 0 for "
            f"BUYER_INITIAL_PRICE={BUYER_INITIAL_PRICE} "
            f"(our_reference_amount={result.our_reference_amount}, "
            f"their_proposed_amount={result.their_proposed_amount}).\n"
            "A terminal decision here means 06b's force_accept will 409 on an "
            "already-closed negotiation.\n"
            "If 'accept': the opening price is at or above the seller floor — "
            "lower BUYER_INITIAL_PRICE so the strategy counters instead.\n"
            "If 'reject': raise BUYER_INITIAL_PRICE toward our_reference_amount "
            "— but read the reason first, since a guard can decline for causes "
            "that have nothing to do with price."
        )
        deal_state._evaluate_negotiate_passed = True
        log.info("[05a] Evaluate-negotiate: decision=%s reason=%s strategy=%s",
                 result.decision, result.decision_reason, result.strategy)


class Stage05b_NegotiationStartsAndVisible:
    def test_05b_buyer_starts_negotiation_and_thread_confirmed(
        self, storefront_client, storefront_admin_client, registry_client,
        deal_driver: ComputeDealDriver, deal_state: ComputeDealState,
    ):
        """Negotiation starts + visible + round-0 confirmed in event stream.

        Combined advance + confirm:
          1. POST /api/v1/negotiate/new → negotiation_id
          2. GET /api/v1/listings/{id}/negotiations → thread listed
          3. GET stage_events → round_decided event with decision != exit
        """
        require_state(deal_state, "seller_listing_id", "_evaluate_negotiate_passed")

        # Pin the escrow deadline here and reuse it when the escrow is
        # created on chain. Left to the client's default, each side computes
        # "now + an hour" at a different moment and settlement verification
        # refuses the attestation over a one-second difference.
        deal_state._escrow_expiration_unix = int(time.time()) + ESCROW_TTL_SECONDS

        # The listing's one Alkahest option, which the domain's opening names
        # where its storefront needs the selection stated explicitly.
        (alkahest_option,) = [
            dict(option)
            for option in registry_client.get_listing(
                deal_state.seller_listing_id
            ).settlement_options
            if dict(option)["mechanism"] == "alkahest.v1"
        ]

        resp = storefront_client.negotiate_new(
            listing_id=deal_state.seller_listing_id,
            initial_amount=BUYER_INITIAL_PRICE,
            escrow_expiration_unix=deal_state._escrow_expiration_unix,
            # The provision terms are negotiated, not settle-time inputs:
            # settle reads them from the accepted terms and refuses to
            # substitute the caller's, so a term missing here cannot be
            # supplied later.
            provision_terms=deal_driver.provision_terms(),
            token=DEAL_TOKEN["contract_address"],
            settlement_selection=deal_driver.opening_selection(
                alkahest_option, deal_state._escrow_expiration_unix
            ),
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
            "Check that the negotiation runtime emits stage_event after decide()."
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

class Stage06b_ForceAcceptAndTerminal:
    def test_06b_force_accept_and_terminal_success(
        self, storefront_admin_client, deal_state: ComputeDealState
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

class Stage07_OnChainEscrowAndProvGate:
    def test_07_create_real_escrow_and_arm_gate(
        self, buyer_config, seller_wallet, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        """Create a real on-chain escrow attestation + arm provisioning pause gate.

        Why on-chain (not a placeholder uid): the storefront reads the EAS
        attestation by uid before it starts provisioning, so a placeholder uid
        fails verification.

        What's "buyer interaction" vs "anvil setup": token *distribution*
        is baked into the chain state (account #1 holds MockERC20 — see
        dev-env/generate_state.py). Token *escrow* is part of the deal flow — in
        production the buyer signs and sends this transaction themselves —
        so we do it here from the buyer's wallet, against the just-finalized
        negotiation terms.

        The pause gate holds the mock create job before it reports success,
        giving stage 08b a window to assert the fulfillment dispatching before
        stage 09a releases it.
        """
        # Alkahest readiness is required before the escrow is created, not only
        # before 07b verifies it: an escrow created on chain cannot be undone.
        require_state(deal_state, "negotiation_terminal_state", "agreed_amount",
                      "_provisioning_mock_mode", "_escrow_expiration_unix",
                      "_alkahest_configured")

        escrow_uid = create_buyer_escrow(
            buyer_private_key=buyer_config["private_key"],
            seller_wallet_address=seller_wallet,
            agreed_amount=int(deal_state.agreed_amount),
            duration_seconds=DURATION_HOURS * 3600,
            token_contract_address=DEAL_TOKEN["contract_address"],
            rpc_url=buyer_config["rpc_url"],
            expiration_unix=deal_state._escrow_expiration_unix,
        )
        deal_state.real_escrow_uid = escrow_uid
        log.info("[07] Created on-chain escrow %s for negotiation %s",
                 escrow_uid, deal_state.negotiation_id)

        deal_driver.arm_create_gate()
        deal_state.provisioning_gate_armed = True
        log.info("[07] Provisioning gate armed with rule=%s", deal_driver.create_rule_id)


# ===========================================================================
# Phase 7b — Verify on-chain escrow via storefront (getRecordFromChain dry-run)
# ===========================================================================

class Stage07b_VerifyEscrow:
    def test_07b_storefront_verifies_on_chain_escrow(
        self, storefront_admin_client, seller_wallet, deal_state: ComputeDealState
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

class Stage08a_EvaluateSettle:
    def test_08a_evaluate_settle_would_submit(
        self, storefront_admin_client, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        """POST /api/v1/admin/settle/{uid}/evaluate → would_submit=True (dry-run).

        Previews the fulfillment settle would start, without chain reads, DB
        writes, or provisioning calls, and confirms a matching host exists
        before committing to settle. What the preview takes and reports beyond
        that is the domain's.
        """
        require_state(deal_state, "real_escrow_uid", "seller_listing_id", "negotiation_id")

        result = storefront_admin_client.evaluate_settle(
            deal_state.real_escrow_uid,
            listing_id=deal_state.seller_listing_id,
            # Settle names this negotiation and commits its acceptance hold,
            # so the preview is asked about the same negotiation.
            negotiation_id=deal_state.negotiation_id,
            **deal_driver.evaluate_settle_arguments(),
        )
        assert result.get("would_submit") is True, (
            f"evaluate_settle returned would_submit=False.\n"
            f"reason={result.get('reason')!r}\n"
            "Check that the deal's capacity is declared at the site and "
            "matches the listing's requirements."
        )
        host_id = deal_driver.check_evaluate_settle(result)
        deal_state._evaluate_settle_host_id = host_id
        deal_state._evaluate_settle_passed = True
        log.info("[08a] Evaluate settle: host_id=%s", host_id)


# ===========================================================================
# Phase 8c — Evaluate provisioning job (provisioning service dry-run)
# ===========================================================================

class Stage08c_EvaluateProvisioningJob:
    def test_08c_evaluate_provisioning_job(
        self, deal_driver: ComputeDealDriver, deal_state: ComputeDealState
    ):
        """POST /test/evaluate-job → params_valid=True, the create rule matched (dry-run).

        Exercises the provisioning service's job routing in isolation:
        confirms the host exists in inventory, the job params are valid,
        and the armed mock rule would match and pause. No job is created.
        """
        require_state(deal_state, "_evaluate_settle_passed", "provisioning_gate_armed")

        host_id = deal_state._evaluate_settle_host_id
        assert host_id, (
            "host_id not captured from stage 08a — cannot evaluate provisioning job."
        )

        result = deal_driver.evaluate_create_job(host_id)
        assert result.get("params_valid") is True, (
            f"Provisioning job params invalid. errors={result.get('errors')!r}"
        )
        assert result.get("host_exists") is True, (
            f"Host {host_id!r} not found in provisioning inventory."
        )
        assert result.get("rule_matched") == deal_driver.create_rule_id, (
            f"Expected mock rule {deal_driver.create_rule_id!r} to match, "
            f"got rule_matched={result.get('rule_matched')!r}."
        )
        assert result.get("would_pause") is True
        deal_state._provision_job_evaluated = True
        log.info("[08c] Provisioning job evaluate: host=%s rule=%s",
                 host_id, result.get("rule_matched"))


# ===========================================================================
# Phase 8b — Settlement pipeline (advance)
# ===========================================================================

class Stage08b_SettlementSubmittedAndJobQueued:
    def test_08b_settlement_submitted_and_provisioning_job_queued(
        self, storefront_client, provisioning_client, buyer_config,
        deal_driver: ComputeDealDriver, deal_state: ComputeDealState,
    ):
        """Settlement submitted + fulfillment dispatched — advance + observe.

        Advance: POST /api/v1/settle/{uid}.
        Observe: the domain's driver asserts what settle answered and reads the
          dispatched fulfillment where the domain reports it.
        Confirms: fulfillment visible in provisioning API, gated in
          "dispatching" state by the paused mock rule armed in stage 07.
        """
        require_state(deal_state, "negotiation_id", "real_escrow_uid", "_provision_job_evaluated")

        settle_resp = storefront_client.settle_evm(
            deal_state.real_escrow_uid,
            negotiation_id=deal_state.negotiation_id,
            buyer_evm_address=buyer_config["wallet_address"],
        )
        # What settle answers and where the dispatched fulfillment is read are
        # the domain's; that a fulfillment was dispatched, and is held, is not.
        fulfillment_id = deal_driver.settle_dispatched(settle_resp, deal_state)
        assert fulfillment_id, (
            f"no fulfillment was dispatched after settlement: {settle_resp}"
        )

        status = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert status.get("state") == "dispatching", (
            f"Expected fulfillment dispatched but gated on the paused mock "
            f"rule, got: {status}"
        )
        deal_state.fulfillment_id = fulfillment_id
        log.info("[08b] Fulfillment %s in state %s", fulfillment_id, status.get("state"))


# ===========================================================================
# Phase 9 — Provisioning completion
# ===========================================================================

class Stage09a_ProvisioningCompletes:
    def test_09a_release_gate_and_job_succeeds(
        self, provisioning_test_client, provisioning_client,
        deal_driver: ComputeDealDriver, deal_state: ComputeDealState,
    ):
        """Release the provisioning gate, then deterministically converge
        the fulfillment to a terminal state.

        The durable fulfillment path surfaces no raw executor job id to the
        storefront (see stage 08b), so this cannot wait on one job by id. Two
        separate things must happen, neither implied by the other:

        1. The gated job actually finishes once the mock rule releases it --
           ``drain()`` waits for every outstanding test job to reach a
           terminal state without needing to know its id, which is
           equivalent to waiting for this one specific job in this
           single-deal, single-job e2e scenario.
        2. The *fulfillment* record separately converges to ``active`` only
           once the convergence watchdog observes the provider's terminal
           status (openspec/specs/fulfillment/spec.md's fulfillment
           convergence worker requirement) -- job completion alone doesn't
           advance it. ``advance_fulfillment_convergence_cycle()``
           triggers that deterministically instead of sleeping against
           its real background interval.

        ``advance`` rather than ``run``: a plain cycle is an advance
        *attempt*. The watchdog keeps its claim on a row whose provider
        answered "pending", so the claim lease spaces the next poll and a
        further cycle inside that lease reaches nothing. Here that is a
        race -- the timer could have claimed this row while the job above
        was still gated -- the same race 11b's advances avoid.
        The advance releases the watchdog's own claims first; the timer is
        paused for the module by ``convergence_advanced_explicitly``.
        """
        require_state(deal_state, "fulfillment_id")

        deal_driver.release_create_gate()
        provisioning_test_client.drain(timeout=30)
        provisioning_client.advance_fulfillment_convergence_cycle()

        status = provisioning_client.get_fulfillment_status(deal_state.fulfillment_id).model_dump(mode="json")
        assert status.get("state") == "active", (
            f"Expected fulfillment to converge to active, got: {status}"
        )
        deal_state.provisioning_result_injected = True
        log.info(
            "[09a] Fulfillment %s converged to active", deal_state.fulfillment_id
        )


class Stage09b_SettlementReadyAndCredentials:
    def test_09b_settlement_ready_credentials_and_listing_closed(
        self, storefront_admin_client, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        """Settlement ready, the domain's delivery present, listing closed.

        The listing closes because its capacity is held by this deal; the
        domain's own reconciliation stage before this one is what asked for
        the close.

        Combined observation of all post-provisioning state:
          1. wait_for_settlement — server-side long-poll until the settlement is
             ready (no client polling)
          2. the domain's delivery, read where the domain delivers it, through
             its driver
          3. GET /api/v1/listings/{id} → status=closed
        """
        require_state(deal_state, "real_escrow_uid", "provisioning_result_injected",
                      "seller_listing_id", "negotiation_id",
                      "_listing_reconciled")

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

        deal_driver.assert_delivery(deal_state)

        listing = storefront_admin_client.get_listing(deal_state.seller_listing_id)
        assert listing.status == "closed", (
            f"Expected listing status=closed while capacity is held, got {listing.status!r}"
        )

        deal_state.settlement_status = wait_result.status
        log.info("[09b] Settlement ready; delivery present; listing status=%s",
                 listing.status)


class Stage09c_LeaseRecorded:
    def test_09c_provisioning_lease_recorded(
        self, deal_driver: ComputeDealDriver, deal_state: ComputeDealState
    ):
        """Provisioning owns the happy-path lease row after fulfillment.

        Placement is confirmed here, not at stage 08b, because ``host_id`` is
        intentionally opaque across the ordinary buyer-facing reservation
        boundary (openspec/specs/site-capacity/spec.md's "Capacity accounting
        is private to the site authority" requirement) -- the domain's
        admin-only lease view is a legitimate, separate introspection channel
        from that guarantee, not a way around it.

        Placement, not physical identity: the lease reports a null
        ``resource_id``. Whether a lease *should* carry its backing resource is
        an open question for the authority that owns physical identity; until
        it does, the executor is what it reports and what an operator needs to
        find the delivered resource.
        """
        require_state(
            deal_state,
            "negotiation_id",
            "real_escrow_uid",
            "settlement_status",
            "fulfillment_id",
        )

        lease_view = deal_driver.lease_view(deal_state)
        lease = lease_view.refresh()
        assert lease.get(lease_view.deal_field) == lease_view.deal_value, (
            f"lease does not name the deal's {lease_view.deal_field} "
            f"{lease_view.deal_value!r}: {lease}"
        )
        assert lease.get("host_id") == deal_state._evaluate_settle_host_id, (
            f"lease bound to executor {lease.get('host_id')!r}; stage 08a's "
            f"evaluate_settle chose {deal_state._evaluate_settle_host_id!r}. "
            f"Lease: {lease}"
        )
        assert lease.get("create_job_id"), (
            f"Expected a tracked create job on the admin lease view, "
            f"got: {lease}"
        )
        assert lease.get("status") in ("active", "pending"), (
            f"Expected active/pending lease after happy-path settlement, got: {lease}"
        )

        deal_state.deal_lease = lease_view
        # The driver's name for the resource, not the lease's null field. The
        # later stages that consume this address the resource in capacity reads
        # and the re-reservation, so the value they need is the one the driver
        # declared -- the lease never reported it.
        deal_state.reserved_resource_id = deal_driver.reserved_resource_id
        deal_state.lease_id = lease.get("id")
        log.info(
            "[09c] Lease %s recorded for escrow %s (resource=%s status=%s mode=%s)",
            deal_state.lease_id,
            deal_state.real_escrow_uid,
            deal_state.reserved_resource_id,
            lease.get("status"),
            "ledger" if lease_view.is_ledger else "legacy",
        )


# ===========================================================================
# Phase 10 — Lease expiry enters durable teardown
# ===========================================================================

class Stage10a_LeaseExpirySetup:
    def test_10a_expire_lease_and_arm_teardown_gate(
        self, provisioning_client, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        """Expire the deal's lease and hold provider teardown at its gate.

        The watchdog is paused first so the expiry sits unobserved until 10b runs
        one cycle: that keeps the trigger and the reaction as separate, asserted
        steps rather than one race.

        Release reaches the storefront through the capacity-released callback,
        so this requires the provisioning-to-storefront link 00h checked.
        """
        # `deal_lease` is a dependency: this stage back-dates through it, so a
        # missing lease view must skip here rather than raise an AttributeError
        # two lines down.
        require_state(deal_state, "lease_id", "real_escrow_uid",
                      "reserved_resource_id", "deal_lease",
                      "_provisioning_storefront_ok")
        assert provisioning_client.pause_lease_watchdog().get("paused") is True
        deal_driver.arm_teardown_gate()
        # Expire the lease rather than interrupting the deal. Expiry is what ends
        # a lease in production; interruption is an operator escape hatch for a
        # deal sold as interruptible, and driving the main teardown path with the
        # escape hatch would leave the ordinary path uncovered.
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


class Stage10b_LeaseCycleBeginsTeardown:
    def test_10b_lease_cycle_records_fulfillment_id(
        self, provisioning_client, storefront_admin_client, deal_state: ComputeDealState,
    ):
        require_state(deal_state, "_termination_requested", "deal_lease",
                      "reserved_resource_id")
        summary = provisioning_client.check_leases()
        assert summary.get("checked", 0) >= 1, summary
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "releasing", lease
        fulfillment_id = lease.get("fulfillment_id")
        assert fulfillment_id, lease
        fulfillment = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert fulfillment.get("state") == "teardown_dispatch_pending", fulfillment
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )
        deal_state.teardown_fulfillment_id = fulfillment_id


# ===========================================================================
# Phase 11 — Fulfillment convergence and observable release
# ===========================================================================

class Stage11a_TeardownDispatch:
    def test_11a_convergence_dispatches_teardown_while_capacity_stays_held(
        self, provisioning_client, storefront_admin_client, deal_state: ComputeDealState,
    ):
        require_state(deal_state, "teardown_fulfillment_id", "reserved_resource_id")
        diagnostics = provisioning_client.advance_fulfillment_convergence_cycle()
        assert "before" in diagnostics and "after" in diagnostics
        fulfillment = provisioning_client.get_fulfillment_status(
            deal_state.teardown_fulfillment_id
        ).model_dump(mode="json")
        assert fulfillment.get("state") == "tearing_down", fulfillment
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )


class Stage11b_TeardownCompletion:
    def test_11b_provider_completion_releases_lease_and_capacity(
        self, provisioning_client, provisioning_test_client,
        storefront_admin_client, deal_driver: ComputeDealDriver,
        deal_state: ComputeDealState,
    ):
        require_state(deal_state, "teardown_fulfillment_id", "lease_id",
                      "reserved_resource_id")
        sync_stage, sync_event = deal_state.deal_lease.released_stage_event
        existing = storefront_admin_client.get_events(limit=500, stage=sync_stage)
        since_id = max((ev.id for ev in existing.events), default=0)

        deal_driver.release_teardown_gate()
        provisioning_test_client.drain(timeout=30)
        # Convergence-driven, not one-shot: `drain` returns when the provider
        # job is no longer gated, which is not the same instant its outcome is
        # durably readable by `converge_teardowns`.
        advance_fulfillment_to(
            provisioning_client, deal_state.teardown_fulfillment_id, "torn_down",
        )

        release_summary = provisioning_client.check_leases()
        assert release_summary.get("released", 0) >= 1, release_summary
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "released", lease

        wait_for_stage_event(storefront_admin_client, sync_stage, sync_event,
                             since_id=since_id, timeout=10.0)
        assert not deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )

        # The endpoint reserves *through a listing's durable capacity
        # binding*, not against a bare site, so the listing is required
        # rather than incidental -- it is what resolves which site the hold
        # lands in. This deal's own listing is closed by now, which is fine:
        # closing never removes the binding, and the endpoint reads
        # open/closed state only to report which listings its reservation
        # closed.
        reserved_again = deal_driver.reserve_released_capacity(
            storefront_admin_client,
            listing_id=deal_state.seller_listing_id,
            escrow_uid=f"{deal_state.real_escrow_uid}-reuse",
        )
        # The claim pinned the resource, so a reservation coming back *is*
        # the match: the capacity boundary strips physical identity from
        # every reservation response.
        assert reserved_again.capacity_reservation_id, (
            "re-reserving the released resource returned no reservation, so "
            "the capacity did not become available again"
        )
        # Released per reservation, as the site releases one in production.
        # `admin_release_reservations` is fleet-wide and would clear other
        # scenarios' holds.
        deal_driver.release_reserved(reserved_again)
        provisioning_client.resume_lease_watchdog()
