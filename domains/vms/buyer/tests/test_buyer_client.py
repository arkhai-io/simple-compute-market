"""Unit tests for the buyer-as-client negotiation library.

Mocks the HTTP transport and verifies that the negotiation loop:
- handles the seller's immediate-accept short-circuit on round 0
- propagates seller-initiated exits
- terminates after max_rounds
- signs every request with a timestamp + EIP-191 signature

The pure decision logic lives in ``bisection_middleware`` / ``rl_middleware``
and is exercised in kit/policy/tests/unit/test_negotiation_strategy.py —
this file just covers the HTTP loop wrapping the chain.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from market_policy.negotiation_middleware import load_negotiation_chain

from market_core.schemas import EscrowProposal
from domains.vms.buyer.buyer_client import NegotiationOutcome, negotiate_with_seller
from domains.vms.provisioning import VmProvisionTerms, make_vm_provision_terms


# Canonical provision / escrow proposals used by every negotiate test —
# kept here so individual tests don't need to repeat the boilerplate.
def _provision(duration_seconds: int = 3600) -> VmProvisionTerms:
    return make_vm_provision_terms(
        duration_seconds=duration_seconds, ssh_public_key="ssh-rsa AAAA",
    )


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address="0x" + "cd" * 20,
        fields={"token": "0x" + "ab" * 20},
        expiration_unix=1_800_000_000,
    )


def _seller_proposal(amount: int) -> dict:
    """Mirror of ``_escrow_proposal`` with ``fields["amount"]`` set.

    The buyer's chain default includes ``buyer_escrow_shape_guard`` which
    vetoes if the seller's response diverges from the buyer's pinned
    shape on any non-amount field. Tests use this helper for realistic
    counter / accept echoes.
    """
    return {
        "chain_name": "anvil",
        "escrow_address": "0x" + "cd" * 20,
        "fields": {"amount": int(amount), "token": "0x" + "ab" * 20},
        "expiration_unix": 1_800_000_000,
    }


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


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_round_0_seller_accepts_immediately(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "accept", "proposal": _seller_proposal(50)},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,        listing_id="seller-1",
        initial_price=50,
        max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_amount == 50
    assert outcome.rounds == 0
    assert outcome.negotiation_id == "neg-1"


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_round_0_request_preserves_literal_fields(mock_urlopen):
    seen_body = {}

    def _capture(req, timeout=None):
        seen_body.update(json.loads(req.data.decode("utf-8")))
        return _MockResponse(
            status=200,
            text=json.dumps({
                "negotiation_id": "neg-1",
                "action": "accept",
                "proposal": _seller_proposal(50),
            }),
        )

    mock_urlopen.side_effect = _capture
    token = "0x" + "ef" * 20
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="seller-1",
        initial_price=50,
        max_price=100,
        provision_terms=_provision(3600),
        escrow_proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address="0x" + "cd" * 20,
            fields={},
            literal_fields={"token": token},
            rates=[{"field": "amount", "per": "hour", "value": "50"}],
            expiration_unix=1_800_000_000,
        ),
    )

    proposal = seen_body["proposal"]
    assert proposal["fields"] == {"amount": 50}
    assert proposal["literal_fields"] == {"token": token}
    assert seen_body["provision_terms"] == {
        "kind": "compute.v1",
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-rsa AAAA",
        },
    }


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_round_0_request_omits_amount_for_amountless_escrow(mock_urlopen):
    seen_body = {}

    def _capture(req, timeout=None):
        seen_body.update(json.loads(req.data.decode("utf-8")))
        return _MockResponse(
            status=200,
            text=json.dumps({
                "negotiation_id": "neg-1",
                "action": "accept",
                "proposal": {
                    "chain_name": "anvil",
                    "escrow_address": "0x" + "cd" * 20,
                    "fields": {},
                    "literal_fields": {"attestationUid": "0x" + "aa" * 32},
                    "rates": [],
                    "expiration_unix": 1_800_000_000,
                },
            }),
        )

    mock_urlopen.side_effect = _capture
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="seller-1",
        initial_price=0,
        max_price=0,
        provision_terms=_provision(3600),
        escrow_proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address="0x" + "cd" * 20,
            fields={},
            literal_fields={"attestationUid": "0x" + "aa" * 32},
            rates=[],
            expiration_unix=1_800_000_000,
        ),
        chain=["accept_exact_listing"],
    )

    proposal = seen_body["proposal"]
    assert proposal["fields"] == {}
    assert proposal["literal_fields"] == {"attestationUid": "0x" + "aa" * 32}


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_round_0_request_preserves_rates(mock_urlopen):
    seen_body = {}

    def _capture(req, timeout=None):
        seen_body.update(json.loads(req.data.decode("utf-8")))
        return _MockResponse(
            status=200,
            text=json.dumps({
                "negotiation_id": "neg-1",
                "action": "accept",
                "proposal": _seller_proposal(50),
            }),
        )

    mock_urlopen.side_effect = _capture
    rates = [{"field": "amount", "per": "hour", "value": "50"}]
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR,
        buyer_private_key=_BUYER_PK,
        listing_id="seller-1",
        initial_price=50,
        max_price=100,
        provision_terms=_provision(3600),
        escrow_proposal=EscrowProposal(
            chain_name="anvil",
            escrow_address="0x" + "cd" * 20,
            fields={"token": "0x" + "ab" * 20},
            literal_fields={"token": "0x" + "ab" * 20},
            rates=rates,
            expiration_unix=1_800_000_000,
        ),
    )

    assert seen_body["proposal"]["rates"] == rates


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_round_0_seller_exits(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "exit", "reason": "price_unreasonable"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=10, max_price=20, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_unreasonable"


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_counter_loop_converges_to_accept(mock_urlopen):
    """Seller keeps countering, buyer accepts when under ceiling."""
    mock_urlopen.side_effect = _urlopen_fake([
        # Round 0: seller counters at 90
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(90)},
        # Round 1: buyer accepts (90 < ceiling 100) → seller echoes accept
        {"action": "accept", "proposal": _seller_proposal(90)},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_amount == 90
    assert outcome.rounds == 1


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_default_listed_price_buyer_exits_above_bound(mock_urlopen):
    """The listed_price default never haggles: a seller counter above the
    buyer's bound ends the negotiation with the buyer's exit."""
    mock_urlopen.side_effect = _urlopen_fake([
        # Round 0: seller counters at 150 (buyer bound 100 → buyer exits)
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(150)},
        # Round 1: the buyer's exit POST gets an ack
        {"action": "exit", "reason": "buyer_exit"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_above_bound"


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_default_listed_price_accepts_counter_within_bound(mock_urlopen):
    """A seller counter at/under the bound is accepted immediately."""
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(90)},
        {"action": "accept", "proposal": _seller_proposal(90)},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_amount == 90


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_counter_loop_seller_walks_away(mock_urlopen):
    """Opt-in bisection haggles: buyer counters, seller exits."""
    mock_urlopen.side_effect = _urlopen_fake([
        # Round 0: seller counters at 150 (buyer ceiling 100 → buyer counters at 100 clamp)
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(150)},
        # Round 1: seller exits
        {"action": "exit", "reason": "price_unreasonable"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
        chain=load_negotiation_chain(["buyer_escrow_shape_guard", "bisection"]),
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_unreasonable"
    assert outcome.rounds == 1


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_buyer_exits_when_seller_unreasonable(mock_urlopen):
    """Seller counters far above ceiling → buyer exits."""
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(500)},
        # Seller receives our exit and echoes terminal.
        {"action": "exit", "reason": "buyer_exit"},
    ])
    outcome = negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    assert outcome.status == "exited"
    # Exit was buyer-initiated (seller priced above the buyer's bound).
    assert outcome.reason == "price_above_bound"


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_signed_requests_include_signature_and_timestamp(mock_urlopen):
    seen_headers = []

    def _capture(req, timeout=None):
        seen_headers.append(dict(req.header_items()))
        return _MockResponse(status=200, text=json.dumps({
            "negotiation_id": "neg-1", "action": "accept", "proposal": _seller_proposal(50),
        }))

    mock_urlopen.side_effect = _capture
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
    )
    # One round, one request.
    assert len(seen_headers) == 1
    hdrs = seen_headers[0]
    # urllib capitalizes — normalize.
    hdrs_lower = {k.lower(): v for k, v in hdrs.items()}
    assert hdrs_lower.get("x-signature", "").startswith("0x")
    assert hdrs_lower.get("x-timestamp", "").isdigit()


@patch("domains.vms.buyer.buyer_client.urllib.request.urlopen")
def test_on_round_hook_receives_each_round(mock_urlopen):
    mock_urlopen.side_effect = _urlopen_fake([
        {"negotiation_id": "neg-1", "action": "counter", "proposal": _seller_proposal(90)},
        {"action": "accept", "proposal": _seller_proposal(90)},
    ])
    seen = []
    negotiate_with_seller(
        seller_url="http://seller:8001",
        buyer_address=_BUYER_ADDR, buyer_private_key=_BUYER_PK, listing_id="seller-1",
        initial_price=50, max_price=100, provision_terms=_provision(3600), escrow_proposal=_escrow_proposal(),
        on_round=lambda i, msg, reply: seen.append((i, msg, reply)),
    )
    assert len(seen) == 2
    assert seen[0][0] == 0   # round index
    assert seen[1][0] == 1


def test_outcome_to_dict_shape():
    o = NegotiationOutcome(
        status="agreed", negotiation_id="neg-1", agreed_amount=99, rounds=3,
    )
    assert o.to_dict() == {
        "status": "agreed", "negotiation_id": "neg-1",
        "agreed_amount": 99, "rounds": 3,
    }
    assert NegotiationOutcome(status="exited", negotiation_id="neg-1",
                              reason="max_rounds", rounds=10).to_dict() == {
        "status": "exited", "negotiation_id": "neg-1",
        "reason": "max_rounds", "rounds": 10,
    }
