"""Token negotiation through the core client: unit scaling, round-0
payload, and the answer_key_challenge pass-through.

Mocks the HTTP transport inside ``core_buyer.negotiation_client`` and
drives ``negotiate_with_seller`` exactly as the tokens CLI does: the
API-tokens default guards, ``unit_count`` = requested quantity, and the
``api_tokens.v1`` provision terms fixed at round 0.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import patch

from market_policy.negotiation_middleware import load_negotiation_chain

from core_buyer.negotiation_client import negotiate_with_seller
from domains.apitokens.negotiation import make_api_tokens_provision_terms
from domains.apitokens.negotiation.buyer_policies import (  # noqa: F401 — registers the middleware
    APITOKENS_BUYER_GUARDS,
    answer_key_challenge,
)
from market_alkahest.schemas import EscrowProposal


_BUYER_PK = "0x" + "11" * 32
_BUYER_ADDR = "0x" + "cc" * 20
_TOKEN = "0x" + "ab" * 20
_ESCROW = "0x" + "cd" * 20


def _chain():
    """The tokens CLI's deterministic default chain (listed_price terminal).

    Built explicitly instead of through ``_load_buyer_chain`` so the
    test never reads the developer's buyer.toml.
    """
    return load_negotiation_chain([*APITOKENS_BUYER_GUARDS, "listed_price"])


def _escrow_proposal() -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN},
        expiration_unix=1_800_000_000,
    )


def _seller_proposal(amount: int, **extra) -> dict:
    return {
        "chain_name": "anvil",
        "escrow_address": _ESCROW,
        "fields": {"amount": int(amount), "token": _TOKEN},
        "expiration_unix": 1_800_000_000,
        **extra,
    }


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


def _urlopen_fake(responses, captured=None):
    it = iter(responses)

    def _fn(req, timeout=None):
        if captured is not None and req.data:
            captured.append(json.loads(req.data.decode("utf-8")))
        return _MockResponse(status=200, text=json.dumps(next(it)))

    return _fn


def _negotiate(*, responses, captured=None, quantity=100, initial=3, ceiling=3,
               key_mode="new", key_id=None, max_rounds=10):
    with patch("core_buyer.negotiation_client.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = _urlopen_fake(responses, captured)
        return negotiate_with_seller(
            seller_url="http://seller:8002",
            buyer_address=_BUYER_ADDR,
            buyer_private_key=_BUYER_PK,
            listing_id="lst-tokens-1",
            initial_price=initial,
            max_price=ceiling,
            unit_count=float(quantity),
            provision_terms=make_api_tokens_provision_terms(
                quantity=quantity, key_mode=key_mode, key_id=key_id,
            ),
            escrow_proposal=_escrow_proposal(),
            max_rounds=max_rounds,
            chain=_chain(),
        )


def test_round0_payload_carries_quantity_key_and_scaled_amount():
    """The opening request: provision terms are the api_tokens.v1 payload
    and the proposal amount is per-token rate × quantity."""
    captured: list[dict] = []
    outcome = _negotiate(
        responses=[
            {"negotiation_id": "neg-1", "action": "accept",
             "proposal": _seller_proposal(300)},
        ],
        captured=captured,
        quantity=100, initial=3, ceiling=3,
        key_mode="existing", key_id="ak_42",
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_amount == 300
    assert outcome.unit_count == 100.0

    round0 = captured[0]
    assert round0["provision_terms"] == {
        "kind": "api_tokens.v1",
        "payload": {"quantity": 100, "key": {"mode": "existing", "key_id": "ak_42"}},
    }
    # listed_price opens at initial_price × quantity, absolute.
    assert round0["proposal"]["fields"]["amount"] == 300


def test_seller_counter_above_scaled_ceiling_exits():
    """listed_price never counters: a seller above quantity × ceiling
    ends the negotiation."""
    outcome = _negotiate(
        responses=[
            {"negotiation_id": "neg-2", "action": "counter",
             "proposal": _seller_proposal(500)},
            # The buyer's exit is POSTed; the seller echoes.
            {"negotiation_id": "neg-2", "action": "exit"},
        ],
        quantity=100, initial=3, ceiling=3,
    )
    assert outcome.status == "exited"
    assert outcome.reason == "price_above_bound"


def test_answer_key_challenge_is_inert_against_v1_sellers():
    """No challenge in the seller's counter → the pass-through defers
    and listed_price accepts at the bound."""
    outcome = _negotiate(
        responses=[
            {"negotiation_id": "neg-3", "action": "counter",
             "proposal": _seller_proposal(300)},
            {"negotiation_id": "neg-3", "action": "accept",
             "proposal": _seller_proposal(300)},
        ],
        quantity=100, initial=3, ceiling=3,
    )
    assert outcome.status == "agreed"
    assert outcome.agreed_amount == 300


def test_answer_key_challenge_exits_cleanly_when_challenged():
    """A seller key-possession challenge is unanswerable without an
    owner keypair: clean exit naming the reason — never chain
    exhaustion, never a silent pass."""
    outcome = _negotiate(
        responses=[
            {"negotiation_id": "neg-4", "action": "counter",
             "proposal": _seller_proposal(300, key_challenge={"nonce": "abc123"})},
            # The buyer's exit is POSTed; the seller acknowledges.
            {"negotiation_id": "neg-4", "action": "exit"},
        ],
        quantity=100, initial=3, ceiling=3,
        key_mode="existing", key_id="ak_42",
    )
    assert outcome.status == "exited"
    assert outcome.reason is not None
    assert outcome.reason.startswith("key_challenge_unanswerable")
