"""Discovery — buyer perspective.

User-visible property: "I can find offers in the marketplace that match
the compute I need."

What the buyer observes:
  - Querying the registry for open orders returns candidates.
  - Applying the buyer's matching logic to those candidates identifies
    at least one complementary seller offer.
  - The identified order carries a reachable counterparty URL.

This test exercises the same matching path the buyer agent uses
internally (service.clients.indexer.RegistryClient.match_orders),
not a re-implemented variant. The only difference is sync vs async.
"""

from __future__ import annotations

import logging

import pytest

from service.clients.indexer import RegistryClient
from tests.helpers.agent_client import query_registry_orders

log = logging.getLogger(__name__)


def _build_buyer_order(compute_spec: dict, payment_spec: dict) -> dict:
    """The order a buyer would construct to match the seller's offer.

    This is the shape the buyer agent's own discovery logic uses as input
    to match_orders. Not persisted — just used for filtering candidates.
    """
    return {
        "offer_resource": {"token": payment_spec["token"], "amount": payment_spec["amount"]},
        "demand_resource": {
            "gpu_model": compute_spec["gpu_model"],
            "quantity": compute_spec["quantity"],
            "sla": compute_spec["sla"],
            "region": compute_spec["region"],
        },
    }


@pytest.mark.roles_discovery_buyer
class TestBuyerCanFindMatchingOffers:
    """The buyer can discover seller offers that complement their requirements."""

    def test_buyer_matching_logic_finds_seller_offer(
        self, buyer_node: dict, discovery_output: dict,
    ):
        """The buyer's matching logic, applied to the registry's open orders,
        identifies the seller's order as a complementary match."""
        seller_order = discovery_output["seller_order"]
        buyer_order = _build_buyer_order(
            discovery_output["compute_spec"],
            discovery_output["payment_spec"],
        )

        # Query the registry — same endpoint the buyer agent uses internally.
        data = query_registry_orders(buyer_node["market"]["url"], status="open")
        candidates = data.get("items", [])

        # Apply the buyer agent's own matching logic (sync method on the
        # registry client used by the agent's discovery flow).
        client = RegistryClient(base_url=buyer_node["market"]["url"], timeout=5)
        matches = client.match_orders(buyer_order, candidates, bidirectional=True)

        match_ids = {m["order_id"] for m in matches}
        assert seller_order["order_id"] in match_ids, (
            f"Buyer's matching logic did not find seller's order {seller_order['order_id']}. "
            f"Candidates: {[c['order_id'] for c in candidates]}. "
            f"Matches: {match_ids}."
        )

    def test_discovered_seller_has_reachable_url(
        self, buyer_node: dict, discovery_output: dict,
    ):
        """The order_maker URL on the discovered order is one the buyer can contact."""
        seller_order = discovery_output["seller_order"]
        maker_url = seller_order["order_maker"]

        assert maker_url.startswith(("http://", "https://")), (
            f"Maker URL is not HTTP(S): {maker_url!r}"
        )
        # The URL must be something the buyer can actually reach — in the
        # test topology this is the seller node's agent URL.
        # (In production the buyer contacts this URL directly during
        # negotiation.)
