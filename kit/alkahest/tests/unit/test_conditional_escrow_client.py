from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from market_alkahest import AlkahestConditionalEscrowClient, alkahest, claims
from market_alkahest.claims import AllArbiterCodec, TrustedOracleArbiterCodec
from market_settlement_runtime import (
    SettlementEffectReadbackUnknown,
    SettlementManualRequired,
)
from market_settlement_runtime.ports import ConditionalEscrowClient
from web3 import Web3

TRUSTED = "0x" + "11" * 20
RECIPIENT = "0x" + "22" * 20
ALL = "0x" + "33" * 20
ORACLE = "0x" + "44" * 20
ESCROW = "0x" + "55" * 20
ESCROW_UID = "0x" + "66" * 32
FULFILLMENT_UID = "0x" + "77" * 32


class FakeOracle:
    def __init__(self) -> None:
        self.requested: list[tuple[Any, ...]] = []
        self.event: Any = None
        self.status_error: Exception | None = None

    async def request_arbitration(self, fulfillment, oracle, demand):
        self.requested.append((fulfillment, oracle, demand))
        return {"transaction_hash": "0xrequest"}

    async def wait_for_arbitration(self, fulfillment, demand, oracle, from_block):
        if self.status_error is not None:
            raise self.status_error
        if self.event is None:
            await asyncio.sleep(60)
        return self.event


class FakeClient:
    def __init__(self) -> None:
        self.oracle = FakeOracle()


def _obligation(*, arbiter: str | None = TRUSTED, demand: bytes | None = None):
    obligation_data: dict[str, Any] = {"token": "0x" + "99" * 20, "amount": 100}
    if arbiter is not None:
        obligation_data["arbiter"] = arbiter
        obligation_data["demand"] = "0x" + (demand or _trusted_demand()).hex()
    return {
        "payer": "buyer",
        "claimant": "seller",
        "expiration_unix": 2_000_000_000,
        "mechanism": "alkahest.v1",
        "params": {
            "chain_name": "test",
            "escrow_contract": ESCROW,
            "obligation_data": obligation_data,
        },
    }


def _trusted_demand() -> bytes:
    return TrustedOracleArbiterCodec().encode_demand_data(
        {"oracle": ORACLE, "data": b"evidence"}
    )


def _client(client: FakeClient, *, clock=lambda: 1_900_000_000):
    return AlkahestConditionalEscrowClient(
        get_client=lambda chain: client,
        default_chain="test",
        arbitration_probe_timeout=0.001,
        clock=clock,
    )


def _install_arbiters(monkeypatch) -> None:
    kinds = {
        TRUSTED.lower(): "trusted_oracle_arbiter",
        RECIPIENT.lower(): "recipient_arbiter",
        ALL.lower(): "all_arbiter",
    }

    def resolve(chain, address, *, config_path=None):
        kind = kinds.get(address.lower())
        if kind is None:
            raise ValueError(f"unknown arbiter {address}")
        return SimpleNamespace(kind=kind)

    monkeypatch.setattr(alkahest, "get_arbiter_codec_for", resolve)


def test_adapter_satisfies_public_port() -> None:
    adapter = _client(FakeClient())
    assert isinstance(adapter, ConditionalEscrowClient)


@pytest.mark.asyncio
async def test_trusted_oracle_requests_once_then_polls_with_stable_identity(
    monkeypatch,
) -> None:
    _install_arbiters(monkeypatch)
    provider = FakeClient()
    adapter = _client(provider)
    operation_ref = "arkhai:settlement:obligation:check"

    first = await adapter.check(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref=operation_ref,
        mechanism_state={},
    )
    second = await adapter.check(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref=operation_ref,
        mechanism_state=first.mechanism_state,
    )

    assert first.decision == second.decision == "pending"
    assert provider.oracle.requested == [(FULFILLMENT_UID, ORACLE, b"evidence")]
    assert first.receipt == {"operation_ref": operation_ref, "receipt": "0xrequest"}
    assert second.receipt == {"operation_ref": operation_ref}
    assert second.mechanism_state["alkahest"]["last_operation_ref"] == operation_ref


