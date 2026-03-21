from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent.app.schema.pydantic_models import (
    Action,
    ActionType,
    ComputeResource,
    ERC20TokenMetadata,
    GPUModel,
    Region,
    TokenResource,
)
from core.agent.app.utils import action_executor as ae


ALICE_URL = "http://alice.example:8000"
BOB_URL = "http://bob.example:8001"


def _compute() -> ComputeResource:
    return ComputeResource(
        gpu_model=GPUModel.H200,
        quantity=1,
        sla=99.0,
        region=Region.CALIFORNIA_US,
    )


def _tokens(amount: int = 1_000_000) -> TokenResource:
    return TokenResource(
        token=ERC20TokenMetadata(
            symbol="USDT",
            contract_address="0xdac17f958d2ee523a2206206994597c13d831ec7",
            decimals=6,
        ),
        amount=amount,
    )


def test_registry_safe_order_strips_local_compute_fields():
    order_dict = {
        "order_id": "seller-order-1",
        "order_maker": BOB_URL,
        "offer_resource": {
            "resource_id": "compute-ww1-001",
            "gpu_model": "RTX 5080",
            "quantity": 1,
            "sla": 90.0,
            "region": "California, US",
            "vm_host": "ww1",
        },
        "demand_resource": _tokens(17).model_dump(mode="json"),
    }

    registry_order = ae._registry_safe_order(order_dict)

    assert "resource_id" not in registry_order["offer_resource"]
    assert "vm_host" not in registry_order["offer_resource"]
    assert registry_order["offer_resource"]["gpu_model"] == "RTX 5080"
    assert registry_order["demand_resource"]["amount"] == 17


@pytest.mark.asyncio
async def test_accept_as_buyer_stamps_counterparty_for_buyer_maker(monkeypatch):
    order_dict = {
        "order_id": "alice-order-1",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens().model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
        "oracle_address": "0xAliceWallet",
    }

    sqlite_client = SimpleNamespace(update_order=AsyncMock())
    registry_client = SimpleNamespace(update_order=AsyncMock(return_value={"status": "accepted"}))

    monkeypatch.setattr(ae, "BASE_URL_OVERRIDE", ALICE_URL)
    monkeypatch.setattr(ae, "SSH_PUBLIC_KEY", "ssh-rsa AAA")
    monkeypatch.setattr(
        ae,
        "CONFIG",
        replace(
            ae.CONFIG,
            agent_wallet_address="0xAliceWallet",
            enable_registry_discovery=True,
        ),
    )
    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(ae, "get_registry_client", lambda: registry_client)
    monkeypatch.setattr(
        ae,
        "buy_compute_with_erc20",
        AsyncMock(return_value={"log": {"uid": "escrow-123"}}),
    )
    monkeypatch.setattr(
        ae,
        "send_to_remote_agent",
        AsyncMock(return_value=SimpleNamespace(content=None)),
    )

    ctx = SimpleNamespace(invocation_id="inv-1", branch="main")
    result = await ae._accept_as_buyer(
        alkahest_client=object(),
        ctx=ctx,
        parameters={
            "counterparty_url": BOB_URL,
            "matched_order_id": "bob-order-1",
        },
        order_dict=order_dict,
        our_order_id="alice-order-1",
        their_order_id="bob-order-1",
    )

    sqlite_client.update_order.assert_awaited_once()
    assert sqlite_client.update_order.await_args.kwargs["order_taker"] == BOB_URL

    registry_client.update_order.assert_awaited_once_with(
        "alice-order-1",
        {
            "status": "accepted",
            "order_taker": BOB_URL,
            "taker_attestation": "escrow-123",
        },
    )
    assert result["offer"]["order_taker"] == BOB_URL


