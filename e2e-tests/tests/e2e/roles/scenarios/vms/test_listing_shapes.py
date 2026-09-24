"""Listing shapes e2e scenario: a stated shape is published and discoverable.

A pool's `listing_shapes` hint states the shape its listings are sold in. This
scenario proves the cross-service path from that declaration to discovery:

1. A pool states a 1-GPU, 8-vCPU, 32 GiB, 100 GiB shape; its one declaration has
   2 GPUs, 16 vCPUs, 64 GiB, and 200 GiB.
2. The provisioning service projects the hint verbatim, and one publication
   cycle publishes exactly that shape, with every declared quantity, and no
   default GPU-only shapes.
3. A buyer discovers it with a typed `ram_gb>=32` resource query and finds
   nothing at `ram_gb>=33`: the registry's range filters match the published
   quantities, which a GPU-only listing never carries.
4. `market buy`, discovering through the same memory query, negotiates, escrows,
   settles, and provisions it to ready.
5. The site's reservation holds every declared quantity, and the provisioning
   job sizes the VM from them rather than from the pool's defaults.
6. A storefront override, written through the typed administrator client,
   replaces the pool's stated shape: the storefront checks the pool against the
   site's live projection and reports the shape feasible, one cycle closes the
   hint's listing and publishes the override's, and deleting the override
   restores the hint's shape.

The listing's terms and region come from the pool's own `pricing` and `region`
hints, so the scenario does not depend on the storefront's configured defaults.
The region is stated twice on purpose: a listing advertises its pool's region
hint, and a reservation matches that region against the declaration's own
`region` attribute, so a pool whose members did not declare it would publish
nothing. How many of the shape
fit, and whether a reservation will be admitted, stay the site's: publication
judges only that the declaration can serve the shape.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import pytest

from tests.e2e.roles.scenarios.vms.conftest import (
    advance_storefront,
    delete_mock_rules_if_present,
    pause_storefront,
    require_state,
)
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_LISTING_SHAPES_HOST,
    E2E_LISTING_SHAPES_POOL_ID,
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)

pytestmark = pytest.mark.e2e_listing_shapes

#: A model no other scenario declares, so discovery counts only this listing.
GPU_MODEL = "L40S"
REGION = "California, US"
RESOURCE_ID = "compute-e2e-listing-shapes-001"
DECLARED = {"gpu_count": 2, "vcpu_count": 16, "ram_gb": 64, "disk_gb": 200}
SHAPE = {
    "gpu": {"count": 1, "model": GPU_MODEL},
    "cpu": {"count": 8},
    "memory": {"gib": 32},
    "storage": {"gib": 100},
}
PUBLISHED = {"gpu_count": 1, "vcpu_count": 8, "ram_gb": 32, "disk_gb": 100}
#: The storefront's own shape for the pool: the hint's, with half the memory.
OVERRIDE_SHAPE = {**SHAPE, "memory": {"gib": 16}}

#: MockERC20 at its deterministic development address, pre-funded to the buyer
#: in the baked development chain; never a public-network token.
TOKEN = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
#: The pool's own terms: 10 whole tokens an hour, which the Alkahest composition
#: publishes in base units, as the one-shot buy scenario's listing advertises.
PRICING = {
    "gpu": {
        GPU_MODEL: {
            "settlements": [{
                "mechanism": "alkahest.v1",
                "asset": TOKEN,
                "rate": "10",
                "per": "hour",
                "mechanism_input": {
                    "chain": "anvil",
                    "escrow_kind": "erc20_escrow_obligation_default",
                },
            }],
        },
    },
}
#: Whole tokens, as the CLI takes them: an opening bid under the asking rate is
#: countered, and the ceiling accepts that first counter.
BUYER_INITIAL_PRICE = 7
BUYER_MAX_PRICE = 12
DURATION_HOURS = 1
CREATE_RULE_ID = "e2e-listing-shapes-create"


@dataclass
class ShapeState:
    paused: bool = False
    declared: bool = False
    listing_id: str | None = None
    provisioning_armed: bool = False
    escrow_uid: str | None = None
    reservation_ids: tuple[str, ...] = ()
    site_id: str | None = None
    overridden: bool = False


@pytest.fixture(scope="module")
def shape_state() -> ShapeState:
    return ShapeState()


class TestStage00_Setup:
    def test_00a_pause_storefront_loops(self, storefront_admin_client, shape_state):
        """Hold the timer loops so this scenario's publication cycle is explicit."""
        shape_state.paused = pause_storefront(storefront_admin_client)
        assert shape_state.paused

    def test_00b_pool_states_a_shape_and_its_declaration_every_dimension(
        self, provisioning_client, site_capacity_admin_client, storefront_admin_client,
        shape_state,
    ):
        require_state(shape_state, "paused")
        provision_e2e_executor(
            provisioning_client,
            site_capacity_admin_client,
            host=E2E_LISTING_SHAPES_HOST,
            pool_id=E2E_LISTING_SHAPES_POOL_ID,
            resource_id=RESOURCE_ID,
            sellable_units=DECLARED["gpu_count"],
            capacity=DECLARED,
            # Claims match region and model against the declaration itself.
            attributes={"gpu_model": GPU_MODEL, "region": REGION},
            listing_mode="fungible",
            listing_shapes={"vm": [SHAPE]},
            pricing=PRICING,
            # The region the listing advertises; see the module docstring.
            region=REGION,
        )
        pool_row = provisioning_client.get_pool(E2E_LISTING_SHAPES_POOL_ID)
        assert pool_row.policy_tags["listing_shapes"] == {"vm": [SHAPE]}
        assert pool_row.policy_tags["region"] == REGION
        sites = refresh_storefront_projections(storefront_admin_client)
        # The storefront configures one site; the override stage addresses it.
        (shape_state.site_id,) = sites
        shape_state.declared = True