@pytest.mark.asyncio
async def test_trusted_oracle_true_is_ready_and_false_is_pending(monkeypatch) -> None:
    _install_arbiters(monkeypatch)
    provider = FakeClient()
    adapter = _client(provider)
    provider.oracle.event = SimpleNamespace(decision=True)

    ready = await adapter.check(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="check-ready",
        mechanism_state={},
    )
    provider.oracle.event = SimpleNamespace(decision=False)
    pending = await adapter.check(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="check-pending",
        mechanism_state={},
    )

    assert ready.decision == "ready"
    assert pending.decision == "pending"


@pytest.mark.asyncio
async def test_recursive_all_arbiter_preserves_child_behavior(monkeypatch) -> None:
    _install_arbiters(monkeypatch)
    provider = FakeClient()
    provider.oracle.event = SimpleNamespace(decision=True)
    inner = AllArbiterCodec().encode_demand_data(
        {
            "arbiters": [RECIPIENT, TRUSTED],
            "demands": [b"", _trusted_demand()],
        }
    )
    outer = AllArbiterCodec().encode_demand_data(
        {"arbiters": [ALL], "demands": [inner]}
    )

    outcome = await _client(provider).check(
        _obligation(arbiter=ALL, demand=outer),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="check-all",
        mechanism_state={},
    )

    assert outcome.decision == "ready"
    assert len(provider.oracle.requested) == 1


@pytest.mark.asyncio
async def test_unsupported_arbiter_normalizes_to_manual(monkeypatch) -> None:
    _install_arbiters(monkeypatch)
    outcome = await _client(FakeClient()).check(
        _obligation(arbiter="0x" + "99" * 20),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="check-manual",
        mechanism_state={},
    )

    assert outcome.decision == "manual_required"
    assert "unknown arbiter" in (outcome.last_error or "")


@pytest.mark.asyncio
async def test_status_transport_error_is_pending_with_durable_request_marker(
    monkeypatch,
) -> None:
    _install_arbiters(monkeypatch)
    provider = FakeClient()
    provider.oracle.status_error = ConnectionError("rpc unavailable")
    operation_ref = "check-error"

    outcome = await _client(provider).check(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref=operation_ref,
        mechanism_state={},
    )

    assert outcome.decision == "pending"
    assert outcome.last_error == "alkahest arbitration status failed: rpc unavailable"
    assert outcome.mechanism_state["alkahest"]["arbitration_requests"]


@pytest.mark.asyncio
async def test_authoritative_status_reads_pre_materialized_escrow(monkeypatch) -> None:
    seen: list[str] = []

    async def read(client, uid, **kwargs):
        seen.append(uid)
        return SimpleNamespace(kind="erc20_default"), {
            "attestation": SimpleNamespace(
                uid=uid,
                revocation_time=0,
                expiration_time=2_000_000_000,
            )
        }

    monkeypatch.setattr(alkahest, "get_escrow_obligation_with_codec", read)
    outcome = await _client(FakeClient()).get_status(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        operation_ref="status-op",
        mechanism_state={"adopted": True},
    )

    assert outcome.status == "ready"
    assert outcome.mechanism_ref == outcome.condition_anchor == ESCROW_UID
    assert outcome.mechanism_state["adopted"] is True
    assert outcome.receipt["operation_ref"] == "status-op"
    assert seen == [ESCROW_UID]


@pytest.mark.asyncio
async def test_authoritative_status_normalizes_expired_and_ambiguous_revocation(
    monkeypatch,
) -> None:
    attestation = SimpleNamespace(
        uid=ESCROW_UID,
        revocation_time=0,
        expiration_time=100,
    )

    async def read(client, uid, **kwargs):
        return SimpleNamespace(kind="erc20_default"), {"attestation": attestation}

    monkeypatch.setattr(alkahest, "get_escrow_obligation_with_codec", read)
    adapter = _client(FakeClient(), clock=lambda: 200)
    expired = await adapter.get_status(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        operation_ref="status-expired",
        mechanism_state={},
    )
    attestation.revocation_time = 150
    manual = await adapter.get_status(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        operation_ref="status-revoked",
        mechanism_state={},
    )

    assert expired.status == "expired"
    assert manual.status == "manual_required"
    assert "cannot distinguish" in (manual.last_error or "")


