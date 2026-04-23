"""Unit tests for the buyer-as-client negotiation library.

Mocks the HTTP transport and verifies that the negotiation loop:
- handles the seller's immediate-accept short-circuit on round 0
- propagates seller-initiated exits
- applies the buyer policy (accept under ceiling, counter at midpoint,
  exit on unreasonable prices)
- terminates after max_rounds
- signs every request with a timestamp + EIP-191 signature
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from market.buyer_client import (
    NegotiationOutcome,
    _decide_buyer_response,
    negotiate_with_seller,
)


# ---------------------------------------------------------------------------
# _decide_buyer_response — pure policy
# ---------------------------------------------------------------------------


def test_accept_when_seller_price_under_ceiling():
    move = _decide_buyer_response(
        seller_counter_price=90, max_price=100, our_previous_counters=[],
    )
    assert move == {"action": "accept"}


def test_accept_at_convergence_boundary():
    move = _decide_buyer_response(
        seller_counter_price=100, max_price=100, our_previous_counters=[],
    )
    assert move == {"action": "accept"}


def test_counter_at_midpoint_when_seller_reasonable():
    """Seller asks 140, ceiling 100 → counter at midpoint 120 — but clamped to 100."""
    move = _decide_buyer_response(
        seller_counter_price=140, max_price=100, our_previous_counters=[],
    )
    assert move["action"] == "counter"
    # Midpoint would be (100+140)//2 = 120, but that's over our ceiling → clamp to 100.
    assert move["price"] == 100


def test_counter_at_midpoint_when_seller_only_slightly_over():
    """Seller asks 110, ceiling 100 → midpoint 105, clamped to 100."""
    move = _decide_buyer_response(
        seller_counter_price=110, max_price=100, our_previous_counters=[],
    )
    assert move == {"action": "counter", "price": 100}


def test_exit_when_seller_price_unreasonable():
    """Seller asks 200, ceiling 100 → exit (ratio > 1.5)."""
    move = _decide_buyer_response(
        seller_counter_price=200, max_price=100, our_previous_counters=[],
    )
    assert move["action"] == "exit"
    assert move["reason"] == "price_unreasonable"


def test_max_rounds_exits():
    move = _decide_buyer_response(
        seller_counter_price=100, max_price=100,
        our_previous_counters=[50] * 10, max_rounds=10,
    )
    assert move["action"] == "exit"
    assert move["reason"] == "max_rounds"


def test_stale_counter_guard_fires():
    move = _decide_buyer_response(
        seller_counter_price=140, max_price=100,
        our_previous_counters=[100, 100],
    )
    assert move["action"] == "exit"
    assert move["reason"] == "stale_negotiation"


# ---------------------------------------------------------------------------
# negotiate_with_seller — integration through mocked HTTP
# ---------------------------------------------------------------------------


@dataclass
class _MockResponse:
    status: int
    text: str

    def read(self):
        return self.text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


def _urlopen_fake(responses):
    """Return a urlopen replacement that yields the given responses in order."""
    it = iter(responses)

    def _fn(req, timeout=None):
        body = next(it)
        return _MockResponse(status=200, text=json.dumps(body))

    return _fn


_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0x" + "cc" * 20


@patch("market.buyer_client.urllib.request.urlopen")
def test_round_0_seller_accepts_immediately(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "accept", "price": 50},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1",
        seller_order_id="seller-1",
        initial_price=50,
        max_price=100,
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_price == 50
    assert outcome.rounds == 0
    assert outcome.negotiation_id == "neg-1"


@patch("market.buyer_client.urllib.request.urlopen")
def test_round_0_seller_exits(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "exit", "reason": "price_unreasonable"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=10, max_price=20,
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_unreasonable"


@patch("market.buyer_client.urllib.request.urlopen")
def test_counter_loop_converges_to_accept(mock_urlopen):
    """Seller keeps countering, buyer accepts when under ceiling."""
    mock_urlopen.side_effect = _urlopen_fake([
        # Round 0: seller counters at 90
        {"negotiation_id": "neg-1", "action": "counter", "price": 90},
        # Round 1: buyer accepts (90 < ceiling 100) → seller echoes accept
        {"action": "accept", "price": 90},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=50, max_price=100,
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_price == 90
    assert outcome.rounds == 1


@patch("market.buyer_client.urllib.request.urlopen")
def test_counter_loop_seller_walks_away(mock_urlopen):
    """Buyer counters, seller exits."""
    mock_urlopen.side_effect = _urlopen_fake([
        # Round 0: seller counters at 150 (buyer ceiling 100 → buyer counters at 100 clamp)
        {"negotiation_id": "neg-1", "action": "counter", "price": 150},
        # Round 1: seller exits
        {"action": "exit", "reason": "price_unreasonable"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=50, max_price=100,
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_unreasonable"
    assert outcome.rounds == 1


@patch("market.buyer_client.urllib.request.urlopen")
def test_buyer_exits_when_seller_unreasonable(mock_urlopen):
    """Seller counters far above ceiling → buyer exits."""
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "counter", "price": 500},
        # Seller receives our exit and echoes terminal.
        {"action": "exit", "reason": "buyer_exit"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=50, max_price=100,
    )
    assert outcome.status == "exited"
    # Exit was buyer-initiated (we detected unreasonable seller price).
    assert outcome.reason == "price_unreasonable"


@patch("market.buyer_client.urllib.request.urlopen")
def test_signed_requests_include_signature_and_timestamp(mock_urlopen):
    seen_headers = []

    def _capture(req, timeout=None):
        seen_headers.append(dict(req.header_items()))
        return _MockResponse(status=200, text=json.dumps({
            "negotiation_id": "neg-1", "action": "accept", "price": 50,
        }))

    mock_urlopen.side_effect = _capture
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=50, max_price=100,
    )
    # One round, one request.
    assert len(seen_headers) == 1
    hdrs = seen_headers[0]
    # urllib capitalizes — normalize.
    hdrs_lower = {k.lower(): v for k, v in hdrs.items()}
    assert hdrs_lower.get("x-signature", "").startswith("0x")
    assert hdrs_lower.get("x-timestamp", "").isdigit()


@patch("market.buyer_client.urllib.request.urlopen")
def test_on_round_hook_receives_each_round(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "counter", "price": 90},
        {"action": "accept", "price": 90},
    ])
    seen = []
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK,
        buyer_order_id="buyer-1", seller_order_id="seller-1",
        initial_price=50, max_price=100,
        on_round=lambda i, msg, reply: seen.append((i, msg, reply)),
    )
    assert len(seen) == 2
    assert seen[0][0] == 0   # round index
    assert seen[1][0] == 1


def test_outcome_to_dict_shape():
    o = NegotiationOutcome(
        status="agreed", negotiation_id="neg-1", agreed_price=99, rounds=3,
    )
    assert o.to_dict() == {
        "status": "agreed", "negotiation_id": "neg-1",
        "agreed_price": 99, "rounds": 3,
    }
    assert NegotiationOutcome(status="exited", negotiation_id="neg-1",
                              reason="max_rounds", rounds=10).to_dict() == {
        "status": "exited", "negotiation_id": "neg-1",
        "reason": "max_rounds", "rounds": 10,
    }
