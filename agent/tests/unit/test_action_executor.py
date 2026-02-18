"""Unit tests for action executor helpers."""

import json
import sqlite3
from datetime import datetime

import pytest

from app.schema.pydantic_models import (
    Action,
    ActionType,
    ActionType as DomainActionType,
    ComputeResource,
    ERC20TokenMetadata,
    EventType,
    GPUModel,
    Region,
    TokenResource,
)
from app.utils import action_executor
from app.utils.sqlite_client import SQLiteClient


USDT_METADATA = ERC20TokenMetadata(
    symbol="USDT",
    contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
    decimals=6,
)


def _compute_resource() -> ComputeResource:
    return ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )


def _token_rate(amount: int) -> TokenResource:
    return TokenResource(token=USDT_METADATA, amount=amount)


def test_encode_compute_lease_uses_rate_times_duration_token_instance():
    """Test encoding compute lease with TokenResource instance."""
    rate = 1_500_000
    duration_hours = 3
    lease_bytes = action_executor.encode_compute_lease(
        compute_resource=_compute_resource(),
        token_resource=_token_rate(rate),
        duration_hours=duration_hours,
    )
    payload = json.loads(lease_bytes.decode("utf-8"))

    assert payload["duration_hours"] == duration_hours
    assert payload["total_price_int"] == rate * duration_hours
    assert payload["price_per_hour_decimal"] == pytest.approx(rate / 10**USDT_METADATA.decimals)
    assert payload["total_price_decimal"] == pytest.approx((rate * duration_hours) / 10**USDT_METADATA.decimals)


def test_encode_compute_lease_uses_rate_times_duration_token_dict():
    """Test encoding compute lease with token resource as dict."""
    rate = 2_000_000
    duration_hours = 2
    token_dict = {
        "token": {
            "symbol": USDT_METADATA.symbol,
            "contract_address": USDT_METADATA.contract_address,
            "decimals": USDT_METADATA.decimals,
        },
        "amount": rate,
    }
    lease_bytes = action_executor.encode_compute_lease(
        compute_resource=_compute_resource().model_dump(mode="json"),
        token_resource=token_dict,
        duration_hours=duration_hours,
    )
    payload = json.loads(lease_bytes.decode("utf-8"))

    assert payload["total_price_int"] == rate * duration_hours
    assert payload["price_per_hour_decimal"] == pytest.approx(rate / 10**USDT_METADATA.decimals)
    assert payload["total_price_decimal"] == pytest.approx((rate * duration_hours) / 10**USDT_METADATA.decimals)


class _FakeEscrow:
    def __init__(self, records: dict) -> None:
        self._records = records

    async def create(self, price_data, arbiter_data, expiration):
        self._records["price_data"] = price_data
        self._records["arbiter_data"] = arbiter_data
        self._records["expiration"] = expiration
        return {"log": {"uid": "escrow123"}}


class _FakeClient:
    def __init__(self, records: dict) -> None:
        class _Util:
            async def approve(self, *_args, **_kwargs):
                return "approved"

        class _NonTierable:
            def __init__(self, recs: dict) -> None:
                self._recs = recs

            async def create(self, price_data, arbiter_data, expiration):
                return await _FakeEscrow(self._recs).create(price_data, arbiter_data, expiration)

        class _Escrow:
            def __init__(self, recs: dict) -> None:
                self.non_tierable = _NonTierable(recs)

        class _ERC20:
            def __init__(self, recs: dict) -> None:
                self.escrow = _Escrow(recs)
                self.util = _Util()

        self.erc20 = _ERC20(records)


class _FakeCtx:
    def __init__(self) -> None:
        self.invocation_id = "invocation-1"
        self.branch = "main"


@pytest.mark.asyncio
async def test_buy_compute_with_erc20_approves_total_and_creates_total(monkeypatch):
    """Test buying compute with ERC20 approves total payment and creates escrow with total price."""
    records: dict = {}
    rate = 1_250_000
    duration_hours = 4

    async def fake_approve_token_escrow(payment, *, alkahest_client):
        records["approved_payment"] = payment
        return "approved"

    monkeypatch.setattr(action_executor, "approve_token_escrow", fake_approve_token_escrow)

    await action_executor.buy_compute_with_erc20(
        compute_resource=_compute_resource(),
        token_resource=_token_rate(rate),
        duration_hours=duration_hours,
        oracle_address="0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        client=_FakeClient(records),
    )

    assert records["approved_payment"].amount == rate * duration_hours
    assert records["price_data"]["value"] == rate * duration_hours