@pytest.mark.asyncio
async def test_accept_as_buyer_prefers_order_oracle_address(monkeypatch):
    order_dict = {
        "order_id": "alice-order-1",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens().model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
        "oracle_address": "0xOrderOracle",
    }

    sqlite_client = SimpleNamespace(update_order=AsyncMock())
    registry_client = SimpleNamespace(update_order=AsyncMock(return_value={"status": "accepted"}))
    buy_compute_with_erc20 = AsyncMock(return_value={"log": {"uid": "escrow-123"}})

    monkeypatch.setattr(ae, "BASE_URL_OVERRIDE", ALICE_URL)
    monkeypatch.setattr(ae, "SSH_PUBLIC_KEY", "ssh-rsa AAA")
    monkeypatch.setattr(
        ae,
        "CONFIG",
        replace(
            ae.CONFIG,
            agent_wallet_address="0xLocalOracle",
            enable_registry_discovery=True,
        ),
    )
    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(ae, "get_registry_client", lambda: registry_client)
    monkeypatch.setattr(ae, "buy_compute_with_erc20", buy_compute_with_erc20)
    monkeypatch.setattr(
        ae,
        "send_to_remote_agent",
        AsyncMock(return_value=SimpleNamespace(content=None)),
    )

    await ae._accept_as_buyer(
        alkahest_client=object(),
        ctx=SimpleNamespace(invocation_id="inv-1", branch="main"),
        parameters={
            "counterparty_url": BOB_URL,
            "matched_order_id": "bob-order-1",
        },
        order_dict=order_dict,
        our_order_id="alice-order-1",
        their_order_id="bob-order-1",
    )

    assert buy_compute_with_erc20.await_args.kwargs["oracle_address"] == "0xOrderOracle"


@pytest.mark.asyncio
async def test_buy_compute_with_erc20_uses_approve_and_create_with_future_expiration(
    monkeypatch,
):
    approve_and_create = AsyncMock(
        return_value=("0xapprove", {"log": {"uid": "escrow-123"}})
    )
    approve = AsyncMock(side_effect=AssertionError("unexpected direct approve call"))
    client = SimpleNamespace(
        erc20=SimpleNamespace(
            util=SimpleNamespace(approve=approve),
            escrow=SimpleNamespace(
                non_tierable=SimpleNamespace(
                    approve_and_create=approve_and_create,
                    permit_and_create=AsyncMock(
                        side_effect=AssertionError("unexpected permit call")
                    ),
                    create=AsyncMock(side_effect=AssertionError("unexpected create call")),
                )
            ),
        )
    )

    monkeypatch.setattr(ae, "get_trusted_oracle_arbiter", lambda: "0xTrustedOracleArbiter")
    monkeypatch.setattr(ae.time, "time", lambda: 1_700_000_000)

    compute = _compute()
    payment = _tokens(1_000_003)

    receipt = await ae.buy_compute_with_erc20(
        compute_resource=compute,
        token_resource=payment,
        duration_hours=1,
        oracle_address="0x1111111111111111111111111111111111111111",
        client=client,
    )

    assert receipt == {"approval_tx_hash": "0xapprove", "log": {"uid": "escrow-123"}}
    approve.assert_not_awaited()
    approve_and_create.assert_awaited_once()
    price_data, arbiter_data, expiration = approve_and_create.await_args.args
    assert price_data == {
        "address": payment.token.contract_address,
        "value": payment.amount,
    }
    assert arbiter_data["arbiter"] == "0xTrustedOracleArbiter"
    assert expiration == 1_700_003_600


@pytest.mark.asyncio
async def test_trust_action_closes_local_order_by_escrow(monkeypatch):
    sqlite_client = SimpleNamespace(
        update_order_by_escrow_uid=AsyncMock(),
        get_order_id_by_escrow_uid=AsyncMock(return_value="alice-order-1"),
        store_credential=AsyncMock(),
    )
    close_for_escrow = AsyncMock(return_value={"status": "closed", "order_id": "alice-order-1"})

    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(
        ae,
        "arbitrate_compute_fulfillment",
        AsyncMock(
            return_value={
                "status": "trusted",
                "message": "Arbitration completed",
                "fulfillment_uid": "ful-123",
                "escrow_uid": "escrow-123",
                "oracle_address": "0xAliceWallet",
                "decisions": [True],
            }
        ),
    )
    monkeypatch.setattr(ae, "_close_local_order_for_escrow_uid", close_for_escrow)

    outcome = await ae.execute_action(
        action=Action(
            action_type=ActionType.TRUST_COMPUTE_OBLIGATION_FULFILLMENT,
            parameters={
                "escrow_uid": "escrow-123",
                "fulfillment_uid": "ful-123",
                "connection_details": '{"ssh_command":"ssh tenant@127.0.0.1"}',
                "tenant_credentials": {"password": "secret"},
            },
        ),
        alkahest_client=None,
        ctx=None,
    )

    close_for_escrow.assert_awaited_once_with("escrow-123")
    assert outcome["result"]["close_order_result"]["status"] == "closed"


