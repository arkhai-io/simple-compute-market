"""Tests verifying counterparty URL propagation through the full Alice↔Bob flow.

The chain being tested:
  1. Bob (seller) receives Alice's offer → mo_action_accept_offer sets
     counterparty_url = order.order_maker (Alice's URL)
  2. Alice receives acceptance → ao_action_fulfill_after_accept sets
     counterparty_url = order.order_taker (Bob's URL, stamped by accept_offer)
  3. fulfill_compute_obligation result carries fulfilling_party_url = order_maker
     (Bob's URL, so Alice knows who to thank)
  4. Alice receives fulfillment → rcf_action_trust_fulfillment sets
     counterparty_url = event.fulfilling_party_url (Bob's URL)
"""

from core.agent.app.schema.pydantic_models import (
    AcceptOfferEvent,
    ComputeResource,
    DecisionContext,
    ERC20TokenMetadata,
    GPUModel,
    MarketOrder,
    ReceiveComputeObligationFulfillmentEvent,
    Region,
    TokenResource,
)
from domain.compute.agent.app.policy.store import (
    ao_action_fulfill_after_accept,
    mo_action_accept_offer,
    rcf_action_trust_fulfillment,
)


ALICE_URL = "http://alice.example:8000"
BOB_URL = "http://bob.example:8001"

USDT = ERC20TokenMetadata(
    symbol="USDT",
    contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
    decimals=6,
)


def _compute() -> ComputeResource:
    return ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )


def _tokens(amount: int = 1_000_000) -> TokenResource:
    return TokenResource(token=USDT, amount=amount)


def _alice_order(*, order_taker: str | None = None) -> MarketOrder:
    """Alice's token-offering (buy-compute) order."""
    return MarketOrder(
        order_id="alice-order-1",
        order_maker=ALICE_URL,
        order_taker=order_taker,
        offer_resource=_tokens(),
        demand_resource=_compute(),
        duration_hours=1,
        oracle_address="0xAliceWallet",
    )


def _bob_order() -> MarketOrder:
    """Bob's compute-offering (sell-compute) order."""
    return MarketOrder(
        order_id="bob-order-1",
        order_maker=BOB_URL,
        offer_resource=_compute(),
        demand_resource=_tokens(),
        duration_hours=1,
    )


# ---------------------------------------------------------------------------
# Step 1: Bob receives Alice's offer → ACCEPT_OFFER action carries Alice's URL
# ---------------------------------------------------------------------------

def test_mo_action_accept_offer_sets_counterparty_to_order_maker():
    """mo_action_accept_offer wires counterparty_url from order.order_maker (Alice's URL)."""
    from core.agent.app.schema.pydantic_models import MakeOfferEvent

    event = MakeOfferEvent(
        event_id="evt-1",
        source=ALICE_URL,
        order=_alice_order(),
    )
    ctx = DecisionContext(event=event, agent_id="bob-agent")
    action = mo_action_accept_offer(ctx)

    assert action is not None
    assert action.parameters["counterparty_url"] == ALICE_URL


# ---------------------------------------------------------------------------
# Step 2: Alice receives Bob's acceptance → FULFILL_COMPUTE_OBLIGATION carries Bob's URL
# ---------------------------------------------------------------------------

def test_ao_action_fulfill_sets_counterparty_to_order_taker():
    """ao_action_fulfill_after_accept wires counterparty_url from order.order_taker (Bob's URL)."""
    # Alice's order now has order_taker = Bob (stamped by accept_offer)
    alice_order_accepted = _alice_order(order_taker=BOB_URL)
    event = AcceptOfferEvent(
        event_id="evt-2",
        source=BOB_URL,
        order=alice_order_accepted,
        escrow_uid="escrow-123",
        ssh_public_key="ssh-rsa AAA",
    )
    ctx = DecisionContext(event=event, agent_id="alice-agent")
    action = ao_action_fulfill_after_accept(ctx)

    assert action is not None
    assert action.parameters["counterparty_url"] == BOB_URL


# ---------------------------------------------------------------------------
# Step 4: Alice receives fulfillment → TRUST action carries Bob's URL
# ---------------------------------------------------------------------------

def test_rcf_action_trust_sets_counterparty_from_fulfilling_party_url():
    """rcf_action_trust_fulfillment wires counterparty_url from fulfilling_party_url (Bob's URL)."""
    event = ReceiveComputeObligationFulfillmentEvent(
        event_id="evt-4",
        source=BOB_URL,
        escrow_uid="escrow-123",
        fulfillment_uid="ful-123",
        connection_details="user@host.example.net",
        fulfilling_party_url=BOB_URL,
    )
    ctx = DecisionContext(event=event, agent_id="alice-agent")
    action = rcf_action_trust_fulfillment(ctx)

    assert action is not None
    assert action.parameters["counterparty_url"] == BOB_URL
