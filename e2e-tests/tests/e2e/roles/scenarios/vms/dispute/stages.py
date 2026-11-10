"""What the VM dispute scenarios share: their deal, its reads, and its ending.

Each scenario is a module of its own on its own once-only deal in
``arkhai.payments.v1``, committed by ``DisputeStage01_HostedDealCommitted`` over
the scenario's own executor, pool and resource. Every stage advances one side
effect through the services' typed clients, the doubles' control client, or the
mediation kit's dispute adapter (``file_as_buyer``), and the storefront's
servicing advances only by ``servicing_step``. No stage steps the storefront's
servicing while a ruling waits at its gate: the storefront's watch records an
end from a delivery-end effect whatever its applied state, so a step then would
end delivery on a ruling not yet applied.

A deal still delivering when its scenario's own stages end is ended by the lease
expiry the shared stages of ``compute_deal_stages.py`` run, from
``Stage09c2_ArmTeardownGate`` to ``Stage11b_TeardownCompletion``, an ending for
which the storefront files no dispute case. ``DisputeStageZ_NoFurtherCase`` then steps the
storefront's servicing once, which dispatches any filing the storefront
journaled for that end, and holds the deal to the scenario's own cases and to no
filing of the storefront's, so neither this module nor a later one's servicing
meets a filing the ending left behind.

These stages are not named ``Test*``: a module collects each by subclassing it
with an empty body, in its run order.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lane_double_controls import CaseView

from tests.e2e.roles.helpers.compute_deal import advance_storefront
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.lane_doubles import LaneDoubleRules
from tests.e2e.roles.scenarios.vms.payment_deal import (
    HostedDeal, commit_hosted_deal, lifecycle_read, payment_snapshot,
)

__all__ = [
    "DisputeStage01_HostedDealCommitted", "DisputeStageZ_NoFurtherCase", "DisputeState",
    "cases", "lifecycle_read", "scenario_driver", "servicing_step", "snapshot_events",
    "snapshot_part",
]

log = logging.getLogger(__name__)


@dataclass
class DisputeState:
    """What a dispute scenario's stages hand each other."""

    #: The directory of the buyer's evidence store, the harness's filings'
    #: operation keys among it.
    buyer_store: Path
    deal: HostedDeal | None = None
    #: Every case the scenario itself filed, in filing order.
    case_refs: list[str] = field(default_factory=list)
    #: The amounts, in minor units, the scenario's ruling reverses, in effect order.
    amounts: list[int] = field(default_factory=list)


def scenario_driver(deal_driver: Any, *, host: str, pool_id: str, resource_id: str) -> Any:
    """The VM deal driver over the scenario's own executor, pool and resource."""
    return dataclasses.replace(
        deal_driver, reserved_resource_id=resource_id, host=host, pool_id=pool_id,
    )


def servicing_step(storefront_admin_client: Any) -> dict:
    """One cycle of the storefront's held ``settlement-servicing`` loop: respondent
    discovery, the authority watch, then the physical end of a recorded end."""
    return advance_storefront(storefront_admin_client, "settlement-servicing")


def cases(rules: LaneDoubleRules, transaction: str) -> list[CaseView]:
    """The mediation double's cases on the transaction, in filing order."""
    return rules.controls["mediation"].cases(transaction).cases


def _snapshot(payments_config: Any, transaction: str) -> dict[str, Any]:
    snapshot: dict[str, Any] = payment_snapshot(payments_config, transaction).model_dump(
        mode="json", by_alias=True, exclude_unset=True)
    return snapshot


def snapshot_part(payments_config: Any, transaction: str, index: int = 0) -> dict[str, Any]:
    """The transaction's part as its signed snapshot states it, read by the buyer."""
    part: dict[str, Any] = _snapshot(payments_config, transaction)["parts"][index]
    return part


def snapshot_events(payments_config: Any, transaction: str, kind: str) -> list[dict[str, Any]]:
    """The transaction's payment events of ``kind``, in sequence."""
    return [event for event in _snapshot(payments_config, transaction)["events"]
            if event["event"]["kind"] == kind]


class DisputeStage01_HostedDealCommitted:
    def test_01_the_hosted_deal_is_committed_and_delivering(
        self, payments_config, deal_driver, deal_state, dispute: DisputeState,
        storefront_seller_client, storefront_client, storefront_admin_client, registry_client,
        provisioning_client, provisioning_test_client, site_capacity,
    ):
        """The scenario's own once-only deal, committed and delivering, its one
        part held whole at the payments double (``commit_hosted_deal``)."""
        require_state(deal_state, "_provisioning_storefront_ok")
        dispute.deal = commit_hosted_deal(
            payments_config, deal_driver, deal_state,
            resource_id=deal_driver.reserved_resource_id,
            storefront_seller_client=storefront_seller_client,
            storefront_client=storefront_client, storefront_admin_client=storefront_admin_client,
            registry_client=registry_client, provisioning_client=provisioning_client,
            provisioning_test_client=provisioning_test_client, site_capacity=site_capacity,
        )
        log.info("[01] Deal %s committed under transaction %s, delivering",
                 dispute.deal.negotiation_id, dispute.deal.transaction)


class DisputeStageZ_NoFurtherCase:
    def test_z_the_ending_filed_no_case(
        self, storefront_admin_client, lane_double_rules: LaneDoubleRules, deal_state,
        dispute: DisputeState,
    ):
        """The deal's ending filed nothing: after a servicing step, which
        dispatches any filing the storefront journaled, the mediation double
        lists only the cases the scenario filed on its transaction."""
        require_state(deal_state, "_teardown_job_completed")
        require_state(dispute, "deal")
        servicing_step(storefront_admin_client)
        listed = [case.case_ref for case in cases(lane_double_rules, dispute.deal.transaction)]
        assert listed == dispute.case_refs, (
            f"the deal's ending filed a case: the double lists {listed}, the scenario "
            f"filed {dispute.case_refs}"
        )
        # Where the buyer filed first, the adapter refuses a second delivery-end
        # filing without sending it, so the storefront's own filings are read too.
        view = lifecycle_read(dispute.deal.negotiation_id)
        assert view.filings == [], f"the deal's ending journaled a filing: {view.filings}"
        log.info("[z] Transaction %s has only the scenario's cases: %s",
                 dispute.deal.transaction, listed)