@pytest.mark.asyncio
async def test_materialize_collect_and_reclaim_keep_codec_calls_and_operation_refs(
    monkeypatch,
) -> None:
    calls: list[tuple[Any, ...]] = []

    class Codec:
        kind = "erc20_default"

        async def create_obligation(self, client, data, expiration):
            calls.append(("materialize", data, expiration))
            return ESCROW_UID

    monkeypatch.setattr(alkahest, "get_escrow_codec_for", lambda *a, **kw: Codec())

    async def collect(client, uid, fulfillment, **kwargs):
        calls.append(("collect", uid, fulfillment))
        return Codec(), {"transaction_hash": "0xcollect"}

    async def reclaim(client, uid, **kwargs):
        calls.append(("reclaim", uid))
        return Codec(), {"transaction_hash": "0xreclaim"}

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)
    monkeypatch.setattr(alkahest, "reclaim_expired_escrow_with_codec", reclaim)
    adapter = _client(FakeClient())

    materialized = await adapter.materialize(
        _obligation(), operation_ref="materialize-op"
    )
    collected = await adapter.collect(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="collect-op",
        mechanism_state=materialized.mechanism_state,
    )
    reclaimed = await adapter.reclaim_expired(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        operation_ref="reclaim-op",
        mechanism_state=materialized.mechanism_state,
    )

    assert materialized.status == "ready"
    assert materialized.mechanism_ref == ESCROW_UID
    assert collected.receipt == {
        "operation_ref": "collect-op",
        "escrow_kind": "erc20_default",
        "receipt": "0xcollect",
    }
    assert reclaimed.receipt["operation_ref"] == "reclaim-op"
    assert calls == [
        ("materialize", _obligation()["params"]["obligation_data"], 2_000_000_000),
        ("collect", ESCROW_UID, FULFILLMENT_UID),
        ("reclaim", ESCROW_UID),
    ]


@pytest.mark.asyncio
async def test_provider_effect_error_is_left_for_shared_retry_policy(
    monkeypatch,
) -> None:
    async def collect(client, uid, fulfillment, **kwargs):
        raise ConnectionError("provider acknowledgement unknown")

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)

    with pytest.raises(ConnectionError, match="acknowledgement unknown"):
        await _client(FakeClient()).collect(
            _obligation(),
            mechanism_ref=ESCROW_UID,
            fulfillment_ref=FULFILLMENT_UID,
            operation_ref="collect-error",
            mechanism_state={},
        )


def _collection_chain_result(*, token=None, recipient=None, amount=100, status=1):
    token = token or _obligation()["params"]["obligation_data"]["token"]
    recipient = recipient or RECIPIENT
    selector = Web3.keccak(text="collect(bytes32,bytes32)")[:4].hex()
    transfer = "0x" + Web3.keccak(text="Transfer(address,address,uint256)").hex()
    escrow_contract = _obligation()["params"]["escrow_contract"]
    return (
        {
            "status": status,
            "transactionHash": "0xcollect",
            "logs": [
                {
                    "address": token,
                    "topics": [
                        transfer,
                        "0x" + "00" * 12 + escrow_contract[2:],
                        "0x" + "00" * 12 + recipient[2:],
                    ],
                    "data": hex(amount),
                }
            ],
        },
        {
            "to": escrow_contract,
            "input": "0x" + selector + ESCROW_UID[2:] + FULFILLMENT_UID[2:],
        },
    )