class TestStage01_Publication:
    def test_01a_one_cycle_publishes_exactly_the_stated_shape(
        self, storefront_admin_client, shape_state
    ):
        require_state(shape_state, "declared")
        cycle = advance_storefront(storefront_admin_client, "publication")
        # What the cycle did with this pool's candidates, so a failure says why.
        this_pool = [
            action for action in cycle.get("actions") or []
            if (action.get("source") or {}).get("pool_id") == E2E_LISTING_SHAPES_POOL_ID
        ]

        page = storefront_admin_client.list_listings(status="open", limit=200)
        shaped = []
        for listing in page.listings:
            resource = listing.listing_resource
            if isinstance(resource, str):
                resource = json.loads(resource)
            if (resource or {}).get("pool_id") == E2E_LISTING_SHAPES_POOL_ID:
                shaped.append((listing.listing_id, resource))

        # The stated list replaces the default shapes as a whole.
        assert len(shaped) == 1, (
            f"expected one listing for the stated shape, got {shaped}; "
            f"the cycle's actions for this pool: {this_pool}"
        )
        listing_id, resource = shaped[0]
        assert {key: resource.get(key) for key in PUBLISHED} == PUBLISHED
        assert (resource["gpu_model"], resource["region"]) == (GPU_MODEL, REGION)
        shape_state.listing_id = listing_id
        log.info("[01a] published %s with shape %s", listing_id, PUBLISHED)


def _survivors(buyer_cli, query: str) -> int:
    run = buyer_cli.run(["listing", "list", "--resource", query, "--explain"], timeout=60.0)
    assert run.returncode == 0, (
        f"`market listing list` exited {run.returncode}\n"
        f"stdout (tail): {run.stdout()[-2000:]}\nstderr (tail): {run.stderr()[-2000:]}"
    )
    lines = run.stdout().splitlines()
    payload = json.loads(lines[lines.index("Explanation JSON:") + 1])
    return int(payload["resource"]["survivor_count"])


class TestStage02_Discovery:
    def test_02a_a_memory_query_finds_the_shape_at_its_value(self, buyer_cli, shape_state):
        require_state(shape_state, "listing_id")
        assert _survivors(buyer_cli, f'gpu_model="{GPU_MODEL}" ram_gb>=32') == 1

    def test_02b_a_memory_query_above_the_shape_finds_nothing(self, buyer_cli, shape_state):
        require_state(shape_state, "listing_id")
        assert _survivors(buyer_cli, f'gpu_model="{GPU_MODEL}" ram_gb>=33') == 0


class TestStage03_Provisioning:
    def test_03a_arm_a_create_rule_that_completes(self, provisioning_test_client, shape_state):
        """The one-shot buy blocks until ready, so the mock create job must finish
        on its own."""
        require_state(shape_state, "listing_id")
        delete_mock_rules_if_present(provisioning_test_client, CREATE_RULE_ID)
        provisioning_test_client.add_mock_rule(
            rule_id=CREATE_RULE_ID,
            match={"vm_action": "create", "host_id": E2E_LISTING_SHAPES_HOST},
            pause_before_result=False,
            result_stdout=(
                '{"vm_name": "e2e-shapes-vm", "tenant_user": "vmuser", '
                '"tenant_ssh_key_path": "/tmp/e2e-shapes.key", '
                '"frp": {"enabled": false}, '
                '"authentication": {"tenant": {"ssh_commands": '
                '{"external": "ssh vmuser@localhost", '
                '"internal": "ssh vmuser@10.0.0.1"}}}}'
            ),
            fail_with=None,
        )
        shape_state.provisioning_armed = True


