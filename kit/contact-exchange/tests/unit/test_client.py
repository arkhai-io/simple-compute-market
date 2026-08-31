from __future__ import annotations

from market_contact_exchange import ContactExchangeClient
from market_settlement_runtime import ConditionalEscrowClient

_OBLIGATION = {
    "payer": "buyer",
    "claimant": "seller",
    "mechanism": "contact-exchange.v1",
}


def test_client_satisfies_the_conditional_escrow_port() -> None:
    assert isinstance(ContactExchangeClient(), ConditionalEscrowClient)


async def test_materialize_is_ready_immediately_and_deterministic() -> None:
    client = ContactExchangeClient()
    first = await client.materialize(dict(_OBLIGATION), operation_ref="op-1")
    again = await client.materialize(dict(_OBLIGATION), operation_ref="op-1")
    assert first.status == "ready"
    assert first.mechanism_ref == "introduction:op-1"
    assert first.mechanism_ref == again.mechanism_ref


async def test_status_and_check_report_satisfied() -> None:
    client = ContactExchangeClient()
    status = await client.get_status(
        dict(_OBLIGATION),
        mechanism_ref="introduction:op-1",
        operation_ref="op-2",
        mechanism_state={},
    )
    condition = await client.check(
        dict(_OBLIGATION),
        mechanism_ref="introduction:op-1",
        fulfillment_ref="fulfill-1",
        operation_ref="op-3",
        mechanism_state={},
    )
    assert status.status == "ready"
    assert condition.decision == "ready"


async def test_collect_produces_the_introduction_receipt() -> None:
    client = ContactExchangeClient()
    outcome = await client.collect(
        dict(_OBLIGATION),
        mechanism_ref="introduction:op-1",
        fulfillment_ref="fulfill-1",
        operation_ref="op-4",
        mechanism_state={},
    )
    assert outcome.receipt["kind"] == "contact_exchange.introduction"
    assert outcome.receipt["mechanism_ref"] == "introduction:op-1"


async def test_reclaim_is_a_noop_receipt() -> None:
    client = ContactExchangeClient()
    outcome = await client.reclaim_expired(
        dict(_OBLIGATION),
        mechanism_ref="introduction:op-1",
        operation_ref="op-5",
        mechanism_state={},
    )
    assert outcome.receipt["kind"] == "contact_exchange.reclaim_noop"