@pytest.mark.asyncio
async def test_collect_escrow_closes_local_order_by_escrow(monkeypatch):
    close_for_escrow = AsyncMock(return_value={"status": "closed", "order_id": "bob-order-1"})

    monkeypatch.setattr(
        ae,
        "collect_escrow",
        AsyncMock(return_value="escrow-collection-123"),
    )
    monkeypatch.setattr(ae, "_close_local_order_for_escrow_uid", close_for_escrow)

    outcome = await ae.execute_action(
        action=Action(
            action_type=ActionType.COLLECT_ESCROW,
            parameters={
                "escrow_uid": "escrow-123",
                "fulfillment_uid": "ful-123",
            },
        ),
        alkahest_client=None,
        ctx=None,
    )

    close_for_escrow.assert_awaited_once_with("escrow-123")
    assert outcome["result"]["close_order_result"]["status"] == "closed"


@pytest.mark.asyncio
async def test_arbitrate_compute_fulfillment_prefers_direct_oracle_path(monkeypatch):
    oracle = SimpleNamespace(
        get_escrow_and_demand=AsyncMock(
            return_value=(object(), SimpleNamespace(data=b"direct-demand"))
        ),
        arbitrate=AsyncMock(return_value="0xarb"),
        arbitrate_many=AsyncMock(side_effect=AssertionError("unexpected log scan")),
    )
    client = SimpleNamespace(oracle=oracle)
    oracle_attestation = MagicMock(return_value="fulfillment-attestation")
    wait_for_receipt = AsyncMock()

    monkeypatch.setattr(ae, "OracleAttestation", oracle_attestation)
    monkeypatch.setattr(ae, "_wait_for_transaction_receipt", wait_for_receipt)

    result = await ae.arbitrate_compute_fulfillment(
        client=client,
        fulfillment_uid="ful-123",
        oracle_address="0xAliceWallet",
        escrow_uid="escrow-123",
    )

    oracle_attestation.assert_called_once()
    oracle.get_escrow_and_demand.assert_awaited_once_with("fulfillment-attestation")
    oracle.arbitrate.assert_awaited_once_with("ful-123", b"direct-demand", True)
    wait_for_receipt.assert_awaited_once_with("0xarb")
    oracle.arbitrate_many.assert_not_called()

    assert result["status"] == "trusted"
    assert result["message"] == "Arbitration completed"
    assert result["decisions"] == [True]
    assert result["transaction_hash"] == "0xarb"


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_updates_local_registry_order(monkeypatch):
    sqlite_client = SimpleNamespace(
        update_order=AsyncMock(),
        reserve_available_compute_vm=AsyncMock(
            return_value={"resource_id": "gpu-1", "vm_host": "host-a"}
        ),
        apply_resource_set_transition=AsyncMock(),
    )
    registry_client = SimpleNamespace(
        update_order=AsyncMock(return_value={"status": "accepted"})
    )

    monkeypatch.setattr(ae, "BASE_URL_OVERRIDE", BOB_URL)
    monkeypatch.setattr(
        ae,
        "CONFIG",
        replace(ae.CONFIG, enable_registry_discovery=True),
    )
    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(ae, "get_registry_client", lambda: registry_client)
    monkeypatch.setattr(
        ae,
        "_do_provision",
        AsyncMock(return_value={"host": "203.0.113.8", "port": 22}),
    )
    monkeypatch.setattr(ae, "_do_shutdown", AsyncMock(return_value={"status": "scheduled"}))

    buyer_order = {
        "order_id": "alice-order-1",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens(18).model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
        "oracle_address": "0xAliceWallet",
    }

    result = await ae.fulfill_compute_obligation(
        client=None,
        escrow_uid="escrow-123",
        ssh_public_key="ssh-rsa AAA",
        order=buyer_order,
        local_order_id="bob-order-1",
    )

    registry_client.update_order.assert_awaited_once_with(
        "bob-order-1",
        {"maker_attestation": result["fulfillment_uid"]},
    )
    assert all(
        call.kwargs["order_id"] == "bob-order-1"
        for call in sqlite_client.update_order.await_args_list
    )


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_passes_buyer_agent_id_to_provisioning(monkeypatch):
    sqlite_client = SimpleNamespace(
        update_order=AsyncMock(),
        reserve_available_compute_vm=AsyncMock(
            return_value={"resource_id": "gpu-1", "vm_host": "host-a"}
        ),
        apply_resource_set_transition=AsyncMock(),
    )

    do_provision = AsyncMock(return_value={"host": "203.0.113.8", "port": 22})

    monkeypatch.setattr(ae, "BASE_URL_OVERRIDE", BOB_URL)
    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(ae, "_do_provision", do_provision)
    monkeypatch.setattr(ae, "_do_shutdown", AsyncMock(return_value={"status": "scheduled"}))

    buyer_order = {
        "order_id": "alice-order-1",
        "agent_id": "eip155:84532:0x8004aa63c570c570ebf15376c0db199918bfe9fb:202",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens(18).model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
        "oracle_address": "0xAliceWallet",
    }

    await ae.fulfill_compute_obligation(
        client=None,
        escrow_uid="escrow-123",
        ssh_public_key="ssh-rsa AAA",
        order=buyer_order,
        local_order_id="bob-order-1",
    )

    assert do_provision.await_args.kwargs["buyer_agent_id"] == buyer_order["agent_id"]


