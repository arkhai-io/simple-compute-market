"""Unit tests for `negotiate_with_seller(resume=...)`.

Resume mode is the path used by `market negotiate --from <id>` and
the negotiation-half of `market buy --from <id>`. The buyer
reconstructs `ResumeState` from a run-log and skips the round-0
``/negotiate/new`` POST: instead the seller's last counter is
synthesized as the in-loop ``reply`` and the round loop runs against
the existing thread.

These tests cover the orchestration in isolation: HTTP is mocked,
the strategy is pinned, and we assert on:
- which URL the buyer POSTs to (must be /negotiate/{id}, never /new)
- the signed canonical message (must be negotiate_continue:..., never
  negotiate_new:...)
- the returned NegotiationOutcome shape
- guard rails (missing last_seller_price, immediate-terminal seller).

Decision logic itself is policy-package territory; here we plug in a
deterministic fake strategy.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from market_policy.negotiation_middleware import (
    NegotiationContext,
    NegotiationDecision,
    NegotiationRound,
    NegotiationStep,
)

from market_buyer.buyer_client import (
    NegotiationOutcome,
    ResumeState,
    negotiate_with_seller,
)


_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0x" + "cc" * 20


# ---------------------------------------------------------------------------
# Test doubles
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


def _urlopen_capture(responses):
    """Return a urlopen replacement that yields the given responses in
    order and records every Request seen.

    The recorded list lets a test assert which URL the buyer POSTed
    to, which headers it set, and which body it sent — the resume
    contract is largely about routing, so observability matters.
    """
    seen: list[dict] = []
    it = iter(responses)

    def _fn(req, timeout=None):
        seen.append({
            "url": req.full_url,
            "headers": dict(req.header_items()),
            "body": json.loads(req.data.decode("utf-8")) if req.data else None,
        })
        body = next(it)
        return _MockResponse(status=200, text=json.dumps(body))

    return _fn, seen


def _fixed_chain(decisions: list[NegotiationDecision]):
    """Build a single-middleware chain that returns pre-baked decisions in order.

    Lets tests pin the buyer's response to a specific seller counter
    without depending on the real ceiling-bisection or RL middlewares.
    """
    state = {"idx": 0}

    def _mw(history, context):
        if state["idx"] >= len(decisions):
            raise AssertionError(
                "_fixed_chain exhausted — test scripted too few decisions"
            )
        d = decisions[state["idx"]]
        state["idx"] += 1
        return d, context

    return [_mw]


# ---------------------------------------------------------------------------
# Resume happy paths
# ---------------------------------------------------------------------------


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_buyer_accepts_recovered_seller_price(mock_urlopen):
    """Resume from a run-log where seller last countered at 90, buyer
    decides to accept. The seller echoes accept → outcome.agreed at 90."""
    fake, seen = _urlopen_capture([
        # Single response: seller's accept echo to our continue-with-accept.
        {"action": "accept", "price": 90},
    ])
    mock_urlopen.side_effect = fake

    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,           # ignored in resume mode
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="accept", price=90),
        ]),
        resume=ResumeState(
            negotiation_id="neg-resumed",
            transcript=[
                NegotiationRound(round_number=0, sender="us", action="initial", price=50),
                NegotiationRound(round_number=0, sender="them", action="counter", price=90),
            ],
            last_seller_price=90,
            rounds_completed=1,
        ),
    )

    assert outcome.status == "agreed"
    assert outcome.agreed_price == 90
    assert outcome.negotiation_id == "neg-resumed"
    # We made exactly one HTTP call — to /negotiate/{id}, never to /new.
    assert len(seen) == 1
    assert seen[0]["url"].endswith("/negotiate/neg-resumed")
    assert "/negotiate/new" not in seen[0]["url"]


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_signed_message_uses_continue_not_new(mock_urlopen):
    """The EIP-191 message must be `negotiate_continue:{neg_id}:...`,
    proving the resume path skipped /negotiate/new entirely."""
    from eth_account import Account
    from eth_account.messages import encode_defunct

    fake, seen = _urlopen_capture([
        {"action": "accept", "price": 80},
    ])
    mock_urlopen.side_effect = fake

    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="accept", price=80),
        ]),
        resume=ResumeState(
            negotiation_id="neg-xyz",
            transcript=[],
            last_seller_price=80,
            rounds_completed=1,
        ),
    )

    hdrs = {k.lower(): v for k, v in seen[0]["headers"].items()}
    sig = hdrs["x-signature"]
    ts = hdrs["x-timestamp"]
    msg_continue = encode_defunct(text=f"negotiate_continue:neg-xyz:{ts}")
    recovered = Account.recover_message(msg_continue, signature=sig)
    # Recovered must match the buyer's wallet derived from _BUYER_PK.
    expected = Account.from_key(_BUYER_PK).address
    assert recovered.lower() == expected.lower()


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_buyer_counters_then_seller_accepts(mock_urlopen):
    """Two-round resume: buyer counters at 70, seller accepts."""
    fake, seen = _urlopen_capture([
        {"action": "accept", "price": 70},
    ])
    mock_urlopen.side_effect = fake

    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="counter", price=70),
        ]),
        resume=ResumeState(
            negotiation_id="neg-2",
            transcript=[],
            last_seller_price=80,
            rounds_completed=1,
        ),
    )

    assert outcome.status == "agreed"
    assert outcome.agreed_price == 70
    assert outcome.negotiation_id == "neg-2"
    assert seen[0]["body"]["action"] == "counter"
    assert seen[0]["body"]["price"] == 70


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_buyer_exits(mock_urlopen):
    """Buyer's strategy chooses exit → outcome.exited, reason carried."""
    fake, _seen = _urlopen_capture([
        # Seller's terminal echo to our exit. Body unused beyond the
        # round-loop's terminal-state detection.
        {"action": "exit", "reason": "buyer_exit"},
    ])
    mock_urlopen.side_effect = fake

    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="exit", reason="ceiling_breached"),
        ]),
        resume=ResumeState(
            negotiation_id="neg-3",
            transcript=[],
            last_seller_price=500,
            rounds_completed=2,
        ),
    )

    assert outcome.status == "exited"
    assert outcome.reason == "ceiling_breached"


