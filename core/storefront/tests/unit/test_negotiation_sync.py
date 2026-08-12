from __future__ import annotations

import json
from market_identity import Identity


from core_storefront.negotiation_sync import (
    coerce_pinned_proposal,
    history_from_messages,
    proposal_with_amount,
)

BUYER = Identity(scheme="eip191", identifier="0x" + "11" * 20)
SELLER = Identity(scheme="eip191", identifier="0x" + "22" * 20)


def test_proposal_with_amount_overlays_fields_without_mutating_pinned() -> None:
    pinned = {
        "chain_name": "anvil",
        "fields": {"token": "0xToken", "amount": 10},
        "literal_fields": {"token": "0xToken"},
    }

    result = proposal_with_amount(pinned, 25)

    assert result == {
        "chain_name": "anvil",
        "fields": {"token": "0xToken", "amount": 25},
        "literal_fields": {"token": "0xToken"},
    }
    assert pinned["fields"]["amount"] == 10


def test_coerce_pinned_proposal_accepts_dict_and_json() -> None:
    payload = {"fields": {"amount": 5}}

    assert coerce_pinned_proposal(payload) is payload
    assert coerce_pinned_proposal(json.dumps(payload)) == payload
    assert coerce_pinned_proposal("not-json") is None
    assert coerce_pinned_proposal(["not", "dict"]) is None


def test_history_from_messages_reconstructs_rounds_from_pinned_proposal() -> None:
    pinned = {"chain_name": "anvil", "fields": {"token": "0xToken"}}
    messages = [
        {
            "sender_principal": BUYER.model_dump(mode="json"),
            "action_taken": "make_offer",
            "proposed_price": "10",
        },
        {
            "sender_principal": SELLER.model_dump(mode="json"),
            "action_taken": "counter_offer",
            "proposed_price": "15",
        },
        {
            "sender_principal": BUYER.model_dump(mode="json"),
            "action_taken": "exit_negotiation",
            "proposed_price": None,
        },
    ]

    history = history_from_messages(
        messages,
        SELLER,
        buyer_pinned_proposal=pinned,
    )

    assert [round.sender for round in history] == ["them", "us", "them"]
    assert [round.action for round in history] == ["initial", "counter", "exit"]
    assert history[0].proposal["fields"] == {"token": "0xToken", "amount": 10}
    assert history[1].proposal["fields"] == {"token": "0xToken", "amount": 15}
    assert history[2].proposal["fields"] == {"token": "0xToken"}
