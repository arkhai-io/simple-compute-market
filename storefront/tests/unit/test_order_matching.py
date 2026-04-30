"""Unit tests for market_storefront.utils.order_matching.

Covers:
- match_orders with plain dicts (backward compat)
- match_orders with ListingSummary instances (canonical path)
- Bidirectional matching both cases (A and B)
- Non-bidirectional (direct) matching
- Non-matching candidates are excluded
- Empty inputs
"""

from __future__ import annotations

import pytest

from market_storefront.utils.order_matching import match_orders, _resource_type


def _dict_order(offer: dict, demand: dict, order_id: str = "ord") -> dict:
    return {"order_id": order_id, "offer_resource": offer, "demand_resource": demand}


def _summary_order(offer: dict, demand: dict, order_id: str = "ord"):
    """Create a minimal ListingSummary-like object."""
    from registry_client.models import ListingSummary
    return ListingSummary(id=order_id, offer=offer, demand=demand, status="open")


COMPUTE = {"gpu_model": "A100", "quantity": 1, "sla": 99.0, "region": "us-west"}
TOKEN = {"token": "USDC", "amount": 100.0}


class TestResourceType:
    def test_token_resource(self):
        assert _resource_type({"token": "USDC", "amount": 10}) == "token"

    def test_compute_resource(self):
        assert _resource_type({"gpu_model": "A100"}) == "compute"

    def test_unknown_resource(self):
        assert _resource_type({"something": "else"}) == "unknown"

    def test_empty_dict(self):
        assert _resource_type({}) == "unknown"


class TestMatchOrdersDicts:
    """match_orders with plain dicts (backward compatibility)."""

    def test_case_a_compute_offer_matches_token_offer_candidate(self):
        our = _dict_order(COMPUTE, TOKEN, "our-1")
        candidate = _dict_order(TOKEN, COMPUTE, "theirs-1")
        result = match_orders(our, [candidate])
        assert len(result) == 1
        assert result[0]["order_id"] == "theirs-1"

    def test_case_b_token_offer_matches_compute_offer_candidate(self):
        our = _dict_order(TOKEN, COMPUTE, "our-2")
        candidate = _dict_order(COMPUTE, TOKEN, "theirs-2")
        result = match_orders(our, [candidate])
        assert len(result) == 1

    def test_no_match_same_resource_types(self):
        our = _dict_order(COMPUTE, TOKEN, "our-3")
        candidate = _dict_order(COMPUTE, TOKEN, "theirs-3")
        assert match_orders(our, [candidate]) == []

    def test_empty_candidates(self):
        our = _dict_order(COMPUTE, TOKEN)
        assert match_orders(our, []) == []

    def test_returns_only_matching_subset(self):
        our = _dict_order(COMPUTE, TOKEN)
        match = _dict_order(TOKEN, COMPUTE, "match")
        no_match = _dict_order(COMPUTE, TOKEN, "no-match")
        result = match_orders(our, [match, no_match])
        assert len(result) == 1
        assert result[0]["order_id"] == "match"


class TestMatchOrdersListingSummary:
    """match_orders with ListingSummary instances (canonical path)."""

    def test_case_a_with_order_summary(self):
        our = _summary_order(COMPUTE, TOKEN, "our-s1")
        candidate = _summary_order(TOKEN, COMPUTE, "theirs-s1")
        result = match_orders(our, [candidate])
        assert len(result) == 1
        assert result[0].id == "theirs-s1"

    def test_case_b_with_order_summary(self):
        our = _summary_order(TOKEN, COMPUTE, "our-s2")
        candidate = _summary_order(COMPUTE, TOKEN, "theirs-s2")
        result = match_orders(our, [candidate])
        assert len(result) == 1

    def test_no_match_with_order_summary(self):
        our = _summary_order(COMPUTE, TOKEN)
        candidate = _summary_order(COMPUTE, TOKEN)
        assert match_orders(our, [candidate]) == []

    def test_returns_order_summary_instances(self):
        from registry_client.models import ListingSummary
        our = _summary_order(COMPUTE, TOKEN)
        candidate = _summary_order(TOKEN, COMPUTE)
        result = match_orders(our, [candidate])
        assert all(isinstance(r, ListingSummary) for r in result)


class TestMatchOrdersNonBidirectional:
    def test_direct_match_accepted(self):
        our = _dict_order(COMPUTE, TOKEN)
        candidate = _dict_order(TOKEN, COMPUTE)
        result = match_orders(our, [candidate], bidirectional=False)
        assert len(result) == 1

    def test_same_type_excluded_in_non_bidirectional(self):
        our = _dict_order(COMPUTE, TOKEN)
        candidate = _dict_order(COMPUTE, TOKEN)
        assert match_orders(our, [candidate], bidirectional=False) == []


class TestMatchOrdersMixed:
    def test_dict_our_order_summary_candidates(self):
        """Mixing types works because both duck-type on _get_offer/_get_demand."""
        our = _dict_order(COMPUTE, TOKEN)
        candidate = _summary_order(TOKEN, COMPUTE, "mix-1")
        result = match_orders(our, [candidate])
        assert len(result) == 1