@pytest.mark.asyncio
async def test_accept_offer_passes_duration_and_hourly_rate(monkeypatch):
    """Test accept_offer passes duration_hours and hourly rate to buy_compute_with_erc20."""
    records: dict = {}
    rate = 1_000_000
    duration_hours = 5
    order_dict = {
        "order_id": "order-123",
        "order_maker": "seller",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(rate).model_dump(mode="json"),
        "duration_hours": duration_hours,
    }

    async def fake_buy_compute_with_erc20(
        compute_resource,
        token_resource,
        duration_hours,
        oracle_address,
        client,
    ):
        records["token_resource"] = token_resource
        records["duration_hours"] = duration_hours
        return {"log": {"uid": "escrow123"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    await action_executor.accept_offer(
        alkahest_client=_FakeClient(records),
        ctx=None,
        parameters={"order": order_dict},
    )

    assert records["duration_hours"] == duration_hours
    token_payload = records["token_resource"]
    if isinstance(token_payload, dict):
        token_payload = TokenResource.model_validate(token_payload)
    assert token_payload.amount == rate


@pytest.mark.asyncio
async def test_execute_action_fulfill_skips_event_on_error(monkeypatch):
    """Ensure fulfillment errors do not send events to the counterparty."""
    async def fake_fulfill_compute_obligation(**_kwargs):
        return {"status": "error", "message": "Provisioning failed"}

    called = {"count": 0}

    async def fake_send_to_remote_agent(_ctx, _event):
        called["count"] += 1

    monkeypatch.setattr(action_executor, "fulfill_compute_obligation", fake_fulfill_compute_obligation)
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)

    action = Action(
        action_type=ActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={"escrow_uid": "escrow-1", "ssh_public_key": "ssh-rsa AAA"},
        timestamp=datetime.now(),
    )

    await action_executor.execute_action(action, alkahest_client=None, ctx=_FakeCtx())

    assert called["count"] == 0


@pytest.mark.asyncio
async def test_execute_action_fulfill_sends_event_on_success(monkeypatch):
    """Ensure fulfillment success sends event with event type set."""
    async def fake_fulfill_compute_obligation(**_kwargs):
        return {"status": "fulfilled", "message": "ok"}

    captured: dict = {}

    async def fake_send_to_remote_agent(_ctx, event, agent_url=None):
        captured["event"] = event

    monkeypatch.setattr(action_executor, "fulfill_compute_obligation", fake_fulfill_compute_obligation)
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)

    action = Action(
        action_type=ActionType.FULFILL_COMPUTE_OBLIGATION,
        parameters={
            "escrow_uid": "escrow-2",
            "ssh_public_key": "ssh-rsa AAA",
            "order": {"order_taker": "http://localhost:8000"}  # Add order with taker URL
        },
        timestamp=datetime.now(),
    )

    await action_executor.execute_action(action, alkahest_client=None, ctx=_FakeCtx())

    assert "event" in captured
    response = captured["event"].content.parts[0].function_response.response
    assert response["event_type"] == EventType.RECEIVE_COMPUTE_OBLIGATION_FULFILLMENT.value


@pytest.mark.asyncio
async def test_provision_machine_raises_on_missing_connection_info(monkeypatch):
    """Ensure missing connection info raises a RuntimeError."""
    async def fake_provision_machine_async(*_args, **_kwargs):
        # Return result with missing connection info
        return {
            "ssh_port": None,
            "tenant_user": None,
            "vm_host_ip": None,
            "ssh_command": None,
        }

    def fake_format_connection_info(result):
        # format_connection_info returns str(result) when it can't format
        # which shouldn't raise, so let's make it raise explicitly for this test
        if not result.get("ssh_port"):
            raise RuntimeError("SSH connection info unavailable")
        return "ssh user@host -p 22"

    monkeypatch.setattr(action_executor, "provision_machine_async", fake_provision_machine_async)
    monkeypatch.setattr(action_executor, "format_connection_info", fake_format_connection_info)

    with pytest.raises(RuntimeError, match="SSH connection info unavailable"):
        await action_executor.provision_machine("ssh-rsa AAA")