class TestStage04_Buy:
    def test_04a_market_buy_discovers_by_memory_and_reaches_ready(
        self, buyer_cli, shape_state
    ):
        require_state(shape_state, "listing_id", "provisioning_armed")
        run = buyer_cli.run(
            [
                "buy",
                "--resource", f'gpu_model="{GPU_MODEL}" ram_gb>=32',
                "--settlement", f"mechanism=alkahest.v1 asset={TOKEN}",
                "--initial-price", str(BUYER_INITIAL_PRICE),
                "--max-price", str(BUYER_MAX_PRICE),
                "--duration-hours", str(DURATION_HOURS),
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
            f"stdout (tail): {run.stdout()[-2500:]}\nstderr (tail): {run.stderr()[-2500:]}"
        )
        terminal = next(
            (e for e in reversed(run.read_events()) if e.get("event") == "run_ended"), None
        )
        assert terminal is not None and terminal.get("status") == "ready", terminal
        assert terminal.get("listing_id") in (None, shape_state.listing_id)
        shape_state.escrow_uid = str(terminal["escrow_uid"])


class TestStage05_Commitment:
    def test_05a_the_reservation_holds_every_declared_quantity(
        self, provisioning_client, shape_state
    ):
        require_state(shape_state, "escrow_uid")
        reservations = provisioning_client.list_capacity_reservations(
            escrow_uid=shape_state.escrow_uid
        ).get("reservations") or []
        assert reservations, f"no reservation for escrow {shape_state.escrow_uid}"
        # The claim requests exactly the shape's quantities: no more, and no
        # dimension the shape omits.
        assert {r["dimensions"] == PUBLISHED for r in reservations} == {True}, reservations
        shape_state.reservation_ids = tuple(
            str(r["capacity_reservation_id"]) for r in reservations
        )

    def test_05b_the_vm_is_sized_from_the_shape_not_pool_defaults(
        self, provisioning_client, shape_state
    ):
        require_state(shape_state, "reservation_ids")
        # A provisioning job records the capacity reservation it fulfils in its
        # `escrow_uid` field, not the on-chain escrow.
        jobs = [
            job
            for reservation_id in shape_state.reservation_ids
            for job in provisioning_client.list_jobs(escrow_uid=reservation_id).jobs
        ]
        creates = [job for job in jobs if job.params.get("vm_action") == "create"]
        assert creates, (
            f"no create job for reservations {shape_state.reservation_ids}: {jobs}"
        )
        params = creates[0].params
        assert (
            params.get("vm_gpu_count"),
            params.get("vm_vcpus"),
            params.get("vm_ram"),
            params.get("vm_disk_size"),
        ) == (1, 8, 32 * 1024, "100G"), params


def _pool_listings(storefront_admin_client) -> dict[str, dict]:
    page = storefront_admin_client.list_listings(status="open", limit=200)
    out = {}
    for listing in page.listings:
        resource = listing.listing_resource
        if isinstance(resource, str):
            resource = json.loads(resource)
        if (resource or {}).get("pool_id") == E2E_LISTING_SHAPES_POOL_ID:
            out[listing.listing_id] = resource
    return out


class TestStage06_StorefrontOverride:
    def test_06a_an_override_is_checked_against_the_live_site(
        self, storefront_admin_client, shape_state
    ):
        require_state(shape_state, "listing_id")
        require_state(shape_state, "site_id")
        written = storefront_admin_client.admin_put_pool_override(
            {
                "site_id": shape_state.site_id,
                "pool_id": E2E_LISTING_SHAPES_POOL_ID,
                "listing_shapes": [OVERRIDE_SHAPE],
            }
        )
        assert [entry.feasible for entry in written.feasibility] == [True], written
        assert written.projection_digest, written
        shape_state.overridden = True

    def test_06b_one_cycle_replaces_the_hints_listing(self, storefront_admin_client, shape_state):
        require_state(shape_state, "overridden")
        advance_storefront(storefront_admin_client, "publication")

        listings = _pool_listings(storefront_admin_client)
        assert shape_state.listing_id not in listings, listings
        assert [resource["ram_gb"] for resource in listings.values()] == [16], listings
        status = storefront_admin_client.get_system_status()
        assert {
            (o["site_id"], o["pool_id"]): o["state"] for o in status.pool_overrides or []
        }.get((shape_state.site_id, E2E_LISTING_SHAPES_POOL_ID)) == "applied", (
            status.pool_overrides
        )

    def test_06c_deleting_the_override_restores_the_hints_shape(
        self, storefront_admin_client, shape_state
    ):
        require_state(shape_state, "overridden")
        deleted = storefront_admin_client.admin_delete_pool_override(
            shape_state.site_id, E2E_LISTING_SHAPES_POOL_ID
        )
        assert deleted.deleted
        advance_storefront(storefront_admin_client, "publication")

        listings = _pool_listings(storefront_admin_client)
        assert [resource["ram_gb"] for resource in listings.values()] == [
            PUBLISHED["ram_gb"]
        ], listings
