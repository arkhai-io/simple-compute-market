"""Unit tests for action executor helpers."""

import json
import sqlite3
from datetime import datetime

import pytest

from app.schema.pydantic_models import (
    Action,
    ActionType,
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
        cur.execute(
            """
            SELECT status, escrow_uid, taker_attestation, matched_offer_id, maker_attestation, fulfillment_resource
            FROM orders
            WHERE order_id=?
            """,
            (order_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}
        return {
            "status": row[0],
            "escrow_uid": row[1],
            "taker_attestation": row[2],
            "matched_offer_id": row[3],
            "maker_attestation": row[4],
            "fulfillment_resource": row[5],
        }
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_accept_offer_updates_buyer_order_only(monkeypatch, tmp_path):
    """Accepting an offer updates the buyer's local order to accepted."""
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
    async def fake_send_to_remote_agent(_ctx, _event, agent_url=None):
        return None
    monkeypatch.setattr(action_executor, "send_to_remote_agent", fake_send_to_remote_agent)
    class _RegistryClient:
        async def update_order(self, *_args, **_kwargs):
            return {"ok": True}

    monkeypatch.setattr(action_executor, "get_registry_client", lambda: _RegistryClient())

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
        order_maker="buyer",
        order_taker=None,
        matched_offer_id=None,
        maker_attestation=None,
        taker_attestation=None,
        escrow_uid=None,
    )

    order_dict = {
        "order_id": order_id,
        "order_maker": "buyer",
        "offer_resource": _token_rate(1_000_000).model_dump(mode="json"),
        "demand_resource": _compute_resource().model_dump(mode="json"),
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

    async def fake_provision_machine(_ssh_public_key: str) -> dict:
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