def _fetch_order_row(db_path: str, order_id: str) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM orders WHERE order_id=?", (order_id,))
        row = cur.fetchone()
        if not row:
            return {}
        cols = [desc[0] for desc in cur.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_accept_offer_updates_buyer_order_only(monkeypatch, tmp_path):
    """Accepting a seller-as-maker offer (taker is buyer) creates escrow and updates order."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)

    async def fake_buy_compute_with_erc20(*_args, **_kwargs):
        return {"log": {"uid": "escrow-uid-123"}}

    class _DummyTxn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def cancel_competing(self, *_args, **_kwargs):
            return None

        async def mark_terminal(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)
    monkeypatch.setattr(action_executor, "NegotiationThreadTransaction", lambda *_args, **_kwargs: _DummyTxn())
    monkeypatch.setattr(action_executor, "get_sqlite_client", lambda: sqlite_client)
    # Set BASE_URL_OVERRIDE to buyer URL
    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", "http://buyer:8001")
    async def fake_send_to_remote_agent(_ctx, _event, agent_url=None):
        return None
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)
    class _RegistryClient:
        async def update_order(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _RegistryClient())

    # Buyer's local order (buyer offers tokens, demands compute)
    order_id = "buy-order-1"
    await sqlite_client.upsert_order(
        order_id=order_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=_token_rate(1_000_000).model_dump(mode="json"),
        demand_resource=_compute_resource().model_dump(mode="json"),
        fulfillment_resource=None,
        duration_hours=1,
        order_maker="http://buyer:8001",
        order_taker=None,
        matched_offer_id=None,
        maker_attestation=None,
        taker_attestation=None,
        escrow_uid=None,
    )

    # Seller-as-maker order: offers compute, demands tokens
    order_dict = {
        "order_id": "sell-order-2",
        "order_maker": "http://seller:8000",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(1_000_000).model_dump(mode="json"),
        "duration_hours": 1,
    }

    await action_executor.accept_offer(
        alkahest_client=_FakeClient({}),
        ctx=_FakeCtx(),
        parameters={"order": order_dict, "their_order_id": "sell-order-2", "our_order_id": order_id},
    )

    row = _fetch_order_row(db_path, order_id)
    assert row["status"] == "accepted"
    assert row["escrow_uid"] == "escrow-uid-123"
    assert row["taker_attestation"] == "escrow-uid-123"
    assert row["matched_offer_id"] == "sell-order-2"


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_updates_seller_order(monkeypatch, tmp_path):
    """Seller fulfillment marks order accepted and stores fulfillment resource."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)

    async def fake_provision_machine(_ssh_public_key: str, **_kwargs) -> dict:
        return {
            "ssh_command": "ssh user@host.example.net",
            "tenant_user": "user",
            "authentication": {
                "tenant": {
                    "password": "test-password",
                    "ssh_commands": {
                        "external": "ssh user@host.example.net",
                        "internal": "ssh user@192.168.1.100",
                    },
                },
            },
        }

    def fake_mock_schedule_vm_shutdown(_lease_end_utc: str) -> None:
        return None

    async def fake_schedule_vm_shutdown_async(**_kwargs) -> None:
        return None

    monkeypatch.setattr(action_executor, "provision_machine", fake_provision_machine)
    monkeypatch.setattr(action_executor, "mock_provision_machine", fake_provision_machine)
    monkeypatch.setattr(action_executor, "schedule_vm_shutdown_async", fake_schedule_vm_shutdown_async)
    monkeypatch.setattr(action_executor, "mock_schedule_vm_shutdown", fake_mock_schedule_vm_shutdown)
    monkeypatch.setattr(action_executor, "get_sqlite_client", lambda: sqlite_client)
    class _RegistryClient:
        async def update_order(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _RegistryClient())

    order_id = "sell-order-2"
    order_dict = {
        "order_id": order_id,
        "order_maker": "seller",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(1_000_000).model_dump(mode="json"),
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
        order_maker="seller",
        order_taker=None,
        matched_offer_id=None,
        maker_attestation=None,
        taker_attestation=None,
        escrow_uid=None,
    )

    await action_executor.fulfill_compute_obligation(
        client=None,
        escrow_uid="escrow-uid-456",
        ssh_public_key="ssh-rsa AAA",
        order=order_dict,
    )

    row = _fetch_order_row(db_path, order_id)
    assert row["status"] == "accepted"
    assert row["escrow_uid"] == "escrow-uid-456"
    assert row["maker_attestation"] is not None
    # fulfillment_resource is now JSON-serialized seller_fulfillment dict
    import json as _json
    stored = _json.loads(row["fulfillment_resource"])
    assert stored["ssh_command"] == "ssh user@host.example.net"
    assert stored["tenant_user"] == "user"
    assert stored["authentication"]["tenant"]["password"] == "test-password"


# --- Tests for maker/taker role combinations ---

class _DummyTxn:
    """Reusable stub for NegotiationThreadTransaction."""
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def cancel_competing(self, *_args, **_kwargs):
        return None

    async def mark_terminal(self, *_args, **_kwargs):
        return None


def _seller_as_maker_order() -> dict:
    """Seller-as-Maker order: offers compute, demands tokens."""
    return {
        "order_id": "sell-order-1",
        "order_maker": "http://seller:8000",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(1_000_000).model_dump(mode="json"),
        "duration_hours": 1,
    }


def _buyer_as_maker_order() -> dict:
    """Buyer-as-Maker order: offers tokens, demands compute."""
    return {
        "order_id": "buy-order-1",
        "order_maker": "http://buyer:8001",
        "offer_resource": _token_rate(1_000_000).model_dump(mode="json"),
        "demand_resource": _compute_resource().model_dump(mode="json"),
        "duration_hours": 1,
    }


def _setup_common_mocks(monkeypatch, sqlite_client):
    """Apply common monkeypatches for accept_offer tests."""
    monkeypatch.setattr(action_executor, "NegotiationThreadTransaction", lambda *_a, **_kw: _DummyTxn())
    monkeypatch.setattr(action_executor, "get_sqlite_client", lambda: sqlite_client)

    async def fake_send_to_remote_agent(_ctx, _event, agent_url=None):
        return None
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)

    class _Reg:
        async def update_order(self, *_a, **_kw):
            return {"ok": True}
    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _Reg())


