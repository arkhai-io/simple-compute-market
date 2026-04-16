"""Discovery stage fixtures.

Input (from layers): external_world + market_registry + (seller_node and/or buyer_node).
Output: at least one open seller order, published and discoverable by buyers
        through the registry.

The ``discovery_output`` fixture runs the real seller-publish behavior
(the seller agent publishes its own order, the registry indexes it).
Tests exercising the discovery stage itself may override this.
"""

from __future__ import annotations

import logging

import pytest

from tests.helpers.cli_client import cli_create_order
from tests.helpers.polling import poll_registry_orders

log = logging.getLogger(__name__)


# The canonical compute + payment pair used throughout role tests.
# Must match the resources pre-imported on the seller node.
COMPUTE = {"gpu_model": "RTX 5080", "quantity": 1, "sla": 90.0, "region": "California, US"}
PAYMENT = {"token": "MOCK", "amount": 100}


@pytest.fixture
def seller_publishes_order(seller_node: dict) -> dict:
    """The seller agent publishes an offer for its compute inventory.

    This is the real "seller does the thing" flow: the seller agent really
    creates an order, its registry client really publishes it, the registry
    really indexes it. Returns the indexed order dict from the registry.
    """
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
    assert matching, f"Seller order {order_id} not indexed in registry"
    return matching[0]


@pytest.fixture
def discovery_output(seller_publishes_order: dict) -> dict:
    """State after discovery has completed: at least one discoverable seller order.

    Downstream stages consume this. By default produces the happy path;
    variant fixtures can override for failure cases.
    """
    return {
        "seller_order": seller_publishes_order,
        "compute_spec": COMPUTE,
        "payment_spec": PAYMENT,
    }
