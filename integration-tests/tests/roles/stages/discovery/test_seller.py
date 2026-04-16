"""Discovery — seller perspective.

User-visible property: "when I publish an offer for my compute inventory,
prospective buyers can find it in the marketplace."

What the seller observes:
  - Their agent's CLI returns status=created with an order_id.
  - The registry indexes the order as status=open.
  - The order's attributes reflect what the seller offered.

The seller does NOT observe anything on the buyer side; other tests
check buyer-observable properties.
"""

from __future__ import annotations

import logging

import pytest

from tests.helpers.agent_client import query_registry_orders

log = logging.getLogger(__name__)


@pytest.mark.roles_discovery_seller
class TestSellerCanPublishOffer:
    """The seller can make their compute inventory visible to the market."""

    def test_published_order_is_visible_in_registry(
        self, seller_node: dict, seller_publishes: dict,
    ):
        """After publishing, the seller's order appears in /orders?status=open."""
        data = query_registry_orders(seller_node["market"]["url"], status="open")
        order_ids = {o["order_id"] for o in data.get("items", [])}
        assert seller_publishes["order_id"] in order_ids

    def test_published_order_is_attributed_to_seller(
        self, seller_node: dict, seller_publishes: dict,
    ):
        """The published order's maker URL points at the seller's agent port.

        The agent advertises itself via BASE_URL_OVERRIDE, which in the test
        deployment is the docker-internal hostname (e.g. 'http://sell_agent:8001/').
        The host-visible URL ('http://localhost:8001') differs in hostname but
        shares the port — both are valid in their respective network contexts.
        Verify the port matches as the stable cross-network identifier.
        """
        from urllib.parse import urlparse
        maker_url = seller_publishes["order_maker"]
        node_url = seller_node["agent_url"]
        assert urlparse(maker_url).port == urlparse(node_url).port, (
            f"order_maker port does not match seller node port: "
            f"maker={maker_url!r}, node={node_url!r}"
        )

    def test_published_order_offers_compute(self, seller_publishes: dict):
        """The seller's order offers a compute resource (GPU) as expected."""
        offer = seller_publishes["offer_resource"]
        assert "gpu_model" in offer, (
            f"Seller's offer is not a compute resource: {offer}"
        )
