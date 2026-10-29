"""VM's part of the canonical compute deal: what the shared stages ask of it.

The shared stages in ``helpers/compute_deal_stages.py`` hold the deal's control
flow and every assertion that is not VM's. This driver holds VM's: the executor
host and capacity it declares, the ``compute.v1`` provision terms, the VM
playbook's create and removal mock rules and their release, the settlement
preview's arguments and expectations, what settle answers and where the
dispatched fulfillment is read, the tenant credentials and escrow claim a ready
VM delivers, the lease view over VM's site, and the claim that re-reserves the
released resource and its release.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compute_provisioning_contracts import MockJobEvaluation, MockRuleCreate

from tests.e2e.roles.helpers.compute_deal import (
    DealLease,
    SiteCapacity,
    delete_mock_rules_if_present,
    wait_for_stage_event,
)
from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.scenarios.vms.host_registry import (
    E2E_DEAL_HOST,
    E2E_DEAL_POOL_ID,
    provision_e2e_executor,
    refresh_storefront_projections,
)

#: The storefront resource and site capacity declaration this deal sells.
E2E_RESOURCE_ID = "compute-e2e-deal-001"
#: Mock rule that holds the VM create job before it reports.
PROV_RULE_ID = "e2e-create-pause"
#: Mock rule that holds the VM removal (provider teardown).
REMOVE_RULE_ID = "e2e-remove-pause"
#: A create rule another scenario arms on the same stack; deleted first so it
#: cannot match this deal's create before this deal's own rule.
_STALE_CREATE_RULES = ("e2e-buy-create",)


def vm_job_evaluation(
    host: str, *, vm_action: str, vm_target: str = "eval-target"
) -> dict[str, Any]:
    """A VM job as VM's evaluate-job route reads it: a job's parameters are its
    domain's, so ``vm_rules.evaluate_job`` takes them as VM describes them."""
    return {"host": host, "vm_target": vm_target, "vm_action": vm_action}


