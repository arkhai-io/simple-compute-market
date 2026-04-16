"""Progressive stage output fixtures, shared across all stage directories.

A deal cascades automatically in the current implementation: once the
buyer creates a matching order, discovery → negotiation → settlement →
provision all run without pause. These fixtures are progressive
observations of that cascade, not separate triggers.

Each fixture depends on the previous one and waits for its specific
milestone. Session-scoped so one deal covers the whole test run.

Fixture dependency chain:
    seller_publishes (discovery-only, seller action)
        ↓
    initiated_deal (buyer creates matching order, starts cascade)
        ↓
    negotiation_complete
        ↓
    settlement_complete
        ↓
    provision_complete

After the rewrite these will become independent triggers instead of
progressive observations, but the fixture contract is unchanged.
"""

from __future__ import annotations

import logging

import pytest

from tests.helpers.cli_client import cli_create_order
from tests.helpers.polling import poll_registry_orders
from tests.roles.helpers.deal import Deal

log = logging.getLogger(__name__)


# The canonical compute + payment pair. Must match resources pre-imported
# on the seller node (ww1-machine.csv). All stage tests share these specs
# unless they explicitly override for variant scenarios.
COMPUTE = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}
PAYMENT = {"token": "MOCK", "amount": 100}


# ---------------------------------------------------------------------------
# Stage 1 output: seller has published an order
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def seller_publishes(seller_node: dict) -> dict:
    """The seller agent publishes an offer. Registry indexes it."""
    resp = cli_create_order(
        agent_url=seller_node["agent_url"],
        env_file=seller_node["agent_env_file"],
        offer=COMPUTE,
        demand=PAYMENT,
    )
    assert resp["status"] == "created", f"Seller publish failed: {resp}"
    order_id = resp["order_id"]
    log.info("Seller published order %s", order_id)

    items = poll_registry_orders(
        seller_node["market"]["url"], status="open", min_count=1,
        timeout_s=30, interval_s=2,
    )
    matching = [i for i in items if i["order_id"] == order_id]
    assert matching, f"Seller order {order_id} not indexed"
    return matching[0]


@pytest.fixture(scope="session")
def discovery_output(seller_publishes: dict) -> dict:
    """Output of discovery: at least one matchable seller order in the registry."""
    return {
        "seller_order": seller_publishes,
        "compute_spec": COMPUTE,
        "payment_spec": PAYMENT,
    }


# ---------------------------------------------------------------------------
# Stage 2 trigger + output: buyer matches, cascade begins, negotiation completes
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def initiated_deal(
    seller_node: dict, buyer_node: dict, discovery_output: dict,
) -> Deal:
    """The buyer creates a matching order, initiating the full cascade.

    Returns a Deal holding both order IDs and both agent-node contexts.
    Individual stage fixtures call .wait_for_X() on this to observe each
    milestone of the cascade.
    """
    resp = cli_create_order(
        agent_url=buyer_node["agent_url"],
        env_file=buyer_node["agent_env_file"],
        offer=PAYMENT,
        demand=COMPUTE,
    )
    assert resp["status"] in ("created", "queued"), f"Buyer publish failed: {resp}"
    buyer_order_id = resp["order_id"]
    log.info("Buyer initiated deal: buyer_order=%s", buyer_order_id)

    return Deal(
        buyer_node=buyer_node,
        seller_node=seller_node,
        buyer_order_id=buyer_order_id,
        seller_order_id=discovery_output["seller_order"]["order_id"],
        registry_url=seller_node["market"]["url"],
    )


@pytest.fixture(scope="session")
def negotiation_output(initiated_deal: Deal) -> dict:
    """Output of negotiation: both sides' threads reached terminal_state=success."""
    snapshot = initiated_deal.wait_for_negotiation_complete()
    return {"deal": initiated_deal, **snapshot}


# ---------------------------------------------------------------------------
# Stage 3 output: escrow created, both orders accepted
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def settlement_output(initiated_deal: Deal, negotiation_output: dict) -> dict:
    """Output of settlement: buyer's escrow exists, both orders status=accepted."""
    snapshot = initiated_deal.wait_for_settlement()
    return {"deal": initiated_deal, **snapshot}


# ---------------------------------------------------------------------------
# Stage 4 output: machine provisioned, buyer has credentials
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def provision_output(initiated_deal: Deal, settlement_output: dict) -> dict:
    """Output of provision: buyer has taker_attestation + tenant credentials."""
    snapshot = initiated_deal.wait_for_provision()
    return {"deal": initiated_deal, **snapshot}
