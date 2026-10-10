"""Bare metal's part of the canonical compute deal: what the shared stages ask of it.

The shared stages in ``helpers/compute_deal_stages.py`` hold the deal's control
flow and every assertion that is not bare metal's. This driver holds bare
metal's: a backed pool, the host record, and one whole machine declared at the
site; the ``bare_metal.v2`` provision terms; the access playbook's grant and
reclaim mock rules, on the bare-metal mock's own routes; the settlement
preview's expectations; what settle answers and where the dispatched
fulfillment is read; the delivery a ready lease serves, through the buyer's own
fulfillment transport; the lease view over the lane's site; and the claim that
re-reserves the released machine and its release at the site.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Any

from arkhai_bare_metal import NODE_GRANT_ACCESS_ACTION, NODE_RECLAIM_ACCESS_ACTION
from compute_provisioning_contracts import ConnectionSubmission, HostCreate
from market_resource_pools_contracts import PoolCreate

from tests.e2e.roles.helpers.compute_deal import DealLease, SiteCapacity
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS

BARE_METAL = "bare_metal"
REGION = "us-central"
GPU_MODEL = "L40S"
#: One whole machine: the unit a bare-metal claim reserves, and the hardware it
#: contains, which its listing publishes.
WHOLE_HOST_CAPACITY = {"units": 1, "gpu_count": 4, "ram_gb": 512}
#: The resource kind a bare-metal declaration is, and fulfillment schedules.
BARE_METAL_RESOURCE_KIND = "compute.bare-metal"
#: Where the mock grant tells the buyer to connect: a documentation address
#: (TEST-NET-2), never dialled, since the mock profile runs no playbook.
MACHINE_ADDRESS = "198.51.100.7"


class BareMetalDealLease(DealLease):
    """The shared lease view, reading a whole machine's hold by its units.

    A whole-machine claim reserves the declaration's one ``units`` and none of
    the hardware it describes one by one, so whether the machine is held is
    read from ``units``, not from the dimension the site mirrors.
    """

    def resource_consumed(self, storefront_admin_client: Any, resource_id: str) -> bool:
        for row in self._site.snapshot():
            if str(row.get("resource_id")) == resource_id:
                capacity = int((row.get("capacity") or {}).get("units") or 0)
                available = int((row.get("available") or {}).get("units") or 0)
                return available < capacity
        raise AssertionError(f"Resource {resource_id!r} not found in site capacity snapshot")


@dataclass
class BareMetalComputeDealDriver:
    """Bare metal's ``ComputeDealDriver``, over the bare-metal lane's clients."""

    site_operator: Any
    site_capacity_admin: Any
    provisioning_client: Any
    provisioning_test_client: Any
    storefront_admin_client: Any
    fulfillment: Any
    site_capacity: SiteCapacity
    buyer_config: dict[str, str]
    site_id: str
    run: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def __post_init__(self) -> None:
        self.pool_id = f"bm-deal-{self.run}"
        self.reserved_resource_id = f"bm-deal-host-{self.run}"
        self.host_id = f"machine-{self.reserved_resource_id}"
        self.physical_host_id = f"physical-{self.reserved_resource_id}"
        self.create_rule_id = f"e2e-bm-grant-pause-{self.run}"
        self.teardown_rule_id = f"e2e-bm-reclaim-pause-{self.run}"

    # -- supply -------------------------------------------------------------

    def seed_supply(self) -> None:
        """A backed pool advertising bare metal, its host, and one whole machine.

        The host record is what dispatch renders the job's inventory from; the
        declaration, a bare-metal resource, is what admission, publication,
        scheduling, and the seller's inventory guard read. The machine's
        publication view names its host and physical machine, as the storefront
        checks a scheduled resource against the accepted terms.
        """
        self.site_operator.create_pool(
            PoolCreate(
                id=self.pool_id,
                label=self.pool_id,
                provider="bare_metal.ansible",
                policy_tags={
                    "deliverable_modes": [BARE_METAL],
                    "advertisable_modes": [BARE_METAL],
                    "capacity_backing": "backed",
                    "region": REGION,
                },
                provider_config={},
            )
        )
        self.provisioning_client.register_host(
            HostCreate(
                host_id=self.host_id,
                connection=ConnectionSubmission(
                    kind="ssh",
                    public={
                        "ssh_host": MACHINE_ADDRESS,
                        "ssh_user": "stub",
                        "key_path": "/dev/null",
                    },
                ),
                gpu_count=WHOLE_HOST_CAPACITY["gpu_count"],
                gpu_model=GPU_MODEL,
                enabled=True,
                pool_id=self.pool_id,
            )
        )
        asyncio.run(
            self.site_capacity_admin.register_resource(
                self.reserved_resource_id,
                pool_id=self.pool_id,
                host_id=self.host_id,
                # Settlement schedules the deal's machine among resources of
                # this kind only.
                resource_type=BARE_METAL_RESOURCE_KIND,
                capacity=dict(WHOLE_HOST_CAPACITY),
                attributes={
                    "gpu_model": GPU_MODEL,
                    "physical_host_id": self.physical_host_id,
                    "allocation_mode": "exclusive",
                    "bare_metal_publication": {
                        "enabled": True,
                        "access_methods": ["ssh"],
                        "host_id": self.host_id,
                        "physical_host_id": self.physical_host_id,
                    },
                },
            )
        )
        # Bare-metal publication reads each site's projection on every pass, so
        # there is no projection to refresh; the site must answer it.
        health = self.storefront_admin_client.get_health()
        state = health.site_projections[self.site_id]["resource_pool"]["state"]
        assert state == "loaded", health.site_projections

    # -- negotiation --------------------------------------------------------

    def provision_terms(self) -> dict[str, Any]:
        return {
            "kind": "bare_metal.v2",
            "version": 1,
            "payload": {
                "duration_seconds": DURATION_HOURS * 3600,
                "access_method": "ssh",
                "ssh_public_key": self.buyer_config["ssh_public_key"],
            },
        }

    # -- mock rules ---------------------------------------------------------

    def _arm(self, rule_id: str, action: str) -> None:
        try:
            self.provisioning_test_client.delete_bare_metal_mock_rule(rule_id)
        except Exception:
            pass
        # Matched on this deal's host, so no other scenario's job is held.
        self.provisioning_test_client.add_bare_metal_mock_rule(
            rule_id=rule_id,
            match={"action": action, "host_id": self.host_id},
            pause_before_result=True,
        )

    def arm_create_gate(self) -> None:
        self._arm(self.create_rule_id, NODE_GRANT_ACCESS_ACTION)

    def release_create_gate(self) -> None:
        self.provisioning_test_client.resume_bare_metal_rule(self.create_rule_id)

    def evaluate_create_job(self, host_id: str) -> dict[str, Any]:
        return self.provisioning_test_client.evaluate_bare_metal_job(
            host_id,
            action=NODE_GRANT_ACCESS_ACTION,
            physical_host_id=self.physical_host_id,
        )

    def arm_teardown_gate(self) -> None:
        self._arm(self.teardown_rule_id, NODE_RECLAIM_ACCESS_ACTION)

    def release_teardown_gate(self) -> None:
        self.provisioning_test_client.resume_bare_metal_rule(self.teardown_rule_id)

    def disarm_gates(self) -> None:
        """Remove both rules, so a later deal's jobs run ungated."""
        for rule_id in (self.create_rule_id, self.teardown_rule_id):
            try:
                self.provisioning_test_client.delete_bare_metal_mock_rule(rule_id)
            except Exception:
                pass

    # -- settlement and delivery -------------------------------------------

    def evaluate_settle_arguments(self) -> dict[str, Any]:
        return {"duration_seconds": DURATION_HOURS * 3600}

    def check_evaluate_settle(self, result: dict[str, Any]) -> str:
        # The preview names the listing's machine and the claim settlement
        # would reserve for it.
        assert result.get("physical_resource_id") == self.reserved_resource_id, result
        claim = result.get("required_attributes") or {}
        assert claim.get("resource_id") == self.reserved_resource_id, result
        assert result.get("site_id") == self.site_id, result
        return result.get("host_id")

    def settle_dispatched(self, settle_response: Any, deal_state: Any) -> str:
        """Bare metal's settle verifies; its first servicing pass begins delivery.

        So the fulfillment exists when settle returns, and the buyer reads it
        through the fulfillments route rather than settle status.
        """
        assert settle_response.status == "settlement_verified", (
            f"Expected status=settlement_verified, got: {settle_response.status!r}. "
            f"Full response: {settle_response}"
        )
        status = self.fulfillment.status(deal_state.negotiation_id)
        assert status.get("fulfillment_id"), (
            f"the settlement's servicing pass began no fulfillment: {status}"
        )
        return str(status["fulfillment_id"])

    def assert_delivery(self, deal_state: Any) -> None:
        """An active lease, a result naming no endpoint, and live access."""
        status = self.fulfillment.status(deal_state.negotiation_id)
        assert status.get("state") == "active", status
        delivered = self.fulfillment.result(deal_state.negotiation_id)
        assert delivered["receipt"]["status"] == "ready", delivered
        result = delivered["result"]
        # Where to connect is served live by the access route, never stored.
        assert "host" not in result and "port" not in result, result
        access = self.fulfillment.access(deal_state.negotiation_id)
        assert access.get("host") == MACHINE_ADDRESS, access
        assert int(access.get("port") or 0) > 0, access
        assert access.get("username") == result.get("ssh_user"), (access, result)

    # -- lease and release --------------------------------------------------

    def opening_selection(self, alkahest_option: dict, expiration_unix: int) -> None:
        # The bare-metal storefront projects the Alkahest selection from the
        # escrow carrier and refuses a selection stated beside it.
        return None

    def lease_view(self, deal_state: Any) -> BareMetalDealLease:
        # Bare metal's Alkahest fulfillment commits its hold under the escrow.
        return BareMetalDealLease(
            self.provisioning_client,
            self.site_capacity,
            escrow_uid=deal_state.real_escrow_uid,
        )

    def reserve_released_capacity(
        self, storefront_admin_client: Any, *, listing_id: str, escrow_uid: str
    ) -> Any:
        # A whole machine is reserved as its listing describes it, so the only
        # attribute stated is one the listing's claim carries.
        return storefront_admin_client.admin_reserve_capacity(
            required_attributes={"gpu_model": GPU_MODEL},
            listing_id=listing_id,
            escrow_uid=escrow_uid,
        )

    def release_reserved(self, reservation: Any) -> None:
        # An administrative reservation exists only at the site, which releases
        # it; the storefront records releases of its deals' leases alone.
        released = self.site_capacity.release(reservation.capacity_reservation_id)
        assert released is not None, (
            f"the site did not release {reservation.capacity_reservation_id!r}"
        )
