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

from datetime import datetime

import pytest

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
from core.agent.app.utils import action_executor
from core.agent.app.utils.sqlite_client import SQLiteClient
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
# Step 3: fulfill_compute_obligation result carries fulfilling_party_url
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fulfill_compute_obligation_result_includes_fulfilling_party_url(
    monkeypatch, tmp_path
):
    """fulfill_compute_obligation embeds fulfilling_party_url = order_maker in its result."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)

    async def fake_provision_machine(_ssh_public_key, *, vm_host="vm1", vm_target="tenant-vm"):
        return "user@host.example.net"

    def fake_schedule_vm_shutdown(_lease_end_utc, *, vm_host="vm1", vm_target="tenant-vm"):
        return None

    monkeypatch.setattr(action_executor, "provision_machine", fake_provision_machine)
    monkeypatch.setattr(action_executor, "mock_provision_machine", fake_provision_machine)
    monkeypatch.setattr(action_executor, "schedule_vm_shutdown", fake_schedule_vm_shutdown)
    monkeypatch.setattr(action_executor, "mock_schedule_vm_shutdown", fake_schedule_vm_shutdown)
    monkeypatch.setattr(action_executor, "get_sqlite_client", lambda: sqlite_client)

    class _RegistryClient:
        async def update_order(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _RegistryClient())

    order_id = "bob-order-fulfill"
    order_dict = {
        "order_id": order_id,
        "order_maker": BOB_URL,
        "offer_resource": _compute().model_dump(mode="json"),
        "demand_resource": _tokens().model_dump(mode="json"),
        "duration_hours": 1,
    }

    await sqlite_client.upsert_order(
        order_id=order_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=order_dict["offer_resource"],
        demand_resource=order_dict["demand_resource"],
        fulfillment_resource=None,
        duration_hours=1,
        order_maker=BOB_URL,
        order_taker=None,
        matched_offer_id=None,
        maker_attestation=None,
        taker_attestation=None,
        escrow_uid=None,
    )
    await sqlite_client.upsert_resource(
        resource_id="resource-1",
        resource_type="compute.gpu",
        resource_subtype="h200",
        state="available",
        attributes={"gpu_model": "H200", "region": "California, US", "vm_host": "vm1"},
    )

    result = await action_executor.fulfill_compute_obligation(
        client=None,
        escrow_uid="escrow-456",
        ssh_public_key="ssh-rsa AAA",
        order=order_dict,
    )

    assert result.get("fulfilling_party_url") == BOB_URL


# ---------------------------------------------------------------------------
# Step 4: Alice receives fulfillment → TRUST action carries Bob's URL
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step 2b: accept_offer stamps order_taker with the taker's own URL
# (This is the URL the seller will later use as counterparty in FULFILL step)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_accept_offer_stamps_order_taker_with_own_url(monkeypatch):
    """accept_offer sets order_taker = BASE_URL_OVERRIDE so the seller knows where to send fulfillment."""
    import dataclasses

    monkeypatch.setattr(
        action_executor,
        "CONFIG",
        dataclasses.replace(action_executor.CONFIG, agent_wallet_address="0xBobWallet"),
    )
    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", BOB_URL)

    captured: dict = {}

    async def fake_buy_compute_with_erc20(**_kwargs):
        return {"log": {"uid": "escrow-stamp-test"}}

    async def fake_send_to_remote_agent(_ctx, event, agent_url=None):
        captured["event_offer"] = event.content.parts[0].function_response.response.get("offer", {})

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)
    monkeypatch.setattr(action_executor, "NegotiationThreadTransaction", lambda *_a, **_kw: _DummyTxn())
    monkeypatch.setattr(action_executor, "get_sqlite_client", lambda: _NullSqliteClient())

    class _RegistryClient:
        async def update_order(self, *_a, **_kw):
            return {"ok": True}

    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _RegistryClient())

    order_dict = {
        "order_id": "alice-order-stamp",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens().model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
    }

    class _FakeCtx:
        invocation_id = "inv-1"
        branch = "main"

    await action_executor.accept_offer(
        alkahest_client=_FakeClient(),
        ctx=_FakeCtx(),
        parameters={"order": order_dict},
    )

    assert captured["event_offer"]["order_taker"] == BOB_URL


class _DummyTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def cancel_competing(self, *_a, **_kw):
        return None

    async def mark_terminal(self, *_a, **_kw):
        return None


class _NullSqliteClient:
    async def update_order(self, *_a, **_kw):
        return None

    async def find_symmetric_open_order(self, *_a, **_kw):
        return None


class _FakeClient:
    class _Util:
        async def approve(self, *_a, **_kw):
            return "approved"

    class _ERC20:
        def __init__(self):
            class _NonTierable:
                async def create(self, *_a, **_kw):
                    return {"log": {"uid": "escrow-stamp-test"}}

            class _Escrow:
                def __init__(self):
                    self.non_tierable = _NonTierable()

            self.escrow = _Escrow()
            self.util = _FakeClient._Util()

    def __init__(self):
        self.erc20 = self._ERC20()


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