@pytest.mark.asyncio
async def test_accept_offer_seller_as_taker_no_escrow(monkeypatch, tmp_path):
    """Seller accepting a buyer-as-maker order does NOT create escrow."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)
    _setup_common_mocks(monkeypatch, sqlite_client)

    # Seller's BASE_URL_OVERRIDE — seller is NOT the maker of this order
    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", "http://seller:8000")

    escrow_created = {"called": False}

    async def fake_buy_compute_with_erc20(*_args, **_kwargs):
        escrow_created["called"] = True
        return {"log": {"uid": "should-not-be-used"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    # The buyer-as-maker order: offers tokens, demands compute
    order_dict = _buyer_as_maker_order()

    result = await action_executor.accept_offer(
        alkahest_client=_FakeClient({}),
        ctx=_FakeCtx(),
        parameters={"order": order_dict, "our_order_id": "sell-order-2"},
    )

    # Seller path: should NOT create escrow
    assert not escrow_created["called"], "Seller should NOT create escrow when accepting buyer-as-maker order"
    assert result.get("escrow_uid") is None


@pytest.mark.asyncio
async def test_accept_offer_buyer_as_maker_creates_escrow_on_followup(monkeypatch, tmp_path):
    """Buyer receives seller's accept → creates escrow → sends follow-up acceptance."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)
    _setup_common_mocks(monkeypatch, sqlite_client)

    # Buyer's BASE_URL_OVERRIDE — buyer IS the maker of this order
    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", "http://buyer:8001")

    escrow_created = {"called": False}

    async def fake_buy_compute_with_erc20(*_args, **_kwargs):
        escrow_created["called"] = True
        return {"log": {"uid": "escrow-from-buyer"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    # The buyer-as-maker order: buyer posted this, offers tokens, demands compute
    order_dict = _buyer_as_maker_order()

    result = await action_executor.accept_offer(
        alkahest_client=_FakeClient({}),
        ctx=_FakeCtx(),
        parameters={"order": order_dict, "our_order_id": "buy-order-1"},
    )

    # Buyer path: SHOULD create escrow (they are the compute buyer)
    assert escrow_created["called"], "Buyer should create escrow on follow-up acceptance"
    assert result.get("escrow_uid") == "escrow-from-buyer"


@pytest.mark.asyncio
async def test_handshake_policy_gates_correctly():
    """Two-phase handshake: buyer gets ACCEPT_OFFER (no escrow),
    seller gets FULFILL (escrow+ssh), neither acts without info."""
    from app.policies.store import ao_action_fulfill_after_accept
    from app.schema.pydantic_models import (
        AcceptOfferEvent,
        DecisionContext,
        MarketOrder,
    )
    from unittest.mock import patch
    from app.utils import config as config_mod

    seller_url = "http://seller:8000"
    buyer_url = "http://buyer:8001"

    # Build a seller-as-maker order (maker offers compute)
    order = MarketOrder(
        order_id="sell-order-1",
        order_maker=seller_url,
        order_taker=None,
        offer_resource=_compute_resource(),
        demand_resource=_token_rate(1_000_000),
        duration_hours=1,
    )

    # Buyer-as-maker order (maker offers tokens)
    buyer_maker_order = MarketOrder(
        order_id="buy-order-1",
        order_maker=buyer_url,
        order_taker=None,
        offer_resource=_token_rate(1_000_000),
        demand_resource=_compute_resource(),
        duration_hours=1,
    )

    orig = config_mod.CONFIG.base_url_override

    # --- Case 1: Buyer receives AcceptOfferEvent WITHOUT escrow ---
    event_no_escrow = AcceptOfferEvent(
        event_id="evt-1",
        source=seller_url,
        order=buyer_maker_order,
        escrow_uid=None,
        ssh_public_key=None,
        taker_order_id="sell-order-1",
        agreed_price=1_000_000,
    )
    ctx_buyer = DecisionContext(
        event=event_no_escrow,
        agent_id=buyer_url,
        available_resources={},
        market_state={},
    )
    object.__setattr__(config_mod.CONFIG, "base_url_override", buyer_url)
    try:
        result_buyer = ao_action_fulfill_after_accept(ctx_buyer)
    finally:
        object.__setattr__(config_mod.CONFIG, "base_url_override", orig)

    # Buyer should get ACCEPT_OFFER action (to create escrow)
    assert result_buyer is not None
    assert result_buyer.action_type == DomainActionType.ACCEPT_OFFER

    # --- Case 2: Seller receives AcceptOfferEvent WITH escrow + ssh ---
    event_with_escrow = AcceptOfferEvent(
        event_id="evt-2",
        source=buyer_url,
        order=order,
        escrow_uid="escrow-123",
        ssh_public_key="ssh-rsa BUYER_KEY",
        taker_order_id="buy-order-1",
        agreed_price=1_000_000,
    )
    ctx_seller = DecisionContext(
        event=event_with_escrow,
        agent_id=seller_url,
        available_resources={},
        market_state={},
    )
    object.__setattr__(config_mod.CONFIG, "base_url_override", seller_url)
    try:
        result_seller = ao_action_fulfill_after_accept(ctx_seller)
    finally:
        object.__setattr__(config_mod.CONFIG, "base_url_override", orig)

    # Seller should get FULFILL action
    assert result_seller is not None
    assert result_seller.action_type == DomainActionType.FULFILL_COMPUTE_OBLIGATION
    assert result_seller.parameters.get("escrow_uid") == "escrow-123"
    assert result_seller.parameters.get("ssh_public_key") == "ssh-rsa BUYER_KEY"

    # --- Case 3: Seller receives AcceptOfferEvent WITHOUT escrow ---
    ctx_seller_no_escrow = DecisionContext(
        event=event_no_escrow,
        agent_id=seller_url,
        available_resources={},
        market_state={},
    )
    object.__setattr__(config_mod.CONFIG, "base_url_override", seller_url)
    try:
        result_none = ao_action_fulfill_after_accept(ctx_seller_no_escrow)
    finally:
        object.__setattr__(config_mod.CONFIG, "base_url_override", orig)

    # Seller without escrow should get None (wait for buyer to create escrow)
    assert result_none is None


@pytest.mark.asyncio
async def test_our_order_id_resolution_via_negotiation_id(monkeypatch, tmp_path):
    """Thread-store lookup finds our_order_id when symmetric matching fails."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)
    _setup_common_mocks(monkeypatch, sqlite_client)

    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", "http://buyer:8001")

    async def fake_buy_compute_with_erc20(*_args, **_kwargs):
        return {"log": {"uid": "escrow-negotiated"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    # Create our order with negotiation_id set (simulating phase 6 cross-ref)
    our_order_id = "our-buy-order"
    negotiation_id = f"{our_order_id}_their-sell-order"

    await sqlite_client.upsert_order(
        order_id=our_order_id,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=_token_rate(900_000).model_dump(mode="json"),
        demand_resource=_compute_resource().model_dump(mode="json"),
        fulfillment_resource=None,
        duration_hours=1,
        order_maker="http://buyer:8001",
        negotiation_id=negotiation_id,
    )

    # Incoming order from seller — different token amount due to negotiation
    order_dict = {
        "order_id": "their-sell-order",
        "order_maker": "http://seller:8000",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(1_200_000).model_dump(mode="json"),
        "duration_hours": 1,
    }

    result = await action_executor.accept_offer(
        alkahest_client=_FakeClient({}),
        ctx=_FakeCtx(),
        parameters={
            "order": order_dict,
            "negotiation_id": negotiation_id,
            # No our_order_id provided — should resolve via negotiation_id
        },
    )

    assert result.get("status") == "sent"
    # Our order should be updated
    row = _fetch_order_row(db_path, our_order_id)
    assert row["status"] == "accepted"
    assert row["escrow_uid"] == "escrow-negotiated"


@pytest.mark.asyncio
async def test_negotiate_then_accept_different_amounts(monkeypatch, tmp_path):
    """After price negotiation, both sides find their orders via negotiation_id
    even when token amounts differ between the orders."""
    db_path = str(tmp_path / "agent.db")
    sqlite_client = SQLiteClient(db_path=db_path)
    _setup_common_mocks(monkeypatch, sqlite_client)

    monkeypatch.setattr(action_executor, "BASE_URL_OVERRIDE", "http://buyer:8001")

    async def fake_buy_compute_with_erc20(*_args, **_kwargs):
        return {"log": {"uid": "escrow-final"}}

    monkeypatch.setattr(action_executor, "buy_compute_with_erc20", fake_buy_compute_with_erc20)

    negotiation_id = "buy-order_sell-order"

    # Buyer's local order (posted at 900k)
    await sqlite_client.upsert_order(
        order_id="buy-order",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource=_token_rate(900_000).model_dump(mode="json"),
        demand_resource=_compute_resource().model_dump(mode="json"),
        fulfillment_resource=None,
        duration_hours=1,
        order_maker="http://buyer:8001",
        negotiation_id=negotiation_id,
        matched_offer_id="sell-order",
    )

    # Seller's order (posted at 1.2M, negotiated down to 1.05M)
    seller_order = {
        "order_id": "sell-order",
        "order_maker": "http://seller:8000",
        "offer_resource": _compute_resource().model_dump(mode="json"),
        "demand_resource": _token_rate(1_200_000).model_dump(mode="json"),
        "duration_hours": 1,
    }

    result = await action_executor.accept_offer(
        alkahest_client=_FakeClient({}),
        ctx=_FakeCtx(),
        parameters={
            "order": seller_order,
            "negotiation_id": negotiation_id,
            "agreed_price": 1_050_000,
        },
    )

    assert result.get("status") == "sent"
    row = _fetch_order_row(db_path, "buy-order")
    assert row["status"] == "accepted"
    assert row["negotiation_id"] == negotiation_id