@dataclass
class VmComputeDealDriver:
    """VM's ``ComputeDealDriver``, over the VM lane's clients."""

    provisioning_client: Any
    provisioning_test_client: Any
    storefront_client: Any
    storefront_admin_client: Any
    storefront_service_client: Any
    site_capacity_admin_client: Any
    site_capacity: SiteCapacity
    buyer_config: dict[str, str]
    #: The site VM's capacity-released callback names.
    site_id: str
    create_rule_id: str = PROV_RULE_ID
    teardown_rule_id: str = REMOVE_RULE_ID
    reserved_resource_id: str = E2E_RESOURCE_ID

    def seed_supply(self) -> None:
        """Register this scenario's executor and declare its sellable capacity.

        The declaration's categorical attributes mirror the seeded listing,
        because the seller's inventory guard compares `region` and `gpu_model`
        by equality.
        """
        host = provision_e2e_executor(
            self.provisioning_client,
            self.site_capacity_admin_client,
            host=E2E_DEAL_HOST,
            pool_id=E2E_DEAL_POOL_ID,
            resource_id=E2E_RESOURCE_ID,
            sellable_units=1,
            attributes={
                "gpu_model": "RTX 5080",
                "region": "California, US",
                "sla": "90.0",
            },
        )
        assert host.host_id == E2E_DEAL_HOST
        refresh_storefront_projections(self.storefront_admin_client)

    def provision_terms(self) -> dict[str, Any]:
        return {
            "kind": "compute.v1",
            "version": 1,
            "payload": {
                "duration_seconds": DURATION_HOURS * 3600,
                # The key is a negotiated term, not a settle-time input:
                # settle reads it from the accepted terms and refuses to
                # substitute the caller's, so an empty value here cannot
                # be supplied later.
                "ssh_public_key": self.buyer_config["ssh_public_key"],
            },
        }

    def arm_create_gate(self) -> None:
        rules = self.provisioning_test_client.vm_rules
        delete_mock_rules_if_present(rules, *_STALE_CREATE_RULES, PROV_RULE_ID)
        rules.add_rule(
            MockRuleCreate(
                rule_id=PROV_RULE_ID,
                match={"vm_action": "create"},
                pause_before_result=True,
            )
        )

    def release_create_gate(self) -> None:
        self.provisioning_test_client.vm_rules.resume_rule(PROV_RULE_ID)

    def evaluate_create_job(self, host_id: str) -> MockJobEvaluation:
        return self.provisioning_test_client.vm_rules.evaluate_job(
            vm_job_evaluation(host_id, vm_action="create")
        )

    def evaluate_settle_arguments(self) -> dict[str, Any]:
        return {
            "ssh_public_key": self.buyer_config["ssh_public_key"],
            "duration_seconds": DURATION_HOURS * 3600,
        }

    def check_evaluate_settle(self, result: dict[str, Any]) -> str:
        # The preview names no guest: provisioning names it from the
        # reservation settle commits.
        assert "vm_target" not in result, result
        return result.get("host_id")

    def settle_dispatched(self, settle_response: Any, deal_state: Any) -> str:
        assert settle_response.status == "provisioning", (
            f"Expected status=provisioning, got: {settle_response.status!r}. "
            f"Full response: {settle_response}"
        )
        # job_submitted fires after the DB row is updated; resource_reserved
        # would race because it fires before the job_id exists.
        wait_for_stage_event(
            self.storefront_admin_client,
            "provision", "job_submitted",
            listing_id=deal_state.seller_listing_id,
            timeout=15.0,
        )
        status = self.storefront_client.get_settle_status(deal_state.real_escrow_uid)
        # provisioning_job_id is always None for a fulfillment on the durable
        # path (no raw executor job id crosses the buyer-facing boundary);
        # fulfillment_id is that path's durable identity. See
        # core_storefront.models.settle_models.SettleStatusResponse.
        assert status.fulfillment_id, (
            f"fulfillment_id absent from settle status after job_submitted event: "
            f"{status}"
        )
        return status.fulfillment_id

    def assert_delivery(self, deal_state: Any) -> None:
        """VM delivers through settle status, and records the claim on the escrow."""
        status = self.storefront_client.get_settle_status(deal_state.real_escrow_uid)
        assert status.status == "ready", (
            f"Settlement not 'ready' after provision fulfilled event. "
            f"Got: {status.status!r}"
        )
        assert status.tenant_credentials, (
            f"tenant_credentials missing from settlement status: {status}"
        )
        # The per-negotiation endpoint is the canonical home for per-deal
        # attestation data. After settlement the primary escrow must surface
        # status=ready + a fulfillment_uid.
        detail = self.storefront_admin_client.get_negotiation(
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

    def opening_selection(self, alkahest_option: dict, expiration_unix: int) -> dict:
        # The VM seller accepts nothing it would have to infer from an escrow's
        # shape, so a fresh negotiation names its settlement option explicitly.
        return {
            "mechanism": "alkahest.v1",
            "option_id": alkahest_option["option_id"],
            "expiration_unix": expiration_unix,
        }

    def lease_view(self, deal_state: Any) -> DealLease:
        # VM holds and commits capacity under the deal's negotiation, whatever
        # its settlement mechanism.
        return DealLease(
            self.provisioning_client,
            self.site_capacity,
            negotiation_id=deal_state.negotiation_id,
        )

    def arm_teardown_gate(self) -> None:
        rules = self.provisioning_test_client.vm_rules
        delete_mock_rules_if_present(rules, REMOVE_RULE_ID)
        rules.add_rule(
            MockRuleCreate(
                rule_id=REMOVE_RULE_ID,
                match={"vm_action": "vm_remove"},
                pause_before_result=True,
            )
        )

    def release_teardown_gate(self) -> None:
        self.provisioning_test_client.vm_rules.resume_rule(REMOVE_RULE_ID)

    def reserve_released_capacity(
        self, storefront_admin_client: Any, *, listing_id: str, escrow_uid: str
    ) -> Any:
        reserved = storefront_admin_client.admin_reserve_capacity(
            required_attributes={"resource_id": E2E_RESOURCE_ID, "gpu_count": 1},
            listing_id=listing_id,
            escrow_uid=escrow_uid,
        )
        # Whether a reservation came back at all is the shared stage's
        # assertion; what it holds is VM's.
        if reserved.capacity_reservation_id:
            assert reserved.gpu_count == 1, reserved
        return reserved

    def release_reserved(self, reservation: Any) -> None:
        # Through the peer callback, which is how provisioning releases a VM
        # reservation in production.
        self.storefront_service_client.notify_capacity_released(
            reservation.capacity_reservation_id,
            site_id=self.site_id,
        )