@pytest.mark.asyncio
async def test_fulfill_compute_obligation_resolves_buyer_agent_id_from_registry(monkeypatch):
    sqlite_client = SimpleNamespace(
        update_order=AsyncMock(),
        reserve_available_compute_vm=AsyncMock(
            return_value={"resource_id": "gpu-1", "vm_host": "host-a"}
        ),
        apply_resource_set_transition=AsyncMock(),
    )
    registry_client = SimpleNamespace(
        get_order=AsyncMock(
            return_value={
                "order_id": "alice-order-1",
                "agent_id": "eip155:84532:0x8004aa63c570c570ebf15376c0db199918bfe9fb:202",
            }
        ),
        update_order=AsyncMock(return_value={"status": "accepted"}),
    )
    do_provision = AsyncMock(return_value={"host": "203.0.113.8", "port": 22})

    monkeypatch.setattr(ae, "BASE_URL_OVERRIDE", BOB_URL)
    monkeypatch.setattr(
        ae,
        "CONFIG",
        replace(ae.CONFIG, enable_registry_discovery=True),
    )
    monkeypatch.setattr(ae, "get_sqlite_client", lambda: sqlite_client)
    monkeypatch.setattr(ae, "get_registry_client", lambda: registry_client)
    monkeypatch.setattr(ae, "_do_provision", do_provision)
    monkeypatch.setattr(ae, "_do_shutdown", AsyncMock(return_value={"status": "scheduled"}))

    buyer_order = {
        "order_id": "alice-order-1",
        "order_maker": ALICE_URL,
        "offer_resource": _tokens(18).model_dump(mode="json"),
        "demand_resource": _compute().model_dump(mode="json"),
        "duration_hours": 1,
        "oracle_address": "0xAliceWallet",
    }

    await ae.fulfill_compute_obligation(
        client=None,
        escrow_uid="escrow-123",
        ssh_public_key="ssh-rsa AAA",
        order=buyer_order,
        local_order_id="bob-order-1",
    )

    registry_client.get_order.assert_awaited_once_with("alice-order-1")
    assert (
        do_provision.await_args.kwargs["buyer_agent_id"]
        == "eip155:84532:0x8004aa63c570c570ebf15376c0db199918bfe9fb:202"
    )