@pytest.mark.asyncio
async def test_exact_collection_receipt_is_required_when_configured(monkeypatch) -> None:
    async def collect(*_args, **_kwargs):
        return SimpleNamespace(kind="erc20_default"), {"transaction_hash": "0xcollect"}

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)
    reads = []

    async def read(chain, transaction_hash):
        reads.append((chain, transaction_hash))
        return _collection_chain_result()

    adapter = AlkahestConditionalEscrowClient(
        get_client=lambda _chain: FakeClient(),
        default_chain="test",
        collection_receipt_reader=read,
        collection_recipient=RECIPIENT,
    )
    result = await adapter.collect(
        _obligation(),
        mechanism_ref=ESCROW_UID,
        fulfillment_ref=FULFILLMENT_UID,
        operation_ref="collect-exact",
        mechanism_state={},
    )

    assert result.receipt["receipt"] == "0xcollect"
    assert reads == [("test", "0xcollect")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": 0}, "did not succeed"),
        ({"token": "0x" + "aa" * 20}, "exact seller token transfer"),
        ({"recipient": "0x" + "99" * 20}, "exact seller token transfer"),
        ({"amount": 101}, "exact seller token transfer"),
    ],
)
async def test_wrong_collection_receipt_fails_before_success(
    monkeypatch, change, message
) -> None:
    async def collect(*_args, **_kwargs):
        return SimpleNamespace(kind="erc20_default"), {"transaction_hash": "0xcollect"}

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)

    async def read(_chain, _transaction_hash):
        return _collection_chain_result(**change)

    adapter = AlkahestConditionalEscrowClient(
        get_client=lambda _chain: FakeClient(),
        default_chain="test",
        collection_receipt_reader=read,
        collection_recipient=RECIPIENT,
    )
    with pytest.raises(SettlementManualRequired) as caught:
        await adapter.collect(
            _obligation(),
            mechanism_ref=ESCROW_UID,
            fulfillment_ref=FULFILLMENT_UID,
            operation_ref="collect-invalid",
            mechanism_state={},
        )
    assert caught.value.code == "collection_receipt_invalid"
    assert message in str(caught.value.__cause__)


@pytest.mark.asyncio
async def test_collection_readback_failure_preserves_safe_transaction_identity(
    monkeypatch,
) -> None:
    async def collect(*_args, **_kwargs):
        return SimpleNamespace(kind="erc20_default"), "0xcollect"

    async def read(_chain, _transaction_hash):
        raise ConnectionError("receipt unavailable")

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)
    adapter = AlkahestConditionalEscrowClient(
        get_client=lambda _chain: FakeClient(),
        default_chain="test",
        collection_receipt_reader=read,
        collection_recipient=RECIPIENT,
    )

    with pytest.raises(SettlementEffectReadbackUnknown) as caught:
        await adapter.collect(
            _obligation(),
            mechanism_ref=ESCROW_UID,
            fulfillment_ref=FULFILLMENT_UID,
            operation_ref="collect-unknown",
            mechanism_state={},
        )
    assert caught.value.receipt["receipt"] == "0xcollect"
    assert (
        caught.value.mechanism_state["alkahest"]["collection_transaction_hash"]
        == "0xcollect"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_field", ["escrow", "fulfillment", "contract"])
async def test_collection_call_must_name_exact_accepted_identities(
    monkeypatch, wrong_field
) -> None:
    async def collect(*_args, **_kwargs):
        return SimpleNamespace(kind="erc20_default"), "0xcollect"

    async def read(_chain, _transaction_hash):
        receipt, transaction = _collection_chain_result()
        if wrong_field == "contract":
            transaction["to"] = "0x" + "aa" * 20
        else:
            marker = ("aa" if wrong_field == "escrow" else "bb") * 32
            offset = 10 if wrong_field == "escrow" else 74
            transaction["input"] = (
                transaction["input"][:offset]
                + marker
                + transaction["input"][offset + 64 :]
            )
        return receipt, transaction

    monkeypatch.setattr(claims, "collect_escrow_with_codec", collect)
    adapter = AlkahestConditionalEscrowClient(
        get_client=lambda _chain: FakeClient(),
        default_chain="test",
        collection_receipt_reader=read,
        collection_recipient=RECIPIENT,
    )
    with pytest.raises(SettlementManualRequired) as caught:
        await adapter.collect(
            _obligation(),
            mechanism_ref=ESCROW_UID,
            fulfillment_ref=FULFILLMENT_UID,
            operation_ref="collect-wrong-identity",
            mechanism_state={},
        )
    assert caught.value.code == "collection_receipt_invalid"
    assert "another" in str(caught.value.__cause__)
