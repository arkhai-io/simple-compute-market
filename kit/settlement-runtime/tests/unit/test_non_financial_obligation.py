"""A non-financial obligation — no amount, no asset — services to completion."""

from __future__ import annotations

from typing import Any

import pytest

from market_settlement_runtime import (
    SettlementRuntime,
    SettlementSQLiteRepository,
    derive_obligation_ref,
)

from test_runtime import BUYER, SELLER, Client


def _introduction_obligation() -> dict[str, Any]:
    return {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.model_dump(mode="json"),
        "expiration_unix": 100,
        "conditions": [],
        "mechanism": "contact-exchange.v1",
        "params": {},
    }


@pytest.fixture
def repository(tmp_path) -> SettlementSQLiteRepository:
    return SettlementSQLiteRepository(str(tmp_path / "settlement.db"))


async def test_amountless_obligation_registers_with_a_stable_identity(
    repository,
) -> None:
    runtime = SettlementRuntime(repository, {})
    (record,) = await runtime.register_plan(
        agreement_ref="intro-1",
        obligations=[_introduction_obligation()],
    )
    assert record.obligation_ref == derive_obligation_ref(
        "intro-1", 0, _introduction_obligation()
    )
    assert "amount" not in record.obligation
    assert "asset" not in record.obligation


async def test_amountless_obligation_services_to_completion(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(
        repository,
        {"contact-exchange.v1": client},
        clock=lambda: 50,
    )
    (record,) = await runtime.register_plan(
        agreement_ref="intro-2",
        obligations=[_introduction_obligation()],
    )
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer",
    )
    await runtime.bind_fulfillment(
        record.obligation_ref,
        "introduction-available",
        local_principal=SELLER,
    )
    await runtime.check(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="seller",
    )
    await runtime.collect(
        obligation_ref=record.obligation_ref,
        local_principal=SELLER,
        worker_id="seller",
    )
    status = await runtime.get_status("intro-2")
    assert status.status == "complete"
    assert client.reclaim_calls == 0
    assert "amount" not in status.obligations[0].obligation


async def test_amountless_status_projection_stays_amountless(repository) -> None:
    client = Client()
    runtime = SettlementRuntime(
        repository,
        {"contact-exchange.v1": client},
        clock=lambda: 50,
    )
    (record,) = await runtime.register_plan(
        agreement_ref="intro-3",
        obligations=[_introduction_obligation()],
    )
    await runtime.materialize(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="buyer",
    )
    outcome = await runtime.reconcile_status(
        obligation_ref=record.obligation_ref,
        local_principal=BUYER,
        worker_id="status",
    )
    assert outcome.status == "pending"