# ---------------------------------------------------------------------------
# Resume guards
# ---------------------------------------------------------------------------


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_without_last_seller_price_raises(mock_urlopen):
    """Cannot resume the round loop without knowing the seller's last
    counter — the strategy needs `their_proposed_price`."""
    mock_urlopen.side_effect = AssertionError("must not be called")

    with pytest.raises(RuntimeError, match="no seller counter price"):
        negotiate_with_seller(
            seller_url="http://seller:8001",
            buyer_address=_BUYER_ADDR,
            buyer_private_key=_BUYER_PK,
            listing_id="L-1",
            initial_price=0,
            max_price=100,
            chain=_fixed_chain([]),
            resume=ResumeState(
                negotiation_id="neg-x",
                transcript=[],
                last_seller_price=None,
                rounds_completed=0,
            ),
        )


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_carries_rounds_completed_into_outcome(mock_urlopen):
    """When resume points at rounds_completed=3, an immediate accept
    in the next round should report rounds=3 (not 1)."""
    fake, _ = _urlopen_capture([
        {"action": "accept", "price": 60},
    ])
    mock_urlopen.side_effect = fake

    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="accept", price=60),
        ]),
        resume=ResumeState(
            negotiation_id="neg-late",
            transcript=[],
            last_seller_price=60,
            rounds_completed=3,
        ),
    )

    assert outcome.rounds == 3


@patch("market_buyer.buyer_client.urllib.request.urlopen")
def test_resume_skips_negotiate_new_endpoint_entirely(mock_urlopen):
    """Cross-cutting check: every HTTP call's URL contains the neg_id
    (i.e. /negotiate/{id}); none hit /negotiate/new."""
    fake, seen = _urlopen_capture([
        {"action": "counter", "price": 75},
        {"action": "accept", "price": 70},
    ])
    mock_urlopen.side_effect = fake

    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="L-1",
        initial_price=0,
        max_price=100,
        chain=_fixed_chain([
            NegotiationDecision(action="counter", price=70),
            NegotiationDecision(action="accept", price=70),
        ]),
        resume=ResumeState(
            negotiation_id="neg-multi",
            transcript=[],
            last_seller_price=85,
            rounds_completed=1,
        ),
    )

    assert len(seen) == 2
    for call in seen:
        assert "/negotiate/neg-multi" in call["url"]
        assert call["url"].endswith("/negotiate/neg-multi")
