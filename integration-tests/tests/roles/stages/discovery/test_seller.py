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
        self, seller_node: dict, seller_publishes_order: dict,
    ):
        """After publishing, the seller's order appears in /orders?status=open."""
        data = query_registry_orders(seller_node["market"]["url"], status="open")
        order_ids = {o["order_id"] for o in data.get("items", [])}
        assert seller_publishes_order["order_id"] in order_ids

    def test_published_order_is_attributed_to_seller(
        self, seller_node: dict, seller_publishes_order: dict,
    ):
        """The published order's maker is the seller's own agent URL."""
        assert seller_publishes_order["order_maker"] == seller_node["agent_url"], (
            f"order_maker={seller_publishes_order['order_maker']!r} "
            f"does not match seller URL={seller_node['agent_url']!r}"
        )

    def test_published_order_offers_compute(self, seller_publishes_order: dict):
        """The seller's order offers a compute resource (GPU) as expected."""
        offer = seller_publishes_order["offer_resource"]
        assert "gpu_model" in offer, (
            f"Seller's offer is not a compute resource: {offer}"
        )
